# -*- coding: utf-8 -*-
"""M04 联网检索工具注册（第 7 波：联网检索落地，引擎沿用 v1.2 SearXNG）。

将 `McpClient`（SearXNG 检索客户端）注册为 ToolRegistry 的真实可调用工具：
- `web.search`：关键词检索（标准结果 + 文本摘要）；
- `web.fetch`：抓取 URL 正文；
- `web.health`：检索引擎健康状态。

handler 签名 `(params: dict) -> Any`，与 ToolRegistry.execute 的本地 handler 约定一致。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .mcp_client import McpClient

if TYPE_CHECKING:
    from .registry import ToolRegistry


def _make_search_handler(client: McpClient):
    def handler(params: dict):
        query = str(params.get('query') or '').strip()
        if not query:
            return False, {'error': '缺少参数: query'}
        top_n = int(params.get('top_n') or 5)
        results = client.search(
            query, top_n=top_n,
            time_range=params.get('time_range'),
            site_filter=params.get('site_filter'),
        )
        return True, {
            'query': query,
            'count': len(results),
            'results': results,
            'summary': client.search_summary(
                query, top_n=top_n,
                time_range=params.get('time_range'),
                site_filter=params.get('site_filter'),
            ),
        }
    return handler


def _make_fetch_handler(client: McpClient):
    def handler(params: dict):
        url = str(params.get('url') or '').strip()
        if not url.startswith(('http://', 'https://')):
            return False, {'error': '缺少或非法参数: url（须为 http(s) URL）'}
        max_chars = int(params.get('max_chars') or 6000)
        text = client.fetch_text(url, max_chars=max_chars)
        return True, {'url': url, 'chars': len(text), 'text': text}
    return handler


def _make_health_handler(client: McpClient):
    def handler(params: dict):  # noqa: ARG001 无参数
        ok = client.health()
        return {'ok': ok, 'engine': 'searxng_mcp', 'stats': client.stats()}
    return handler


def register_web_tools(registry: 'ToolRegistry', client: McpClient | None = None) -> list[str]:
    """把联网检索工具注册进 ToolRegistry，返回注册的工具 id 列表。"""
    client = client or McpClient()
    ids = []
    for tool_id, name, desc, cap, make in (
        ('web.search', 'web_search', 'SearXNG 联网关键词检索（返回标准化结果 + 文本摘要）', 'web', _make_search_handler),
        ('web.fetch', 'web_fetch', '抓取 URL 正文文本（限制字符数）', 'web', _make_fetch_handler),
        ('web.health', 'web_search_health', 'SearXNG 检索引擎健康状态', 'web', _make_health_handler),
    ):
        spec = {
            'id': tool_id,
            'name': name,
            'description': desc,
            'capability': cap,
            'handler': make(client),
        }
        ids.append(registry.register(spec))
    return ids


__all__ = ['register_web_tools']
