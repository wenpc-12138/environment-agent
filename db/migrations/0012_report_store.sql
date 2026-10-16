-- M19 报告持久化：报告实例 / 章节 / 标准引用落库（重启不丢数据）
-- reports          报告主表（元数据 + 正文快照）
-- report_sections  章节表（name/content/refs，seq 顺序）
-- report_citations 标准引用表（含有效性标注，M06 强制标注）
CREATE TABLE IF NOT EXISTS reports (
  report_id    TEXT PRIMARY KEY,
  type         TEXT NOT NULL DEFAULT '',
  project_id   TEXT NOT NULL DEFAULT '',
  version      INTEGER NOT NULL DEFAULT 1,
  status       TEXT NOT NULL DEFAULT 'drafting',
  created_by   TEXT NOT NULL DEFAULT 'R4',
  content      TEXT NOT NULL DEFAULT '',
  docx_path    TEXT NOT NULL DEFAULT '',
  data_sources TEXT NOT NULL DEFAULT '[]',
  created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  updated_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_reports_status  ON reports(status);
CREATE INDEX IF NOT EXISTS idx_reports_type   ON reports(type);
CREATE INDEX IF NOT EXISTS idx_reports_updated ON reports(updated_at DESC);

CREATE TABLE IF NOT EXISTS report_sections (
  report_id TEXT NOT NULL,
  seq       INTEGER NOT NULL,
  name      TEXT NOT NULL DEFAULT '',
  content   TEXT NOT NULL DEFAULT '',
  refs      TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (report_id, seq)
);

CREATE TABLE IF NOT EXISTS report_citations (
  report_id TEXT NOT NULL,
  code      TEXT NOT NULL,
  clause    TEXT NOT NULL DEFAULT '',
  valid     INTEGER NOT NULL DEFAULT 1,
  source    TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (report_id, code)
);
