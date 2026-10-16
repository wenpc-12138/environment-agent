# -*- coding: utf-8 -*-
"""M10 报告模板管理（contracts.md §3.M10）：monitoring / acceptance / eia 三类。"""
from __future__ import annotations

from ..models.core import ReportTemplate

BUILTIN_TEMPLATES: dict[str, ReportTemplate] = {
    'monitoring': ReportTemplate(
        id='monitoring', type='monitoring', docx_path='templates/report_monitoring.docx',
        placeholders=['project_name', 'points', 'items', 'standards', 'results', 'conclusion'],
    ),
    'acceptance': ReportTemplate(
        id='acceptance', type='acceptance', docx_path='templates/report_acceptance.docx',
        placeholders=['project_name', 'acceptance_scope', 'standards', 'results', 'verdict'],
    ),
    'eia': ReportTemplate(
        id='eia', type='eia', docx_path='templates/report_eia.docx',
        placeholders=['project_name', 'environment_baseline', 'impacts', 'measures', 'conclusion'],
    ),
}


def get_template(template_id: str | None) -> ReportTemplate | None:
    """按 id 取模板；None 返回 None（用默认结构）。"""
    if template_id is None:
        return None
    return BUILTIN_TEMPLATES.get(template_id)
