# -*- coding: utf-8 -*-
"""S3-H1 goal 持久化目标测试：登记/幂等/更新/查询/收尾钩子自动登记。

覆盖：
- register 首次登记（in_progress→completed 语义由调用方给）；
- 同任务重复登记幂等（不重复建行，仅更新）；
- update_status 改状态与进度；
- list_for_task / list_active / get；
- 任务收尾钩子（Agent.run 完成后 goals 自动登记 completed）。
"""
from __future__ import annotations

import pytest

from src.memory import goals


@pytest.fixture(autouse=True)
def _clean_goals():
    from src.core.db import get_conn
    conn = get_conn()
    conn.execute('DELETE FROM goals')
    conn.commit()
    yield
    conn = get_conn()
    conn.execute('DELETE FROM goals')
    conn.commit()


def test_register_creates_goal():
    gid = goals.register(1001, '编制验收报告', progress=100, status='completed')
    row = goals.get(gid)
    assert row is not None
    assert row['task_id'] == 1001
    assert row['objective'] == '编制验收报告'
    assert row['status'] == 'completed'
    assert row['progress'] == 100


def test_register_idempotent_per_task():
    gid1 = goals.register(1002, '目标A', progress=100, status='completed')
    gid2 = goals.register(1002, '目标A-更新', progress=80, status='in_progress')
    assert gid1 == gid2  # 同任务不重复建行
    assert goals.get(gid1)['objective'] == '目标A-更新'
    assert goals.get(gid1)['progress'] == 80


def test_update_status_and_progress():
    gid = goals.register(1003, '查新 GB 3838', progress=100, status='completed')
    assert goals.update_status(gid, 'in_progress', 50) is True
    row = goals.get(gid)
    assert row['status'] == 'in_progress' and row['progress'] == 50
    assert goals.update_status(99999, 'completed') is False  # 不存在


def test_list_for_task_and_active():
    goals.register(1004, '目标1', progress=100, status='completed')
    gid = goals.register(1005, '目标2', progress=30, status='in_progress')
    assert len(goals.list_for_task(1004)) == 1
    active = goals.list_active()
    assert any(g['id'] == gid for g in active)


def test_progress_clamped():
    gid = goals.register(1006, '目标', progress=999, status='completed')
    assert goals.get(gid)['progress'] == 100


def test_agent_run_registers_goal():
    """任务收尾钩子：Agent.run 完成后 goals 自动登记 completed。"""
    from src.core import db_v12 as db
    from src import agent as agent_core
    tid = db.create_task('S3目标冒烟', mode='craft')
    prov = {'kind': 'mock', 'model': 'mock-eco'}
    agent = agent_core.Agent(tid, prov, 'craft')
    for _ev in agent.run('测试 目标登记'):
        if _ev.get('event') == 'done':
            break
    # 收尾钩子是后台线程，轮询等待
    import time
    rows = []
    for _ in range(20):
        rows = goals.list_for_task(tid)
        if rows:
            break
        time.sleep(0.1)
    assert rows, '任务收尾后应自动登记 goal'
    assert rows[0]['status'] == 'completed'
    assert rows[0]['progress'] == 100
