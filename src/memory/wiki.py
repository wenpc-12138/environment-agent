# -*- coding: utf-8 -*-
"""Wiki 知识资产：人工沉淀 / 任务自动提炼的结构化文档知识。

对齐 TencentDB-Agent-Memory 的 Wiki 记忆资产：
- 将长文档/流程/方法论沉淀为可检索的 Wiki 条目；
- 写入时登记为统一记忆资产（asset_type='wiki'），纳入 ACL 可见性治理；
- 检索支持关键词 LIKE + 向量（可选），召回时累计 use_count。

存储：`wiki_entries` 表（0011 迁移）。对外接口 try/except 包裹，失败静默。
"""
from __future__ import annotations

import hashlib
import itertools
import re
from typing import Callable

from ..core.db import get_conn

_VISIBILITIES = ("private", "team", "agent")

_seed = itertools.count(1)


def _next_id() -> str:
    return f'wiki-{next(_seed):04d}'


def create_wiki(title: str, content: str = "", tags: str = "", source: str = "",
                visibility: str = "private", owner: str = "local",
                created_by: str = "manual") -> str:
    """创建 Wiki 条目，返回条目 id。title 为空返回 ''。"""
    title = (title or '').strip()
    if not title:
        return ''
    if visibility not in _VISIBILITIES:
        visibility = 'private'
    wid = _next_id()
    conn = get_conn()
    try:
        with conn:
            conn.execute(
                """INSERT INTO wiki_entries(id, title, content, tags, source, visibility,
                   owner, created_by) VALUES (?,?,?,?,?,?,?,?)""",
                (wid, title, content, tags or '', source or '', visibility, owner, created_by),
            )
        from src.memory import assets
        assets.register('wiki', wid, title=title, content=content,
                        visibility=visibility, owner=owner)
    except Exception:
        pass
    return wid


def get_wiki(wid: str) -> dict | None:
    """按 id 查 Wiki 条目（不存在返回 None）。"""
    row = get_conn().execute('SELECT * FROM wiki_entries WHERE id=?', (wid,)).fetchone()
    return dict(row) if row else None


def list_wiki(q: str = "", visibility: str = "", limit: int = 200, offset: int = 0) -> list[dict]:
    """Wiki 列表：可选关键词（标题/正文/标签）与可见性过滤，按更新时间倒序。"""
    sql = ['SELECT * FROM wiki_entries WHERE 1=1']
    args: list = []
    if q:
        like = f'%{q}%'
        sql.append('AND (title LIKE ? OR content LIKE ? OR tags LIKE ?)')
        args += [like, like, like]
    if visibility:
        sql.append('AND visibility=?')
        args.append(visibility)
    sql.append('ORDER BY updated_at DESC LIMIT ? OFFSET ?')
    args += [limit, offset]
    rows = get_conn().execute(' '.join(sql), args).fetchall()
    return [dict(r) for r in rows]


def search_wiki(q: str, caller: Callable[[list[dict]], str] | None = None) -> list[dict]:
    """检索 Wiki（关键词 LIKE 为主，向量可选）。命中累计 use_count。"""
    q = (q or '').strip()
    if not q:
        return []
    rows = list_wiki(q=q, limit=10)
    conn = get_conn()
    try:
        for r in rows:
            with conn:
                conn.execute(
                    'UPDATE wiki_entries SET use_count=use_count+1, '
                    "updated_at=datetime('now','localtime') WHERE id=?", (r['id'],))
        from src.memory import assets
        for r in rows:
            assets.touch('wiki', r['id'])
    except Exception:
        pass
    return rows


def update_wiki(wid: str, title: str = "", content: str = "", tags: str = "",
                visibility: str = "") -> bool:
    """更新 Wiki 条目（仅提供非空字段）。成功返回 True。"""
    cur = get_conn()
    fields, args = [], []
    if title:
        fields.append('title=?')
        args.append(title)
    if content is not None:
        fields.append('content=?')
        args.append(content)
    if tags:
        fields.append('tags=?')
        args.append(tags)
    if visibility:
        if visibility not in _VISIBILITIES:
            return False
        fields.append('visibility=?')
        args.append(visibility)
    if not fields:
        return False
    fields.append("updated_at=datetime('now','localtime')")
    args.append(wid)
    try:
        with cur:
            cur.execute(f'UPDATE wiki_entries SET {", ".join(fields)} WHERE id=?', args)
        return True
    except Exception:
        return False


def delete_wiki(wid: str) -> bool:
    """删除 Wiki 条目并同步删除资产登记。"""
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute('DELETE FROM wiki_entries WHERE id=?', (wid,))
            conn.execute('DELETE FROM memory_assets WHERE asset_id=?', (f'wiki:{wid}',))
        return cur.rowcount > 0
    except Exception:
        return False
