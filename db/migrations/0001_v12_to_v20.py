# -*- coding: utf-8 -*-
"""v1.2 → v2.0 基线迁移 0001（M19）。

双轨共存原则（见 db/migrations/README.md）：
- v1.2 Flask（run.py / 根目录 db.py）与 v2.0（src/）共用 `data/ecoagent.db`。
- 本迁移**只加列 / 只建新表**，禁止破坏性重建 v1.2 既有表。
- 幂等：列已存在 / 表已存在时静默跳过；重复执行安全。
- 迁移前自动备份 db 文件到 `<db_dir>/backups/auto/`。
"""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# M06 StandardKB 需要的 kb_entries 扩展列（check_validity / get_standard）
_KB_EXTRA_COLUMNS: tuple[tuple[str, str], ...] = (
    ('standard_code', 'standard_code TEXT DEFAULT \'\''),
    ('validity_status', 'validity_status TEXT DEFAULT \'\''),
    ('effective_date', 'effective_date TEXT DEFAULT \'\''),
)

_NEW_TABLES_SQL = """
-- M05 EpisodicMemory 事件表（FTS 索引随 M05 实现落地）
CREATE TABLE IF NOT EXISTS memory_episodes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity TEXT NOT NULL,
  event TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  ts TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT ''
);

-- M07 / M05 ProceduralMemory Skill 库（SkillDef 契约 §2）
CREATE TABLE IF NOT EXISTS v2_skills(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  level INTEGER NOT NULL DEFAULT 1,
  role TEXT NOT NULL,
  domain TEXT NOT NULL,
  version TEXT NOT NULL DEFAULT '1.0.0',
  status TEXT NOT NULL DEFAULT 'active',
  definition TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT 'manual',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- M14 安全审计哈希链（表结构预留，逻辑随 M14 实现）
CREATE TABLE IF NOT EXISTS audit_log(
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  who TEXT NOT NULL,
  action TEXT NOT NULL,
  input_hash TEXT NOT NULL DEFAULT '',
  output_hash TEXT NOT NULL DEFAULT '',
  prev_hash TEXT NOT NULL DEFAULT '',
  ts TEXT NOT NULL
);
"""


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """表存在且列缺失时补列（SQLite 加列天然幂等前置检查）。"""
    if not _has_table(conn, table):
        return
    if column not in _columns(conn, table):
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {ddl}')


def run(conn: sqlite3.Connection, db_file: Path) -> None:
    """应用 v1.2 → v2.0 基线演进：备份 + kb_entries 加列 + 建 v2 新表。"""
    db_file = Path(db_file)
    # 1) 迁移前备份（仅当库文件存在）
    if db_file.exists():
        backup_dir = db_file.parent / 'backups' / 'auto'
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        target = backup_dir / f'v12_before_v20_{stamp}.db'
        shutil.copy2(db_file, target)
    # 2) kb_entries 加列（v1.2 有该表才补）
    for column, ddl in _KB_EXTRA_COLUMNS:
        _ensure_column(conn, 'kb_entries', column, ddl)
    # 3) 建 v2 新表（幂等）
    conn.executescript(_NEW_TABLES_SQL)
