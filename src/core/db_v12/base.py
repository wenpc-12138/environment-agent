# -*- coding: utf-8 -*-
"""S1-W5 db.py 拆分：连接管理与通用查询（base 域）。

从根 db.py 原样搬移：ensure_dirs/get_db/init_db/close_db/q/w/begin_batch/
commit_batch + 路径/线程局部常量。_VEC_OK/_VEC_METRIC 为跨模块共享状态
（init_db 写入、kb 域读取），由本模块持有，kb 域经 `_base._VEC_OK` 动态引用。
"""
from __future__ import annotations

import os
import sqlite3
import json
import threading
from pathlib import Path

from .schema import SCHEMA, FTS_TRIGGERS

# S1-W5 拆分适配：本文件位于 src/core/db_v12/，项目根 = parents[3]（原 db.py 在根目录）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

DATA_DIR = os.path.join(str(_PROJECT_ROOT), "data")

DB_PATH = os.environ.get("ECOAGENT_DB", os.path.join(DATA_DIR, "ecoagent.db"))

TASK_OUTPUT_DIR = os.path.join(DATA_DIR, "task_outputs")

_thread_local = threading.local()

VEC_DIM = 256  # 与 kb_pipeline.embed_text 输出维度保持一致

# sqlite-vec 可用性标志(init_db 时探测;关闭后向量检索降级 numpy 暴力)
_VEC_OK = False
_VEC_METRIC = "cosine"  # vec0 距离度量: cosine / l2

def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    kb_dir = os.path.join(DATA_DIR, "kb")
    os.makedirs(kb_dir, exist_ok=True)
    agents_dir = os.path.join(DATA_DIR, "agents", "skills")
    os.makedirs(agents_dir, exist_ok=True)
    os.makedirs(TASK_OUTPUT_DIR, exist_ok=True)


def get_db():
    if not hasattr(_thread_local, "conn") or _thread_local.conn is None:
        _thread_local.conn = sqlite3.connect(DB_PATH)
        _thread_local.conn.row_factory = sqlite3.Row
        _thread_local.conn.execute("PRAGMA journal_mode=WAL")
        _thread_local.conn.execute("PRAGMA foreign_keys=ON")
        # 每个连接加载 sqlite-vec 扩展(vec0 虚拟表依赖;失败静默,检索自动降级)
        try:
            import sqlite_vec
            _thread_local.conn.enable_load_extension(True)
            sqlite_vec.load(_thread_local.conn)
        except Exception:
            pass
    return _thread_local.conn


def init_db():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executescript(FTS_TRIGGERS)
    # 迁移:老库补齐 reasoning_effort / context_length 列
    cols = [r[1] for r in conn.execute("PRAGMA table_info(providers)")]
    if "reasoning_effort" not in cols:
        conn.execute("ALTER TABLE providers ADD COLUMN reasoning_effort TEXT NOT NULL DEFAULT 'high'")
    if "context_length" not in cols:
        conn.execute("ALTER TABLE providers ADD COLUMN context_length INTEGER DEFAULT 0")
    if "use_server_search" not in cols:
        conn.execute("ALTER TABLE providers ADD COLUMN use_server_search INTEGER DEFAULT 0")
    # 迁移:cache_log 补齐 token/成本统计扩展列(兼容老库)
    cl_cols = [r[1] for r in conn.execute("PRAGMA table_info(cache_log)")]
    CL_EXTRA_COLS = {
        "cache_creation": "INTEGER DEFAULT 0",
        "thinking_tokens": "INTEGER DEFAULT 0",
        "latency_ms": "INTEGER DEFAULT 0",
        "mode": "TEXT DEFAULT ''",
        "domain": "TEXT DEFAULT ''",
    }
    for _col, _ddl in CL_EXTRA_COLS.items():
        if _col not in cl_cols:
            conn.execute(f"ALTER TABLE cache_log ADD COLUMN {_col} {_ddl}")
    conn.commit()
    # 迁移:kb_entries 补齐知识库系统扩展列(兼容老库)
    kb_cols = [r[1] for r in conn.execute("PRAGMA table_info(kb_entries)")]
    KB_EXTRA_COLS = {
        "item_type": "TEXT NOT NULL DEFAULT 'knowledge'",
        "domain": "TEXT DEFAULT ''",
        "source_type": "TEXT DEFAULT '原文'",
        "validity": "TEXT DEFAULT '未知'",
        "confidence": "REAL DEFAULT 0.8",
        "status": "TEXT NOT NULL DEFAULT 'active'",
        "std_no": "TEXT DEFAULT ''",
        "org": "TEXT DEFAULT ''",
        "publish_date": "TEXT DEFAULT ''",
        "implement_date": "TEXT DEFAULT ''",
        "metadata_json": "TEXT DEFAULT '{}'",
        "updated_at": "TEXT",
    }
    for _col, _ddl in KB_EXTRA_COLS.items():
        if _col not in kb_cols:
            conn.execute(f"ALTER TABLE kb_entries ADD COLUMN {_col} {_ddl}")
    # 预置常用 Provider(未激活)
    cur = conn.execute("SELECT COUNT(*) c FROM providers")
    if cur.fetchone()["c"] == 0:
        presets = [
            ("DeepSeek", "openai", "deepseek-v4-pro", "https://api.deepseek.com", "DeepSeek 官方 API,支持上下文硬盘缓存(命中记账)"),
            ("OpenAI", "openai", "gpt-4o-mini", "https://api.openai.com/v1", "OpenAI 官方 API"),
            ("智谱 GLM", "openai", "glm-4-flash", "https://open.bigmodel.cn/api/paas/v4", "智谱清言,glm-4-flash 免费"),
            ("通义 Qwen", "openai", "qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1", "阿里云百炼,OpenAI 兼容模式"),
            ("本地 Ollama", "openai", "qwen2.5:7b", "http://localhost:11434/v1", "本地部署,无数据出网"),
            ("演示模式", "mock", "mock-eco", "", "内置模拟智能体:无需密钥,演示完整工具调用闭环"),
        ]
        for name, kind, model, base, desc in presets:
            conn.execute(
                "INSERT INTO providers(name,kind,model,base_url,api_key,is_active) VALUES(?,?,?,?,?,0)",
                (name, kind, model, base, ""),
            )
    # 默认激活演示模式
    cur = conn.execute("SELECT COUNT(*) c FROM providers WHERE is_active=1")
    if cur.fetchone()["c"] == 0:
        conn.execute("UPDATE providers SET is_active=1 WHERE name='演示模式'")
    # 迁移:sqlite-vec 向量表(可选;扩展不可用时静默跳过,检索自动降级 numpy 暴力)
    global _VEC_OK, _VEC_METRIC
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        try:  # 优先 cosine 度量(distance=1-cosine),老版本不支持则回退 L2
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS kb_vec USING vec0"
                "(entry_id INTEGER PRIMARY KEY, embedding float[256] distance_metric=cosine)"
            )
            _VEC_METRIC = "cosine"
        except Exception:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS kb_vec USING vec0"
                "(entry_id INTEGER PRIMARY KEY, embedding float[256])"
            )
            _VEC_METRIC = "l2"
        _VEC_OK = True
    except Exception:
        _VEC_OK = False
    conn.commit()
    conn.close()


def close_db():
    if hasattr(_thread_local, "conn") and _thread_local.conn is not None:
        _thread_local.conn.close()
        _thread_local.conn = None


def q(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    if one:
        return dict(rows[0]) if rows else None
    return [dict(r) for r in rows]


def w(sql, args=()):
    conn = get_db()
    cur = conn.execute(sql, args)
    if not getattr(_thread_local, "batch", 0):
        conn.commit()
    return cur.lastrowid


def begin_batch():
    """开启批量写入事务(线程局部): 期间 w() 不再逐条 commit, 显著加速批量导入"""
    b = getattr(_thread_local, "batch", 0)
    if b == 0:
        get_db().execute("BEGIN")
    _thread_local.batch = b + 1


def commit_batch():
    """结束批量写入事务并提交"""
    b = getattr(_thread_local, "batch", 0)
    if b > 0:
        _thread_local.batch = b - 1
        if b - 1 == 0:
            get_db().commit()
