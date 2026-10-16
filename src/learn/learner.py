# -*- coding: utf-8 -*-
"""M13 闭环学习：Pattern 提取器与 Learner（contracts.md §3.M13 / 契约测试骨架）。

契约测试（tests/learn/test_learn_contract.py）要求：
- `Pattern`：字段含 domain / rule / confidence；
- `Learner.learn_from_review(self, reviews)`：从审核反馈（R5 意见）提取可复用模式；
- `Learner.extract_pattern(self, samples)`：从样本对（输入/输出/反馈）归纳模式。

产物经 OercrEngine.crystallize 沉淀为 SkillDef（status=pending_review，待 R8 审核）。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models.core import ReviewFeedback

_UTC_ISO = lambda: datetime.now(UTC).isoformat(timespec='seconds')


class Pattern(BaseModel):
    """可复用的行为模式（M13 学习产物）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    domain: str = ''  # 所属域（D1..D6）
    rule: str  # 模式规则描述（如 "报告数据单位统一使用 μg/m³"）
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: str = 'review'  # review / sample / oercr
    evidence: str = ''  # 支撑证据摘要
    ts: str = Field(default_factory=_UTC_ISO)


class Learner:
    """从审核反馈与样本对中提取可复用模式。"""

    def learn_from_review(self, reviews: list[Any]) -> list[Pattern]:
        """从审核反馈中学习模式。

        reviews 元素可为 `ReviewFeedback`（P0/P1 问题 → 规则）或 dict
        （{"issues": [{"type": ..., "description": ...}], "domain": ...}）。
        仅提取问题类型明确且描述非空的条目；summary 作为证据。
        """
        patterns: list[Pattern] = []
        for rv in reviews:
            if isinstance(rv, ReviewFeedback):
                issues = rv.issues
                domain = ''
                summary = rv.summary
            elif isinstance(rv, dict):
                issues = rv.get('issues') or []
                domain = rv.get('domain', '')
                summary = rv.get('summary', '')
            else:
                continue
            for issue in issues:
                if isinstance(issue, dict):
                    itype = issue.get('type') or ''
                    desc = issue.get('description') or ''
                    severity = issue.get('severity', 'P1')
                else:
                    itype = getattr(issue, 'type', '') or ''
                    desc = getattr(issue, 'description', '') or ''
                    severity = getattr(issue, 'severity', 'P1')
                if not itype or not desc:
                    continue
                confidence = 0.9 if severity == 'P0' else (0.7 if severity == 'P1' else 0.5)
                patterns.append(
                    Pattern(
                        domain=domain,
                        rule=f'{itype}: {desc}',
                        confidence=confidence,
                        source='review',
                        evidence=summary,
                    )
                )
        return patterns

    def extract_pattern(self, samples: list[Any]) -> list[Pattern]:
        """从样本对（输入/输出/反馈）归纳模式。

        每个样本可为 dict（{"input":..., "output":..., "feedback":...,
        "domain":...}）或 (input, output, feedback, domain?) 元组。
        依据反馈信号提炼规则：正面反馈提升置信度，负面反馈标记缺口。
        """
        patterns: list[Pattern] = []
        for sample in samples:
            if isinstance(sample, dict):
                inp = sample.get('input') or ''
                out = sample.get('output') or ''
                fb = sample.get('feedback') or ''
                domain = sample.get('domain', '')
            else:
                parts = list(sample)
                inp = parts[0] if len(parts) > 0 else ''
                out = parts[1] if len(parts) > 1 else ''
                fb = parts[2] if len(parts) > 2 else ''
                domain = parts[3] if len(parts) > 3 else ''
            if not fb:
                continue
            positive = any(k in str(fb).lower() for k in ('ok', 'pass', '正确', '通过', '符合'))
            negative = any(k in str(fb).lower() for k in ('fail', '错误', '超限', '不符合', '修正'))
            if not positive and not negative:
                continue
            rule = f'input={inp} -> output={out}' if out else f'input={inp}'
            patterns.append(
                Pattern(
                    domain=domain,
                    rule=rule,
                    confidence=0.85 if positive else 0.6,
                    source='sample',
                    evidence=fb,
                )
            )
        return patterns


__all__ = ['Learner', 'Pattern']
