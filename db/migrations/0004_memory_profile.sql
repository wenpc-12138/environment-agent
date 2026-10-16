-- M3 用户画像：跨会话蒸馏的稳定用户属性（对齐腾讯 Agent Memory L3 用户画像）。
-- user_key 多用户隔离（默认 'local'）；weight 聚合权重；updated_at 更新时间。
CREATE TABLE IF NOT EXISTS memory_profile(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_key TEXT NOT NULL,
  attr TEXT NOT NULL,
  value TEXT NOT NULL,
  weight INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_profile_user ON memory_profile(user_key);
