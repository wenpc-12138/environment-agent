# -*- coding: utf-8 -*-
"""M05 三层记忆契约测试（contracts.md §3.M05）。

src/memory/ 未实现时自动 skip；实现后自动激活并校验公开签名。
"""
from __future__ import annotations

import inspect

import pytest


def test_memory_manager_layers() -> None:
    """MemoryManager 暴露 working / episodic / procedural 三实例。"""
    memory = pytest.importorskip('src.memory', reason='M05 MemoryManager 未实现')
    if not hasattr(memory, 'MemoryManager'):
        pytest.skip('M05 MemoryManager 未实现（src/memory 为骨架占位）')
    assert hasattr(memory.MemoryManager, 'working')
    assert hasattr(memory.MemoryManager, 'episodic')
    assert hasattr(memory.MemoryManager, 'procedural')


def test_episodic_signatures() -> None:
    """EpisodicMemory.add / query / summarize 签名。"""
    epi = pytest.importorskip('src.memory.episodic', reason='M05 EpisodicMemory 未实现')
    add = inspect.signature(epi.EpisodicMemory.add)
    assert list(add.parameters)[:4] == ['self', 'entity', 'event', 'payload']
    assert 'ts' in add.parameters
    query = inspect.signature(epi.EpisodicMemory.query)
    assert list(query.parameters)[:2] == ['self', 'q']
    assert 'top_k' in query.parameters and query.parameters['top_k'].default == 10
    summ = inspect.signature(epi.EpisodicMemory.summarize)
    assert list(summ.parameters)[:3] == ['self', 'entity', 'since']
    assert {'entity', 'snippet', 'score', 'ts'} <= set(epi.MemoryHit.model_fields)


def test_procedural_signatures() -> None:
    """ProceduralMemory.create_skill / update_skill / best_match / mark_deprecated。"""
    proc = pytest.importorskip('src.memory.procedural', reason='M05 ProceduralMemory 未实现')
    create = inspect.signature(proc.ProceduralMemory.create_skill)
    assert list(create.parameters)[:2] == ['self', 'defn']
    update = inspect.signature(proc.ProceduralMemory.update_skill)
    assert list(update.parameters)[:4] == ['self', 'id', 'new_def', 'reviewer']
    match = inspect.signature(proc.ProceduralMemory.best_match)
    assert list(match.parameters)[:2] == ['self', 'task']
    assert 'domain' in match.parameters
    dep = inspect.signature(proc.ProceduralMemory.mark_deprecated)
    assert list(dep.parameters)[:2] == ['self', 'standard_code']


def test_review_flow_signatures() -> None:
    """第 8 波 R8 审核联动：approve_skill / reject_skill / list_skills 签名。"""
    proc = pytest.importorskip('src.memory.procedural', reason='M05 ProceduralMemory 未实现')
    approve = inspect.signature(proc.ProceduralMemory.approve_skill)
    assert list(approve.parameters)[:3] == ['self', 'id', 'reviewer']
    reject = inspect.signature(proc.ProceduralMemory.reject_skill)
    assert list(reject.parameters)[:3] == ['self', 'id', 'reviewer']
    listing = inspect.signature(proc.ProceduralMemory.list_skills)
    assert list(listing.parameters)[:2] == ['self', 'status']
    assert listing.parameters['status'].default is None


def test_working_signatures() -> None:
    """WorkingMemory.set(key, value, ttl=3600) / get(key)。"""
    wm = pytest.importorskip('src.memory.working', reason='M05 WorkingMemory 未实现')
    set_sig = inspect.signature(wm.WorkingMemory.set)
    names = list(set_sig.parameters)
    assert names[:3] == ['self', 'key', 'value']
    assert set_sig.parameters['ttl'].default == 3600
    get_sig = inspect.signature(wm.WorkingMemory.get)
    assert list(get_sig.parameters)[:2] == ['self', 'key']
