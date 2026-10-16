# -*- coding: utf-8 -*-
"""M07 技能库契约测试（contracts.md §3.M07）。

src/skills/ 未实现时自动 skip；实现后自动激活。
"""
from __future__ import annotations

import inspect

import pytest


def test_skill_result_fields() -> None:
    """SkillResult 字段与契约一致。"""
    exec_mod = pytest.importorskip('src.skills.executor', reason='M07 SkillExecutor 未实现')
    assert {'ok', 'outputs', 'trace_id', 'usage_tokens'} <= set(exec_mod.SkillResult.model_fields)


def test_skill_executor_signatures() -> None:
    """SkillExecutor.run / run_dag。"""
    exec_mod = pytest.importorskip('src.skills.executor', reason='M07 SkillExecutor 未实现')
    run_sig = inspect.signature(exec_mod.SkillExecutor.run)
    assert list(run_sig.parameters)[:4] == ['self', 'skill_id', 'params', 'context']
    dag_sig = inspect.signature(exec_mod.SkillExecutor.run_dag)
    assert list(dag_sig.parameters)[:3] == ['self', 'skill_ids', 'params']
