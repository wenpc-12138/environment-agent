# -*- coding: utf-8 -*-
"""M12 合规引擎行为测试（与契约测试 tests/compliance/test_compliance_contract.py 互补）。"""
from __future__ import annotations

from src.compliance import ComplianceChecker, ComplianceEngine, ChecklistItem
from src.compliance.rules import load_rules
from src.models.core import Project, StandardRef

FULL_REPORT = {
    'content': (
        '本报告依据本单位检验检测能力表（CMA 附表）编制。\n'
        '监测方法依据 GB 3838-2002，仪器校准有效期至 2026-12-31。\n'
        '监测目的明确，点位与频次已列明，结果如下。\n'
        '结论：达标。本报告经授权签字人签发并加盖 CMA 章。'
    ),
    'refs': [StandardRef(code='GB 3838-2002')],
}


class _StubKB:
    def check_validity(self, code: str):
        from src.models.core import ValidityInfo
        if code == 'GB 3838-2002':
            return ValidityInfo(code=code, status='已废止', effective_date='2002-06-01')
        return ValidityInfo(code=code, status='现行有效', effective_date='2024-01-01')


def test_rule_package_loaded():
    rules = load_rules()
    assert len(rules) >= 5
    ids = {r['id'] for r in rules}
    assert {'CMA-001', 'CMA-005', 'CMA-006'} <= ids


def test_checker_unknown_rule_passes():
    checker = ComplianceChecker()
    r = checker.check('HJ 166-2026', '5.1.3')
    assert r.passed is True
    assert '未收录' in r.note


def test_checker_run_checklist():
    checker = ComplianceChecker()
    items = [
        ChecklistItem(id='a', rule_id='CMA-001', text='能力表', mandatory=True),
        ChecklistItem(id='b', rule_id='CMA-XXX', text='未知规则', mandatory=False),
    ]
    results = checker.run_checklist(items)
    assert len(results) == 2
    assert results[0].rule_id == 'CMA-001'


def test_engine_missing_mandatory_rule_violation():
    eng = ComplianceEngine()
    res = eng.check(report={'content': '仅有一段简单结论。'})
    assert res.passed is False
    mandatory = [v for v in res.violations if v.severity == 'P1']
    assert mandatory, '缺失 mandatory 规则应记 P1'
    assert res.retry_allowed is True


def test_engine_full_report_passes():
    eng = ComplianceEngine()
    res = eng.check(report=FULL_REPORT)
    assert res.passed is True, [v.message for v in res.violations]


def test_engine_repealed_standard_is_p0_no_retry():
    eng = ComplianceEngine(kb=_StubKB())
    res = eng.check(report=FULL_REPORT)
    p0 = [v for v in res.violations if v.severity == 'P0']
    assert p0 and 'GB 3838-2002' in p0[0].rule_id
    assert res.retry_allowed is False


def test_engine_standard_validity_downgrade_without_kb():
    eng = ComplianceEngine()
    infos = eng.check_standard_validity([StandardRef(code='GB 3838-2002')])
    assert infos[0].status == '未知'
    assert infos[0].note == 'KB 未接入'


def test_engine_check_scope():
    proj = Project(id='prj-20260806-001', name='项目一', domain='D1',
                   capacity=['水', '气', '声'])
    out = ComplianceEngine().check_scope(proj, ['水', '土'])
    assert out == ['土']


def test_engine_audit_summary():
    eng = ComplianceEngine()
    proj = Project(id='prj-20260806-001', name='项目一', domain='D1')
    eng.check(project=proj, report={'content': '简单结论。'})
    eng.check(project=proj, report={'content': '简单结论。'})
    report = eng.audit('prj-20260806-001')
    assert report['checks'] == 2
    assert report['violations_total'] > 0
