-- 0011 Wiki 资产 + 任务符号画布（对齐 TencentDB-Agent-Memory 的 Wiki 知识资产
-- 与 Mermaid 符号画布 / 上下文卸载设计）

-- Wiki 知识资产：人工沉淀 / 任务自动提炼的结构化文档知识
CREATE TABLE IF NOT EXISTS wiki_entries(
  id          TEXT PRIMARY KEY,             -- 'wiki-<md5前8>-<seq>'
  title       TEXT NOT NULL,
  content     TEXT DEFAULT '',              -- Markdown 正文
  tags        TEXT DEFAULT '',              -- 逗号分隔标签
  source      TEXT DEFAULT '',              -- 来源（任务号/文件/链接）
  visibility  TEXT NOT NULL DEFAULT 'private', -- private / team / agent
  owner       TEXT NOT NULL DEFAULT 'local',
  created_by  TEXT NOT NULL DEFAULT 'manual',   -- manual / agent_forge
  use_count   INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT DEFAULT (datetime('now','localtime')),
  updated_at  TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_wiki_title ON wiki_entries(title);
CREATE INDEX IF NOT EXISTS idx_wiki_vis ON wiki_entries(visibility);

-- 任务符号画布：Mermaid 图 + offload 统计（对齐 TencentDB 短期任务上下文卸载）
CREATE TABLE IF NOT EXISTS task_canvases(
  task_id       TEXT PRIMARY KEY,
  canvas_md     TEXT DEFAULT '',   -- Mermaid 图源码
  node_count    INTEGER DEFAULT 0,
  offloaded     INTEGER DEFAULT 0, -- 卸载的工具输出条数
  offloaded_chars INTEGER DEFAULT 0, -- 卸载的总字符数
  created_at    TEXT DEFAULT (datetime('now','localtime'))
);
