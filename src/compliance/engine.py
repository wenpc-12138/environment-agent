# -*- coding: utf-8 -*-
"""M12 合规引擎（contracts.md §3.M12）。

- `ComplianceEngine.check(project, report)`：对报告执行 CMA 规则包 → ComplianceResult；
- `check_standard_validity(refs)`：对接 M06 StandardKB.check_validity；
- `check_scope(project, scope)`：资质范围校验（返回超范围项）；
- `audit(project_id, since)`：合规检查记录汇总。

Violation / ComplianceResult 定义于 src/models/core.py（模块间共享类型）。
P0 = 不可整改重检（已废止标准引用）；P1 = 应修（mandatory 规则缺失）；
P2 = 建议（非强制规则）。
"""
from __future__ import annotations

from datetime import UTC, datetime

from ..models.core import ComplianceResult, Project, StandardRef, ValidityInfo, Violation
from .rules import load_rules


def _report_text(report) -> str:
    if isinstance(report, str):
        return report
    if isinstance(report, dict):
        return str(report.get('content') or report)
    content = getattr(report, 'content', None)
    return str(content) if isinstance(content, str) else str(report)


class ComplianceEngine:
    """CMA 合规检查引擎（R5/R6 协同职责）。"""

    def __init__(self, rules: list[dict] | None = None, kb=None):
        self._rules = rules if rules is not None else load_rules()
        self._kb = kb  # M06 StandardKB；None 时标准有效性检查降级
        self._records: list[dict] = []

    def check(self, project: Project | None = None, report=None) -> ComplianceResult:
        """对报告执行规则包检查：关键词未命中 mandatory 规则即违规。"""
        text = _report_text(report).lower()
        violations: list[Violation] = []
        for rule in self._rules:
            keywords = [str(k).lower() for k in rule.get('keywords', [])]
            satisfied = bool(keywords) and any(k in text for k in keywords)
            if not satisfied:
                violations.append(Violation(
                    rule_id=rule['id'],
                    severity='P1' if rule.get('mandatory') else 'P2',
                    message=rule.get('text', ''),
                    location='报告全文',
                ))
        # 标准有效性（已废止 → P0 不可重检）
        refs = _extract_standard_refs(report)
        for ref in refs:
            info = self._check_validity(ref.code)
            if info.status in ('已废止', '废止'):
                violations.append(Violation(
                    rule_id=f'CMA-STD-{ref.code}',
                    severity='P0',
                    message=f'引用标准已废止：{ref.code}（{info.status}）',
                    location=f'引用条款 {ref.clause or ""}'.strip(),
                ))
        self._records.append({
            'ts': datetime.now(UTC).isoformat(),
            'project_id': (project.id if project else None),
            'violations': [v.model_dump() for v in violations],
        })
        return ComplianceResult(
            passed=not violations,
            violations=violations,
            retry_allowed=not any(v.severity == 'P0' for v in violations),
        )

    def check_standard_validity(self, refs: list[StandardRef]) -> list[ValidityInfo]:
        """对接 M06：逐条返回标准有效性；KB 未就绪降级为'未知'。"""
        out: list[ValidityInfo] = []
        for ref in refs:
            out.append(self._check_validity(ref.code))
        return out

    def _check_validity(self, code: str) -> ValidityInfo:
        if self._kb is None:
            return ValidityInfo(code=code, status='未知', note='KB 未接入')
        try:
            return self._kb.check_validity(code)
        except Exception:
            return ValidityInfo(code=code, status='未知', note='KB 查询异常')

    def check_scope(self, project: Project | None = None, scope: list[str] | None = None) -> list[str]:
        """资质范围校验：返回 scope 中超出能力表的项（空列表 = 全部合规）。"""
        capacity = set(project.capacity) if project and getattr(project, 'capacity', None) else set()
        return [s for s in (scope or []) if s not in capacity]

    def audit(self, project_id: str, since: str | None = None) -> dict:
        """合规检查记录汇总（审计用）。"""
        records = [r for r in self._records if r.get('project_id') == project_id]
        if since:
            records = [r for r in records if r.get('ts', '') >= since]
        total = sum(len(r['violations']) for r in records)
        return {
            'project_id': project_id,
            'checks': len(records),
            'violations_total': total,
            'records': records,
        }


def _extract_standard_refs(report) -> list[StandardRef]:
    raw: list = []
    if isinstance(report, dict):
        raw = list(report.get('refs') or report.get('standard_refs') or [])
    else:
        raw = list(getattr(report, 'refs', None) or [])
    refs: list[StandardRef] = []
    for item in raw:
        if isinstance(item, StandardRef):
            refs.append(item)
        elif isinstance(item, str) and item.strip():
            refs.append(StandardRef(code=item.strip()))
    return refs


__all__ = ['ComplianceEngine', 'ComplianceResult', 'Violation']
