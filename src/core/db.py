# -*- coding: utf-8 -*-
"""v2.0 统一 SQLite 连接层（coding_standards §4）。

- src/ 全部模块通过 `get_conn()` 获取连接（threading.local 线程隔离）。
- `run_migrations()` 按编号顺序应用 `db/migrations/NNNN_*.sql` 与 `NNNN_*.py`（幂等，记录于
  `schema_migrations` 表）；禁止手改线上 schema。
- `.py` 迁移约定：文件导出 `run(conn, db_file)`，适合加列检查 / 数据转换 / FTS 重建等
  SQL 表达不了的逻辑（如 `0001_v12_to_v20.py`）。
- FTS5 中文检索统一使用 jieba 预分词（M06 迁移知识库时落地），不依赖 SQLite 内置分词器。
"""
from __future__ import annotations

import importlib.util
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .config import get_settings

_thread_local = threading.local()


def get_conn() -> sqlite3.Connection:
    """获取当前线程的连接（自动建库目录、开外键、WAL 模式）。"""
    conn = getattr(_thread_local, 'conn', None)
    if conn is None:
        db_file = get_settings().db_file
        db_file.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_file), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('PRAGMA journal_mode = WAL')
        _thread_local.conn = conn
    return conn


def close_db() -> None:
    """关闭当前线程连接（幂等）。"""
    conn = getattr(_thread_local, 'conn', None)
    if conn is not None:
        conn.close()
        _thread_local.conn = None


def _load_py_migration(path: Path) -> Any:
    """动态加载 .py 迁移模块（约定：导出 `run(conn, db_file)` 函数）。"""
    spec = importlib.util.spec_from_file_location(f'ea_mig_{path.stem}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _applied_migrations(conn: sqlite3.Connection) -> set[str]:
    conn.execute(
        'CREATE TABLE IF NOT EXISTS schema_migrations('
        '  version TEXT PRIMARY KEY,'
        '  applied_at TEXT DEFAULT (datetime(\'now\',\'localtime\'))'
        ')'
    )
    rows = conn.execute('SELECT version FROM schema_migrations').fetchall()
    return {r['version'] for r in rows}


def run_migrations() -> list[str]:
    """按编号顺序应用迁移脚本，返回本次应用的版本列表。"""
    applied: list[str] = []
    conn = get_conn()
    done = _applied_migrations(conn)
    mig_dir = get_settings().migrations_dir_path
    if not mig_dir.is_dir():
        return applied
    for f in sorted(mig_dir.glob('*.sql')):
        version = f.stem
        if version in done:
            continue
        sql = f.read_text(encoding='utf-8')
        with conn:  # 单事务：脚本 + 版本记录原子应用
            conn.executescript(sql)
            conn.execute('INSERT INTO schema_migrations(version) VALUES (?)', (version,))
        applied.append(version)
    for f in sorted(mig_dir.glob('*.py')):
        version = f.stem
        if version in done:
            continue
        mod = _load_py_migration(f)
        with conn:
            if callable(getattr(mod, 'run', None)):
                mod.run(conn, get_settings().db_file)
            conn.execute('INSERT INTO schema_migrations(version) VALUES (?)', (version,))
        applied.append(version)
    return applied
