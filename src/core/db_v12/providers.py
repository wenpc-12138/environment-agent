# -*- coding: utf-8 -*-
"""S1-W5 db.py 拆分：Provider 数据层（providers 域）。

从根 db.py 原样搬移：list_providers/get_provider/get_active_provider/
set_active_provider/upsert_provider/delete_provider。
"""
from __future__ import annotations

import os

from .base import q, w, get_db

# 通过环境变量注入的模型凭据字段（密钥永不写入代码/仓库）
ENV_KEY = 'EA_LLM_API_KEY'
ENV_BASE_URL = 'EA_LLM_BASE_URL'
ENV_MODEL = 'EA_LLM_MODEL'
ENV_PROVIDER = 'EA_LLM_PROVIDER'


def apply_env_override():
    """把环境变量里的模型配置写入数据库（未设置任何变量时不改动数据）。

    用途：容器/CI/无界面场景下无需打开设置面板即可接入真实模型，
    密钥只存在于运行环境（.env 已被 .gitignore 排除），不进入代码仓库。

    变量：
      EA_LLM_API_KEY   API 密钥
      EA_LLM_BASE_URL  OpenAI 兼容端点，如 https://api.deepseek.com
      EA_LLM_MODEL     模型名，如 deepseek-chat
      EA_LLM_PROVIDER  目标 Provider 名称（可选，默认当前激活或首个非 mock）

    返回：被更新的 provider id；未做任何改动时返回 None。
    """
    key = (os.environ.get(ENV_KEY) or '').strip()
    base = (os.environ.get(ENV_BASE_URL) or '').strip()
    model = (os.environ.get(ENV_MODEL) or '').strip()
    name = (os.environ.get(ENV_PROVIDER) or '').strip()
    if not (key or base or model):
        return None

    target = q("SELECT * FROM providers WHERE name=? LIMIT 1", (name,), one=True) if name else None
    if target is None:
        active = get_active_provider()
        # 演示模式不接受真实密钥，避免把 key 写到 mock 行上
        if active and active.get('kind') != 'mock':
            target = active
    if target is None:
        target = q("SELECT * FROM providers WHERE kind<>'mock' ORDER BY id LIMIT 1", one=True)
    if target is None:
        return None

    sets, params = [], []
    if key:
        sets.append('api_key=?')
        params.append(key)
    if base:
        sets.append('base_url=?')
        params.append(base)
    if model:
        sets.append('model=?')
        params.append(model)
    if not sets:
        return None
    w(
        "UPDATE providers SET %s, updated_at=datetime('now','localtime') WHERE id=?" % ", ".join(sets),
        params + [target['id']],
    )
    # 通过环境变量显式提供了凭据 -> 自动激活该 Provider（含 base_url 才可用）
    if not target.get('is_active'):
        if base or target.get('base_url'):
            set_active_provider(target['id'])
    return target['id']


def list_providers():
    return q("SELECT * FROM providers ORDER BY is_active DESC, id ASC")


def get_provider(pid):
    return q("SELECT * FROM providers WHERE id=?", (pid,), one=True)


def get_active_provider():
    return q("SELECT * FROM providers WHERE is_active=1 ORDER BY id LIMIT 1", one=True)


def set_active_provider(pid):
    conn = get_db()
    conn.execute("UPDATE providers SET is_active=0, updated_at=datetime('now','localtime')")
    conn.execute("UPDATE providers SET is_active=1, updated_at=datetime('now','localtime') WHERE id=?", (pid,))
    conn.commit()


def upsert_provider(data):
    fields = ["name", "kind", "model", "base_url", "api_key", "reasoning_effort", "context_length",
              "use_server_search"]
    try:
        ctx = max(0, int(data.get("context_length") or 0))
    except (TypeError, ValueError):
        ctx = 0
    try:
        use_ss = 1 if int(data.get("use_server_search") or 0) else 0
    except (TypeError, ValueError):
        use_ss = 0
    payload = [
        data.get("name", ""), data.get("kind", "openai"), data.get("model", ""),
        data.get("base_url", ""), data.get("api_key", ""),
        data.get("reasoning_effort", "high") or "high", ctx, use_ss,
    ]
    pid = data.get("id")
    if pid:
        sets = ", ".join(f"{f}=?" for f in fields)
        w(f"UPDATE providers SET {sets}, updated_at=datetime('now','localtime') WHERE id=?", payload + [pid])
        return pid
    return w(
        "INSERT INTO providers(name,kind,model,base_url,api_key,reasoning_effort,context_length,use_server_search)"
        " VALUES(?,?,?,?,?,?,?,?)",
        payload,
    )


def delete_provider(pid):
    w("DELETE FROM providers WHERE id=?", (pid,))
