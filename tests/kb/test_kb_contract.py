# -*- coding: utf-8 -*-
"""M06 知识库契约测试（contracts.md §3.M06）。

src/kb/ 未实现时自动 skip；实现后自动激活并校验公开签名。
"""
from __future__ import annotations

import inspect

import pytest


def test_standard_kb_ingest_signature() -> None:
    """StandardKB.ingest(path, kind) -> int。"""
    kb = pytest.importorskip('src.kb.standards', reason='M06 StandardKB 未实现')
    sig = inspect.signature(kb.StandardKB.ingest)
    assert list(sig.parameters)[:3] == ['self', 'path', 'kind']


def test_standard_kb_search_signature() -> None:
    """StandardKB.search(query, filters=None, top_k=10)。"""
    kb = pytest.importorskip('src.kb.standards', reason='M06 StandardKB 未实现')
    sig = inspect.signature(kb.StandardKB.search)
    names = list(sig.parameters)
    assert names[:2] == ['self', 'query']
    assert 'filters' in names
    assert sig.parameters['top_k'].default == 10


def test_standard_kb_validity_signatures() -> None:
    """get_standard / check_validity。"""
    kb = pytest.importorskip('src.kb.standards', reason='M06 StandardKB 未实现')
    assert 'code' in inspect.signature(kb.StandardKB.get_standard).parameters
    assert list(inspect.signature(kb.StandardKB.check_validity).parameters)[:2] == ['self', 'code']


def test_kb_models_fields() -> None:
    """KBHit / ValidityInfo 字段与契约一致。"""
    kb = pytest.importorskip('src.kb.standards', reason='M06 模型未实现')
    assert {'doc_id', 'clause', 'snippet', 'score'} <= set(kb.KBHit.model_fields)
    assert {'code', 'status', 'effective_date', 'note'} <= set(kb.ValidityInfo.model_fields)
