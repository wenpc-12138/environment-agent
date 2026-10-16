# -*- coding: utf-8 -*-
"""反幻觉管线行为测试：认知分级 / 来源标注 / CRAG 检索分级。"""
from __future__ import annotations

from src.llm import EpistemicClaim, GroundedSpan, VerifiedClaim
from src.llm import ground_spans, label_claims, verify_claims


def test_label_claims_levels() -> None:
    claims = label_claims('标准已发布。预计下月实施。具体日期待核实。')
    assert len(claims) == 3
    levels = [c.level for c in claims]
    assert 'assert' in levels
    assert 'hedge' in levels
    assert 'uncertain' in levels
    assert all(isinstance(c, EpistemicClaim) for c in claims)


def test_ground_spans_coverage() -> None:
    spans = ground_spans(
        '本报告依据HJ 166-2026编制。此处无明确来源。',
        ['HJ 166-2026: 土壤环境监测技术规范'],
    )
    assert len(spans) == 2
    assert spans[0].covered is True
    assert 'HJ 166-2026' in spans[0].source
    assert spans[1].covered is False
    assert spans[1].source == '[UNVERIFIED]'
    assert all(isinstance(s, GroundedSpan) for s in spans)


def test_verify_claims_no_kb_unchecked() -> None:
    claims = label_claims('氨氮执行HJ 535-2009。标准将于明年废止。')
    verified = verify_claims(claims, kb=None)
    assert len(verified) == len(claims)
    assert all(v.status == 'unchecked' for v in verified)
    assert all(isinstance(v, VerifiedClaim) for v in verified)
