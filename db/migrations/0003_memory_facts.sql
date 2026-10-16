-- M2/M4 事实记忆：结构化事实/偏好/约束/结论表。
-- 时间维度：valid_from / valid_until（NULL=当前有效）；冲突消解：审批激活时置旧事实 valid_until。
-- 幂等：表已存在时静默跳过。
CREATE TABLE IF NOT EXISTS memory_facts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity TEXT NOT NULL,
  attr TEXT NOT NULL,
  value TEXT NOT NULL,
  ftype TEXT NOT NULL DEFAULT 'fact',
  source TEXT NOT NULL DEFAULT '',
  valid_from TEXT NOT NULL,
  valid_until TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_facts_key ON memory_facts(entity, attr);
