# -*- coding: utf-8 -*-
"""M09 工作流引擎行为测试：内置报告状态机流转 / escalate / retry / YAML 加载。"""
from __future__ import annotations

from pathlib import Path

from src.workflow import BUILTIN_REPORT_SM, WorkflowEngine
from src.workflow.scheduler import next_run


def test_builtin_pipeline_full_flow() -> None:
    eng = WorkflowEngine()
    iid = eng.start('report_pipeline', {'project': 'prj-20260806-001'})
    assert eng.get_state(iid) == 'drafting'

    flow = [('submit', 'review'), ('approve', 'compliance'), ('pass', 'signoff'),
            ('sign', 'learn'), ('done', 'done')]
    for event, expected in flow:
        r = eng.transition(iid, {'type': event})
        assert r.to_state == expected
        assert eng.get_state(iid) == expected


def test_auto_fix_loop_and_retry_count() -> None:
    eng = WorkflowEngine()
    iid = eng.start('report_pipeline', {})
    eng.transition(iid, {'type': 'submit'})          # drafting -> review
    eng.transition(iid, {'type': 'fix'})             # review -> auto_fix
    r = eng.transition(iid, {'type': 'fixed'})       # auto_fix -> review
    assert r.from_state == 'auto_fix' and r.to_state == 'review'
    r = eng.transition(iid, {'type': 'fail'})        # compliance 失败回 review
    assert r.retry_count == 1
    assert r.from_state == 'review' and r.to_state == 'review'


def test_escalate_from_any_state() -> None:
    eng = WorkflowEngine()
    for state, event in [('drafting', None), ('review', 'submit')]:
        iid = eng.start('report_pipeline', {})
        if event:
            eng.transition(iid, {'type': event})
        r = eng.transition(iid, {'type': 'escalate'})
        assert r.escalated is True
        assert r.to_state == 'escalate'
        assert eng.get_state(iid) == 'escalate'


def test_invalid_event_stays() -> None:
    eng = WorkflowEngine()
    iid = eng.start('report_pipeline', {})
    r = eng.transition(iid, {'type': 'nonsense'})
    assert r.from_state == r.to_state == 'drafting'


def test_missing_instance_raises() -> None:
    eng = WorkflowEngine()
    try:
        eng.transition('nope', {'type': 'submit'})
        raise AssertionError('应当抛 KeyError')
    except KeyError:
        pass


def test_yaml_load(tmp_path: Path) -> None:
    sm = """name: custom_flow
trigger: manual
initial: ready
states:
  ready: {run: doing, escalate: escalate}
  doing: {finish: done}
  done: {}
  escalate: {resolve: ready}
"""
    p = tmp_path / 'custom.yaml'
    p.write_text(sm, encoding='utf-8')
    eng = WorkflowEngine()
    spec = eng.load(str(p))
    assert spec.name == 'custom_flow' and spec.trigger == 'manual'
    iid = eng.start('custom_flow', {})
    assert eng.get_state(iid) == 'ready'
    assert eng.transition(iid, {'type': 'run'}).to_state == 'doing'
    assert eng.transition(iid, {'type': 'finish'}).to_state == 'done'


def test_cron_next_run() -> None:
    from datetime import datetime, timezone

    base = datetime(2026, 8, 6, 10, 30, tzinfo=timezone.utc)
    assert next_run('0 9 * * 1', base).weekday() == 0  # 下周一九点
    n = next_run('* * * * *', base)
    assert n == base.replace(second=0, microsecond=0).replace(minute=31)
