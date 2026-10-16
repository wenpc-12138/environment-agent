-- S3-H1 goal 持久化目标（对标 Harness goal 子系统）
-- goals 目标表：任务收尾自动登记「目标-进度」结构，供任务侧栏展示进度
CREATE TABLE IF NOT EXISTS goals (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id     INTEGER NOT NULL DEFAULT 0,
  objective   TEXT NOT NULL DEFAULT '',
  status      TEXT NOT NULL DEFAULT 'in_progress',  -- in_progress / completed / abandoned
  progress    INTEGER NOT NULL DEFAULT 0,           -- 0..100
  created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_goals_task    ON goals(task_id);
CREATE INDEX IF NOT EXISTS idx_goals_status  ON goals(status);
