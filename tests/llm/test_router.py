# -*- coding: utf-8 -*-
"""LLMRouter 行为测试：优先级路由 + 结构化补全（注入 caller 隔离外部调用）。"""
from __future__ import annotations

from pydantic import BaseModel

from src.llm import LLMRouter


def test_route_default_cost() -> None:
    model = LLMRouter().route()
    assert isinstance(model, str) and model


def test_route_priority_different() -> None:
    llm = LLMRouter()
    cost = llm.route(priority='cost')
    quality = llm.route(priority='quality')
    latency = llm.route(priority='latency')
    assert isinstance(cost, str) and cost
    assert isinstance(quality, str) and quality
    assert isinstance(latency, str) and latency
    # 无 Provider 池时三档映射到不同默认模型
    assert len({cost, quality, latency}) == 3


def test_route_unknown_priority_fallback_cost() -> None:
    llm = LLMRouter()
    assert llm.route(priority='weird') == llm.route(priority='cost')


def test_complete_no_schema_returns_str() -> None:
    llm = LLMRouter(caller=lambda prov, messages: '结构化输出文本')
    out = llm.complete('mock', [{'role': 'user', 'content': 'hi'}])
    assert isinstance(out, str)


def test_complete_with_schema_validates() -> None:
    class _Out(BaseModel):
        ok: bool
        note: str = ''

    llm = LLMRouter(caller=lambda prov, messages: '{"ok": true, "note": "hit"}')
    out = llm.complete('mock', [{'role': 'user', 'content': 'hi'}], schema=_Out)
    assert isinstance(out, _Out)
    assert out.ok is True
    assert out.note == 'hit'


def test_complete_schema_fallback_to_str() -> None:
    class _Out(BaseModel):
        ok: bool

    # caller 返回非 JSON：schema 解析失败回退原始文本
    llm = LLMRouter(caller=lambda prov, messages: 'not json at all')
    out = llm.complete('mock', [{'role': 'user', 'content': 'hi'}], schema=_Out)
    assert isinstance(out, str)
