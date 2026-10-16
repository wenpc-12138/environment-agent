# -*- coding: utf-8 -*-
"""H2 自然语言定时任务：parse_nl / next_run_at / 管理 / 到期触发。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.core import config, db as core_db
from src.scheduler import ScheduleManager, next_run_at, parse_nl, start_scheduler


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'scheduler.db'))
    config.get_settings.cache_clear()
    core_db.run_migrations()
    yield
    core_db.close_db()


class TestParseNl:
    @pytest.mark.parametrize('text, expect', [
        ('每天9点', 'daily 09:00'),
        ('每日10:30', 'daily 10:30'),
        ('每天早上8点', 'daily 08:00'),
        ('每天23点15分', 'daily 23:15'),
        ('每天', 'daily 09:00'),              # 未指定时刻 -> 兜底早9点
        ('每周一10:30', 'weekly 0 10:30'),
        ('每周五晚上8点', 'weekly 4 20:00'),
        ('每周日9点', 'weekly 6 09:00'),
        ('每小时', 'hourly 00'),
        ('每小时15分', 'hourly 15'),
        ('每30分钟', 'interval 30'),
        ('每隔5分钟', 'interval 5'),
    ])
    def test_ok(self, text, expect):
        ok, desc, _ = parse_nl(text)
        assert ok and desc == expect

    @pytest.mark.parametrize('text', [
        '', '  ', '明天记得提醒我', '每月1号检查',
    ])
    def test_bad(self, text):
        ok, _, _ = parse_nl(text)
        assert ok is False

    def test_invalid_weekday(self):
        ok, _, reason = parse_nl('每周十10:30')
        assert ok is False and '星期' in reason


class TestNextRunAt:
    def _now(self):
        return datetime(2026, 8, 8, 8, 0, 0)  # 周六 08:00

    def test_daily_past_today(self):
        nxt = next_run_at('daily 09:00', self._now())
        assert nxt == datetime(2026, 8, 8, 9, 0, 0)

    def test_daily_already_passed(self):
        nxt = next_run_at('daily 07:00', self._now())
        assert nxt == datetime(2026, 8, 9, 7, 0, 0)  # 今天已过 -> 明天

    def test_weekly_next_days(self):
        nxt = next_run_at('weekly 0 10:30', self._now())  # 周六 -> 下周一
        assert nxt == datetime(2026, 8, 10, 10, 30, 0)

    def test_weekly_same_day_later(self):
        nxt = next_run_at('weekly 5 20:00', self._now())  # 今天(周六)晚8点
        assert nxt == datetime(2026, 8, 8, 20, 0, 0)

    def test_hourly(self):
        nxt = next_run_at('hourly 30', datetime(2026, 8, 8, 8, 40, 0))
        assert nxt == datetime(2026, 8, 8, 9, 30, 0)

    def test_interval(self):
        nxt = next_run_at('interval 30', self._now())
        assert nxt == self._now() + timedelta(minutes=30)

    def test_invalid(self):
        assert next_run_at('monthly 1', self._now()) is None


class TestManager:
    def test_add_list_pause_resume_remove(self, _db):
        mgr = ScheduleManager()
        r = mgr.add('每天9点生成空气质量日报', '', '生成今日空气质量日报', 'craft')
        assert r['ok'] and r['cron_desc'] == 'daily 09:00'
        sid = r['id']
        rows = mgr.list()
        assert len(rows) == 1 and rows[0]['title'] == '每天9点生成空气质量日报'

        assert mgr.pause(sid)['ok']
        rows = mgr.list()
        assert rows[0]['enabled'] == 0

        assert mgr.resume(sid)['ok']
        rows = mgr.list()
        assert rows[0]['enabled'] == 1

        assert mgr.remove(sid)['ok']
        assert mgr.list() == []

    def test_add_explicit_cron(self, _db):
        mgr = ScheduleManager()
        r = mgr.add('空气质量日报', 'daily 07:30', '生成日报', 'craft')
        assert r['ok'] and r['cron_desc'] == 'daily 07:30'

    def test_add_invalid(self, _db):
        mgr = ScheduleManager()
        r = mgr.add('随便写点什么', '', '', 'craft')
        assert not r['ok'] and 'error' in r

    def test_pause_nonexistent(self, _db):
        assert ScheduleManager().pause(999)['ok'] is False

    def test_resume_recomputes_next_run(self, _db):
        mgr = ScheduleManager()
        r = mgr.add('每小时', '', '', 'craft')
        sid = r['id']
        mgr.pause(sid)
        mgr.resume(sid)
        row = mgr.list()[0]
        assert row['next_run'] is not None


class TestTick:
    def test_tick_fires_due_task(self, _db, monkeypatch):
        fired = {}

        def fake_trigger(item):
            fired.update(item)

        monkeypatch.setattr('src.scheduler._trigger_task', fake_trigger)
        mgr = ScheduleManager()
        r = mgr.add('每1分钟', '', '做点事', 'craft')
        sid = r['id']
        # 直接把 next_run 拨到过去，触发到期
        from src.core.db import get_conn
        get_conn().execute(
            'UPDATE task_schedule SET next_run=? WHERE id=?',
            ((datetime.now() - timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%S'), sid))
        get_conn().commit()

        out = mgr.tick()
        assert len(out) == 1 and out[0]['id'] == sid
        assert fired.get('id') == sid
        # 触发后 next_run 已推进到未来，不再重复触发
        assert mgr.tick() == []

    def test_tick_skips_disabled(self, _db, monkeypatch):
        calls = []

        def fake_trigger(item):
            calls.append(item)

        monkeypatch.setattr('src.scheduler._trigger_task', fake_trigger)
        mgr = ScheduleManager()
        r = mgr.add('每1分钟', '', '', 'craft')
        mgr.pause(r['id'])
        assert mgr.tick() == [] and calls == []

    def test_reentry_guard(self, _db, monkeypatch):
        """上次触发距今 <60s：不重复触发。"""
        calls = []

        def fake_trigger(item):
            calls.append(item)

        monkeypatch.setattr('src.scheduler._trigger_task', fake_trigger)
        mgr = ScheduleManager()
        r = mgr.add('每1分钟', '', '', 'craft')
        sid = r['id']
        past = datetime.now() - timedelta(minutes=1)
        from src.core.db import get_conn
        get_conn().execute(
            'UPDATE task_schedule SET next_run=?, last_run=? WHERE id=?',
            (past.strftime('%Y-%m-%dT%H:%M:%S'),
             (datetime.now() - timedelta(seconds=10)).strftime('%Y-%m-%dT%H:%M:%S'), sid))
        get_conn().commit()
        assert mgr.tick() == [] and calls == []


class TestStartScheduler:
    def test_start_scheduler_thread(self, _db):
        th = start_scheduler()
        assert th.name == 'ea-scheduler' and th.is_alive()
