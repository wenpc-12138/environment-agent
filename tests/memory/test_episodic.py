# -*- coding: utf-8 -*-
"""EpisodicMemory 行为测试：add/query/summarize（临时库隔离）。"""
from __future__ import annotations

from src.core import config
from src.core.db import get_conn
from src.memory.episodic import EpisodicMemory


def test_add_and_query(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'ep.db'))
    config.get_settings.cache_clear()
    try:
        # 0001 迁移建 memory_episodes 表
        from src.core import db as core_db
        core_db.run_migrations()
        epi = EpisodicMemory()
        eid = epi.add('client-a', '提交了水质监测报告 v1')
        assert eid is not None and int(eid) > 0
        epi.add('client-a', '要求补充大气数据', ts='2026-08-01T10:00:00Z')
        hits = epi.query('大气数据', filters={'entity': 'client-a'})
        assert hits, '应命中事件'
        assert hits[0].entity == 'client-a'
        assert hits[0].score > 0
        assert hits[0].ts
    finally:
        config.get_settings.cache_clear()


def test_query_no_match_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'ep2.db'))
    config.get_settings.cache_clear()
    try:
        from src.core import db as core_db
        core_db.run_migrations()
        epi = EpisodicMemory()
        epi.add('x', '无关事件')
        assert epi.query('完全不存在词') == []
    finally:
        config.get_settings.cache_clear()


def test_summarize_rule_based(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'ep3.db'))
    config.get_settings.cache_clear()
    try:
        from src.core import db as core_db
        core_db.run_migrations()
        epi = EpisodicMemory()
        epi.add('client-b', '完成采样')
        epi.add('client-b', '完成采样')
        epi.add('client-b', '开始编制报告')
        s = epi.summarize('client-b')
        assert 'client-b' in s
        assert '采样' in s
        assert '报告' in s
    finally:
        config.get_settings.cache_clear()


def test_summarize_with_llm_inject(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'ep4.db'))
    config.get_settings.cache_clear()
    try:
        from src.core import db as core_db
        core_db.run_migrations()
        calls: list[str] = []

        def fake_sum(raw: str) -> str:
            calls.append(raw)
            return 'LLM摘要'

        epi = EpisodicMemory(summarizer=fake_sum)
        epi.add('c', '事件一')
        assert epi.summarize('c') == 'LLM摘要'
        assert len(calls) == 1
    finally:
        config.get_settings.cache_clear()
