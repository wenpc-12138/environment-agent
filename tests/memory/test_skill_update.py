# -*- coding: utf-8 -*-
"""H1 技能迭代提案：同 gap 已存在技能 → 提案 → R8 审批版本递增。"""
from __future__ import annotations

import pytest

from src.core import config, db as core_db
from src.learn.engine import OercrEngine
from src.memory.procedural import ProceduralMemory
from src.models.core import SkillDef


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'skill_update.db'))
    config.get_settings.cache_clear()
    core_db.run_migrations()
    yield


def _make_skill(sid: str = 'sk-oer-901', version: str = '1.0.0',
                status: str = 'active', definition: str = 'gap: 数据单位错误'):
    return SkillDef(id=sid, name='迭代测试', level=2, role='R8', domain='D1',
                    version=version, status=status, definition=definition,
                    created_by='agent_oercr')


class TestProposeUpdate:
    def test_crystallize_proposes_not_duplicates(self, _db):
        """同 gap 已有 active 技能：不重复结晶，生成迭代提案。"""
        mem = ProceduralMemory()
        mem.create_skill(_make_skill())
        eng = OercrEngine()
        # 用与已存在技能同 gap 的反思触发
        from src.models.core import Reflection
        ref = Reflection(ref_id='r1', obs_id='o1', domain='D1', gap='数据单位错误',
                         pattern_hint='D1 -> 数据单位错误', severity='P1', confidence=0.8)
        produced = eng.crystallize([ref])
        assert produced == []  # 未重复结晶
        props = eng.pending_updates()
        assert len(props) == 1
        assert props[0]['skill_id'] == 'sk-oer-901'

    def test_new_gap_crystallizes(self, _db):
        """无同 gap 技能：正常结晶（pending_review）。"""
        eng = OercrEngine()
        from src.models.core import Reflection
        ref = Reflection(ref_id='r2', obs_id='o2', domain='D1', gap='全新问题',
                         pattern_hint='D1 -> 全新问题', severity='P2', confidence=0.9)
        produced = eng.crystallize([ref])
        assert len(produced) == 1
        assert produced[0].status == 'pending_review'

    def test_dedup_same_session(self, _db):
        """会话内同 gap 不重复提案。"""
        mem = ProceduralMemory()
        mem.create_skill(_make_skill())
        eng = OercrEngine()
        from src.models.core import Reflection
        ref = Reflection(ref_id='r3', obs_id='o3', domain='D1', gap='数据单位错误',
                         pattern_hint='D1 -> 数据单位错误', severity='P1', confidence=0.8)
        eng.crystallize([ref])
        eng.crystallize([ref])  # 同会话重复
        assert len(eng.pending_updates()) == 1


class TestApproveUpdate:
    def test_approve_bumps_version(self, _db):
        mem = ProceduralMemory()
        mem.create_skill(_make_skill())
        eng = OercrEngine()
        from src.models.core import Reflection
        ref = Reflection(ref_id='r4', obs_id='o4', domain='D1', gap='数据单位错误',
                         pattern_hint='D1 -> 数据单位错误', severity='P1', confidence=0.8)
        eng.crystallize([ref])
        pid = eng.pending_updates()[0]['id']
        assert eng.approve_update(pid, 'R8') is True
        updated = mem.get_skill('sk-oer-901')
        assert updated.version == '1.0.1'  # 版本递增
        assert 'iteration: updated' in updated.definition
        assert eng.pending_updates() == []  # 提案已消费

    def test_reject(self, _db):
        mem = ProceduralMemory()
        mem.create_skill(_make_skill())
        eng = OercrEngine()
        from src.models.core import Reflection
        ref = Reflection(ref_id='r5', obs_id='o5', domain='D1', gap='数据单位错误',
                         pattern_hint='D1 -> 数据单位错误', severity='P1', confidence=0.8)
        eng.crystallize([ref])
        pid = eng.pending_updates()[0]['id']
        assert eng.reject_update(pid, 'R8') is True
        assert eng.pending_updates() == []
        assert mem.get_skill('sk-oer-901').version == '1.0.0'  # 未变

    def test_approve_non_r8_rejected(self, _db):
        mem = ProceduralMemory()
        mem.create_skill(_make_skill())
        eng = OercrEngine()
        from src.models.core import Reflection
        ref = Reflection(ref_id='r6', obs_id='o6', domain='D1', gap='数据单位错误',
                         pattern_hint='D1 -> 数据单位错误', severity='P1', confidence=0.8)
        eng.crystallize([ref])
        pid = eng.pending_updates()[0]['id']
        assert eng.approve_update(pid, 'agent') is False


class TestBridge:
    def test_auto_learn_returns_proposals(self, _db):
        ProceduralMemory().create_skill(_make_skill())
        import v2_bridge
        r = v2_bridge.oercr_auto_learn('数据单位错误', task_id=94001,
                                       outcome='failed', feedback='单位错误须修正')
        assert r.get('proposals') == 1
        p = v2_bridge.skills_update_pending()
        assert p['count'] == 1
        assert v2_bridge.skills_update_approve(p['proposals'][0]['id'])['ok'] is True

    def test_review_center_lists_skill_update(self, _db, monkeypatch):
        ProceduralMemory().create_skill(_make_skill())
        import v2_bridge
        monkeypatch.setattr(v2_bridge, '_AUTO_ENGINE', None)  # 强制重建，消除顺序耦合
        v2_bridge.oercr_auto_learn('数据单位错误', task_id=94002,
                                   outcome='failed', feedback='单位错误须修正')
        lst = v2_bridge.pending_review_list()
        assert any(i['type'] == 'skill_update' for i in lst['items'])
