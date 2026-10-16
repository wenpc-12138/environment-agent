# -*- coding: utf-8 -*-
"""S3-H1 goal 持久化目标（对标 DeepSeek Harness `goal` 子系统）。

任务收尾自动登记「目标-进度」结构：
- `register(task_id, objective, progress=100)`：任务完成后登记目标（幂等：同任务
  已存在则更新 objective/progress/status）；
- `list(task_id)` / `get(goal_id)` / `update_status(goal_id, status, progress)`；
- `list_active(limit)`：进行中的目标（供前端任务侧栏展示）。

数据落 `goals` 表（迁移 0016），经 `src.core.db.get_conn` 访问，与
`src.memory` 其他模块（facts/profile/summary）风格一致。
"""
from __future__ import annotations

from ..core.db import get_conn


def register(task_id: int, objective: str, progress: int = 100,
             status: str = 'completed') -> int:
    """登记任务目标（幂等 upsert，返回 goal_id）。

    任务收尾钩子调用：目标 = 任务标题（或首条用户意图），完成后置
    completed/progress=100；同任务重复登记仅更新（不重复建行）。
    """
    conn = get_conn()
    row = conn.execute('SELECT id FROM goals WHERE task_id=?', (int(task_id),)).fetchone()
    if not isinstance(objective, str):
        objective = str(objective or '')
    objective = objective.strip()
    progress = max(0, min(int(progress or 0), 100))
    now = "datetime('now','localtime')"
    if row:
        conn.execute(
            f'UPDATE goals SET objective=?, status=?, progress=?, updated_at={now}'
            ' WHERE id=?',
            (objective, status, progress, row['id']))
        conn.commit()
        return int(row['id'])
    cur = conn.execute(
        f'INSERT INTO goals(task_id, objective, status, progress, created_at, updated_at)'
        f' VALUES (?,?,?,?,{now},{now})',
        (int(task_id), objective, status, progress))
    conn.commit()
    return int(cur.lastrowid)


def list_for_task(task_id: int) -> list[dict]:
    """返回任务的全部目标（按 id 升序）。"""
    rows = get_conn().execute(
        'SELECT * FROM goals WHERE task_id=? ORDER BY id', (int(task_id),)).fetchall()
    return [dict(r) for r in rows]


def get(goal_id: int) -> dict | None:
    row = get_conn().execute('SELECT * FROM goals WHERE id=?', (int(goal_id),)).fetchone()
    return dict(row) if row else None


def update_status(goal_id: int, status: str, progress: int | None = None) -> bool:
    """更新目标状态（status: in_progress/completed/abandoned；progress 0..100）。"""
    conn = get_conn()
    if progress is not None:
        progress = max(0, min(int(progress), 100))
        cur = conn.execute(
            "UPDATE goals SET status=?, progress=?, updated_at=datetime('now','localtime')"
            ' WHERE id=?', (status, progress, int(goal_id)))
    else:
        cur = conn.execute(
            "UPDATE goals SET status=?, updated_at=datetime('now','localtime')"
            ' WHERE id=?', (status, int(goal_id)))
    conn.commit()
    return cur.rowcount > 0


def list_active(limit: int = 20) -> list[dict]:
    """进行中的目标（in_progress，按最近更新倒序）。"""
    rows = get_conn().execute(
        'SELECT * FROM goals WHERE status=? ORDER BY updated_at DESC LIMIT ?',
        ('in_progress', int(limit))).fetchall()
    return [dict(r) for r in rows]
