# -*- coding: utf-8 -*-
"""M2/M4 事实记忆：add / 冲突消解 / 审核 / 查询 / 抽取。"""
from __future__ import annotations

import pytest

from src.core import config
from src.memory import facts


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'facts.db'))
    config.get_settings.cache_clear()
    from src.core import db as core_db
    core_db.run_migrations()
    yield


class TestAddApprove:
    def test_add_pending(self, _db):
        f = facts.add_fact('客户A', '行业', '污水处理', 'fact', 'test')
        assert f.status == 'pending'
        assert f.valid_from and f.valid_until is None

    def test_approve_supersedes_old(self, _db):
        f1 = facts.add_fact('客户A', '偏好', '蓝色', 'preference', 'test', approved=True)
        assert f1.status == 'active'
        # 同 key 新事实审批激活 → 旧事实自动失效（M4 冲突消解）
        f2 = facts.add_fact('客户A', '偏好', '绿色', 'preference', 'test')
        assert f2.status == 'pending'
        facts.approve_fact(f2.id, 'R8')
        old = facts._get_fact(f1.id)
        assert old.status == 'active'
        assert old.valid_until is not None  # 已被置失效

    def test_query_active_only(self, _db):
        facts.add_fact('客户A', '偏好', '蓝色', 'preference', 'test', approved=True)
        facts.add_fact('客户A', '约束', '需提供原始记录', 'constraint', 'test')  # pending 不生效
        active = facts.query_facts(entity='客户A')
        assert all(f.status == 'active' for f in active)
        assert len(active) == 1

    def test_reject(self, _db):
        f = facts.add_fact('x', 'y', 'z')
        facts.reject_fact(f.id)
        assert facts._get_fact(f.id).status == 'rejected'

    def test_add_invalid_ftype(self, _db):
        f = facts.add_fact('x', 'y', 'z', 'bogus')
        assert f.ftype == 'fact'


class TestExtract:
    def test_rule_extract_preference(self, _db):
        out = facts.extract_facts('用户偏好使用中文界面', caller=None, source='test')
        assert any(f.ftype == 'preference' for f in out)
        assert all(f.status == 'pending' for f in out)

    def test_rule_extract_constraint(self, _db):
        out = facts.extract_facts('要求提供监测原始记录')
        assert any(f.ftype == 'constraint' for f in out)

    def test_rule_extract_standard(self, _db):
        out = facts.extract_facts('执行标准：GB 3838-2002')
        assert any(f.attr == 'GB 3838-2002' for f in out)

    def test_rule_extract_empty(self, _db):
        assert facts.extract_facts('') == []
        assert facts.extract_facts('今天天气不错') == []

    def test_llm_extract(self, _db):
        def caller(messages):
            return ('[{"entity":"客户A","attr":"行业","value":"污水处理","ftype":"fact"},'
                    '{"entity":"客户A","attr":"偏好","value":"蓝色","ftype":"preference"}]')
        out = facts.extract_facts('客户A 是污水处理行业，偏好蓝色', caller=caller, source='test')
        assert len(out) == 2
        assert all(f.status == 'pending' for f in out)
        assert {f.attr for f in out} == {'行业', '偏好'}

    def test_llm_garbage_falls_back_rule(self, _db):
        def caller(messages):
            return 'not json'
        out = facts.extract_facts('用户要求提供数据', caller=caller)
        assert any(f.ftype == 'constraint' for f in out)


class TestBridge:
    def test_v2_facts_flow(self, _db):
        import v2_bridge
        v2_bridge.facts_add('客户A', '行业', '电镀', 'fact', 'test')
        p = v2_bridge.facts_pending()
        assert p['count'] == 1
        fid = p['facts'][0]['id']
        r = v2_bridge.facts_approve(fid)
        assert r['fact']['status'] == 'active'
        q = v2_bridge.facts_query(entity='客户A')
        assert q['count'] == 1
