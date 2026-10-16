# -*- coding: utf-8 -*-
"""StandardKB 行为测试：ingest/search/get_standard/check_validity（临时库）。"""
from __future__ import annotations

from pathlib import Path

from src.core import config
from src.kb.standards import StandardKB


def _setup_db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'kb.db'))
    config.get_settings.cache_clear()
    from src.core import db as core_db
    core_db.run_migrations()


def test_ingest_and_search(tmp_path, monkeypatch) -> None:
    _setup_db(tmp_path, monkeypatch)
    try:
        kb = StandardKB()
        f = tmp_path / 'hj166.md'
        f.write_text('HJ 166-2026 土壤环境监测技术规范\n第一段正文内容……', encoding='utf-8')
        eid = kb.ingest(str(f), kind='HJ')
        assert eid > 0
        hits = kb.search('土壤环境监测')
        assert hits, '应命中导入条目'
        assert hits[0].doc_id == str(eid)
        assert hits[0].score > 0
        # 按标准号检索权重最高
        code_hits = kb.search('HJ 166-2026')
        assert code_hits and code_hits[0].score >= hits[0].score
    finally:
        config.get_settings.cache_clear()


def test_search_filters(tmp_path, monkeypatch) -> None:
    _setup_db(tmp_path, monkeypatch)
    try:
        kb = StandardKB()
        f = tmp_path / 'gb.txt'
        f.write_text('GB 3838-2002 地表水环境质量标准\n正文', encoding='utf-8')
        kb.ingest(str(f), kind='GB')
        hits = kb.search('地表水', filters={'category': 'gb'})
        assert hits, 'category 过滤后应命中'
        miss = kb.search('地表水', filters={'category': 'hj'})
        assert miss == []
    finally:
        config.get_settings.cache_clear()


def test_get_standard(tmp_path, monkeypatch) -> None:
    _setup_db(tmp_path, monkeypatch)
    try:
        kb = StandardKB()
        f = tmp_path / 'hj166.md'
        f.write_text('HJ 166-2026 土壤环境监测技术规范\n正文内容', encoding='utf-8')
        kb.ingest(str(f), kind='HJ')
        doc = kb.get_standard('HJ 166-2026')
        assert doc is not None
        assert doc.code == 'HJ166-2026'
        assert '正文' in doc.content
        assert kb.get_standard('HJ 9999-2099') is None
    finally:
        config.get_settings.cache_clear()


def test_check_validity(tmp_path, monkeypatch) -> None:
    _setup_db(tmp_path, monkeypatch)
    try:
        kb = StandardKB()
        f = tmp_path / 'hj166.md'
        f.write_text('HJ 166-2026 土壤环境监测技术规范\n正文', encoding='utf-8')
        kb.ingest(str(f), kind='HJ')
        vi = kb.check_validity('HJ 166-2026')
        assert vi.code == 'HJ 166-2026'
        assert vi.status in ('未知', '现行有效')
        # 未收录
        vi2 = kb.check_validity('XX 9999-2099')
        assert vi2.status == '未知'
        assert '未收录' in vi2.note
    finally:
        config.get_settings.cache_clear()
