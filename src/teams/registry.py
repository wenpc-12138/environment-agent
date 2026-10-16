# -*- coding: utf-8 -*-
"""领域团队注册表（P0 团队基座）。

组织模型：领域 = 团队（Team）。角色降级为团队内流程节点标签（node_id/label/tools），
不再全局激活；技能/流程模板/报告模板/工具白名单全部归集到团队。

- `TeamRegistry`：list / get / get_by_domain / create / update / remove / assign_task
- 团队上下文装配：build_team_context(domain) → {skills, tools, wf_template, report_tmpls}
- 新领域自举：create_onboarding_team（status=onboarding，产物 pending 审核）
"""
from __future__ import annotations

import json
from typing import Any

from ..core.db import get_conn

# 默认流程模板（无团队指定时兜底）
DEFAULT_WF = "report_pipeline"


def _r(row: Any) -> dict:
    return {
        "team_id": row["team_id"],
        "domain": row["domain"],
        "name": row["name"],
        "description": row["description"],
        "roles": json.loads(row["roles"] or "[]"),
        "skills": json.loads(row["skills"] or "[]"),
        "wf_template": row["wf_template"] or DEFAULT_WF,
        "report_tmpls": json.loads(row["report_tmpls"] or "[]"),
        "tools": json.loads(row["tools"] or "[]"),
        "status": row["status"],
        "created_at": row["created_at"],
    }


class TeamRegistry:
    """团队注册表：领域维度聚合角色/技能/流程/模板。"""

    def list(self) -> list[dict]:
        conn = get_conn()
        rows = conn.execute("SELECT * FROM team ORDER BY created_at").fetchall()
        return [_r(r) for r in rows]

    def get(self, team_id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute("SELECT * FROM team WHERE team_id = ?", (team_id,)).fetchone()
        return _r(row) if row else None

    def get_by_domain(self, domain: str) -> dict | None:
        conn = get_conn()
        row = conn.execute("SELECT * FROM team WHERE domain = ?", (domain,)).fetchone()
        return _r(row) if row else None

    def create(self, team_id: str, domain: str, name: str, description: str = "",
               roles: list | None = None, skills: list | None = None,
               wf_template: str = DEFAULT_WF, report_tmpls: list | None = None,
               tools: list | None = None, status: str = "active") -> dict:
        conn = get_conn()
        with conn:
            conn.execute(
                "INSERT INTO team(team_id, domain, name, description, roles, skills, wf_template, report_tmpls, tools, status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (team_id, domain, name, description,
                 json.dumps(roles or [], ensure_ascii=False),
                 json.dumps(skills or [], ensure_ascii=False),
                 wf_template,
                 json.dumps(report_tmpls or [], ensure_ascii=False),
                 json.dumps(tools or [], ensure_ascii=False),
                 status),
            )
        return self.get(team_id)  # type: ignore[return-value]

    def update(self, team_id: str, **fields: Any) -> dict | None:
        """按字段更新团队（roles/skills/wf_template/report_tmpls/tools/status/description）。"""
        allow = {"description", "wf_template", "status"}
        conn = get_conn()
        sets, vals = [], []
        for k, v in fields.items():
            if k in ("roles", "skills", "report_tmpls", "tools"):
                sets.append(f"{k} = ?")
                vals.append(json.dumps(v or [], ensure_ascii=False))
            elif k in allow:
                sets.append(f"{k} = ?")
                vals.append(v)
        if not sets:
            return self.get(team_id)
        vals.append(team_id)
        with conn:
            conn.execute(f"UPDATE team SET {', '.join(sets)} WHERE team_id = ?", vals)
        return self.get(team_id)

    def remove(self, team_id: str) -> bool:
        conn = get_conn()
        with conn:
            cur = conn.execute("DELETE FROM team WHERE team_id = ?", (team_id,))
            return cur.rowcount > 0

    def build_team_context(self, domain: str | None) -> dict:
        """按领域装配团队上下文（供对话 system prompt 注入 / 任务上下文挂载）。

        未命中领域时回退到默认团队（首个 active，冷启动兜底）；
        完全无团队时返回空上下文（skill 匹配仍走全库技能）。
        """
        team = self.get_by_domain(domain) if domain else None
        if not team:
            conn = get_conn()
            row = conn.execute(
                "SELECT * FROM team WHERE status='active' ORDER BY created_at LIMIT 1"
            ).fetchone()
            team = _r(row) if row else None
        if not team:
            return {"team": None, "skills": [], "tools": [], "wf_template": DEFAULT_WF,
                    "report_tmpls": [], "domain": domain}
        return {
            "team": team,
            "skills": team["skills"],
            "tools": team["tools"],
            "wf_template": team["wf_template"],
            "report_tmpls": team["report_tmpls"],
            "domain": team["domain"],
        }

    def create_onboarding_team(self, domain: str, name: str,
                               description: str = "", skills: list | None = None,
                               roles: list | None = None) -> dict:
        """新领域自举：创建 onboarding 状态团队（产物 pending 审核）。

        幂等：同领域已存在团队时复用（返回既有团队）。
        """
        existing = self.get_by_domain(domain)
        if existing:
            # 补充技能/节点（合并去重），不重复创建
            merged_skills = list(dict.fromkeys((existing["skills"] or []) + (skills or [])))
            if merged_skills and merged_skills != existing["skills"]:
                self.update(existing["team_id"], skills=merged_skills)
                existing = self.get(existing["team_id"]) or existing
            return existing
        team_id = f"T-{domain[:6]}-{len(self.list()) + 1:03d}"
        return self.create(
            team_id=team_id, domain=domain, name=name, description=description,
            roles=roles or [], skills=skills or [], status="onboarding",
        )


_registry: TeamRegistry | None = None


def get_registry() -> TeamRegistry:
    global _registry
    if _registry is None:
        _registry = TeamRegistry()
    return _registry
