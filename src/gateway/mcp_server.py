# -*- coding: utf-8 -*-
"""G7 MCP 双向打通（server 侧）：把 EA 垂直能力暴露为标准 MCP server。

- 实现 MCP 协议子集（JSON-RPC 2.0）：`initialize` / `tools/list` / `tools/call`。
- 工具清单来自 v1.2 `tools.TOOL_SCHEMAS`（转 MCP inputSchema）；执行走 `tools.execute_tool` 统一出口。
- 纯函数 `handle_jsonrpc(body)` 便于任意载体（HTTP 端点 / stdio / 测试）。
- 效果：Claude Code / Cursor 等 MCP 客户端可调用 EA 的 kb 检索/公式计算/记忆/技能等垂直能力（双向打通）。

零新增依赖；对齐 MCP 规范（initialize 握手 / tools/list / tools/call 的 content+isError）。
"""
from __future__ import annotations

import json
from typing import Any

_SERVER_INFO = {'name': 'environment-agent', 'version': '2.0.0'}
_PROTOCOL_VERSION = '2025-03-26'


def _tool_schemas() -> list[dict]:
    """从 v1.2 工具表提取 name/description/inputSchema（懒加载，失败降级空表）。"""
    from ..tools._v12 import get_tool_schemas
    return get_tool_schemas()


def _mcp_tool(schema: dict) -> dict:
    fn = (schema or {}).get('function', {})
    params = (fn.get('parameters') or {}) or {'type': 'object', 'properties': {}}
    return {'name': fn.get('name', ''), 'description': fn.get('description', ''),
            'inputSchema': params}


def _call_tool(name: str, arguments: dict) -> dict:
    """执行 EA 工具（v1.2 tools.execute_tool 统一出口，G2 子代理同源）。"""
    from ..tools._v12 import execute_tool
    ok, out = execute_tool(name, arguments or {})
    if not ok:
        return {'content': [{'type': 'text', 'text': f'error: {str(out)[:2000]}'}],
                'isError': True}
    text = str(out) if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
    return {'content': [{'type': 'text', 'text': text[:8000]}], 'isError': False}


class McpServer:
    """EA MCP server（JSON-RPC 2.0 分发）。"""

    def handle(self, body: dict) -> dict:
        """JSON-RPC 请求分发；非法请求返回 error 响应。"""
        if not isinstance(body, dict) or body.get('jsonrpc') != '2.0':
            return self._error(None, -32600, 'Invalid Request')
        req_id = body.get('id')
        method = body.get('method', '')
        params = body.get('params') or {}
        try:
            result = self._dispatch(method, params)
        except Exception as exc:  # noqa: BLE001
            return self._error(req_id, -32603, f'Internal error: {type(exc).__name__}: {exc}')
        return {'jsonrpc': '2.0', 'id': req_id, 'result': result}

    def _dispatch(self, method: str, params: dict) -> Any:
        if method == 'initialize':
            client_info = (params.get('clientInfo') or {})
            return {'protocolVersion': _PROTOCOL_VERSION,
                    'capabilities': {'tools': {'listChanged': False}},
                    'serverInfo': _SERVER_INFO,
                    'clientInfo': client_info}
        if method == 'tools/list':
            return {'tools': [_mcp_tool(s) for s in _tool_schemas()]}
        if method == 'tools/call':
            name = str((params or {}).get('name') or '')
            if not name:
                raise ValueError('missing tool name')
            return _call_tool(name, (params or {}).get('arguments') or {})
        if method == 'ping':
            return {}
        raise ValueError(f'method not supported: {method}')

    def _error(self, req_id, code: int, message: str) -> dict:
        return {'jsonrpc': '2.0', 'id': req_id,
                'error': {'code': code, 'message': message}}


# ---- 模块级便捷函数 ----

def handle_jsonrpc(body: dict) -> dict:
    """纯函数入口：任何载体（HTTP/stdio/测试）直接调用。"""
    return McpServer().handle(body)


def tools_list() -> dict:
    """MCP 工具清单（供前端展示）。"""
    return {'tools': [_mcp_tool(s) for s in _tool_schemas()], 'count': len(_tool_schemas())}
