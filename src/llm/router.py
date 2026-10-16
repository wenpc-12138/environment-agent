# -*- coding: utf-8 -*-
"""M03 LLM 路由与结构化补全（LLMRouter，contracts.md §3.M03）。

- `route(task, priority)`：按 cost/quality/latency 从 Provider 池选择模型名；
  Provider 池懒加载自 v1.2 `db.get_providers()`，不可用时降级内置默认模型表。
- `complete(model, messages, schema)`：调用 Provider 补全；提供 Pydantic schema 时
  尝试结构化校验（失败回退原始文本）。补全器可注入（ADR-010 可注入降级）。

设计对齐 ADR-010：零硬依赖、可注入，LLM 实体调用（providers.chat_text）仅在实际
配置存在时发生，测试/离线环境自动降级。
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from ..models.core import RouteResult  # noqa: F401  (契约导出 RouteResult)

# 内置模型优先级表（Provider 池不可用时兜底）
_DEFAULT_MODELS: dict[str, list[str]] = {
    'cost': ['deepseek-chat', 'glm-4-flash', 'qwen-turbo'],
    'quality': ['gpt-4o', 'claude-3-5-sonnet', 'deepseek-chat'],
    'latency': ['qwen-turbo', 'glm-4-flash', 'deepseek-chat'],
}

# 模型名 -> 粗略成本/质量档（用于无池时的排序）
_MODEL_ORDER = {'cost': 0, 'quality': 1, 'latency': 2}


def _find_provider_for_model(pool: dict, model: str) -> dict | None:
    """在 provider 池中按 model 名精确/包含匹配。"""
    if not pool:
        return None
    if isinstance(pool, dict):
        for prov in pool.values():
            m = (prov.get('model') or '') if isinstance(prov, dict) else ''
            if m == model or (model and m and model in m):
                return prov
    return None


class LLMRouter:
    """LLM 路由：任务路由 + 结构化补全。

    - `provider_pool`（第 7 波新增）：注入 `ProviderPool` 后，route/complete 委托真实
      Provider 池（优先级选择 + 失败切换）；未注入时保持原 dict 池 / 默认模型表逻辑。
    """

    def __init__(self, pool: dict | None = None, caller: Callable | None = None,
                 provider_pool: Any | None = None) -> None:
        self._pool = pool
        self._caller = caller  # 可注入补全回调 (provider, messages, **kw) -> (text, usage)
        self._provider_pool = provider_pool

    # -- provider 池 ----------------------------------------------------
    def _load_pool(self) -> dict:
        if self._pool is not None:
            return self._pool
        try:
            from src.core import db_v12 as v12_db  # S2-M6：数据层统一

            raw = v12_db.get_providers() or {}
            if isinstance(raw, dict):
                self._pool = raw
                return raw
        except Exception:
            pass
        return {}

    # -- 路由 -----------------------------------------------------------
    def route(self, task: str = '', priority: str = 'cost') -> str:
        """按优先级选择模型名。

        priority ∈ {cost, quality, latency}；未知 priority 回退 cost。
        注入 provider_pool 时委托真实 Provider 池选择（池为空回退默认表）。
        """
        priority = priority if priority in _DEFAULT_MODELS else 'cost'
        if self._provider_pool is not None:
            try:
                spec = self._provider_pool.pick(priority)
                if spec is not None and spec.model:
                    return spec.model
            except Exception:
                pass
        ordered = _DEFAULT_MODELS[priority]
        pool = self._load_pool()
        if pool:
            for model in ordered:
                if _find_provider_for_model(pool, model):
                    return model
            # 池中有其它模型：按相同档位近似排序取第一个
            names = [p.get('model') for p in pool.values() if isinstance(p, dict) and p.get('model')]
            if names:
                return names[0]
        return ordered[0]

    # -- 补全 -----------------------------------------------------------
    def complete(self, model: str, messages: list[dict], schema: type | None = None) -> Any:
        """调用补全；schema 提供时尝试结构化校验。

        注入 provider_pool 时委托真实 Provider 池（失败切换）；池不可用回退原逻辑。
        返回：schema 校验成功 -> BaseModel 实例；否则 -> 文本（str）。
        """
        if self._provider_pool is not None:
            try:
                out = self._provider_pool.complete(model, messages, schema=schema)
                if out is not None:
                    return out
            except Exception:
                pass
        text = self._raw_complete(model, messages)
        if schema is None:
            return text
        try:
            return schema.model_validate_json(text)
        except Exception:
            return text

    # -- 内部 -----------------------------------------------------------
    def _raw_complete(self, model: str, messages: list[dict]) -> str:
        pool = self._load_pool()
        prov = _find_provider_for_model(pool, model)
        if prov is not None and self._caller is None:
            try:
                from src.llm.providers import chat_text as _chat_text, ProviderError as _ProviderError

                text, _usage = _chat_text(prov, messages or [])
                return text if isinstance(text, str) else str(text or '')
            except Exception:
                pass
        if self._caller is not None:
            try:
                text = self._caller(prov or {'model': model}, messages or [])
                return text if isinstance(text, str) else str(text or '')
            except Exception:
                pass
        # 降级：回显最后一条 user 文本（离线/测试确定性）
        for m in reversed(messages or []):
            if m.get('role') == 'user' and m.get('content'):
                return str(m['content'])
        return ''


def extract_json(text: str) -> dict | None:
    """从 LLM 输出中提取 JSON 对象（fenced / 裸 JSON），失败返回 None。"""
    if not text:
        return None
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.S)
    candidate = m.group(1) if m else text
    try:
        return json.loads(candidate)
    except Exception:
        return None
