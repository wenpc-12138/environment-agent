# 数据库迁移（db/migrations）

v2.0 数据库规范（coding_standards §4）：**所有表结构变更走迁移脚本，禁止手改线上 schema**。

## 规则

- 文件命名：`NNNN_描述.sql` 或 `NNNN_描述.py`，如 `0001_v12_to_v20.py`；按编号升序应用
  （同编号优先 `.sql`）。
- 幂等：`src/core/db.py::run_migrations()` 将已应用版本记录在 `schema_migrations` 表，
  重复执行不会重复应用。
- `.py` 迁移约定：文件导出 `run(conn, db_file)` 函数，适用于列存在性检查（SQLite
  `ALTER TABLE ADD COLUMN` 非幂等，需先查 `PRAGMA table_info`）、数据备份/转换、FTS 重建等
  SQL 表达不了的逻辑。脚本须自包含，不 import 项目模块（只接收 conn 与 db_file 参数）。
- 时间戳统一 UTC ISO 8601（业务展示时转本地时区）。
- FTS5 中文检索用 jieba 预分词（M06 知识库迁移时落地），不依赖 SQLite 内置分词器。

## 使用

```bash
python -c "import src.core.db as db; print(db.run_migrations())"
```

## 示例

```sql
-- 0001_skills_state.sql
CREATE TABLE IF NOT EXISTS v2_skills(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  level INTEGER NOT NULL DEFAULT 1,
  role TEXT NOT NULL,
  domain TEXT NOT NULL,
  version TEXT NOT NULL DEFAULT '1.0.0',
  status TEXT NOT NULL DEFAULT 'active',
  definition TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT 'manual'
);
```

## 与 v1.2 兼容说明

v1.2 的 `db.py`（根目录）直接管理 `data/ecoagent.db`（kb_* / memory_* / providers 等表）。
v2.0 与 v1.2 **共用同一库文件**，双轨共存：v1.2 表由 v1.2 `init_db` 维护，v2.0 迁移只做
**加列 / 建新表**，禁止破坏性重建。

已落地：
- `0001_v12_to_v20.py`（M19）：迁移前自动备份到 `data/backups/auto/`；`kb_entries` 补
  `standard_code / validity_status / effective_date` 列（M06 标准库需要）；新建
  `memory_episodes`（M05）、`v2_skills`（M07）、`audit_log`（M14 预留）三表。

后续模块各自的表 / FTS 索引在对应模块（M05/M06/M09/M10/M11/M14...）的迁移脚本中补齐。
