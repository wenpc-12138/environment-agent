# -*- coding: utf-8 -*-
"""M11 版本差异与回滚保护（contracts.md §3.M11）。

`diff_texts` 逐行比较两版本报告；`diff_worsened` 检测"越改越乱"
（新增问题行数 > 修复行数即判定恶化，auto_fix 结果须通过此闸门才采纳）。
"""
from __future__ import annotations

import difflib

_MARKERS = ('待填写', '超标', '错误', '矛盾', '不一致', '缺失')


def diff_texts(a: str, b: str) -> list[str]:
    """两版本报告的逐行差异（统一 diff 文本行）。"""
    if a == b:
        return []
    la = [x.rstrip() for x in a.splitlines()]
    lb = [x.rstrip() for x in b.splitlines()]
    out: list[str] = []
    sm = difflib.SequenceMatcher(None, la, lb, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        if tag == 'replace':
            for i in range(i1, i2):
                out.append(f'- {la[i]}')
            for j in range(j1, j2):
                out.append(f'+ {lb[j]}')
        elif tag == 'delete':
            for i in range(i1, i2):
                out.append(f'- {la[i]}')
        elif tag == 'insert':
            for j in range(j1, j2):
                out.append(f'+ {lb[j]}')
    return out


def _issue_count(text: str) -> int:
    """统计文本中的问题标记出现次数（越改越乱度量）。"""
    return sum(text.count(mk) for mk in _MARKERS)


def diff_worsened(a: str, b: str) -> bool:
    """越改越乱检测：b 的问题标记数多于 a 视为恶化（auto_fix 结果须通过闸门）。"""
    return _issue_count(b) > _issue_count(a)


__all__ = ['diff_texts', 'diff_worsened']
