# -*- coding: utf-8 -*-
"""M10 报告服务（contracts.md §3.M10）：generate / render_docx / fill_table / cite_standard。

- `cite_standard` 强制标注标准有效性：对接 M06 `StandardKB.check_validity`，
  无效标准（已废止）将 `StandardRef.valid` 置 False 并记入报告引用清单。
- 报告实例 / 章节 / 引用持久化于 SQLite（迁移 `0012_report_store`）：
  进程内 `_reports` 等为热缓存，任何变更即 upsert 落库，重启不丢数据。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from ..core.db import get_conn
from ..models.core import Report, ReportSection, StandardRef
from .generator import ReportGenerator
from .templates import BUILTIN_TEMPLATES, get_template


def _iso(dt: datetime | None) -> str:
    return dt.isoformat() if dt else ''


def _parse_dt(s: str | None) -> datetime:
    if not s:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except ValueError:
        return datetime.now(UTC)


class ReportService:
    """报告生成与引用管理（内存热缓存 + SQLite 持久化）。"""

    def __init__(self) -> None:
        self._generator = ReportGenerator()
        self._reports: dict[str, Report] = {}
        self._sections: dict[str, list[ReportSection]] = {}
        self._citations: dict[str, list[StandardRef]] = {}
        self._updated_at: dict[str, str] = {}
        self._load()

    # ---- 持久化 ----
    def _load(self) -> None:
        """启动时从 DB 恢复报告 / 章节 / 引用；表缺失（迁移未跑）则保持纯内存模式。"""
        conn = get_conn()
        try:
            conn.execute('SELECT 1 FROM reports LIMIT 1').fetchone()
        except sqlite3.Error:
            return
        for row in conn.execute('SELECT * FROM reports'):
            r = Report(
                id=row['report_id'], type=row['type'] or '', project_id=row['project_id'] or '',
                version=row['version'], docx_path=row['docx_path'] or None,
                content=row['content'] or '', status=row['status'] or 'drafting',
                data_sources=json.loads(row['data_sources'] or '[]'),
                created_by=row['created_by'] or 'R4',
                created_at=_parse_dt(row['created_at']),
            )
            self._reports[r.id] = r
            self._updated_at[r.id] = row['updated_at'] or ''
        for row in conn.execute('SELECT * FROM report_sections ORDER BY report_id, seq'):
            secs = self._sections.setdefault(row['report_id'], [])
            secs.append(ReportSection(
                name=row['name'] or '', content=row['content'] or '',
                refs=json.loads(row['refs'] or '[]'),
            ))
        for row in conn.execute('SELECT * FROM report_citations'):
            refs = self._citations.setdefault(row['report_id'], [])
            refs.append(StandardRef(
                code=row['code'], clause=row['clause'] or None,
                valid=bool(row['valid']), source=row['source'] or '',
            ))

    def save(self, report: Report) -> None:
        """将报告与关联章节 / 引用 upsert 落库（幂等，业务变更后调用）。"""
        self._reports[report.id] = report
        now = datetime.now(UTC).isoformat()
        conn = get_conn()
        with conn:
            conn.execute(
                'INSERT INTO reports(report_id, type, project_id, version, status, created_by,'
                ' content, docx_path, data_sources, created_at, updated_at)'
                ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
                ' ON CONFLICT(report_id) DO UPDATE SET'
                ' type=excluded.type, project_id=excluded.project_id, version=excluded.version,'
                ' status=excluded.status, created_by=excluded.created_by, content=excluded.content,'
                ' docx_path=excluded.docx_path, data_sources=excluded.data_sources,'
                ' updated_at=excluded.updated_at',
                (report.id, report.type, report.project_id, report.version, report.status,
                 report.created_by, report.content, report.docx_path or '',
                 json.dumps(report.data_sources, ensure_ascii=False),
                 _iso(report.created_at), now),
            )
            conn.execute('DELETE FROM report_sections WHERE report_id = ?', (report.id,))
            for i, sec in enumerate(self._sections.get(report.id, [])):
                conn.execute(
                    'INSERT INTO report_sections(report_id, seq, name, content, refs)'
                    ' VALUES (?, ?, ?, ?, ?)',
                    (report.id, i, sec.name, sec.content,
                     json.dumps(sec.refs, ensure_ascii=False)))
            conn.execute('DELETE FROM report_citations WHERE report_id = ?', (report.id,))
            for ref in self._citations.get(report.id, []):
                conn.execute(
                    'INSERT INTO report_citations(report_id, code, clause, valid, source)'
                    ' VALUES (?, ?, ?, ?, ?)',
                    (report.id, ref.code, ref.clause or '', int(ref.valid), ref.source))
        self._updated_at[report.id] = now

    def updated_at(self, report_id: str) -> str:
        """报告最近更新时间（ISO 字符串，展示用）。"""
        return self._updated_at.get(report_id, '')

    # ---- 生成 ----
    def generate(self, report_type: str, project_id: str,
                 template: str | None = None) -> Report:
        """创建报告（v1/drafting，编制员 R4），可选模板；返回 Report。

        P1 泛化：report_type 不再限定 monitoring/acceptance/eia 三枚举，
        从模板库取（用户上传归纳模板 / 内置兜底）。
        """
        now = datetime.now(UTC)
        report_id = f'rpt-{now:%Y%m%d}-{self._next_seq(now):03d}'
        report = Report(
            id=report_id, type=report_type, project_id=project_id,
            version=1, status='drafting', created_by='R4',
        )
        # P1：优先模板库（按类型取已发布模板；用户模板覆盖内置），内置字典兜底
        tpl = get_template(template)
        if tpl is None:
            try:
                from .template_store import get_store
                db_tpl = get_store().get_by_type(report_type)
            except Exception:
                db_tpl = None
            tpl = db_tpl if db_tpl else BUILTIN_TEMPLATES.get(report_type)
        placeholders = tpl.get('placeholders') if isinstance(tpl, dict) else (tpl.placeholders if tpl else [])
        plan = {'_report_id': report_id, 'type': report_type, 'placeholders': placeholders}
        self._sections[report_id] = self._generator.generate(plan, [], {})
        # 学习闭环：生成时应用同类报告语料模式（反复学习、提炼、结晶，后续报告更完善）
        self._apply_learning(report_id, report_type)
        self._reports[report_id] = report
        self._citations.setdefault(report_id, [])
        self.save(report)
        return report

    def _apply_learning(self, report_id: str, report_type: str) -> None:
        """从 report_learning 语料模式提炼增强：附加高频学习章节 + 编制指引。"""
        try:
            import report_learning as rl

            pat = rl.pattern(report_type)
            if not pat.get('sections'):
                return
            sections = self._sections.setdefault(report_id, [])
            known = {getattr(s, 'name', '') for s in sections}
            # 1) 硬编码 5 节之外的高频学习章节（同任务累计语料提炼）
            for extra in rl.extra_sections(pat):
                name = extra.get('name', '')
                if name and name not in known:
                    sections.append(ReportSection(
                        name=name, content=rl.learned_extra_content(extra), refs=[]))
            # 2) 编制指引合并进 monitoring_plan（数据要求先于正文给出）
            guide = rl.render_guide(pat, max_n=8)
            if guide:
                for sec in sections:
                    if getattr(sec, 'name', '') == 'monitoring_plan':
                        sec.content = f"{sec.content}\n\n{guide}"
                        break
        except Exception:
            pass  # 语料模式不可用不影响生成

    @staticmethod
    def learning_stats() -> dict:
        """报告知识库学习统计：三类语料模式 + 报告沉淀的知识库条目数。"""
        out: dict[str, Any] = {'patterns': {}, 'kb': {}}
        try:
            import report_learning as rl
            for t in ('monitoring', 'acceptance', 'eia'):
                out['patterns'][t] = rl.pattern(t)
        except Exception:
            pass
        try:
            conn = get_conn()
            total = conn.execute('SELECT COUNT(*) c FROM kb_entries').fetchone()['c']
            report_entries = conn.execute(
                "SELECT COUNT(*) c FROM kb_entries WHERE url LIKE 'report://%'").fetchone()['c']
            out['kb'] = {'total': total, 'report_entries': report_entries}
        except Exception:
            pass
        return out

    def _next_seq(self, day: datetime) -> int:
        prefix = f'rpt-{day:%Y%m%d}-'
        existing = {r.id for r in self._reports.values() if r.id.startswith(prefix)}
        # DB 兜底：多实例/跨重启同日已存在 ID 不重复（避免主键冲突）
        try:
            conn = get_conn()
            rows = conn.execute('SELECT report_id FROM reports WHERE report_id LIKE ?',
                                (prefix + '%',)).fetchall()
            existing.update(row['report_id'] for row in rows)
        except sqlite3.Error:
            pass
        return len(existing) + 1

    # ---- 渲染 ----
    def render_docx(self, report: Report) -> str:
        """渲染 docx 并更新 report.docx_path，返回路径。"""
        from .exporter import docx

        path = docx(self._sections.get(report.id, []), f'data/reports/{report.id}.docx')
        report.docx_path = path
        self.save(report)
        return path

    # ---- 表格填充 ----
    def fill_table(self, report_id: str, data: list[dict]) -> None:
        """将监测结果数据填入 'results' 章节（达标判定自动重算）。"""
        if report_id not in self._reports:
            raise KeyError(f'报告不存在: {report_id}')
        sections = self._sections.setdefault(report_id, [])
        for sec in sections:
            if sec.name == 'results':
                sec.content = ReportGenerator._results({}, data)
        self._citations.setdefault(report_id, [])
        self.save(self._reports[report_id])

    # ---- 标准引用（强制有效性标注）----
    def cite_standard(self, report_id: str, ref: StandardRef) -> None:
        """引用标准并强制标注有效性（M06 check_validity；DB 不可用降级按原值）。"""
        if report_id not in self._reports:
            raise KeyError(f'报告不存在: {report_id}')
        try:
            from ..kb.standards import StandardKB

            info = StandardKB().check_validity(ref.code)
            ref.valid = info.status in ('现行有效', '即将实施', '未知')
            ref.source = 'kb'
        except Exception:
            pass  # 知识库未就绪：保留 ref.valid 原值
        refs = self._citations.setdefault(report_id, [])
        if not any(r.code == ref.code for r in refs):
            refs.append(ref)
        self.save(self._reports[report_id])

    def citations(self, report_id: str) -> list[StandardRef]:
        """报告已引用标准（含有效性标注）。"""
        return self._citations.get(report_id, [])

    def get(self, report_id: str) -> Report | None:
        return self._reports.get(report_id)
