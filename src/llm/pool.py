# -*- coding: utf-8 -*-
"""M03 真实 LLM Provider 池（第 7 波：真实 Provider 池接入）。

- `ProviderSpec`：单个 Provider 规格（对齐 v1.2 `providers` 表 + 成本/质量/延迟档）。
- `ProviderPool`：Provider 池管理——
  - `load()`：懒加载真实池（默认 v1.2 `db.list_providers()`，可注入 dict/list）；
  - `pick(priority)`：按 cost/quality/latency 排序选择可用 Provider；
  - `complete()`：带失败切换（fallback）的结构化补全；
  - `health_check()`：健康探测（默认离线规则探测，可注入 probe）；
  - `estimate_cost()`：token 成本估算。

设计对齐 ADR-010/ADR-011：零硬依赖、可注入，真实 LLM 调用（providers.chat_text）
仅在实际配置存在时发生，测试/离线环境自动降级。
"""
from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

# 默认价格表（元 / 1K tokens）：model 前缀 -> (input, output)，兜底成本
_DEFAULT_PRICES: list[tuple[str, float, float]] = [
    ('deepseek-chat', 0.001, 0.002),
    ('deepseek-reasoner', 0.002, 0.008),
    ('glm-4', 0.005, 0.005),
    ('qwen', 0.002, 0.006),
    ('gpt-4o', 0.01, 0.03),
    ('claude-3', 0.01, 0.03),
]
_FALLBACK_PRICE = (0.002, 0.002)

# 默认质量档（0..1）：model 前缀启发式
_HIGH_QUALITY_PREFIXES = ('gpt-4', 'claude-3', 'deepseek-reasoner', 'o1', 'o3', 'gemini-1.5', 'glm-4.5', 'qwen-max')
_MID_QUALITY_PREFIXES = ('deepseek-chat', 'glm-4', 'qwen-plus', 'qwen-turbo', 'moonshot', 'hunyuan')
_LATENCY_FAST_PREFIXES = ('qwen-turbo', 'glm-4-flash', 'deepseek-chat', 'minimax', 'kimi')

# 优先级 -> 排序字段（Provider 无显式档位时的启发式排序键）
_PRIORITY_KEY = {'cost', 'quality', 'latency'}


class ProviderSpec(BaseModel):
    """Provider 规格（对齐 v1.2 `providers` 表字段）。"""

    id: int | str
    name: str = ''
    kind: str = 'openai'  # openai | mock | anthropic | gemini ...
    model: str = ''
    base_url: str = ''
    api_key: str = ''
    enabled: bool = True  # v1.2 is_active
    priority: int = 50  # 0..100，越大越优先（平级时再按 priority 排序键）
    cost_per_1k_in: float = 0.0  # 元 / 1K input tokens（0 表示未配置，用启发式）
    cost_per_1k_out: float = 0.0
    quality: float = 0.5  # 0..1 启发式质量档
    latency: float = 1.0  # 相对延迟（越小越快）
    reasoning_effort: str = 'high'


def _heuristic_quality(model: str) -> float:
    if any(model.startswith(p) for p in _HIGH_QUALITY_PREFIXES):
        return 0.95
    if any(model.startswith(p) for p in _MID_QUALITY_PREFIXES):
        return 0.7
    if any(model.startswith(p) for p in _LATENCY_FAST_PREFIXES):
        return 0.5
    return 0.5


def _heuristic_latency(model: str) -> float:
    if any(model.startswith(p) for p in _LATENCY_FAST_PREFIXES):
        return 0.6
    if any(model.startswith(p) for p in _HIGH_QUALITY_PREFIXES):
        return 1.4
    return 1.0


def _heuristic_price(model: str) -> tuple[float, float]:
    for prefix, p_in, p_out in _DEFAULT_PRICES:
        if model.startswith(prefix):
            return p_in, p_out
    return _FALLBACK_PRICE


def _to_provider_spec(raw: dict | ProviderSpec) -> ProviderSpec:
    """把 v1.2 providers 表行 / dict / ProviderSpec 规范化为 ProviderSpec。"""
    if isinstance(raw, ProviderSpec):
        return raw
    model = str(raw.get('model') or '')
    p_in, p_out = _heuristic_price(model)
    return ProviderSpec(
        id=raw.get('id'),
        name=str(raw.get('name') or model or 'provider'),
        kind=str(raw.get('kind') or 'openai'),
        model=model,
        base_url=str(raw.get('base_url') or ''),
        api_key=str(raw.get('api_key') or ''),
        enabled=bool(raw.get('is_active', raw.get('enabled', True))),
        priority=int(raw.get('priority') or 50),
        cost_per_1k_in=float(raw.get('cost_per_1k_in') or 0.0),
        cost_per_1k_out=float(raw.get('cost_per_1k_out') or 0.0),
        quality=float(raw.get('quality') or _heuristic_quality(model)),
        latency=float(raw.get('latency') or _heuristic_latency(model)),
        reasoning_effort=str(raw.get('reasoning_effort') or 'high'),
    )


class ProviderPool:
    """真实 LLM Provider 池：加载 / 优先级选择 / 失败切换补全 / 成本估算 / 健康探测。

    - `providers`：注入的 provider 列表（list[dict | ProviderSpec]），供测试/离线注入；
    - `load_fn`：自定义加载函数（默认懒加载 v1.2 `db.list_providers`）；
    - `caller`：补全回调 `(prov, messages) -> str | (text, usage)`，默认 v1.2 `providers.chat_text`；
    - `probe`：健康探测回调 `(prov) -> bool`，默认离线规则探测。
    """

    def __init__(
        self,
        providers: list[dict | ProviderSpec] | None = None,
        load_fn: Callable[[], list] | None = None,
        caller: Callable | None = None,
        probe: Callable[[dict], bool] | None = None,
    ) -> None:
        self._injected = providers
        self._load_fn = load_fn
        self._caller = caller
        self._probe = probe
        self._pool: list[ProviderSpec] | None = None
        self.last_errors: list[str] = []

    # -- 加载 -----------------------------------------------------------
    def load(self) -> list[ProviderSpec]:
        """加载 Provider 池（懒加载 + 缓存，`refresh()` 强制重载）。"""
        if self._pool is not None:
            return self._pool
        raw: list = []
        if self._injected is not None:
            raw = list(self._injected)
        elif self._load_fn is not None:
            try:
                raw = list(self._load_fn() or [])
            except Exception as exc:  # noqa: BLE001 加载失败降级为空池
                self.last_errors.append(f'load: {type(exc).__name__}: {exc}')
                raw = []
        else:
            try:
                from src.core import db_v12 as v12_db  # S2-M6：数据层统一

                raw = list(v12_db.list_providers() or [])
            except Exception as exc:  # noqa: BLE001 无 v1.2 模块时保持空池
                self.last_errors.append(f'load: {type(exc).__name__}: {exc}')
                raw = []
        self._pool = [_to_provider_spec(r) for r in raw if isinstance(r, dict) or isinstance(r, ProviderSpec)]
        return self._pool

    def refresh(self) -> list[ProviderSpec]:
        """强制重新加载。"""
        self._pool = None
        self.last_errors = []
        return self.load()

    def list(self, active_only: bool = True) -> list[ProviderSpec]:
        """返回池内 Provider 列表（默认仅 enabled）。"""
        pool = self.load()
        if active_only:
            return [p for p in pool if p.enabled]
        return list(pool)

    # -- 选择 -----------------------------------------------------------
    def pick(self, priority: str = 'cost') -> ProviderSpec | None:
        """按优先级选择第一个可用 Provider。

        priority ∈ {cost, quality, latency}；未知 priority 回退 cost。
        返回 None 表示池为空或全部禁用。
        """
        priority = priority if priority in _PRIORITY_KEY else 'cost'
        active = self.list(active_only=True)
        if not active:
            return None
        if priority == 'cost':
            def _key(p: ProviderSpec):
                return (p.cost_per_1k_in + p.cost_per_1k_out, -p.quality)
        elif priority == 'quality':
            def _key(p: ProviderSpec):
                return (-p.quality, p.cost_per_1k_in + p.cost_per_1k_out)
        else:  # latency
            def _key(p: ProviderSpec):
                return (p.latency, -p.quality)
        ordered = sorted(active, key=_key)
        return ordered[0]

    # -- 补全（失败切换） ----------------------------------------------
    def complete(self, model: str, messages: list[dict], schema: type | None = None,
                 priority: str = 'cost') -> Any:
        """结构化补全，带失败切换（fallback）。

        候选顺序：精确/包含匹配 model 的 provider -> 按 priority 排序的全部 enabled。
        逐个调用 caller；schema 校验失败或调用异常时继续尝试下一个候选；
        全部失败返回 None（错误记录在 `last_errors`）。
        """
        pool = self.load()
        active = [p for p in pool if p.enabled]
        if not active:
            self.last_errors.append('complete: Provider 池为空')
            return None
        # 候选排序：匹配 model 优先，其余按 priority
        matched = [p for p in active if p.model == model or (model and p.model and model in p.model)]
        rest = sorted(
            [p for p in active if p not in matched],
            key=lambda p: (p.priority, -(p.cost_per_1k_in + p.cost_per_1k_out)),
            reverse=True,
        )
        candidates = matched + rest
        for prov in candidates:
            try:
                text = self._call(prov, messages)
                if not isinstance(text, str) or not text.strip():
                    self.last_errors.append(f'complete[{prov.model}]: 空输出')
                    continue
                if schema is None:
                    return text
                try:
                    return schema.model_validate_json(text)
                except Exception as exc:  # noqa: BLE001 schema 解析失败 -> 尝试下一候选
                    self.last_errors.append(f'complete[{prov.model}]: schema 校验失败: {type(exc).__name__}')
                    continue
            except Exception as exc:  # noqa: BLE001 调用异常 -> 失败切换
                self.last_errors.append(f'complete[{prov.model}]: {type(exc).__name__}: {exc}')
                continue
        return None

    def _call(self, prov: ProviderSpec, messages: list[dict]) -> str:
        raw = prov.model_dump()
        if self._caller is not None:
            res = self._caller(raw, messages or [])
        else:
            from src.llm.providers import chat_text as _chat_text, ProviderError as _ProviderError  # v1.2 顶层模块（真实 LLM 调用）

            res = _chat_text(raw, messages or [])
        if isinstance(res, tuple):
            res = res[0]
        return res if isinstance(res, str) else str(res or '')

    # -- 健康探测 -------------------------------------------------------
    def health_check(self, provider_id: int | str | None = None) -> dict:
        """健康探测。返回 {provider_id: bool}（provider_id=None 时探测全部）。

        默认离线规则探测（mock / 缺 base_url / 缺 api_key 判不可用），可注入 `probe`。
        """
        pool = self.load()
        targets = pool if provider_id is None else [p for p in pool if str(p.id) == str(provider_id)]
        out: dict[str, bool] = {}
        for p in targets:
            raw = p.model_dump()
            if self._probe is not None:
                try:
                    out[str(p.id)] = bool(self._probe(raw))
                except Exception as exc:  # noqa: BLE001
                    out[str(p.id)] = False
                    self.last_errors.append(f'health[{p.model}]: {type(exc).__name__}: {exc}')
            else:
                out[str(p.id)] = self._default_probe(raw)
        return out

    @staticmethod
    def _default_probe(prov: dict) -> bool:
        """离线规则探测：mock / 缺 base_url / 缺 api_key 视为不可用（避免真实联网）。"""
        if prov.get('kind') == 'mock':
            return False
        if not (prov.get('base_url') or '').startswith(('http://', 'https://')):
            return False
        if not prov.get('api_key'):
            return False
        return True

    # -- 成本估算 -------------------------------------------------------
    def estimate_cost(self, model: str, in_tokens: int, out_tokens: int) -> float:
        """按 model 匹配 Provider 的成本字段估算（元）；未配置时用启发式默认价格。"""
        p_in, p_out = _heuristic_price(model)
        for p in self.load():
            if p.model == model or (model and p.model and model in p.model):
                if p.cost_per_1k_in > 0:
                    p_in, p_out = p.cost_per_1k_in, p.cost_per_1k_out
                break
        return (in_tokens / 1000.0) * p_in + (out_tokens / 1000.0) * p_out

    # -- 状态 -----------------------------------------------------------
    def status(self) -> dict:
        """池状态汇总。"""
        pool = self.load()
        active = [p for p in pool if p.enabled]
        return {
            'total': len(pool),
            'active': len(active),
            'providers': [p.model for p in active],
            'last_errors': list(self.last_errors[-5:]),
        }


__all__ = ['ProviderSpec', 'ProviderPool']
