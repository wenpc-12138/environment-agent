# -*- coding: utf-8 -*-
"""v1.2 工具层兼容出口（S2-M3 退役版）。

原实现按绝对路径加载根 `tools.py`（规避 tests/tools 包同名劫持）；
S2-M3 已把根 tools.py 迁入 `src/tools/v12.py`（根文件转重导出），本模块
改为直接委托 `src.tools.v12`，公开函数签名不变（load/get_tool_schemas/
execute_tool），供 G2 子代理 / G7 MCP 等既有调用方使用。
"""
from __future__ import annotations

from typing import Any

from . import v12 as _v12


def load() -> Any:
    """返回 v1.2 工具模块（现为 src.tools.v12）。"""
    return _v12


def get_tool_schemas() -> list[dict]:
    return list(getattr(_v12, 'TOOL_SCHEMAS', None) or [])


def execute_tool(name: str, args: dict) -> tuple[bool, Any]:
    """统一工具执行出口（与 v1.2 tools.execute_tool 同签名）。"""
    try:
        return _v12.execute_tool(name, args)
    except Exception as e:  # noqa: BLE001
        return False, f'工具执行异常: {e}'
