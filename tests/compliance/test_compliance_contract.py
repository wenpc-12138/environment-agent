# -*- coding: utf-8 -*-
"""M12 合规审查契约测试（contracts.md §3.M12）。

src/compliance/ 未实现时自动 skip；实现后自动激活。
"""
from __future__ import annotations

import inspect

import pytest


def test_checklist_item_fields() -> None:
    """ChecklistItem 字段与契约一致。"""
    checker = pytest.importorskip('src.compliance.checker', reason='M12 ComplianceChecker 未实现')
    assert {'id', 'rule_id', 'text', 'mandatory'} <= set(checker.ChecklistItem.model_fields)


def test_compliance_checker_signatures() -> None:
    """ComplianceChecker.check / run_checklist。"""
    checker = pytest.importorskip('src.compliance.checker', reason='M12 ComplianceChecker 未实现')
    check = inspect.signature(checker.ComplianceChecker.check)
    assert list(check.parameters)[:3] == ['self', 'standard_code', 'clause_id']
    cl = inspect.signature(checker.ComplianceChecker.run_checklist)
    assert list(cl.parameters)[:2] == ['self', 'checklist']


def test_check_result_fields() -> None:
    """CheckResult 字段与契约一致。"""
    checker = pytest.importorskip('src.compliance.checker', reason='M12 CheckResult 未实现')
    assert {'rule_id', 'passed', 'evidence', 'note'} <= set(checker.CheckResult.model_fields)
