# -*- coding: utf-8 -*-
"""M13/M15 学习与自主进化契约测试（contracts.md §3.M13/M15）。

src/learn/ 未实现时自动 skip；实现后自动激活。
"""
from __future__ import annotations

import inspect

import pytest


def test_learner_signatures() -> None:
    """Learner.learn_from_review / extract_pattern。"""
    learner = pytest.importorskip('src.learn.learner', reason='M13 Learner 未实现')
    learn = inspect.signature(learner.Learner.learn_from_review)
    assert list(learn.parameters)[:2] == ['self', 'reviews']
    pat = inspect.signature(learner.Learner.extract_pattern)
    assert list(pat.parameters)[:2] == ['self', 'samples']


def test_pattern_fields() -> None:
    """Pattern 字段与契约一致。"""
    learner = pytest.importorskip('src.learn.learner', reason='M13 Pattern 未实现')
    assert {'domain', 'rule', 'confidence'} <= set(learner.Pattern.model_fields)


def test_module_pipeline_signature() -> None:
    """ModulePipeline.run(conversation, uploaded) 模块生成流水线入口（M15，contracts.md §3.M15）。"""
    pipeline = pytest.importorskip('src.learn.module_pipeline', reason='M15 ModulePipeline 未实现')
    sig = inspect.signature(pipeline.ModulePipeline.run)
    assert list(sig.parameters)[:3] == ['self', 'conversation', 'uploaded']
    search = inspect.signature(pipeline.ModulePipeline.search_regulations)
    assert list(search.parameters)[:2] == ['self', 'domain']
    ingest = inspect.signature(pipeline.ModulePipeline.ingest_materials)
    assert list(ingest.parameters)[:2] == ['self', 'paths']


def test_oercr_engine_signature() -> None:
    """OercrEngine observe/reflect/crystallize/reuse 四阶段（M13，contracts.md §3.M13）。"""
    engine = pytest.importorskip('src.learn.engine', reason='M13 OercrEngine 未实现')
    observe = inspect.signature(engine.OercrEngine.observe)
    assert list(observe.parameters)[:2] == ['self', 'task_log']
    reflect = inspect.signature(engine.OercrEngine.reflect)
    assert list(reflect.parameters)[:2] == ['self', 'obs']
    cryst = inspect.signature(engine.OercrEngine.crystallize)
    assert list(cryst.parameters)[:2] == ['self', 'reflections']
    reuse = inspect.signature(engine.OercrEngine.reuse)
    assert list(reuse.parameters)[:2] == ['self', 'task']
