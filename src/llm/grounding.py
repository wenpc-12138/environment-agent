# -*- coding: utf-8 -*-
"""M03 反幻觉管线（grounding，contracts.md §3.M03 改动点 4）。

三件套：
- `label_claims(text)` -> `list[EpistemicClaim]`：对句子做认知分级标注
  （断言 assert / 推测 hedge / 不确定 uncertain）。
- `ground_spans(answer, sources)` -> `list[GroundedSpan]`：按来源关键词把答案
  拆分为带来源标注的片段；无来源覆盖的片段标 `[UNVERIFIED]`。
- `verify_claims(claims, kb)` -> `list[VerifiedClaim]`：CRAG 检索分级
  （supported / unsupported / unchecked），对接 M06 StandardKB。

零硬依赖：不调用 LLM，纯规则 + 可选注入 KB 检索。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..kb.standards import StandardKB

_HEDGE_WORDS = ['可能', '或许', '预计', '大概', '估计', '或', '左右', '大约']
_UNCERTAIN_WORDS = ['不确定', '未知', '待核实', '无法确认', '不明确', '待查']


@dataclass
class EpistemicClaim:
    """认知分级标注结果。"""

    text: str
    level: str = 'assert'  # assert | hedge | uncertain
    reason: str = ''


@dataclass
class GroundedSpan:
    """答案片段 + 来源标注。"""

    text: str
    source: str = '[UNVERIFIED]'
    covered: bool = False


@dataclass
class VerifiedClaim:
    """CRAG 检索分级结果。"""

    text: str
    status: str = 'unchecked'  # supported | unsupported | unchecked
    source: str = ''
    score: float = 0.0


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[。！？!?])', text or '')
    return [p.strip() for p in parts if p.strip()]


def label_claims(text: str) -> list[EpistemicClaim]:
    """句子级认知分级标注。"""
    claims: list[EpistemicClaim] = []
    for s in _split_sentences(text):
        if any(w in s for w in _UNCERTAIN_WORDS):
            claims.append(EpistemicClaim(s, 'uncertain', '含不确定性词'))
        elif any(w in s for w in _HEDGE_WORDS):
            claims.append(EpistemicClaim(s, 'hedge', '含推测/约数词'))
        else:
            claims.append(EpistemicClaim(s, 'assert', ''))
    return claims


def ground_spans(answer: str, sources: list[str] | None = None) -> list[GroundedSpan]:
    """按来源关键词标注答案片段。

    sources 形如 ["标准号: 标题", ...] 或纯文本；片段含来源中 4 字以上关键词视为已覆盖。
    """
    sources = sources or []
    keys: list[tuple[str, str]] = []
    for s in sources:
        head = s.split(':', 1)[0].strip()
        keys.append((s, head if len(head) >= 2 else s))
    spans: list[GroundedSpan] = []
    for s in _split_sentences(answer):
        matched = ''
        for full, key in keys:
            if len(key) >= 4 and key in s:
                matched = full
                break
        spans.append(GroundedSpan(s, matched if matched else '[UNVERIFIED]', covered=bool(matched)))
    return spans


def verify_claims(claims: list[EpistemicClaim], kb: 'StandardKB | None' = None,
                  query_for: 'str | None' = None) -> list[VerifiedClaim]:
    """CRAG 检索分级：对断言/推测句用关键词查询知识库。

    - kb 为 None 或检索无命中 -> unchecked；
    - 命中且分数 >= 阈值 -> supported（附来源与分数）；
    - 未命中 -> unsupported。
    """
    out: list[VerifiedClaim] = []
    for c in claims:
        if kb is None or c.level == 'uncertain':
            out.append(VerifiedClaim(c.text, 'unchecked'))
            continue
        try:
            q = query_for or _extract_query(c.text)
            hits = kb.search(q, limit=1)
            if hits:
                top = hits[0]
                out.append(VerifiedClaim(
                    c.text, 'supported',
                    source=f'{top.get("std_no") or top.get("title") or ""}: {top.get("title") or ""}',
                    score=float(top.get('score') or 0.0),
                ))
            else:
                out.append(VerifiedClaim(c.text, 'unsupported'))
        except Exception:
            out.append(VerifiedClaim(c.text, 'unchecked'))
    return out


def _extract_query(text: str) -> str:
    """从句子提取检索关键词：取标准号形态（含数字的连续串）或去停用词前 12 字。"""
    m = re.search(r'[A-Za-z]{1,5}[\s-]?\d{3,5}(?:[.-]\d+)?', text)
    if m:
        return m.group(0)
    return text[:12]
