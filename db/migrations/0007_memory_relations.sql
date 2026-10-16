-- G5 记忆知识图谱（对齐 Neo4j Agent Memory 实体关系层，实现完全自研）。
-- entity_a -rel-> entity_b 有向关系；weight 聚合权重（同三元组重复出现累加）；
-- note 存决策痕迹说明（rel='decision_trace' 时 entity_b 为决策内容摘要，对齐 reasoning memory）。
CREATE TABLE IF NOT EXISTS memory_relations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_a TEXT NOT NULL,
  rel TEXT NOT NULL,
  entity_b TEXT NOT NULL,
  source TEXT DEFAULT '',
  weight INTEGER NOT NULL DEFAULT 1,
  note TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_rel_a ON memory_relations(entity_a);
CREATE INDEX IF NOT EXISTS idx_memory_rel_b ON memory_relations(entity_b);
