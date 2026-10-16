# -*- coding: utf-8 -*-
"""M3 用户画像层（对齐腾讯 Agent Memory L3 用户画像）。

- `distill(user_key, facts)`：从（已审核 active 的）事实聚合稳定偏好到画像（同值累加权重）
- `upsert(user_key, attr, value)`：直接写入/累加画像项
- `get_profile(user_key)`：按权重降序返回画像
- `render_profile(user_key)`：生成注入系统提示的画像文本段
- 默认 user_key='local'；画像默认仅从 active 事实蒸馏（防即时需求误入长期画像）

设计（对齐方案 §四）：跨会话稳定偏好聚合 + user_key 隔离；可手动删除（隐私治理）。
"""
from __future__ import annotations

from typing import Any

from ..core.db import get_conn
from ..core.utils import now_iso
from ..models.core import ProfileItem

# 从事实蒸馏到画像的属性白名单（偏好/约束类；fact 结论类不蒸馏，避免噪音）
_DISTILL_ATTRS = ('preference', 'constraint')


def _row(item: Any) -> ProfileItem:
    return ProfileItem(id=item['id'], user_key=item['user_key'], attr=item['attr'],
                       value=item['value'], weight=item['weight'], updated_at=item['updated_at'])


def upsert(user_key: str, attr: str, value: str) -> ProfileItem:
    """写入/累加画像项：同 (user_key, attr, value) 权重 +1。"""
    if not user_key or not attr or not value:
        raise ValueError('user_key/attr/value 不能为空')
    row = get_conn().execute(
        'SELECT * FROM memory_profile WHERE user_key=? AND attr=? AND value=?',
        (user_key, attr, value)).fetchone()
    ts = now_iso()
    if row:
        get_conn().execute('UPDATE memory_profile SET weight=weight+1, updated_at=? WHERE id=?',
                           (ts, row['id']))
    else:
        get_conn().execute(
            'INSERT INTO memory_profile(user_key,attr,value,weight,updated_at) VALUES(?,?,?,1,?)',
            (user_key, attr, value, ts))
    get_conn().commit()
    # P0-2：登记用户画像为记忆资产（失败静默）
    try:
        from .assets import register
        register('profile', f'{user_key}:{attr}:{value}', title=f'{user_key} {attr}',
                 content=f'{attr}={value}', visibility='private', owner=user_key)
    except Exception:
        pass
    if row:
        return _row(get_conn().execute('SELECT * FROM memory_profile WHERE id=?', (row['id'],)).fetchone())
    cur = get_conn().execute(
        'SELECT * FROM memory_profile WHERE user_key=? AND attr=? AND value=?',
        (user_key, attr, value)).fetchone()
    return _row(cur)


def get_profile(user_key: str = 'local') -> list[ProfileItem]:
    rows = get_conn().execute(
        'SELECT * FROM memory_profile WHERE user_key=? ORDER BY weight DESC, updated_at DESC LIMIT 100',
        (user_key,)).fetchall()
    return [_row(r) for r in rows]


def remove(user_key: str, pid: int | None = None, attr: str = '') -> int:
    """删除画像项（隐私治理）：按 id 或 (attr) 删除，返回删除数。"""
    if pid is not None:
        cur = get_conn().execute('DELETE FROM memory_profile WHERE user_key=? AND id=?', (user_key, pid))
    elif attr:
        cur = get_conn().execute('DELETE FROM memory_profile WHERE user_key=? AND attr=?', (user_key, attr))
    else:
        cur = get_conn().execute('DELETE FROM memory_profile WHERE user_key=?', (user_key,))
    get_conn().commit()
    return cur.rowcount


def distill(user_key: str = 'local', facts: list[Any] | None = None) -> dict:
    """从（active）事实蒸馏稳定偏好到画像。

    聚合规则：仅偏好/约束类；同 (attr,value) 权重累加；返回新增/累计统计。
    """
    from . import facts as facts_mod
    src = facts if facts is not None else facts_mod.query_facts(active_only=True)
    added = upserted = 0
    for f in src:
        if f.ftype not in _DISTILL_ATTRS:
            continue
        try:
            upsert(user_key, f.attr, f.value)
            upserted += 1
        except Exception:
            continue
    return {'distilled': upserted, 'total': len(get_profile(user_key))}


def render_profile(user_key: str = 'local', limit: int = 8) -> str:
    """生成注入系统提示的画像文本段（无画像返回空串）。"""
    items = get_profile(user_key)[:limit]
    if not items:
        return ''
    lines = ['[用户画像]']
    for it in items:
        label = {'preference': '偏好', 'constraint': '约束'}.get(it.attr, it.attr)
        lines.append(f'- {label}：{it.value}（出现 {it.weight} 次）')
    return '\n'.join(lines)
