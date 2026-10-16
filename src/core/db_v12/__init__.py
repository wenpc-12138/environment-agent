# -*- coding: utf-8 -*-
"""S1-W5 db.py 拆分：v1.2 数据层按域拆分子包（聚合导出）。

根 `db.py` 保持为兼容重导出（`import db` 用法不变）；本包承载全部实现：
- `schema.py`    SCHEMA / FTS_TRIGGERS 常量
- `base.py`      连接管理 + 通用查询（ensure_dirs/get_db/init_db/close_db/q/w/begin_batch/commit_batch + 路径常量）
- `providers.py` Provider CRUD
- `tasks.py`     任务/消息/断点/输出
- `kb.py`        知识库（检索/CRUD/向量/审计/备份/导入导出，最大）
- `memory.py`    任务记忆 KV
- `usage.py`     用量统计/成本/搜索缓存/技能开关

`__all__` 与根 db.py 原公共名一致（92 个），`from db import *` 语义不变。
"""
from __future__ import annotations

from .base import (
    DATA_DIR, DB_PATH, FTS_TRIGGERS, SCHEMA, TASK_OUTPUT_DIR, VEC_DIM,
    begin_batch, close_db, commit_batch, ensure_dirs, get_db, init_db,
    q, w,
)
from .providers import (
    delete_provider, get_active_provider, get_provider, list_providers,
    set_active_provider, upsert_provider,
)
from .tasks import (
    add_message, checkpoint_set_status, clear_checkpoint, create_task,
    delete_task, export_task_chat, get_checkpoint, get_messages, get_task,
    last_message_id, list_task_outputs, list_tasks, read_task_output,
    save_checkpoint, task_output_dir, task_output_save, update_message_content,
    update_task,
)
from .kb import (
    kb_add, kb_audit, kb_audit_latest, kb_backup, kb_backup_if_due,
    kb_backups_list, kb_cache_get, kb_cache_set, kb_chunk_add, kb_chunk_clear,
    kb_classify_doc, kb_conflicts, kb_correct, kb_correct_resolve, kb_delete,
    kb_embed_all, kb_embed_entry, kb_export, kb_get, kb_get_chunks,
    kb_get_detail, kb_harvest_conversation, kb_hybrid_search, kb_import_files,
    kb_imports_list, kb_list, kb_locate, kb_memory_add, kb_memory_list,
    kb_qc_check, kb_qc_list, kb_qc_stats, kb_relation_add, kb_restore,
    kb_search, kb_stats, kb_update, kb_vec_load, kb_vector_search,
    kb_version_add,
)
from .memory import memory_delete, memory_get, memory_list, memory_set
from .usage import (
    USAGE_PRICING, calc_cost, log_usage, search_cache_get, search_cache_set,
    skill_set, skill_state, stats_cache, task_usage, usage_stats,
)

__all__ = [
    # 常量
    'DATA_DIR', 'DB_PATH', 'FTS_TRIGGERS', 'SCHEMA', 'TASK_OUTPUT_DIR',
    'USAGE_PRICING', 'VEC_DIM',
    # 连接/通用
    'begin_batch', 'close_db', 'commit_batch', 'ensure_dirs', 'get_db',
    'init_db', 'q', 'w',
    # providers
    'delete_provider', 'get_active_provider', 'get_provider', 'list_providers',
    'set_active_provider', 'upsert_provider',
    # tasks
    'add_message', 'checkpoint_set_status', 'clear_checkpoint', 'create_task',
    'delete_task', 'export_task_chat', 'get_checkpoint', 'get_messages',
    'get_task', 'last_message_id', 'list_task_outputs', 'list_tasks',
    'read_task_output', 'save_checkpoint', 'task_output_dir', 'task_output_save',
    'update_message_content', 'update_task',
    # kb
    'kb_add', 'kb_audit', 'kb_audit_latest', 'kb_backup', 'kb_backup_if_due',
    'kb_backups_list', 'kb_cache_get', 'kb_cache_set', 'kb_chunk_add',
    'kb_chunk_clear', 'kb_classify_doc', 'kb_conflicts', 'kb_correct',
    'kb_correct_resolve', 'kb_delete', 'kb_embed_all', 'kb_embed_entry',
    'kb_export', 'kb_get', 'kb_get_chunks', 'kb_get_detail',
    'kb_harvest_conversation', 'kb_hybrid_search', 'kb_import_files',
    'kb_imports_list', 'kb_list', 'kb_locate', 'kb_memory_add', 'kb_memory_list',
    'kb_qc_check', 'kb_qc_list', 'kb_qc_stats', 'kb_relation_add', 'kb_restore',
    'kb_search', 'kb_stats', 'kb_update', 'kb_vec_load', 'kb_vector_search',
    'kb_version_add',
    # memory
    'memory_delete', 'memory_get', 'memory_list', 'memory_set',
    # usage
    'calc_cost', 'log_usage', 'search_cache_get', 'search_cache_set',
    'skill_set', 'skill_state', 'stats_cache', 'task_usage', 'usage_stats',
]
