# -*- coding: utf-8 -*-
"""G2 动态子代理：规格/系统提示/角色权限/工具循环/异步 spawn/并行。"""
from __future__ import annotations

import json
import time

import pytest

from src.agents.subagent import (SubAgentRunner, SubAgentSpec, build_system_prompt,
                                 run_agent_task)


@pytest.fixture()
def _stub_tools(monkeypatch):
    """stub v1.2 工具执行（patch 加载器出口）：不依赖真实知识库数据。"""
    from src.tools import _v12
    monkeypatch.setattr(_v12, 'execute_tool',
                        lambda name, args: (True, f'stub:{name}'))


def _caller_script(script):
    """按脚本顺序返回决策 JSON 的 caller。"""
    it = iter(script)

    def caller(messages):
        return next(it)

    return caller


class TestSpec:
    def test_default_tools_by_role(self):
        spec = SubAgentSpec(role_id='R4')
        assert 'kb_lookup' in spec.allowed_tools()
        assert 'calc_formula' in spec.allowed_tools()
        # R5 无 kb_save 权限
        spec5 = SubAgentSpec(role_id='R5')
        assert 'kb_save' not in spec5.allowed_tools()

    def test_custom_tools_override(self):
        spec = SubAgentSpec(role_id='R4', tools=['kb_lookup'])
        assert spec.allowed_tools() == {'kb_lookup'}

    def test_system_prompt(self):
        p = build_system_prompt(SubAgentSpec(name='检索员', role_id='R2'), '查限值')
        assert '检索员' in p and 'R2' in p
        assert '"action":"tool"' in p and '"action":"final"' in p
        assert '查限值' in p


class TestRunAgentTask:
    def test_tool_loop_and_final(self, _stub_tools):
        script = [
            json.dumps({'action': 'tool', 'name': 'kb_lookup', 'params': {'query': 'GB 3838'}}),
            json.dumps({'action': 'final', 'text': '查得 GB 3838-2002 Ⅲ类限值 20 mg/L'}),
        ]
        out = run_agent_task(SubAgentSpec(role_id='R2'), '查标准限值',
                             caller=_caller_script(script))
        assert out['ok'] and out['tool_calls'] == 1
        assert 'GB 3838-2002' in out['result']
        assert out['steps'][0]['output'].startswith('stub:')

    def test_tool_permission_denied(self):
        """R1 不允许 calc_formula -> 拒绝并最终降级。"""
        script = [
            json.dumps({'action': 'tool', 'name': 'calc_formula', 'params': {}}),
            json.dumps({'action': 'final', 'text': '工具被拒'}),
        ]
        out = run_agent_task(SubAgentSpec(role_id='R1'), '算指数',
                             caller=_caller_script(script))
        # calc_formula 不在 R1 白名单
        assert any(s.get('error') and '权限' in s['error'] for s in out['steps'])
        assert out['tool_calls'] == 0

    def test_max_steps_limit(self, _stub_tools):
        script = [json.dumps({'action': 'tool', 'name': 'kb_lookup', 'params': {}})] * 10
        out = run_agent_task(SubAgentSpec(role_id='R2', max_steps=2), 't',
                             caller=_caller_script(script))
        assert len(out['steps']) <= 2
        assert out['result']  # 未产出 final -> 兜底文案

    def test_caller_none_degrades(self):
        out = run_agent_task(SubAgentSpec(role_id='R4'), 't')
        assert out['ok'] and out['tool_calls'] == 0

    def test_bad_decision_treated_as_final(self):
        out = run_agent_task(SubAgentSpec(role_id='R2'), 't',
                             caller=_caller_script(['这不是JSON'])
                             )
        assert out['result'] == '这不是JSON'

    def test_loose_tool_protocol(self, _stub_tools):
        out = run_agent_task(SubAgentSpec(role_id='R2'), 't',
                             caller=_caller_script(['[tool:kb_lookup] {"query":"x"}']))
        assert out['tool_calls'] == 1


class TestRunner:
    def test_spawn_collect(self, _stub_tools):
        runner = SubAgentRunner()
        sub_id = runner.spawn(SubAgentSpec(role_id='R4'), '写结论',
                              caller=_caller_script(
                                  [json.dumps({'action': 'final', 'text': '完成'})]))
        r = runner.collect(sub_id, timeout=5)
        assert r['status'] == 'done'
        assert r['result']['result'] == '完成'

    def test_collect_missing(self):
        assert SubAgentRunner().collect('nope') is None

    def test_list(self, _stub_tools):
        runner = SubAgentRunner()
        sub_id = runner.spawn(SubAgentSpec(role_id='R4'), 't',
                              caller=_caller_script(
                                  [json.dumps({'action': 'final', 'text': 'x'})]))
        ids = [j['id'] for j in runner.list()]
        assert sub_id in ids

    def test_run_parallel(self, _stub_tools):
        runner = SubAgentRunner()
        results = runner.run_parallel(
            [SubAgentSpec(name='a', role_id='R4'), SubAgentSpec(name='b', role_id='R4')],
            ['任务A', '任务B'],
            caller=_caller_script([json.dumps({'action': 'final', 'text': 'ok'})]),
            timeout=5)
        assert len(results) == 2
        assert all(r['status'] == 'done' for r in results)


class TestEpisodicPersist:
    def test_result_written_to_episodic(self, tmp_path, monkeypatch, _stub_tools):
        monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'sub.db'))
        from src.core import config, db as core_db
        config.get_settings.cache_clear()
        core_db.run_migrations()
        runner = SubAgentRunner()
        sub_id = runner.spawn(SubAgentSpec(name='研究员', role_id='R2'), '查标准',
                              caller=_caller_script(
                                  [json.dumps({'action': 'final', 'text': 'GB 3838-2002'})]))
        runner.collect(sub_id, timeout=5)
        time.sleep(0.1)
        rows = core_db.get_conn().execute(
            "SELECT entity FROM memory_episodes WHERE entity LIKE 'sub:%'").fetchall()
        assert any('研究员' in r['entity'] for r in rows)
