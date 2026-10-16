# -*- coding: utf-8 -*-
"""S1-W1 工作流实例持久化测试：db 模式落库 / 跨引擎实例恢复 / 热缓存回源。

覆盖：
- db 模式 start/transition 后实例落 workflow_instances 表；
- 新引擎实例（同库）可从 DB 恢复 state/history/retry_count（模拟重启）；
- memory 模式行为不变（回归保护）；
- 非法 storage 参数报错；
- transition 后 DB 与内存镜像一致。
"""
from __future__ import annotations

import json

import pytest

from src.workflow import WorkflowEngine


@pytest.fixture()
def db_engine() -> WorkflowEngine:
    """db 模式引擎（使用测试库连接，src.core.db 线程本地）。"""
    return WorkflowEngine(storage='db')


def test_db_start_persists_instance(db_engine: WorkflowEngine) -> None:
    iid = db_engine.start('report_pipeline', {'project': 'prj-001'})
    assert db_engine.get_state(iid) == 'drafting'
    # 落库验证
    from src.core.db import get_conn
    row = get_conn().execute(
        'SELECT * FROM workflow_instances WHERE instance_id=?', (iid,)).fetchone()
    assert row is not None
    assert row['workflow'] == 'report_pipeline'
    assert row['state'] == 'drafting'
    assert row['retry_count'] == 0


def test_db_transition_persists(db_engine: WorkflowEngine) -> None:
    iid = db_engine.start('report_pipeline', {})
    db_engine.transition(iid, {'type': 'submit'})
    db_engine.transition(iid, {'type': 'approve'})
    from src.core.db import get_conn
    row = get_conn().execute(
        'SELECT state, retry_count, history FROM workflow_instances WHERE instance_id=?',
        (iid,)).fetchone()
    assert row['state'] == 'compliance'
    assert row['retry_count'] == 0
    assert len(json.loads(row['history'])) == 3  # 初始 + submit + approve


def test_db_retry_count_persists(db_engine: WorkflowEngine) -> None:
    iid = db_engine.start('report_pipeline', {})
    db_engine.transition(iid, {'type': 'submit'})
    db_engine.transition(iid, {'type': 'fail'})  # review 无 fail -> 原地 + retry
    db_engine.transition(iid, {'type': 'fail'})
    assert db_engine.get_state(iid) == 'review'
    # 新引擎实例恢复（模拟重启）
    fresh = WorkflowEngine(storage='db')
    fresh._instances.clear()  # 清空热缓存，强制回源 DB
    assert fresh.get_state(iid) == 'review'
    r = fresh.transition(iid, {'type': 'fix'})
    assert r.retry_count == 2


def test_db_recover_after_restart(db_engine: WorkflowEngine) -> None:
    """完整流转后，新引擎（空缓存）从 DB 恢复全部状态与历史。"""
    iid = db_engine.start('report_pipeline', {'project': 'prj-002'})
    for ev in ('submit', 'approve', 'pass'):
        db_engine.transition(iid, {'type': ev})
    fresh = WorkflowEngine(storage='db')  # 新实例 = 模拟进程重启
    assert fresh.get_state(iid) == 'signoff'
    fresh.transition(iid, {'type': 'sign'})
    assert fresh.get_state(iid) == 'learn'
    assert iid in fresh.instances()


def test_db_instances_lists_all(db_engine: WorkflowEngine) -> None:
    a = db_engine.start('report_pipeline', {})
    b = db_engine.start('report_pipeline', {})
    ids = set(db_engine.instances())
    assert a in ids and b in ids


def test_memory_mode_unchanged() -> None:
    """memory 模式：不落库、行为与改造前一致（回归保护）。"""
    eng = WorkflowEngine()
    iid = eng.start('report_pipeline', {})
    eng.transition(iid, {'type': 'submit'})
    assert eng.get_state(iid) == 'review'
    from src.core.db import get_conn
    row = get_conn().execute(
        'SELECT * FROM workflow_instances WHERE instance_id=?', (iid,)).fetchone()
    assert row is None  # memory 模式不写库


def test_invalid_storage_raises() -> None:
    with pytest.raises(ValueError):
        WorkflowEngine(storage='redis')


def test_missing_instance_still_raises(db_engine: WorkflowEngine) -> None:
    with pytest.raises(KeyError):
        db_engine.transition('nope', {'type': 'submit'})
    with pytest.raises(KeyError):
        db_engine.get_state('nope')
