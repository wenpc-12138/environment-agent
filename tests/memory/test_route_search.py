# -*- coding: utf-8 -*-
"""M6 检索意图路由：意图→检索源分发（操作型→kb / 提问→情景 / 个性化→画像+情景）。"""
from __future__ import annotations

import pytest

import v2_bridge
from src.core import config
from src.memory import profile


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'route.db'))
    config.get_settings.cache_clear()
    from src.core import db as core_db
    core_db.run_migrations()
    import db as root_db
    root_db.init_db()  # 根 db 表（kb_entries 等）
    yield


class TestRouteSearch:
    def test_plan_routes_kb(self, _db):
        r = v2_bridge.memory_route_search('废水监测方案怎么做', top_k=3)
        assert r['route']['intent'] == 'plan'
        assert r['sources'][0]['source'] == 'kb'
        assert r['plan'] == 'plan'

    def test_ask_routes_episodic(self, _db):
        v2_bridge.epi_add('客户A', '上次要求补充点位数据')
        r = v2_bridge.memory_route_search('上次客户要求了什么', top_k=3)
        assert r['route']['intent'] in ('ask', 'craft')
        assert any(s['source'] == 'episodic' for s in r['sources'])

    def test_personalized_profile_and_episodic(self, _db):
        profile.upsert('local', 'preference', '使用中文')
        v2_bridge.epi_add('客户A', '偏好中文报告')
        r = v2_bridge.memory_route_search('我记得用户偏好是什么', top_k=3)
        assert r['plan'] == 'personalized'
        sources = {s['source'] for s in r['sources']}
        assert 'profile' in sources and 'episodic' in sources

    def test_craft_routes_kb(self, _db):
        r = v2_bridge.memory_route_search('帮我写监测结论', top_k=3)
        assert r['sources'][0]['source'] == 'kb'

    def test_route_structure(self, _db):
        r = v2_bridge.memory_route_search('你好', top_k=3)
        assert 'route' in r and 'sources' in r and 'plan' in r
