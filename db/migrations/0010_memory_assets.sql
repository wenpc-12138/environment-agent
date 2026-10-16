-- 0010 统一记忆资产目录（Memory Assets 轻量版：所有权/可见性/使用统计）
-- 对标 TencentDB-Agent-Memory 的 Memory Assets + ACL 治理
CREATE TABLE IF NOT EXISTS memory_assets(
  asset_id      TEXT PRIMARY KEY,        -- 形如 'episodic:123' / 'fact:456' / 'skill:xx'
  asset_type    TEXT NOT NULL,           -- episodic / fact / skill / profile / summary
  source_id     TEXT NOT NULL,           -- 各层原始记录 id
  visibility    TEXT NOT NULL DEFAULT 'private', -- private / team / agent
  team_id       TEXT DEFAULT '',         -- 团队共享时的团队 id
  owner         TEXT NOT NULL DEFAULT 'local',
  title         TEXT DEFAULT '',
  content_preview TEXT DEFAULT '',       -- 内容预览（供面板展示）
  use_count     INTEGER NOT NULL DEFAULT 0,  -- 召回次数（排序加权/淘汰依据）
  status        TEXT NOT NULL DEFAULT 'active', -- active / archived
  created_at    TEXT DEFAULT (datetime('now','localtime')),
  updated_at    TEXT DEFAULT (datetime('now','localtime')),
  last_used_at  TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_mem_assets_type ON memory_assets(asset_type);
CREATE INDEX IF NOT EXISTS idx_mem_assets_vis ON memory_assets(visibility, status);

-- L2 场景记忆：任务摘要索引表（M5 摘要从"只落盘"升级为"可召回"）
CREATE TABLE IF NOT EXISTS task_summaries(
  task_id    TEXT PRIMARY KEY,
  title      TEXT DEFAULT '',
  abstract   TEXT DEFAULT '',   -- L1 摘要（原子概述）
  overview   TEXT DEFAULT '',   -- L2 概览（跨任务可复用经验）
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_task_summaries_t ON task_summaries(title);
