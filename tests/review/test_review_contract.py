# -*- coding: utf-8 -*-
"""M11 报告审核契约测试（contracts.md §3.M11）。

src/review/ 未实现时自动 skip；实现后自动激活。
"""
from __future__ import annotations

import inspect

import pytest


def test_review_issue_fields() -> None:
    """ReviewIssue 字段与契约一致（description 必填）。"""
    engine = pytest.importorskip('src.review.engine', reason='M11 ReviewEngine 未实现')
    fields = engine.ReviewIssue.model_fields
    assert {'table', 'row_id', 'field', 'description', 'severity'} <= set(fields)
    assert fields['description'].is_required()


def test_review_feedback_fields() -> None:
    """ReviewFeedback 字段与契约一致。"""
    engine = pytest.importorskip('src.review.engine', reason='M11 ReviewEngine 未实现')
    assert {'issue', 'status', 'comment', 'reviewer'} <= set(engine.ReviewFeedback.model_fields)


def test_review_engine_signatures() -> None:
    """ReviewEngine.run / submit_feedback。"""
    engine = pytest.importorskip('src.review.engine', reason='M11 ReviewEngine 未实现')
    run = inspect.signature(engine.ReviewEngine.run)
    assert list(run.parameters)[:2] == ['self', 'report']
    feedback = inspect.signature(engine.ReviewEngine.submit_feedback)
    assert list(feedback.parameters)[:2] == ['self', 'feedback']
