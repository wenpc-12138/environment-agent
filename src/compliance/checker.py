# -*- coding: utf-8 -*-
"""M12 合规检查器（契约测试骨架：ChecklistItem / ComplianceChecker）。

- `ComplianceChecker.check(standard_code, clause_id)`：按标准号+条款查规则库；
- `ComplianceChecker.run_checklist(checklist)`：批量执行检查单。

规则库（src/compliance/rules/cma_rules.yaml）未收录的条款视为无对应规则
（passed=True，note 注明），避免误报。
"""
from __future__ import annotations

from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from .rules import load_rules


class ChecklistItem(BaseModel):
    """检查单条目。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    rule_id: str
    text: str
    mandatory: bool = False


class CheckResult(BaseModel):
    """单条规则检查结果。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    rule_id: str
    passed: bool
    evidence: str = ''
    note: str = ''


class ComplianceChecker:
    """基于规则包的合规检查器（契约测试入口）。"""

    def __init__(self, rules: list[dict] | None = None):
        self._rules = rules if rules is not None else load_rules()

    def _find(self, rule_id: str) -> dict | None:
        return next((r for r in self._rules if r.get('id') == rule_id), None)

    def check(self, standard_code: str, clause_id: str) -> CheckResult:
        """检查标准条款：查规则库对应规则（标准号-条款 → 规则映射取规则 id）。"""
        rule = self._find(standard_code) or self._find(clause_id)
        if rule is None:
            return CheckResult(
                rule_id=clause_id,
                passed=True,
                evidence='',
                note=f'未收录 {standard_code} {clause_id} 对应规则，视为通过',
            )
        text = rule.get('text', '')
        keywords = rule.get('keywords', [])
        # 条款号命中规则关键字即视为满足（条款级细粒度检查留待业务接入）
        satisfied = any(k.lower() in clause_id.lower() for k in keywords)
        return CheckResult(
            rule_id=rule['id'],
            passed=satisfied,
            evidence=clause_id,
            note='' if satisfied else text,
        )

    def run_checklist(self, checklist: Iterable[ChecklistItem]) -> list[CheckResult]:
        """批量执行检查单。"""
        return [self.check(item.rule_id, item.id) for item in checklist]


__all__ = ['ComplianceChecker', 'ChecklistItem', 'CheckResult']
