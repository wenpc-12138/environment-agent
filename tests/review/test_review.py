# -*- coding: utf-8 -*-
"""M11 审核引擎行为测试（与契约测试 tests/review/test_review_contract.py 互补）。"""
from __future__ import annotations

import pytest

from src.models.core import StandardRef
from src.review import ReviewEngine, ReviewFeedback
from src.review.diff import diff_texts, diff_worsened
from src.review.filters import significant_figure_filter, standard_validity_filter, unit_filter

CLEAN_REPORT = (
    '监测目的：验证排放口达标。\n'
    '监测点位：厂界东侧 1 个点位，监测频次每日 3 次。\n'
    '监测结果：颗粒物浓度 12.3 mg/L，符合 GB 3838-2002 限值。\n'
    '结论：各项指标均达标。\n'
)


class _StubKB:
    """M06 有效性桩：GB 3838-2002 已废止。"""

    def check_validity(self, code: str):
        from src.models.core import ValidityInfo
        if code == 'GB 3838-2002':
            return ValidityInfo(code=code, status='已废止', effective_date='2002-06-01')
        return ValidityInfo(code=code, status='现行有效', effective_date='2024-01-01')


def test_unit_filter_detects_inconsistent_unit():
    issues = unit_filter('颗粒物浓度 12.3 mgL，参考限值 10 mg/L')
    assert issues, '应检出 mgL 与 mg/L 混用'
    assert issues[0]['type'] == 'unit_inconsistent'
    assert issues[0]['auto_fixable'] is True


def test_unit_filter_clean():
    assert unit_filter('浓度 12.3 mg/L 与 5.0 μg/m³ 均为规范写法') == []


def test_sigfig_filter_detects_precision_overflow():
    issues = significant_figure_filter('结果保留1位小数。颗粒物 12.345 mg/L')
    assert issues, '12.345 超出保留 1 位小数的声明精度'
    assert issues[0]['type'] == 'significant_figure'


def test_review_clean_report_passes():
    eng = ReviewEngine()
    fb = eng.review(CLEAN_REPORT)
    assert fb.issues == []
    assert fb.summary == '未发现问题，通过审核'
    assert fb.reviewer == 'R5'


def test_review_assigns_auto_fixable_p2_issue():
    eng = ReviewEngine()
    fb = eng.review(CLEAN_REPORT + '补充数据：0.5 mgL 未统一单位。')
    p2 = [i for i in fb.issues if i.severity == 'P2']
    assert p2 and p2[0].auto_fixable
    assert p2[0].id.startswith('P2-')
    assert 'P2 1' in fb.summary


def test_auto_fix_fixes_only_fixable_and_bumps_version():
    eng = ReviewEngine()
    text = '数据 0.5 mgL 未统一。'
    fb = eng.review(text)                # v1
    fixed = eng.auto_fix(text, fb.issues)  # v2
    assert fixed.status == 'auto_fix'
    assert 'mg/L' in fixed.content
    assert 2 in eng.versions()


def test_diff_between_versions():
    eng = ReviewEngine()
    eng.review('版本甲：数据 0.5 mgL。')          # v1
    fb = eng.review('版本甲：数据 0.5 mgL。')     # v2（文本未变，版本号递增）
    eng.auto_fix('版本甲：数据 0.5 mgL。', fb.issues)  # v3（修复单位）
    diffs = eng.diff(1, 3)
    assert diffs, '两版本应有差异'
    assert any(d.startswith('+') for d in diffs)


def test_diff_worsened_detects_regression():
    a = '结论：全部达标，无超标。'
    b = '结论：全部达标，无超标。补充：存在 2 处超标。'
    assert diff_worsened(a, b) is True
    assert diff_worsened(b, a) is False


def test_standard_validity_filter_marks_repealed():
    report = {'content': '引用 GB 3838-2002 判定达标。',
              'refs': [StandardRef(code='GB 3838-2002')]}
    issues = standard_validity_filter(report, kb=_StubKB())
    assert issues
    assert issues[0]['type'] == 'standard_invalid'
    assert issues[0]['severity'] == 'P1'


def test_review_with_kb_flags_repealed_standard():
    eng = ReviewEngine(kb=_StubKB())
    fb = eng.review({'content': '按 GB 3838-2002 判定。',
                     'refs': [StandardRef(code='GB 3838-2002')]})
    types = {i.type for i in fb.issues}
    assert 'standard_invalid' in types


def test_submit_feedback_records_reviewer_opinion():
    eng = ReviewEngine()
    eng.review(CLEAN_REPORT)
    eng.submit_feedback(ReviewFeedback(issue='同意', status='approved',
                                       reviewer='R5', comment='无修改意见'))
    assert len(eng.feedback_history()) == 1
    assert eng.feedback_history()[0].status == 'approved'


def test_hallucination_filter_needs_kb():
    from src.review.filters import hallucination_filter
    assert hallucination_filter(CLEAN_REPORT, kb=None) == []
