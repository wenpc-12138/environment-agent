# -*- coding: utf-8 -*-
"""M11 审核引擎（contracts.md §3.M11）。

- engine.py：ReviewEngine（review/auto_fix/diff + 契约别名 run/submit_feedback）、
  ReviewIssue / ReviewFeedback；
- filters.py：四类过滤器（反幻觉/单位/有效数字/标准有效性）；
- diff.py：版本差异与"越改越乱"回滚保护。
"""
from .diff import diff_texts, diff_worsened
from .engine import ReviewEngine, ReviewFeedback, ReviewIssue
from .filters import run_filters

__all__ = ['ReviewEngine', 'ReviewIssue', 'ReviewFeedback',
           'run_filters', 'diff_texts', 'diff_worsened']
