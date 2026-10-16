-- M1 情景记忆语义检索：事件向量表（独立表，避免 memory_episodes 主表膨胀）
-- embedding 存 float32 归一化向量二进制（kb_pipeline.embed_text_semantic 输出 512 维）。
-- 幂等：表已存在时静默跳过；仅建新表，不破坏 v1.2 既有表。
CREATE TABLE IF NOT EXISTS memory_episode_vec(
  episode_id INTEGER PRIMARY KEY,
  embedding BLOB NOT NULL
);
