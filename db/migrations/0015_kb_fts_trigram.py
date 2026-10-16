# -*- coding: utf-8 -*-
"""S1-W3 FTS5 中文检索增强（0015）：新增 trigram FTS 表 kb_fts_tg（幂等）。

背景：kb_fts 使用 unicode61 分词，中文检索依赖 `_build_fts_query` 二元分词
OR 组合；对标准号/英文数字子串召回弱（如查 "3095" 无法命中 "GB 3095-2012"）。
trigram 分词对 >=3 字符的子串召回强，但 <3 字符（2 字中文如"氨氮"）无法命中，
故**不替换** kb_fts，而是新增 kb_fts_tg（trigram）作为增强通道（双 FTS 表，
零回归）：中文检索仍走 kb_fts（unicode61），标准号/数字/英文子串走 kb_fts_tg。

本迁移：
1. 建 kb_fts_tg（trigram，外部内容表 content='kb_entries'）；
2. rebuild 回灌存量数据；
3. 建同步触发器（INSERT/DELETE/UPDATE 联动 kb_entries）。
"""
from __future__ import annotations

import sqlite3


def run(conn: sqlite3.Connection, db_file) -> None:
    # 前置：确保 kb_entries 存在（v1.2 init_db / StandardKB._ensure_kb_table 兜底建表，
    # 临时库 run_migrations 时可能尚未建表；此处建与 StandardKB._ensure_kb_table 一致的
    # 完整结构，避免最小结构遮蔽后续完整建表导致缺列）
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS kb_entries (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT, url TEXT, category TEXT, content TEXT, source TEXT,
      item_type TEXT, domain TEXT, source_type TEXT, validity TEXT,
      confidence REAL, status TEXT, std_no TEXT, org TEXT,
      publish_date TEXT, implement_date TEXT, metadata_json TEXT,
      standard_code TEXT, validity_status TEXT, effective_date TEXT,
      updated_at TEXT
    );
    ''')
    conn.executescript('''
    CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts_tg USING fts5(
      title, content, content='kb_entries', content_rowid='id', tokenize='trigram'
    );
    ''')
    # 回灌存量数据（幂等：外部内容表 rebuild 全量重建）
    try:
        conn.execute("INSERT INTO kb_fts_tg(kb_fts_tg) VALUES('rebuild')")
        conn.commit()
    except sqlite3.OperationalError:
        # 表刚建且为空时 rebuild 无副作用；异常静默（外部内容表未就绪场景）
        pass
    # 同步触发器（与 kb_fts 的 FTS_TRIGGERS 同构，独立命名避免冲突）
    conn.executescript('''
    CREATE TRIGGER IF NOT EXISTS kb_tg_ai AFTER INSERT ON kb_entries BEGIN
      INSERT INTO kb_fts_tg(rowid, title, content) VALUES (new.id, new.title, new.content);
    END;
    CREATE TRIGGER IF NOT EXISTS kb_tg_ad AFTER DELETE ON kb_entries BEGIN
      INSERT INTO kb_fts_tg(kb_fts_tg, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
    END;
    CREATE TRIGGER IF NOT EXISTS kb_tg_au AFTER UPDATE ON kb_entries BEGIN
      INSERT INTO kb_fts_tg(kb_fts_tg, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
      INSERT INTO kb_fts_tg(rowid, title, content) VALUES (new.id, new.title, new.content);
    END;
    ''')
    conn.commit()
