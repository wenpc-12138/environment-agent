-- H2 自然语言定时任务：应用内轻量调度器（对齐 Hermes 内置调度器，零新增依赖）。
-- cron_desc 支持四类：daily HH:MM / weekly W HH:MM / hourly MM / interval N(分钟)
CREATE TABLE IF NOT EXISTS task_schedule(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  cron_desc TEXT NOT NULL,
  prompt TEXT NOT NULL DEFAULT '',
  mode TEXT NOT NULL DEFAULT 'craft',
  enabled INTEGER NOT NULL DEFAULT 1,
  next_run TEXT,          -- 下次执行时间（本地时间 ISO，如 2026-08-08T09:00:00）
  last_run TEXT,          -- 上次触发时间（本地时间 ISO）
  last_status TEXT NOT NULL DEFAULT '',   -- ok / no_provider / error:<简述>
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_task_schedule_next ON task_schedule(enabled, next_run);
