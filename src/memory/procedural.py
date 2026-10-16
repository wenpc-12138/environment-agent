# -*- coding: utf-8 -*-
"""M05 ProceduralMemory：程序性记忆（技能库 v2_skills + 版本化）。

契约（contracts.md §3.M05）：
- `create_skill(defn: SkillDef) -> str`：登记新技能
- `update_skill(id, new_def, reviewer) -> bool`：R8 审核后更新版本
- `best_match(task, domain=None) -> SkillDef | None`：任务匹配（优先于 RAG）
- `mark_deprecated(standard_code) -> list[str]`：标准废止联动置废

存储：`v2_skills` 表（0001 迁移已建，与 M07 共享）。definition 字段存 YAML 定义文本，
best_match 用轻量分词打分（jieba 可选增强）。
"""
from __future__ import annotations

import re
from typing import Any

from ..core.db import get_conn
from ..models.core import SkillDef

_TOKEN_RE = re.compile(r'[A-Za-z0-9]+|[\u4e00-\u9fff]')


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or '')]


class ProceduralMemory:
    """技能库：登记 / 更新 / 匹配 / 废止联动。"""

    # ---- 登记 ----
    def create_skill(self, defn: SkillDef) -> str:
        """登记新技能，返回技能 ID。已存在则覆盖（幂等）。"""
        conn = get_conn()
        conn.execute(
            'INSERT INTO v2_skills(id, name, level, role, domain, version, status, definition, created_by)'
            ' VALUES(?,?,?,?,?,?,?,?,?)'
            ' ON CONFLICT(id) DO UPDATE SET name=excluded.name, level=excluded.level,'
            ' role=excluded.role, domain=excluded.domain, version=excluded.version,'
            ' status=excluded.status, definition=excluded.definition, created_by=excluded.created_by',
            (
                defn.id, defn.name, defn.level, defn.role, defn.domain,
                defn.version, defn.status, defn.definition, defn.created_by,
            ),
        )
        conn.commit()
        # P0-2：登记技能为记忆资产（失败静默）
        try:
            from .assets import register
            register('skill', defn.id, title=defn.name, content=defn.definition,
                     visibility='private', owner=defn.created_by or 'local')
        except Exception:
            pass
        return defn.id

    # ---- 更新 / 审核流转 ----
    def update_skill(self, id: str, new_def: SkillDef, reviewer: str) -> bool:
        """更新技能版本（仅 R8 审核后，contracts.md §3.M05）。

        第 8 波增强：
        - reviewer 必须为 R8（非 R8 直接拒绝，返回 False）；
        - 状态流转约束：仅允许更新 active 技能（或保持原状态）；被 rejected/deprecated
          的技能不得通过本方法复活，须重新结晶/登记。
        """
        if reviewer != 'R8':
            return False
        row = get_conn().execute('SELECT status FROM v2_skills WHERE id=?', (id,)).fetchone()
        if row is None:
            return False
        old_status = row['status']
        if old_status not in ('active', 'pending_review'):
            return False  # rejected/deprecated 不可直接改回
        conn = get_conn()
        cur = conn.execute(
            'UPDATE v2_skills SET name=?, level=?, role=?, domain=?, version=?, status=?,'
            ' definition=? WHERE id=?',
            (
                new_def.name, new_def.level, new_def.role, new_def.domain,
                new_def.version, new_def.status, new_def.definition, id,
            ),
        )
        conn.commit()
        return cur.rowcount > 0

    def approve_skill(self, id: str, reviewer: str) -> bool:
        """R8 审核通过：pending_review → active（第 8 波审核联动）。

        返回 False 表示：审核人非 R8 / 技能不存在 / 当前状态非 pending_review。
        """
        if reviewer != 'R8':
            return False
        conn = get_conn()
        cur = conn.execute(
            "UPDATE v2_skills SET status='active' WHERE id=? AND status='pending_review'", (id,)
        )
        conn.commit()
        return cur.rowcount > 0

    def reject_skill(self, id: str, reviewer: str) -> bool:
        """R8 驳回：pending_review → rejected（第 8 波审核联动）。

        返回 False 表示：审核人非 R8 / 技能不存在 / 当前状态非 pending_review。
        """
        if reviewer != 'R8':
            return False
        conn = get_conn()
        cur = conn.execute(
            "UPDATE v2_skills SET status='rejected' WHERE id=? AND status='pending_review'", (id,)
        )
        conn.commit()
        return cur.rowcount > 0

    def list_skills(self, status: str | None = None) -> list[SkillDef]:
        """查询技能库（可按 status 过滤；None 返回全部），供 R8 审核列表使用。"""
        conn = get_conn()
        if status is not None:
            rows = conn.execute('SELECT * FROM v2_skills WHERE status=?', (status,)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM v2_skills').fetchall()
        return [
            SkillDef(
                id=r['id'], name=r['name'], level=r['level'], role=r['role'], domain=r['domain'],
                version=r['version'], status=r['status'], definition=r['definition'],
                created_by=r['created_by'],
            )
            for r in rows
        ]

    # ---- 匹配 ----
    def get_skill(self, id: str) -> SkillDef | None:
        """按 ID 查技能（任意状态）。"""
        row = get_conn().execute('SELECT * FROM v2_skills WHERE id=?', (id,)).fetchone()
        if row is None:
            return None
        return SkillDef(
            id=row['id'], name=row['name'], level=row['level'], role=row['role'],
            domain=row['domain'], version=row['version'], status=row['status'],
            definition=row['definition'], created_by=row['created_by'],
        )

    def best_match(self, task: str, domain: str | None = None) -> SkillDef | None:
        """按任务关键词匹配技能（status=active）；domain 过滤可选。返回最佳命中或 None。"""
        conn = get_conn()
        if domain:
            rows = conn.execute(
                'SELECT * FROM v2_skills WHERE status=? AND domain=?',
                ('active', domain),
            ).fetchall()
        else:
            rows = conn.execute('SELECT * FROM v2_skills WHERE status=?', ('active',)).fetchall()
        if not rows:
            return None
        tokens = set(_tokenize(task))
        if not tokens:
            return None
        best: tuple[float, Any] | None = None
        for r in rows:
            hay = ' '.join([r['name'], r['domain'], r['definition']]).lower()
            score = sum(1 for t in tokens if t in hay)
            # 名称命中权重更高
            name = (r['name'] or '').lower()
            score += 2 * sum(1 for t in tokens if t in name)
            if score > 0 and (best is None or score > best[0]):
                best = (score, r)
        if best is None:
            return None
        r = best[1]
        return SkillDef(
            id=r['id'], name=r['name'], level=r['level'], role=r['role'], domain=r['domain'],
            version=r['version'], status=r['status'], definition=r['definition'],
            created_by=r['created_by'],
        )

    # ---- 废止联动 ----
    def mark_deprecated(self, standard_code: str) -> list[str]:
        """将引用指定标准号的 active 技能置为 deprecated，返回受影响技能 ID 列表。"""
        conn = get_conn()
        rows = conn.execute(
            "SELECT id FROM v2_skills WHERE status='active' AND (name LIKE ? OR definition LIKE ?)",
            (f'%{standard_code}%', f'%{standard_code}%'),
        ).fetchall()
        ids = [r['id'] for r in rows]
        if ids:
            placeholders = ','.join('?' * len(ids))
            conn.execute(
                f"UPDATE v2_skills SET status='deprecated' WHERE id IN ({placeholders})", ids
            )
            conn.commit()
        return ids
