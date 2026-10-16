# -*- coding: utf-8 -*-
"""M04 网络检索 MCP 客户端（收编 v1.2 searxng_mcp，contracts.md §3.M04）。

第 7 波「联网检索落地」（继续用 V1.2 的 SearXNG 引擎）：
- 代理 v1.2 searxng_mcp 的 `search` / `fetch_text` / `health`（懒加载，零硬依赖）；
- TTL 结果缓存（避免重复请求、降并发压力）；
- 失败重试（指数退避，`max_retries` 次）；
- 结果标准化（title/url/snippet 键齐全，缺失补空）；
- `search_summary()`：拼装文本摘要（供 LLM 上下文 / grounding 在线证据）；
- `stats()`：缓存命中/未命中统计。
"""
from __future__ import annotations

import importlib
import time
from typing import Any

# 缓存默认配置
_DEFAULT_CACHE_TTL = 60.0  # 秒
_DEFAULT_RETRIES = 2
_RETRY_BASE_DELAY = 0.5  # 秒


class McpClient:
    """SearXNG MCP 检索客户端（懒加载 v1.2 searxng_mcp 模块）。

    - `module_name`：v1.2 模块名（测试可注入假模块对象）；
    - `cache_ttl`：结果缓存有效期（秒，0 禁用）；
    - `max_retries`：失败重试次数（0 禁用）。
    """

    def __init__(self, module_name: str = 'searxng_mcp',
                 cache_ttl: float = _DEFAULT_CACHE_TTL,
                 max_retries: int = _DEFAULT_RETRIES) -> None:
        self._mod: Any | None = None
        self._module_name = module_name
        self._cache_ttl = max(0.0, cache_ttl)
        self._max_retries = max(0, max_retries)
        self._cache: dict[tuple, tuple[float, Any]] = {}
        self._hits = 0
        self._misses = 0

    # -- 底层模块 -------------------------------------------------------
    def _load(self) -> Any | None:
        if self._mod is None:
            try:
                self._mod = importlib.import_module(self._module_name)
            except Exception:
                self._mod = False
        return self._mod or None

    def _cached(self, key: tuple) -> Any | None:
        if not self._cache_ttl or key not in self._cache:
            return None
        ts, value = self._cache[key]
        if time.time() - ts > self._cache_ttl:
            self._cache.pop(key, None)
            return None
        self._hits += 1
        return value

    def _store(self, key: tuple, value: Any) -> None:
        if not self._cache_ttl:
            return
        self._misses += 1
        self._cache[key] = (time.time(), value)

    @staticmethod
    def _retry(fn, attempts: int) -> Any:
        last: Exception | None = None
        for i in range(attempts + 1):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 网络抖动等，退避后重试
                last = exc
                if i < attempts:
                    time.sleep(_RETRY_BASE_DELAY * (2 ** i))
        raise last  # type: ignore[misc] 全部重试失败后上抛

    # -- 检索 -----------------------------------------------------------
    def search(self, query: str, top_n: int = 5, time_range: str | None = None,
               site_filter: str | None = None) -> list[dict]:
        """检索并返回标准化结果列表（每项含 title/url/snippet）。

        v1.2 searxng_mcp.search 可能返回 list[dict] 或 list[str]（旧格式），
        统一规范化为 dict；失败/不可用返回空列表。
        """
        key = ('search', query, top_n, time_range, site_filter)
        cached = self._cached(key)
        if cached is not None:
            return cached
        mod = self._load()
        if mod is None:
            self._store(key, [])
            return []
        try:
            raw = self._retry(
                lambda: mod.search(query, top_n=top_n, time_range=time_range, site_filter=site_filter) or [],
                self._max_retries,
            )
        except Exception:
            self._store(key, [])
            return []
        results = [self._norm(item) for item in raw if self._norm(item)]
        self._store(key, results)
        return results

    @staticmethod
    def _norm(item: Any) -> dict | None:
        """标准化单条结果 -> {'title', 'url', 'snippet'}；无效项返回 None。"""
        if isinstance(item, dict):
            url = str(item.get('url') or '')
            if not url:
                return None
            return {
                'title': str(item.get('title') or url),
                'url': url,
                'snippet': str(item.get('snippet') or item.get('content') or ''),
            }
        text = str(item or '').strip()
        if not text:
            return None
        return {'title': text[:120], 'url': text, 'snippet': ''}

    def fetch_text(self, url: str, max_chars: int = 6000) -> str:
        """抓取 URL 正文文本（带缓存；失败返回空字符串）。"""
        key = ('fetch', url, max_chars)
        cached = self._cached(key)
        if cached is not None:
            return cached
        mod = self._load()
        if mod is None:
            self._store(key, '')
            return ''
        try:
            text = self._retry(
                lambda: mod.fetch_text(url, max_chars=max_chars) or '',
                self._max_retries,
            )
        except Exception:
            text = ''
        self._store(key, text)
        return text

    def health(self) -> bool:
        """底层引擎健康探测（5s 短缓存）。"""
        key = ('health',)
        cached = self._cached(key)
        if cached is not None:
            return bool(cached)
        mod = self._load()
        ok = False
        if mod is not None:
            try:
                ok = bool(mod.health())
            except Exception:
                ok = False
        self._store(key, ok)
        return ok

    # -- 摘要 / 统计 ----------------------------------------------------
    def search_summary(self, query: str, top_n: int = 5, time_range: str | None = None,
                       site_filter: str | None = None) -> str:
        """把检索结果拼装为文本摘要（供 LLM 上下文 / grounding 在线证据）。"""
        results = self.search(query, top_n=top_n, time_range=time_range, site_filter=site_filter)
        if not results:
            return ''
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get('title') or ''
            url = r.get('url') or ''
            snippet = r.get('snippet') or ''
            lines.append(f'[{i}] {title}\n    URL: {url}\n    {snippet}')
        return f'在线检索「{query}」结果（{len(results)} 条）:\n' + '\n'.join(lines)

    def stats(self) -> dict:
        """缓存统计。"""
        return {'cache_size': len(self._cache), 'hits': self._hits, 'misses': self._misses}


__all__ = ['McpClient']
