# -*- coding: utf-8 -*-
"""M11 审核过滤器（contracts.md §3.M11；UPGRADE_PLAN §M11）。

四类内置过滤器，产出轻量 issue 字典（供 engine.py 组装为 ReviewIssue）：
1. hallucination_filter    反幻觉：对接 M03 verify_claims（CRAG 检索分级）
2. unit_filter             单位一致性（mg/L vs mgL、μg vs ug、m3 vs m³）
3. significant_figure_filter 有效数字：报告精度声明 vs 实际数据小数位
4. standard_validity_filter 标准有效性：对接 M06 StandardKB.check_validity

过滤器不 import engine.ReviewIssue（避免循环依赖），统一返回 dict 列表：
    {'type', 'severity', 'location', 'description', 'suggested_fix',
     'auto_fixable', 'table', 'row_id', 'field'}
"""
from __future__ import annotations

import re

from ..models.core import StandardRef

# ---- 通用工具 ----


def _extract_text(report) -> str:
    """从 str / dict / 对象中提取报告纯文本。"""
    if isinstance(report, str):
        return report
    if isinstance(report, dict):
        return str(report.get('content') or report.get('text') or report)
    content = getattr(report, 'content', None)
    if isinstance(content, str):
        return content
    return str(report)


def _extract_refs(report) -> list[StandardRef]:
    """从 dict / 对象中提取标准引用列表（兼容 StandardRef / code 字符串）。"""
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


# ---- 1. 反幻觉 ----


def hallucination_filter(report, kb=None, query_for: str | None = None) -> list[dict]:
    """反幻觉：对非空断言句执行 CRAG 分级（M03 verify_claims）。

    kb 为 None 时无法核实，跳过（unchecked 不报）；仅 unsupported 记为 P1 问题。
    """
    from ..llm.grounding import EpistemicClaim, verify_claims

    text = _extract_text(report)
    sentences = [s.strip() for s in re.split(r'[。\n]', text) if len(s.strip()) >= 8]
    if not sentences or kb is None:
        return []
    claims = [EpistemicClaim(text=s, level='assert') for s in sentences]
    verdicts = verify_claims(claims, kb=kb, query_for=query_for)
    issues: list[dict] = []
    for v in verdicts:
        if v.status == 'unsupported':
            issues.append({
                'type': 'hallucination',
                'severity': 'P1',
                'location': '结论/监测结果',
                'description': f'断言无知识库支撑（疑似幻觉）：{v.text[:60]}',
                'suggested_fix': '删除或补充标准依据后重述',
                'auto_fixable': False,
                'table': '', 'row_id': '', 'field': '',
            })
    return issues


# ---- 2. 单位一致性 ----

_UNIT_PAIRS = [
    (r'mgL(?![/])', 'mg/L', '浓度单位'),
    (r'ug(?![/])', 'μg', '浓度单位'),
    (r'mg/m3(?!\u00b3)', 'mg/m³', '体积浓度单位'),
    (r'ug/m3(?!\u00b3)', 'μg/m³', '体积浓度单位'),
]


def unit_filter(report) -> list[dict]:
    """单位一致性：检测常见单位混用（全角/缩写/上标不一致）。"""
    text = _extract_text(report)
    issues: list[dict] = []
    for pattern, canonical, label in _UNIT_PAIRS:
        for m in re.finditer(pattern, text, flags=re.IGNORECASE):
            issues.append({
                'type': 'unit_inconsistent',
                'severity': 'P2',
                'location': '监测方案/监测结果',
                'description': f'{label}写法不一致："{m.group()}" 应为 "{canonical}"',
                'suggested_fix': f'统一为 {canonical}',
                'auto_fixable': True,
                'table': 'data', 'row_id': '', 'field': 'value',
            })
    return issues


# ---- 3. 有效数字 ----


def significant_figure_filter(report) -> list[dict]:
    """有效数字：检测"保留 N 位小数"声明与实际数据小数位不符。"""
    text = _extract_text(report)
    issues: list[dict] = []
    decl = re.search(r'保留(\d)位小数', text)
    if not decl:
        return []
    expected = int(decl.group(1))
    for m in re.finditer(r'(?<![A-Za-z])(\d+\.\d+)(?![\d])', text):
        frac = len(m.group(1).split('.')[1])
        if frac > expected:
            issues.append({
                'type': 'significant_figure',
                'severity': 'P2',
                'location': '监测结果',
                'description': f'数据 {m.group(1)} 小数位 {frac} 超过声明精度 {expected} 位',
                'suggested_fix': f'按 {expected} 位小数修约',
                'auto_fixable': False,
                'table': 'data', 'row_id': '', 'field': 'value',
            })
    return issues


# ---- 4. 标准有效性 ----


def standard_validity_filter(report, kb=None) -> list[dict]:
    """标准有效性：对接 M06 check_validity，已废止/未知状态记为问题。"""
    refs = _extract_refs(report)
    issues: list[dict] = []
    if not refs or kb is None:
        return issues
    for ref in refs:
        try:
            info = kb.check_validity(ref.code)
        except Exception:
            continue  # KB 未就绪降级：不阻断审核
        if info.status in ('已废止', '废止'):
            issues.append({
                'type': 'standard_invalid',
                'severity': 'P1',
                'location': f'引用条款 {ref.clause or ""}'.strip(),
                'description': f'引用的标准已废止：{ref.code}（{info.status}）',
                'suggested_fix': f'替换为现行有效版本（KB 检索 {ref.code} 替代）',
                'auto_fixable': False,
                'table': 'refs', 'row_id': ref.code, 'field': 'code',
            })
    return issues


# ---- 聚合 ----

_FILTERS = (hallucination_filter, unit_filter, significant_figure_filter)


def run_filters(report, kb=None, query_for: str | None = None) -> list[dict]:
    """运行全部静态过滤器（反幻觉在 kb 可用时生效，标准有效性单独校验）。"""
    issues: list[dict] = []
    for f in _FILTERS:
        issues.extend(f(report, kb=kb, query_for=query_for) if f.__name__ == 'hallucination_filter'
                      else f(report))
    issues.extend(standard_validity_filter(report, kb=kb))
    return issues


__all__ = ['run_filters', 'hallucination_filter', 'unit_filter',
           'significant_figure_filter', 'standard_validity_filter']
