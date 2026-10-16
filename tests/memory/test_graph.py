# -*- coding: utf-8 -*-
"""G5 记忆知识图谱：关系写入/幂等/实体抽取/事实建图/图谱展开/决策痕迹/邻居。"""
from __future__ import annotations

import pytest

from src.core import config, db as core_db
from src.memory import facts, graph


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'graph.db'))
    config.get_settings.cache_clear()
    core_db.run_migrations()
    yield


class TestRelations:
    def test_add_and_get(self, _db):
        graph.add_relation('武汉', '位于', '长江中游', source='test')
        r = graph.add_relation('武汉', '水质类别', 'Ⅲ类', source='test')
        assert r['weight'] == 1 and r['entity_b'] == 'Ⅲ类'
        out = graph.query('武汉')
        assert any(x['rel'] == '位于' for x in out['relations'])

    def test_idempotent_weight_accumulate(self, _db):
        graph.add_relation('A', '关联', 'B')
        graph.add_relation('A', '关联', 'B')
        r = graph.add_relation('A', '关联', 'B')
        assert r['weight'] == 3  # 重复出现累加

    def test_add_requires_entities(self, _db):
        with pytest.raises(ValueError):
            graph.add_relation('', 'r', 'B')

    def test_decision_trace(self, _db):
        r = graph.trace_decision('排污许可证', '2026-08-08 批准换发，有效期 3 年', source='r8')
        assert r['rel'] == 'decision_trace'
        out = graph.query('排污许可证')
        assert len(out['decision_traces']) >= 1

    def test_extract_entities(self, _db):
        es = graph.extract_entities(
            '武汉市XX污水处理厂执行 GB 18918-2002，COD 与氨氮需达标排放')
        joined = '|'.join(es)
        assert 'GB 18918-2002' in joined
        assert any('武汉' in e for e in es)
        assert any('COD' in e for e in es)

    def test_link_from_facts(self, _db):
        facts.add_fact('项目A', '委托方', '市环境监测站', approved=True)
        facts.add_fact('项目A', '截止日期', '2026-09-01', approved=True)
        n = graph.link_from_facts()
        assert n == 2
        out = graph.query('项目A')
        assert len(out['facts']) == 2
        assert any(x['rel'] == '委托方' for x in out['relations'])


class TestQueryExpand:
    def test_query_unknown_entity(self, _db):
        out = graph.query('')
        assert out['entity'] == '' and out['relations'] == []
        out = graph.query('不存在实体XYZ')
        assert out['relations'] == [] and out['facts'] == []

    def test_query_profile_and_skills(self, _db):
        graph.add_relation('用户', '偏好', '使用电子记录', source='profile')
        try:
            core_db.get_conn().execute(
                'INSERT INTO memory_profile(user_key,attr,value,weight,updated_at)'
                ' VALUES(?,?,?,?,datetime(\'now\',\'localtime\'))',
                ('local', '报告格式', '用户要求简洁版', 3))
            core_db.get_conn().commit()
        except Exception:
            pass
        out = graph.query('用户')
        assert any(x['rel'] == '偏好' for x in out['relations'])
        # profile 匹配 value（value 含实体"用户"）
        assert any('简洁版' in (p.get('value') or '') for p in out['profile'])


class TestNeighbors:
    def test_bfs_depth1(self, _db):
        graph.add_relation('A', 'r1', 'B')
        graph.add_relation('B', 'r2', 'C')
        n = graph.neighbors('A', depth=1)
        assert any(x['id'] == 'B' for x in n['nodes'])
        assert len(n['edges']) >= 1

    def test_bfs_depth2(self, _db):
        graph.add_relation('A', 'r1', 'B')
        graph.add_relation('B', 'r2', 'C')
        n = graph.neighbors('A', depth=2)
        ids = [x['id'] for x in n['nodes']]
        assert 'B' in ids and 'C' in ids
