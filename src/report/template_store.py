# -*- coding: utf-8 -*-
"""报告模板库（P1 泛化基座）。

- `TemplateStore`：DB 持久化模板 CRUD + 按类型取用 + 归纳入库。
- `learn_template_from_upload`：用户上传报告 → 解析结构 → 提取占位符 → 生成模板建议。
- 内置模板（monitoring/acceptance/eia）冷启动兜底；用户模板同 type 可覆盖升级。
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..core.db import get_conn

# 常见报告章节标题（用于结构解析）
_SECTION_KW = [
    "项目概况", "工程分析", "环境现状", "现状监测", "监测方案", "质量控制", "质量保证",
    "监测结果", "结果与讨论", "影响预测", "防治措施", "环保措施", "风险识别", "响应流程",
    "应急预案", "评价结论", "结论与建议", "验收方案", "验收结论", "排放边界", "数据收集",
    "核算方法", "核算结果", "组织保障", "保障措施", "总则", "编制依据", "适用范围",
]


def _r(row: Any) -> dict:
    return {
        "template_id": row["template_id"],
        "type": row["type"],
        "name": row["name"],
        "sections": json.loads(row["sections"] or "[]"),
        "placeholders": json.loads(row["placeholders"] or "[]"),
        "prompt": row["prompt"] or "",
        "export_title": row["export_title"] or "",
        "docx_path": row["docx_path"] or "",
        "source_uploads": json.loads(row["source_uploads"] or "[]"),
        "status": row["status"],
        "builtin": bool(row["builtin"]),
        "created_at": row["created_at"],
    }


class TemplateStore:
    """报告模板库：配置驱动 + 自学习。"""

    def list(self, status: str = "") -> list[dict]:
        conn = get_conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM report_template WHERE status=? ORDER BY builtin, created_at", (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM report_template ORDER BY builtin, created_at"
            ).fetchall()
        return [_r(r) for r in rows]

    def get(self, template_id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM report_template WHERE template_id=?", (template_id,)
        ).fetchone()
        return _r(row) if row else None

    def get_by_type(self, type_: str) -> dict | None:
        """按报告类型取已发布模板（用户模板优先，内置兜底）。"""
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM report_template WHERE type=? AND status='published'"
            " ORDER BY builtin ASC, created_at DESC LIMIT 1", (type_,)
        ).fetchone()
        return _r(row) if row else None

    def save(self, template_id: str, type_: str, name: str, sections: list | None = None,
             placeholders: list | None = None, prompt: str = "", export_title: str = "",
             docx_path: str = "", source_uploads: list | None = None,
             status: str = "draft", builtin: bool = False) -> dict:
        conn = get_conn()
        exists = conn.execute(
            "SELECT 1 FROM report_template WHERE template_id=?", (template_id,)
        ).fetchone()
        with conn:
            if exists:
                conn.execute(
                    "UPDATE report_template SET type=?, name=?, sections=?, placeholders=?,"
                    " prompt=?, export_title=?, docx_path=?, source_uploads=?, status=? WHERE template_id=?",
                    (type_, name, json.dumps(sections or [], ensure_ascii=False),
                     json.dumps(placeholders or [], ensure_ascii=False), prompt, export_title,
                     docx_path, json.dumps(source_uploads or [], ensure_ascii=False),
                     status, template_id),
                )
            else:
                conn.execute(
                    "INSERT INTO report_template(template_id, type, name, sections, placeholders,"
                    " prompt, export_title, docx_path, source_uploads, status, builtin)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (template_id, type_, name, json.dumps(sections or [], ensure_ascii=False),
                     json.dumps(placeholders or [], ensure_ascii=False), prompt, export_title,
                     docx_path, json.dumps(source_uploads or [], ensure_ascii=False),
                     status, 1 if builtin else 0),
                )
        return self.get(template_id)  # type: ignore[return-value]

    def publish(self, template_id: str) -> dict | None:
        conn = get_conn()
        with conn:
            conn.execute(
                "UPDATE report_template SET status='published' WHERE template_id=?", (template_id,)
            )
        return self.get(template_id)

    def delete(self, template_id: str) -> bool:
        conn = get_conn()
        with conn:
            cur = conn.execute("DELETE FROM report_template WHERE template_id=?", (template_id,))
            return cur.rowcount > 0


# ---------------- 模板归纳引擎 ----------------

def _extract_sections(text: str) -> list[dict]:
    """从报告正文解析章节结构（按标题关键词 + 编号模式）。"""
    lines = (text or "").splitlines()
    sections: list[dict] = []
    cur: dict | None = None
    for ln in lines:
        s = ln.strip()
        if not s or len(s) > 40:
            continue
        # 匹配 "1 项目概况" / "一、项目概况" / "1.1 监测方案" 等标题行
        if re.match(r"^(\d+(\.\d+)?[、.．\s]|[一二三四五六七八九十]+[、.．])", s):
            title = re.sub(r"^[\d一二三四五六七八九十]+[、.．\s]+", "", s).strip()
            if title:
                if cur:
                    sections.append(cur)
                cur = {"name": title, "desc": ""}
                continue
        # 无编号但匹配已知关键词
        if cur is None and any(k in s for k in _SECTION_KW):
            cur = {"name": s, "desc": ""}
    if cur:
        sections.append(cur)
    return sections


def _extract_placeholders(text: str) -> list[str]:
    """提取通用占位符：中括号/花括号字段 + 常见数据类名词（去具体值）。"""
    phs: list[str] = []
    for m in re.finditer(r"[【\[]([^】\]]{2,20})[】\]]", text or ""):
        v = m.group(1).strip()
        if v and v not in phs:
            phs.append(v)
    return phs[:20]


def learn_template_from_upload(upload_id: str, text: str, report_type: str,
                               name: str = "") -> dict:
    """用户上传报告 → 自动归纳模板建议。

    返回模板规格建议（sections + placeholders + 建议 prompt），由前端预览确认后 save/publish。
    """
    sections = _extract_sections(text)
    if not sections:
        # 兜底：按常见 5 节结构
        sections = [{"name": "项目概况", "desc": ""}, {"name": "环境现状", "desc": ""},
                    {"name": "主要结论", "desc": ""}, {"name": "防治措施", "desc": ""},
                    {"name": "结论与建议", "desc": ""}]
    placeholders = _extract_placeholders(text)
    if not name:
        name = f"{report_type}报告模板"
    template_id = f"tpl-{report_type}-{len(placeholders)}-{upload_id[-6:]}"
    return {
        "template_id": template_id,
        "type": report_type,
        "name": name,
        "sections": sections,
        "placeholders": placeholders,
        "prompt": f"按{name}结构生成报告：{'; '.join(s['name'] for s in sections)}。",
        "export_title": name,
        "status": "draft",
    }


_store: TemplateStore | None = None


def get_store() -> TemplateStore:
    global _store
    if _store is None:
        _store = TemplateStore()
    return _store
