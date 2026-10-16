# -*- coding: utf-8 -*-
"""G4 会话断点续传：save/resume/clear + 恢复上下文注入。"""
from __future__ import annotations

import pytest

from src.agents.checkpoint import CheckpointManager


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'checkpoint.db'))
    import db as v12_db
    v12_db.init_db()  # 应用根 SCHEMA（含 task_checkpoints 表）
    from src.core import config, db as core_db
    config.get_settings.cache_clear()
    core_db.run_migrations()
    yield


class TestCheckpointManager:
    def test_save_get(self, _db):
        mgr = CheckpointManager()
        r = mgr.save(1, round_no=2, window_summary='已完成点位布置',
                     done_steps=[{'name': 'kb_lookup', 'ok': True}],
                     partial_outputs={'points': 3})
        assert r['ok'] and r['status'] == 'paused'
        ck = mgr.get(1)
        assert ck['round'] == 2
        assert ck['status'] == 'paused'
        assert ck['window_summary'] == '已完成点位布置'
        assert ck['done_steps'][0]['name'] == 'kb_lookup'

    def test_upsert_idempotent(self, _db):
        mgr = CheckpointManager()
        mgr.save(1, round_no=1, window_summary='a')
        mgr.save(1, round_no=3, window_summary='b')  # 同一任务覆盖
        ck = mgr.get(1)
        assert ck['round'] == 3 and ck['window_summary'] == 'b'

    def test_get_missing(self, _db):
        assert CheckpointManager().get(999) is None

    def test_resume_marks_status(self, _db):
        mgr = CheckpointManager()
        mgr.save(1, window_summary='x')
        ck = mgr.resume(1)
        assert ck is not None and ck['status'] == 'resumed'
        assert mgr.get(1)['status'] == 'resumed'

    def test_resume_missing(self, _db):
        assert CheckpointManager().resume(999) is None

    def test_clear(self, _db):
        mgr = CheckpointManager()
        mgr.save(1)
        mgr.clear(1)
        assert mgr.get(1) is None

    def test_build_resume_context(self, _db):
        mgr = CheckpointManager()
        mgr.save(1, round_no=2, window_summary='进度摘要内容',
                 done_steps=[{'name': 'kb_lookup', 'ok': True},
                             {'name': 'calc_formula', 'ok': False}])
        ctx = mgr.build_resume_context(mgr.get(1))
        assert '会话恢复' in ctx
        assert '进度摘要内容' in ctx
        assert 'kb_lookup(已完成)' in ctx
        assert 'calc_formula(失败)' in ctx

    def test_db_layer(self, _db):
        """根 db.py 数据层直连可用（幂等 upsert + 删除联动）。"""
        import db as v12_db
        v12_db.save_checkpoint(7, round_no=1, window_summary='s')
        assert v12_db.get_checkpoint(7)['window_summary'] == 's'
        v12_db.checkpoint_set_status(7, 'resumed')
        assert v12_db.get_checkpoint(7)['status'] == 'resumed'
        v12_db.clear_checkpoint(7)
        assert v12_db.get_checkpoint(7) is None
        # 删除任务联动清理断点（直接 SQL 建任务，避免写真实 task_outputs 目录）
        tid = v12_db.w("INSERT INTO tasks(title) VALUES(?)", ('ck-test',))
        v12_db.save_checkpoint(tid, window_summary='x')
        v12_db.delete_task(tid)
        assert v12_db.get_checkpoint(tid) is None
