# -*- coding: utf-8 -*-
"""M12 合规引擎（contracts.md §3.M12）。

- checker.py：ComplianceChecker（契约测试入口：check / run_checklist）；
- engine.py：ComplianceEngine（check / check_standard_validity / check_scope / audit）；
- rules/：CMA 规则包（YAML 静态规则：能力表/方法标准/人员资格/设备校准/报告要素）。

Violation / ComplianceResult 定义于 src/models/core.py。
"""
from .checker import CheckResult, ChecklistItem, ComplianceChecker
from .engine import ComplianceEngine

__all__ = ['ComplianceEngine', 'ComplianceChecker', 'ChecklistItem', 'CheckResult']
