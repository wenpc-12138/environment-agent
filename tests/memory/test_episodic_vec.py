# -*- coding: utf-8 -*-
"""M1 情景记忆语义检索：向量写入 / 余弦检索 / hybrid RRF 融合 / 兼容降级。"""
from __future__ import annotations

import struct

from src.core import config
from src.core.db import get_conn
from src.memory import episodic


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'epi_vec.db'))
    config.get_settings.cache_clear()
    from src.core import db as core_db
    core_db.run_migrations()  # 含 0002 向量表


def _embed_fixed(text: str):
    """构造确定性伪向量：按字符哈希归一化（512 维，位置无关），用于测试余弦排序。"""
    import hashlib
    dim = 512
    vec = [0.0] * dim
    for ch in text[:64]:
        h = int(hashlib.md5(ch.encode()).hexdigest()[:8], 16)
        vec[h % dim] += 1.0
    norm = (sum(v * v for v in vec) ** 0.5) or 1.0
    return [v / norm for v in vec]


class TestVectorWrite:
    def test_add_writes_vector(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        monkeypatch.setattr(episodic, '_embed', _embed_fixed)
        m = episodic.EpisodicMemory()
        eid = m.add('client-a', '提交了水质监测报告 v1')
        row = get_conn().execute(
            'SELECT embedding FROM memory_episode_vec WHERE episode_id=?', (int(eid),)).fetchone()
        assert row is not None
        assert len(row['embedding']) == 512 * 4  # float32 512 维

    def test_add_without_model_ok(self, tmp_path, monkeypatch):
        """向量不可用时主写入不受影响。"""
        _setup(tmp_path, monkeypatch)
        monkeypatch.setattr(episodic, '_embed', lambda t: None)
        m = episodic.EpisodicMemory()
        eid = m.add('x', '事件')
        assert int(eid) > 0


class TestVectorQuery:
    def test_vector_mode_ranks_similar(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        monkeypatch.setattr(episodic, '_embed', _embed_fixed)
        m = episodic.EpisodicMemory()
        m.add('a', '化学需氧量超标排放记录')
        m.add('b', '今天阳光明媚天气很好')
        hits = m.query('化学需氧量超标', mode='vector', top_k=5)
        assert hits, 'vector 检索应命中'
        assert hits[0].entity == 'a'  # 字符重合度高 → 余弦更大

    def test_hybrid_returns_ranked(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        monkeypatch.setattr(episodic, '_embed', _embed_fixed)
        m = episodic.EpisodicMemory()
        m.add('a', 'COD 超标排放记录')
        m.add('b', '大气数据补充')
        hits = m.query('COD 超标', top_k=5)
        assert hits and hits[0].entity == 'a'
        assert all(h.score > 0 for h in hits)

    def test_hybrid_filters(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        monkeypatch.setattr(episodic, '_embed', _embed_fixed)
        m = episodic.EpisodicMemory()
        m.add('a', 'COD 超标')
        m.add('b', 'COD 超标')
        hits = m.query('COD', filters={'entity': 'a'}, top_k=5)
        assert hits and all(h.entity == 'a' for h in hits)

    def test_vector_absent_falls_back_like(self, tmp_path, monkeypatch):
        """无向量（旧数据/模型失败）时 hybrid 自动降级 LIKE，不报错。"""
        _setup(tmp_path, monkeypatch)
        monkeypatch.setattr(episodic, '_embed', lambda t: None)
        m = episodic.EpisodicMemory()
        m.add('a', 'COD 超标排放记录')
        hits = m.query('COD', top_k=5)
        assert hits and hits[0].entity == 'a'


class TestCompat:
    def test_default_mode_backward_compatible(self, tmp_path, monkeypatch):
        """旧调用 query(q, filters, top_k) 不传 mode：仍返回结构化结果。"""
        _setup(tmp_path, monkeypatch)
        monkeypatch.setattr(episodic, '_embed', _embed_fixed)
        m = episodic.EpisodicMemory()
        m.add('client-a', '要求补充大气数据', ts='2026-08-01T10:00:00Z')
        hits = m.query('大气数据', filters={'entity': 'client-a'})
        assert hits
        assert hits[0].entity == 'client-a'
        assert hits[0].score > 0
        assert hits[0].ts

    def test_query_no_match_empty(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        monkeypatch.setattr(episodic, '_embed', _embed_fixed)
        m = episodic.EpisodicMemory()
        m.add('x', '无关事件')
        assert m.query('完全不存在词') == []
