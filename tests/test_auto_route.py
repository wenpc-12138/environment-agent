# -*- coding: utf-8 -*-
"""P8 M03 自动路由 + M07 技能执行链：意图路由 / 技能执行 / best_match 兜底 / 硬闸门。"""
from __future__ import annotations

import pytest

import v2_bridge
from src.core import config, db as core_db
from src.llm.intent import IntentRouter
from src.skills.executor import SkillExecutor


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'auto_route.db'))
    config.get_settings.cache_clear()
    core_db.run_migrations()
    v2_bridge._AUTO_ENGINE = None
    v2_bridge._LEARN = None
    yield


def _insert_skill(sid: str, status: str = 'active', name: str = '测试技能',
                  domain: str = 'D1', definition: str = '执行步骤一'):
    conn = core_db.get_conn()
    conn.execute(
        'INSERT INTO v2_skills(id,name,level,role,domain,version,status,definition,created_by) '
        'VALUES(?,?,?,?,?,?,?,?,?)',
        (sid, name, '1', '', domain, '1', status, definition, 'test'))
    conn.commit()


class TestIntentRouter:
    def test_auto_plan(self):
        r = IntentRouter().analyze('编制废水监测方案，具体步骤怎么做')
        assert r.domain == 'D1'
        assert r.mode == 'auto'
        assert r.confidence >= 0.85

    def test_interactive_ask(self):
        r = IntentRouter().analyze('什么是 COD')
        assert r.domain == 'D1'
        assert r.mode in ('interactive', 'auto')

    def test_manual_greeting(self):
        r = IntentRouter().analyze('你好')
        assert r.mode == 'manual'
        assert r.domain == ''

    def test_mode_hint_override(self):
        r = IntentRouter().analyze('随便一句话', {'mode_hint': 'manual'})
        assert r.mode == 'manual'


class TestAutoRouteExecute:
    def test_auto_tolerant(self, _db):
        # auto 模式容错：无论技能注册与否都不抛异常，返回结构完整
        r = v2_bridge.auto_route_execute('编制废水监测方案，具体步骤怎么做', 'auto')
        assert r['route']['mode'] == 'auto'
        assert 'route' in r and 'results' in r and 'executed' in r

    def test_active_skill_executes(self, _db):
        _insert_skill('ep-acceptance-report', status='active', name='验收报告',
                      domain='D1', definition='{"steps": [{"tool": "kb_retrieve", "args": {}}]}')
        r = v2_bridge.auto_route_execute('编制废水监测方案，具体步骤怎么做', 'auto')
        assert r['executed'] is True
        assert any(x['ok'] for x in r['results'])

    def test_pending_skill_gate(self, _db):
        _insert_skill('ep-acceptance-report', status='pending_review', name='验收报告',
                      domain='D1', definition='步骤')
        r = v2_bridge.auto_route_execute('编制废水监测方案，具体步骤怎么做', 'auto')
        # 硬闸门：D1 映射含 ep-acceptance-report（pending）-> 拒绝执行
        # （映射首位 water-monitoring 为真实 active 技能，仅断言待审技能被拒）
        ep = next((res for res in r['results']
                   if (res.get('outputs') or {}).get('skill_id') == 'ep-acceptance-report'), None)
        assert ep is not None and ep['ok'] is False
        assert '禁止执行' in (ep['outputs'].get('error') or '')

    def test_interactive_no_execute(self, _db):
        _insert_skill('ep-acceptance-report', status='active', name='验收报告',
                      domain='D1', definition='步骤')
        r = v2_bridge.auto_route_execute('编制废水监测方案，具体步骤怎么做', 'interactive')
        assert r['executed'] is False  # 非 auto 只路由不执行

    def test_best_match_fallback(self, _db):
        # 结晶 + R8 审批一个 active 技能；无领域命中（skill_ids 空）时 best_match 兜底填充
        v2_bridge.oercr_auto_learn('验收数据单位错误', task_id=92001,
                                   outcome='failed', feedback='验收单位错误须修正')
        v2_bridge._auto_engine().approve_pending('R8')
        # best_match 直接命中已激活技能
        s = v2_bridge._learn()._memory.best_match('单位错误', '')
        assert s is not None and s.status == 'active'
        # auto_route_execute 无领域命中时 skill_ids 由 best_match 兜底填充（manual 不执行）
        r = v2_bridge.auto_route_execute('这有一个单位错误', 'manual')
        assert r['route']['skill_ids'], 'best_match 应兜底填充技能'
        assert r['executed'] is False


class TestSkillExecutorDirect:
    def test_run_dag_orders(self, _db):
        _insert_skill('ep-a', status='active', name='A', domain='D1', definition='步骤A')
        _insert_skill('ep-b', status='active', name='B', domain='D1', definition='步骤B')
        rs = SkillExecutor().run_dag(['ep-a', 'ep-b'], {'domain': 'D1'})
        assert len(rs) == 2 and all(r.ok for r in rs)
        assert rs[1].outputs['skill_id'] == 'ep-b'
