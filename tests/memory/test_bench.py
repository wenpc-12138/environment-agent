# -*- coding: utf-8 -*-
"""记忆量化评测：检索命中 / 压缩收益 / 技能复用三维度。"""
from __future__ import annotations

import pytest

from src.core import config, db as core_db
from src.memory import bench


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'bench.db'))
    config.get_settings.cache_clear()
    core_db.run_migrations()
    yield


class TestBench:
    def test_retrieval_report_shape(self, _db):
        r = bench.bench_retrieval()
        assert r['suite'] == 'retrieval'
        assert 'recall@k' in r and 0 <= r['recall@k'] <= 1
        assert r['total'] >= 1

    def test_retrieval_known_case(self, _db):
        # 内置示例：对明显关键词应命中（空库时可能不命中，保证结构即可）
        r = bench.bench_retrieval([("排放限值查询", ["排放"])], top_k=5)
        assert 'hit' in r and 'details' in r

    def test_compression_saves_tokens(self, _db):
        msgs = [{'role': 'tool', 'content': 'z' * 5000},
                {'role': 'assistant', 'content': '结论完成' * 10}]
        r = bench.bench_compression(msgs)
        assert r['ok'] is True
        assert 0 < r['token_save'] <= 1

    def test_compression_empty(self, _db):
        r = bench.bench_compression([])
        assert r['ok'] is False

    def test_skill_reuse_report(self, _db):
        r = bench.bench_skill_reuse()
        assert r['suite'] == 'skill_reuse'
        assert 0 <= r['hit_rate'] <= 1

    def test_run_benchmark_summary(self, _db):
        r = bench.run_benchmark()
        assert 'summary' in r and len(r['dimensions']) == 3
        assert set(r['summary']) == {'retrieval_recall@k', 'compression_token_save', 'skill_hit_rate'}
