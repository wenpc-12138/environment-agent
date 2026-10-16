# -*- coding: utf-8 -*-
"""M09 工作流引擎契约测试（contracts.md §3.M09）。

src/workflow/ 未实现时自动 skip；实现后自动激活。
"""
from __future__ import annotations

import inspect

import pytest


def test_workflow_spec_fields() -> None:
    """WorkflowSpec 字段与契约一致。"""
    engine = pytest.importorskip('src.workflow.engine', reason='M09 WorkflowEngine 未实现')
    assert {'name', 'trigger', 'state_machine'} <= set(engine.WorkflowSpec.model_fields)


def test_workflow_engine_signatures() -> None:
    """WorkflowEngine.load / start / transition / get_state。"""
    engine = pytest.importorskip('src.workflow.engine', reason='M09 WorkflowEngine 未实现')
    load = inspect.signature(engine.WorkflowEngine.load)
    assert list(load.parameters)[:2] == ['self', 'yaml_path']
    start = inspect.signature(engine.WorkflowEngine.start)
    assert list(start.parameters)[:3] == ['self', 'workflow_name', 'payload']
    trans = inspect.signature(engine.WorkflowEngine.transition)
    assert list(trans.parameters)[:3] == ['self', 'instance_id', 'event']
    state = inspect.signature(engine.WorkflowEngine.get_state)
    assert list(state.parameters)[:2] == ['self', 'instance_id']
