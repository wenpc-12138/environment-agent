-- H1 技能迭代提案：同 gap 技能已存在时生成升级建议，R8 审批后 update_skill 演进版本。
CREATE TABLE IF NOT EXISTS skill_update_proposals(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  skill_id TEXT NOT NULL,
  base_version TEXT NOT NULL,
  new_definition TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_proposals_status ON skill_update_proposals(status);
