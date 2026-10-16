# -*- coding: utf-8 -*-
"""S1-W2 审计链落库（0014）：audit_log 表补全 hash/ok 列 + 索引（幂等）。

背景：`0001_v12_to_v20.py` 已创建 audit_log 表（seq/who/action/input_hash/
output_hash/prev_hash/ts，无 hash/ok 列）；本迁移对存量表做列探测补列
（ALTER TABLE ADD COLUMN），并用 CREATE TABLE IF NOT EXISTS 兜底空库。
SQL 无法表达"列不存在才加"，故用 .py 迁移（约定：导出 run(conn, db_file)）。
"""
from __future__ import annotations

import sqlite3


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f'PRAGMA table_info({table})').fetchall()
    return {r['name'] for r in rows}


def run(conn: sqlite3.Connection, db_file) -> None:
    # 空库兜底：完整建表（幂等）
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS audit_log (
      seq          INTEGER PRIMARY KEY AUTOINCREMENT,
      who          TEXT NOT NULL DEFAULT '',
      action       TEXT NOT NULL DEFAULT '',
      input_hash   TEXT NOT NULL DEFAULT '',
      output_hash  TEXT NOT NULL DEFAULT '',
      prev_hash    TEXT NOT NULL DEFAULT 'GENESIS',
      ts           TEXT NOT NULL DEFAULT '',
      hash         TEXT NOT NULL DEFAULT '',
      ok           INTEGER NOT NULL DEFAULT 1
    );
    ''')
    # 存量表补列（0001 建的旧表缺 hash/ok）
    cols = _columns(conn, 'audit_log')
    if 'hash' not in cols:
        conn.execute("ALTER TABLE audit_log ADD COLUMN hash TEXT NOT NULL DEFAULT ''")
    if 'ok' not in cols:
        conn.execute('ALTER TABLE audit_log ADD COLUMN ok INTEGER NOT NULL DEFAULT 1')
    # 索引（幂等）
    conn.executescript('''
    CREATE INDEX IF NOT EXISTS idx_audit_log_who    ON audit_log(who);
    CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
    CREATE INDEX IF NOT EXISTS idx_audit_log_ts     ON audit_log(ts);
    ''')
    # 存量数据补哈希：为已有行计算链式 hash（按 seq 顺序，prev 链式）
    rows = conn.execute(
        'SELECT seq, who, action, input_hash, output_hash, prev_hash, ts, hash'
        ' FROM audit_log ORDER BY seq').fetchall()
    need_fix = [r for r in rows if not (r['hash'] or '')]
    if need_fix:
        import hashlib
        prev_hash = 'GENESIS'
        for r in conn.execute('SELECT * FROM audit_log ORDER BY seq').fetchall():
            payload = '|'.join([
                str(r['seq']), r['who'] or '', r['action'] or '',
                r['input_hash'] or '', r['output_hash'] or '',
                (r['prev_hash'] if (r['prev_hash'] or '') else prev_hash),
                r['ts'] or '',
            ])
            h = hashlib.sha256(payload.encode('utf-8')).hexdigest()
            conn.execute('UPDATE audit_log SET hash=?, prev_hash=? WHERE seq=?',
                         (h, (r['prev_hash'] if (r['prev_hash'] or '') else prev_hash),
                          r['seq']))
            prev_hash = h
    conn.commit()
