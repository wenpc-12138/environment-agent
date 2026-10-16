-- S1-W1 工作流实例持久化：M09 状态机实例落库（重启不丢状态）
-- workflow_instances 实例主表：state / payload / history / retry_count 全量持久化
CREATE TABLE IF NOT EXISTS workflow_instances (
  instance_id TEXT PRIMARY KEY,
  workflow    TEXT NOT NULL DEFAULT '',
  state       TEXT NOT NULL DEFAULT '',
  payload     TEXT NOT NULL DEFAULT '{}',
  history     TEXT NOT NULL DEFAULT '[]',
  retry_count INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_workflow_instances_workflow ON workflow_instances(workflow);
CREATE INDEX IF NOT EXISTS idx_workflow_instances_state    ON workflow_instances(state);
