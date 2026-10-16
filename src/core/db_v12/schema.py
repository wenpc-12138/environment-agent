# -*- coding: utf-8 -*-
"""S1-W5 db.py 拆分：数据库 Schema 常量（SCHEMA + FTS_TRIGGERS）。

从根 db.py 原样搬移（纯数据常量），供 src/core/db_v12/base.py 使用。
"""
SCHEMA = """
CREATE TABLE IF NOT EXISTS providers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'openai',
  model TEXT NOT NULL,
  base_url TEXT DEFAULT '',
  api_key TEXT DEFAULT '',
  reasoning_effort TEXT NOT NULL DEFAULT 'high',
  context_length INTEGER DEFAULT 0,
  use_server_search INTEGER DEFAULT 0,
  is_active INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL DEFAULT '新任务',
  mode TEXT NOT NULL DEFAULT 'craft',
  status TEXT NOT NULL DEFAULT 'idle',
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT DEFAULT '',
  meta TEXT DEFAULT '{}',
  tokens INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS kb_entries(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  url TEXT DEFAULT '',
  category TEXT DEFAULT 'network',
  source TEXT DEFAULT '',
  content TEXT NOT NULL,
  score REAL DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
  title, content, content='kb_entries', content_rowid='id', tokenize='unicode61'
);
-- S1-W3 trigram 增强通道:标准号/数字/英文子串召回(与 kb_fts 双轨,不替换);
-- 存量库由迁移 0015_kb_fts_trigram.py 建立并 rebuild,此处供新库初始化兜底
CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts_tg USING fts5(
  title, content, content='kb_entries', content_rowid='id', tokenize='trigram'
);
CREATE TABLE IF NOT EXISTS memory_entries(
  key TEXT PRIMARY KEY,
  content TEXT NOT NULL,
  hits INTEGER DEFAULT 0,
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS cache_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER DEFAULT 0,
  provider_id INTEGER DEFAULT 0,
  model TEXT DEFAULT '',
  prompt_tokens INTEGER DEFAULT 0,
  completion_tokens INTEGER DEFAULT 0,
  cache_hit INTEGER DEFAULT 0,
  cache_miss INTEGER DEFAULT 0,
  cache_creation INTEGER DEFAULT 0,
  thinking_tokens INTEGER DEFAULT 0,
  latency_ms INTEGER DEFAULT 0,
  mode TEXT DEFAULT '',
  domain TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS skills_state(
  key TEXT PRIMARY KEY,
  enabled INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS search_cache(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  query_hash TEXT NOT NULL UNIQUE,
  query_text TEXT NOT NULL,
  results_json TEXT NOT NULL,
  provider TEXT DEFAULT '',
  ttl_hours INTEGER DEFAULT 24,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS kb_versions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id INTEGER NOT NULL,
  prev_id INTEGER DEFAULT 0,
  version INTEGER DEFAULT 1,
  diff TEXT DEFAULT '',
  note TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS kb_corrections(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id INTEGER NOT NULL,
  reporter TEXT DEFAULT '',
  issue TEXT NOT NULL,
  suggestion TEXT DEFAULT '',
  corrected_content TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS kb_relations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_id INTEGER NOT NULL,
  to_id INTEGER NOT NULL,
  rel_type TEXT NOT NULL DEFAULT 'related',
  note TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS kb_sources(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id INTEGER NOT NULL,
  kind TEXT DEFAULT 'web',
  name TEXT DEFAULT '',
  url TEXT DEFAULT '',
  fetched_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS kb_chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id INTEGER NOT NULL,
  chunk_index INTEGER DEFAULT 0,
  chunk_type TEXT DEFAULT 'para',
  content TEXT NOT NULL,
  token_count INTEGER DEFAULT 0,
  embedding BLOB,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_entry ON kb_chunks(entry_id);
CREATE TABLE IF NOT EXISTS kb_imports(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_name TEXT DEFAULT '',
  status TEXT DEFAULT 'running',
  total_files INTEGER DEFAULT 0,
  ok_files INTEGER DEFAULT 0,
  fail_files INTEGER DEFAULT 0,
  entry_ids TEXT DEFAULT '[]',
  report_json TEXT DEFAULT '{}',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS kb_query_cache(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  query_hash TEXT NOT NULL UNIQUE,
  query_text TEXT NOT NULL,
  results_json TEXT NOT NULL,
  hit_count INTEGER DEFAULT 0,
  last_hit_at TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS kb_memories(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_type TEXT DEFAULT 'fact',
  scope TEXT DEFAULT 'kb',
  scope_id TEXT DEFAULT '',
  content TEXT NOT NULL,
  confidence REAL DEFAULT 0.6,
  source_conversation TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS kb_audits(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report_json TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS kb_import_qc(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER DEFAULT 0,
  file TEXT DEFAULT '',
  title TEXT DEFAULT '',
  verdict TEXT DEFAULT 'pass',
  reason TEXT DEFAULT '',
  entry_id INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS kb_backups(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT DEFAULT 'manual',
  path TEXT NOT NULL,
  db_size INTEGER DEFAULT 0,
  files_count INTEGER DEFAULT 0,
  status TEXT DEFAULT 'done',
  note TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
-- G4 会话断点续传：任务中途暂停落点，恢复时注入摘要继续
CREATE TABLE IF NOT EXISTS task_checkpoints(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL UNIQUE,
  round INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'paused',   -- paused=暂停待恢复 / resumed=已恢复进行中 / ''=未暂停
  window_summary TEXT DEFAULT '',
  done_steps TEXT DEFAULT '[]',            -- 已完成步骤 JSON（工具轨迹摘要）
  partial_outputs TEXT DEFAULT '{}',       -- 中间产物片段 JSON
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);
"""


FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS kb_ai AFTER INSERT ON kb_entries BEGIN
  INSERT INTO kb_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
CREATE TRIGGER IF NOT EXISTS kb_ad AFTER DELETE ON kb_entries BEGIN
  INSERT INTO kb_fts(kb_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
END;
CREATE TRIGGER IF NOT EXISTS kb_au AFTER UPDATE ON kb_entries BEGIN
  INSERT INTO kb_fts(kb_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
  INSERT INTO kb_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
-- S1-W3: kb_fts_tg(trigram) 同步触发器(与 kb_fts 同构,独立命名)
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
"""
