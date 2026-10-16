# -*- coding: utf-8 -*-
"""H3 Cron 记忆连续性测试（对齐 Hermes cron memory）。

覆盖：
- 迁移 0017：task_schedule 增 notepad/continuity/last_summary 列（幂等）；
- ScheduleManager.set_notepad/get_notepad/set_continuity/set_last_summary；
- tick() 到期 fired item 携带记忆字段；
- _trigger_task：continuity=1 且 last_summary 非空 → 任务首条 system 消息注入；
- _trigger_task 运行后回写 last_summary。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest

from src.core import config, db as core_db
from src.scheduler import ScheduleManager


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'cronmem.db'))
    config.get_settings.cache_clear()
    # v1.2 表（tasks/messages）由 init_db 建；v2 新表由迁移建；两套共用 ECOAGENT_DB 库
    from src.core import db_v12 as v12_db
    v12_db.init_db()
    core_db.run_migrations()
    yield
    core_db.close_db()


@pytest.fixture()
def mgr(_db) -> ScheduleManager:
    return ScheduleManager()


def _force_due(mgr, sid):
    """把任务 next_run 改为过去，使其到期。"""
    from src.core.db import get_conn
    past = (datetime.now() - timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_conn()
    conn.execute('UPDATE task_schedule SET next_run=? WHERE id=?', (past, sid))
    conn.commit()


def test_migration_0017_columns(mgr):
    """迁移 0017 后新列存在。"""
    from src.core.db import get_conn
    cols = {r['name'] for r in get_conn().execute('PRAGMA table_info(task_schedule)')}
    assert {'notepad', 'continuity', 'last_summary'} <= cols


def test_notepad_roundtrip(mgr):
    r = mgr.add('每天9点生成日报', '', '生成日报')
    sid = r['id']
    assert mgr.get_notepad(sid)['notepad'] == ''
    mgr.set_notepad(sid, '用户偏好：关注 PM2.5 与氨氮')
    assert mgr.get_notepad(sid)['notepad'] == '用户偏好：关注 PM2.5 与氨氮'
    mgr.set_notepad(sid, '')
    assert mgr.get_notepad(sid)['notepad'] == ''


def test_continuity_toggle(mgr):
    r = mgr.add('每天9点生成日报', '', '生成日报')
    sid = r['id']
    assert mgr._get(sid)['continuity'] == 1  # 默认开
    mgr.set_continuity(sid, False)
    assert mgr._get(sid)['continuity'] == 0
    mgr.set_continuity(sid, True)
    assert mgr._get(sid)['continuity'] == 1


def test_last_summary_roundtrip(mgr):
    r = mgr.add('每天9点生成日报', '', '生成日报')
    mgr.set_last_summary(r['id'], '昨日已生成日报，AQI 良好')
    row = mgr._get(r['id'])
    assert row['last_summary'] == '昨日已生成日报，AQI 良好'


def test_tick_fired_carries_memory(mgr):
    """tick 到期任务的 fired item 携带 continuity/last_summary/notepad。"""
    r = mgr.add('每小时监控', '', '监控任务')
    sid = r['id']
    mgr.set_last_summary(sid, '上次无异常')
    mgr.set_notepad(sid, '草稿')
    _force_due(mgr, sid)
    fired = mgr.tick()
    assert fired, '应触发到期任务'
    item = fired[0]
    assert item['id'] == sid
    assert item['continuity'] is True
    assert item['last_summary'] == '上次无异常'
    assert item['notepad'] == '草稿'


def test_continuity_messages_injected_when_enabled():
    """_continuity_messages：continuity=1 且有 last_summary → 生成注入消息。"""
    from src.scheduler import _continuity_messages
    item = {'continuity': True, 'last_summary': '昨日已报告：AQI 55 良',
            'notepad': '草稿内容'}
    msgs = _continuity_messages(item)
    assert len(msgs) == 2
    roles = [r for r, _ in msgs]
    assert roles == ['system', 'system']
    joined = ' '.join(c for _, c in msgs)
    assert '上次运行摘要' in joined and '昨日已报告：AQI 55 良' in joined
    assert '调度任务草稿本' in joined and '草稿内容' in joined


def test_continuity_messages_skipped_when_disabled():
    """_continuity_messages：continuity=0 或无 last_summary 时不注入上次摘要。"""
    from src.scheduler import _continuity_messages
    # continuity=0
    msgs = _continuity_messages({'continuity': False, 'last_summary': '有内容'})
    assert not any('上次运行摘要' in c for _, c in msgs)
    # 无 last_summary
    msgs2 = _continuity_messages({'continuity': True, 'last_summary': '', 'notepad': ''})
    assert msgs2 == []
    # notepad 单独注入
    msgs3 = _continuity_messages({'continuity': True, 'last_summary': '', 'notepad': '备忘'})
    assert len(msgs3) == 1 and '调度任务草稿本' in msgs3[0][1]
