# -*- coding: utf-8 -*-
"""M04 工具层契约测试（contracts.md §3.M04）。

src/tools/ 未实现时自动 skip；实现后自动激活并校验公开签名。
"""
from __future__ import annotations

import inspect

import pytest


def test_tool_spec_fields() -> None:
    """ToolSpec 字段（sandbox 默认 none）。"""
    registry = pytest.importorskip('src.tools.registry', reason='M04 ToolRegistry 未实现')
    fields = registry.ToolSpec.model_fields
    assert {'id', 'name', 'capability', 'input_schema', 'output_schema', 'sandbox'} <= set(fields)
    assert fields['sandbox'].default == 'none'


def test_tool_result_fields() -> None:
    """ToolResult 字段（ok/data/error/trace_id）。"""
    registry = pytest.importorskip('src.tools.registry', reason='M04 ToolRegistry 未实现')
    assert {'ok', 'data', 'error', 'trace_id'} <= set(registry.ToolResult.model_fields)


def test_registry_signatures() -> None:
    """ToolRegistry.register / execute / list。"""
    registry = pytest.importorskip('src.tools.registry', reason='M04 ToolRegistry 未实现')
    assert list(inspect.signature(registry.ToolRegistry.register).parameters)[:2] == ['self', 'tool']
    exec_sig = inspect.signature(registry.ToolRegistry.execute)
    assert list(exec_sig.parameters)[:3] == ['self', 'tool_id', 'params']
    list_sig = inspect.signature(registry.ToolRegistry.list)
    assert 'capability' in list_sig.parameters
