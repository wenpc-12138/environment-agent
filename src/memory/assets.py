# -*- coding: utf-8 -*-
"""统一记忆资产目录（Memory Assets 轻量版）
对标 TencentDB-Agent-Memory 的 Memory Assets + ACL 治理：
- 各记忆层（episodic/fact/skill/profile/summary）写入时登记为资产；
- 召回时累计 use_count，作为排序加权与淘汰依据；
- 支持 private/team/agent 三级可见性，团队内可共享经验。

对外接口全部 try/except 包裹，登记失败不阻断主流程。
"""
from __future__ import annotations

from ..core.db import get_conn

_VISIBILITIES = ("private", "team", "agent")


def _conn():
    return get_conn()


def register(asset_type: str, source_id: str, title: str = "",
             content: str = "", visibility: str = "private",
             team_id: str = "", owner: str = "local") -> None:
    """登记（或更新）一条记忆资产。content 仅取预览，避免冗余存储。"""
    if asset_type not in ("episodic", "fact", "skill", "profile", "summary", "wiki", "canvas"):
        return
    if visibility not in _VISIBILITIES:
        visibility = "private"
    asset_id = f"{asset_type}:{source_id}"
    preview = (content or "")[:200]
    conn = _conn()
    try:
        with conn:
            conn.execute(
                """INSERT INTO memory_assets
                   (asset_id, asset_type, source_id, visibility, team_id, owner,
                    title, content_preview, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?, datetime('now','localtime'), datetime('now','localtime'))
                   ON CONFLICT(asset_id) DO UPDATE SET
                     title=excluded.title,
                     content_preview=excluded.content_preview,
                     visibility=excluded.visibility,
                     team_id=excluded.team_id,
                     owner=excluded.owner,
                     status='active',
                     updated_at=datetime('now','localtime')""",
                (asset_id, asset_type, source_id, visibility, team_id, owner,
                 title, preview),
            )
    except Exception:
        pass


def touch(asset_type: str, source_id: str) -> None:
    """召回时累计使用次数与最近使用时间。"""
    asset_id = f"{asset_type}:{source_id}"
    conn = _conn()
    try:
        with conn:
            conn.execute(
                "UPDATE memory_assets SET use_count=use_count+1, "
                "last_used_at=datetime('now','localtime') WHERE asset_id=?",
                (asset_id,),
            )
    except Exception:
        pass


def list_assets(asset_type: str | None = None, visibility: str | None = None,
                status: str = "active", q: str = "",
                limit: int = 200, offset: int = 0) -> list[dict]:
    """资产列表查询：可过滤类型/可见性/关键词，按最近使用排序。"""
    sql = ["SELECT * FROM memory_assets WHERE 1=1"]
    args: list = []
    if asset_type:
        sql.append("AND asset_type=?")
        args.append(asset_type)
    if visibility:
        sql.append("AND visibility=?")
        args.append(visibility)
    if status:
        sql.append("AND status=?")
        args.append(status)
    if q:
        sql.append("AND (title LIKE ? OR content_preview LIKE ? OR asset_id LIKE ?)")
        args += [f"%{q}%", f"%{q}%", f"%{q}%"]
    sql.append("ORDER BY use_count DESC, updated_at DESC LIMIT ? OFFSET ?")
    args += [limit, offset]
    try:
        rows = _conn().execute(" ".join(sql), args).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def set_visibility(asset_id: str, visibility: str, team_id: str = "") -> bool:
    """修改资产可见性（private/team/agent）。"""
    if visibility not in _VISIBILITIES:
        return False
    try:
        with _conn():
            cur = _conn().execute(
                "UPDATE memory_assets SET visibility=?, team_id=?, "
                "updated_at=datetime('now','localtime') WHERE asset_id=?",
                (visibility, team_id, asset_id),
            )
        return cur.rowcount > 0
    except Exception:
        return False


def set_status(asset_id: str, status: str) -> bool:
    """归档/恢复资产（active/archived）。"""
    if status not in ("active", "archived"):
        return False
    try:
        with _conn():
            cur = _conn().execute(
                "UPDATE memory_assets SET status=?, "
                "updated_at=datetime('now','localtime') WHERE asset_id=?",
                (status, asset_id),
            )
        return cur.rowcount > 0
    except Exception:
        return False


def remove(asset_type: str, source_id: str) -> None:
    """删除资产登记（对应底层记忆删除时联动）。"""
    asset_id = f"{asset_type}:{source_id}"
    try:
        with _conn():
            _conn().execute("DELETE FROM memory_assets WHERE asset_id=?", (asset_id,))
    except Exception:
        pass


def stats() -> dict:
    """资产统计：各类型数量 + 可见性分布。"""
    try:
        rows = _conn().execute(
            "SELECT asset_type, COUNT(*) AS n FROM memory_assets "
            "WHERE status='active' GROUP BY asset_type").fetchall()
        vis_rows = _conn().execute(
            "SELECT visibility, COUNT(*) AS n FROM memory_assets "
            "WHERE status='active' GROUP BY visibility").fetchall()
        return {
            "by_type": {r["asset_type"]: r["n"] for r in rows},
            "by_visibility": {r["visibility"]: r["n"] for r in vis_rows},
            "total": sum(r["n"] for r in rows),
        }
    except Exception:
        return {"by_type": {}, "by_visibility": {}, "total": 0}


def add_team_visibility_filters(extra_team_ids: list[str] | None = None) -> str:
    """ACL 辅助：拼接可见性过滤 SQL 片段（private 仅自己 / team 团队内 / agent 全量）。"""
    # 当前为单用户本地场景，private+team 均可见；预留多用户扩展点。
    return "(visibility IN ('private','team','agent'))"
