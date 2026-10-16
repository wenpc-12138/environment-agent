# -*- coding: utf-8 -*-
"""db 模块测试：连接、迁移、线程隔离（全部在临时库上运行，不碰 data/ecoagent.db）。"""
from __future__ import annotations

import sqlite3

import pytest

from src.core import config, db


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """每个用例指向临时数据库并清理连接缓存。"""
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'test.db'))
    config.get_settings.cache_clear()
    yield
    db.close_db()
    config.get_settings.cache_clear()


def test_get_conn_creates_file(tmp_path) -> None:
    """首次连接自动创建数据库文件与目录。"""
    conn = db.get_conn()
    assert isinstance(conn, sqlite3.Connection)
    assert (tmp_path / 'test.db').exists()
    assert conn.execute('SELECT 1').fetchone()[0] == 1


def test_conn_thread_local() -> None:
    """线程隔离：不同线程连接不同。"""
    import threading

    conns: list = []

    def worker():
        conns.append(db.get_conn())

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert conns[0] is not db.get_conn()


def test_close_db_idempotent() -> None:
    """close_db 幂等。"""
    db.get_conn()
    db.close_db()
    db.close_db()


def test_run_migrations_with_sql(tmp_path, monkeypatch) -> None:
    """应用迁移脚本并记录版本，二次运行跳过。"""
    mig_dir = tmp_path / 'migrations'
    mig_dir.mkdir()
    (mig_dir / '0001_demo.sql').write_text(
        'CREATE TABLE IF NOT EXISTS demo_tbl(id INTEGER PRIMARY KEY);',
        encoding='utf-8',
    )
    monkeypatch.setenv('MIGRATIONS_DIR', str(mig_dir))
    config.get_settings.cache_clear()
    try:
        assert db.run_migrations() == ['0001_demo']
        assert db.run_migrations() == []  # 幂等
        cols = db.get_conn().execute("SELECT name FROM sqlite_master WHERE name='demo_tbl'").fetchone()
        assert cols is not None
        ver = db.get_conn().execute('SELECT version FROM schema_migrations').fetchall()
        assert [r['version'] for r in ver] == ['0001_demo']
    finally:
        config.get_settings.cache_clear()


def test_run_migrations_with_py(tmp_path, monkeypatch) -> None:
    """.py 迁移脚本：run(conn, db_file) 被调用、版本记录、幂等。"""
    mig_dir = tmp_path / 'migrations'
    mig_dir.mkdir()
    (mig_dir / '0002_py_demo.py').write_text(
        'def run(conn, db_file):\n'
        "    conn.execute('CREATE TABLE IF NOT EXISTS py_tbl(id INTEGER PRIMARY KEY)')\n",
        encoding='utf-8',
    )
    monkeypatch.setenv('MIGRATIONS_DIR', str(mig_dir))
    config.get_settings.cache_clear()
    try:
        assert db.run_migrations() == ['0002_py_demo']
        assert db.run_migrations() == []  # 幂等
        row = db.get_conn().execute("SELECT name FROM sqlite_master WHERE name='py_tbl'").fetchone()
        assert row is not None
    finally:
        config.get_settings.cache_clear()


def test_run_migrations_mixed_sql_and_py(tmp_path, monkeypatch) -> None:
    """.sql 与 .py 混合按编号升序应用。"""
    mig_dir = tmp_path / 'migrations'
    mig_dir.mkdir()
    (mig_dir / '0001_a.sql').write_text(
        'CREATE TABLE IF NOT EXISTS a_tbl(id INTEGER);', encoding='utf-8'
    )
    (mig_dir / '0002_b.py').write_text(
        'def run(conn, db_file):\n'
        "    conn.execute('CREATE TABLE IF NOT EXISTS b_tbl(id INTEGER)')\n",
        encoding='utf-8',
    )
    monkeypatch.setenv('MIGRATIONS_DIR', str(mig_dir))
    config.get_settings.cache_clear()
    try:
        assert db.run_migrations() == ['0001_a', '0002_b']
        names = {r['name'] for r in db.get_conn().execute(
            "SELECT name FROM sqlite_master WHERE name IN ('a_tbl','b_tbl')")}
        assert names == {'a_tbl', 'b_tbl'}
    finally:
        config.get_settings.cache_clear()


def test_migration_0001_v12_to_v20(tmp_path, monkeypatch) -> None:
    """真实 0001 迁移冒烟：备份 + 加列 + 建新表 + 幂等（临时库，不碰 data/）。"""
    conn = db.get_conn()
    conn.execute('CREATE TABLE kb_entries(id INTEGER PRIMARY KEY, title TEXT, content TEXT)')
    conn.commit()
    applied = db.run_migrations()
    assert '0001_v12_to_v20' in applied
    cols = {r['name'] for r in conn.execute('PRAGMA table_info(kb_entries)')}
    assert {'standard_code', 'validity_status', 'effective_date'} <= cols
    for tbl in ('memory_episodes', 'v2_skills', 'audit_log'):
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
        ).fetchone()
        assert row is not None, f'缺表 {tbl}'
    assert db.run_migrations() == []  # 幂等
    backups = list((tmp_path / 'backups' / 'auto').glob('*.db'))
    assert len(backups) == 1
