# -*- coding: utf-8 -*-
"""M03 推理引擎契约测试（contracts.md §3.M03）。

src/llm/ 未实现时自动 skip；实现后自动激活并校验公开签名。
"""
from __future__ import annotations

import inspect

import pytest


def test_route_result_fields() -> None:
    """RouteResult 模型字段与契约一致。"""
    router = pytest.importorskip('src.llm.router', reason='M03 LLMRouter 未实现')
    fields = set(router.RouteResult.model_fields)
    assert {'skill_ids', 'confidence', 'mode'} <= fields


def test_llm_router_route_signature() -> None:
    """LLMRouter.route(task, priority='cost') -> model 名。"""
    router = pytest.importorskip('src.llm.router', reason='M03 LLMRouter 未实现')
    sig = inspect.signature(router.LLMRouter.route)
    names = list(sig.parameters)
    assert names[:2] == ['self', 'task']
    assert 'priority' in names
    assert sig.parameters['priority'].default == 'cost'


def test_llm_router_complete_signature() -> None:
    """LLMRouter.complete(model, messages, schema=None)。"""
    router = pytest.importorskip('src.llm.router', reason='M03 LLMRouter 未实现')
    sig = inspect.signature(router.LLMRouter.complete)
    names = list(sig.parameters)
    assert names[:3] == ['self', 'model', 'messages']
    assert 'schema' in names


def test_intent_router_analyze_signature() -> None:
    """IntentRouter.analyze(text, context) -> RouteResult。"""
    intent = pytest.importorskip('src.llm.intent', reason='M03 IntentRouter 未实现')
    sig = inspect.signature(intent.IntentRouter.analyze)
    names = list(sig.parameters)
    assert names[:2] == ['self', 'text']
    assert 'context' in names
