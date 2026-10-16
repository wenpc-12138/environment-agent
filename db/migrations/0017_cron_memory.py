# -*- coding: utf-8 -*-
"""H3 Cron 记忆连续性（0017）：task_schedule 表补 notepad/continuity/last_summary 列。

背景：`0006_task_schedule.sql` 已建 task_schedule 表（无记忆列）；本迁移对存量表
做列探测补列（ALTER TABLE ADD COLUMN），空库用完整 CREATE 兜底。SQL 无法表达
"列不存在才加"，故用 .py 迁移（约定：导出 run(conn, db_file)）。
"""
from __future__ import annotations

import sqlite3


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f'PRAGMA table_info({table})').fetchall()
    return {r['name'] for r in rows}


def run(conn: sqlite3.Connection, db_file) -> None:
    # 空库兜底：完整建表（幂等）
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS task_schedule (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      cron_desc TEXT NOT NULL,
      prompt TEXT NOT NULL DEFAULT '',
      mode TEXT NOT NULL DEFAULT 'craft',
      enabled INTEGER NOT NULL DEFAULT 1,
      next_run TEXT,
      last_run TEXT,
      last_status TEXT NOT NULL DEFAULT '',
      notepad TEXT NOT NULL DEFAULT '',
      continuity INTEGER NOT NULL DEFAULT 1,
      last_summary TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT
    );
    ''')
    # 存量表补列（0006 建的旧表缺记忆列）
    cols = _columns(conn, 'task_schedule')
    if 'notepad' not in cols:
        conn.execute("ALTER TABLE task_schedule ADD COLUMN notepad TEXT NOT NULL DEFAULT ''")
    if 'continuity' not in cols:
        conn.execute('ALTER TABLE task_schedule ADD COLUMN continuity INTEGER NOT NULL DEFAULT 1')
    if 'last_summary' not in cols:
        conn.execute("ALTER TABLE task_schedule ADD COLUMN last_summary TEXT NOT NULL DEFAULT ''")
    conn.commit()
