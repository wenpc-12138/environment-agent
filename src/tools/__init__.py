# -*- coding: utf-8 -*-
"""M04 工具层包：注册表 + 执行器 + MCP 检索客户端。

- `ToolRegistry`（register/execute/list，双轨重铸 v1.2 TOOL_SCHEMAS）
- `ToolExecutor`（run/run_sequence，带 trace）
- `McpClient`（SearXNG 检索，动态导入降级）
"""
from .executor import ToolExecutor
from .mcp_client import McpClient
from .registry import ToolRegistry, ToolResult, ToolSpec
from .web_tools import register_web_tools

__all__ = [
    'ToolRegistry', 'ToolSpec', 'ToolResult', 'ToolExecutor',
    'McpClient', 'register_web_tools',
]
