# -*- coding: utf-8 -*-
"""M3 用户画像层：upsert / distill / 注入文本 / 删除。"""
from __future__ import annotations

import pytest

from src.core import config
from src.memory import profile


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'profile.db'))
    config.get_settings.cache_clear()
    from src.core import db as core_db
    core_db.run_migrations()
    yield


class TestUpsert:
    def test_upsert_accumulates(self, _db):
        p1 = profile.upsert('local', 'preference', '使用中文')
        p2 = profile.upsert('local', 'preference', '使用中文')
        assert p1.weight == 1 and p2.weight == 2
        assert len(profile.get_profile('local')) == 1

    def test_upsert_distinct_values(self, _db):
        profile.upsert('local', 'preference', 'A')
        profile.upsert('local', 'preference', 'B')
        assert len(profile.get_profile('local')) == 2

    def test_user_isolated(self, _db):
        profile.upsert('u1', 'preference', 'X')
        assert profile.get_profile('u2') == []


class TestDistill:
    def test_distill_from_active_facts(self, _db):
        from src.memory import facts
        facts.add_fact('用户', 'preference', '使用中文', 'preference', 'test', approved=True)
        facts.add_fact('用户', 'constraint', '需提供原始记录', 'constraint', 'test', approved=True)
        facts.add_fact('用户', 'fact', '行业是电镀', 'fact', 'test', approved=True)  # 不蒸馏
        r = profile.distill('local')
        assert r['distilled'] == 2  # 仅偏好/约束
        assert r['total'] == 2
        items = {p.attr for p in profile.get_profile('local')}
        assert items == {'preference', 'constraint'}

    def test_distill_ignores_pending(self, _db):
        from src.memory import facts
        facts.add_fact('用户', 'preference', 'X', 'preference', 'test')  # pending 不蒸馏
        r = profile.distill('local')
        assert r['distilled'] == 0


class TestRender:
    def test_render_empty(self, _db):
        assert profile.render_profile() == ''

    def test_render_has_text(self, _db):
        profile.upsert('local', 'preference', '使用中文')
        text = profile.render_profile()
        assert '[用户画像]' in text and '偏好' in text and '使用中文' in text


class TestRemove:
    def test_remove_by_attr(self, _db):
        profile.upsert('local', 'preference', 'A')
        profile.upsert('local', 'constraint', 'B')
        profile.remove('local', attr='preference')
        assert len(profile.get_profile('local')) == 1

    def test_remove_all(self, _db):
        profile.upsert('local', 'preference', 'A')
        profile.remove('local')
        assert profile.get_profile('local') == []


class TestBridge:
    def test_v2_profile_flow(self, _db):
        import v2_bridge
        v2_bridge.profile_upsert('local', 'preference', '中文')
        v2_bridge.profile_upsert('local', 'preference', '中文')
        g = v2_bridge.profile_get('local')
        assert g['count'] == 1 and g['profile'][0]['weight'] == 2
        assert '用户画像' in v2_bridge.profile_render('local')
