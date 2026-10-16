# -*- coding: utf-8 -*-
"""G1 显式规划器：plan 拆解 / execute 顺序执行 / $prev 注入 / 失败中断。"""
from __future__ import annotations

import pytest

from src.llm.planner import PlanAgent
from src.models.core import PlanStep


class TestPlan:
    def test_plan_generates_steps(self):
        steps = PlanAgent().plan('生成一份噪声监测报告并计算超标情况')
        assert len(steps) >= 3
        assert steps[0].action == 'tool' and steps[0].target == 'kb_lookup'
        # 含计算步骤（文本含"计算/超标"）
        assert any(s.target == 'calc_formula' for s in steps)
        # 最后一步是 llm 汇总
        assert steps[-1].action == 'llm'

    def test_plan_report_uses_skill(self):
        steps = PlanAgent().plan('编制环评报告', 'D6')
        assert any(s.action == 'skill' for s in steps)

    def test_plan_qa_adds_check(self):
        steps = PlanAgent().plan('审核监测报告合规性', 'D6')
        assert any('审核' in s.goal or '核对' in s.goal for s in steps)

    def test_plan_llm_caller(self):
        def caller(prompt):
            return '[{"goal":"查标准","action":"tool","target":"kb_lookup","params":{"query":"GB 3838"},"outputs_name":"kb","note":""}]'
        steps = PlanAgent(planner_caller=caller).plan('xx')
        assert len(steps) == 1 and steps[0].target == 'kb_lookup'

    def test_plan_llm_caller_bad_json_fallback(self):
        def caller(prompt):
            return 'not json'
        steps = PlanAgent(planner_caller=caller).plan('计算超标倍数')
        assert len(steps) >= 3  # 降级规则

    def test_plan_empty(self):
        assert PlanAgent().plan('') != []  # 规则模板仍产出检索步


class TestExecutePlan:
    def _steps(self):
        return [
            PlanStep(seq=1, goal='检索', action='tool', target='kb_lookup',
                     params={'query': 'GB 3838', 'top_n': 3}, outputs_name='kb'),
            PlanStep(seq=2, goal='汇总', action='llm', target='summarize',
                     params={'$prev': 'all'}, outputs_name='summary'),
        ]

    def test_execute_success(self, monkeypatch):
        class FakeRegistry:
            def execute(self, name, params):
                return type('R', (), {'ok': True, 'data': {'hit': name}})()
        out = PlanAgent().execute_plan(self._steps(), '任务',
                                       tool_registry=FakeRegistry())
        assert out['executed'] == 2 and out['failed'] == 0 and out['ok']
        # 步骤状态
        assert out['steps'][0]['status'] == 'done'
        # llm 汇总含前序产出键名
        assert 'kb' in out['steps'][1]['result']

    def test_execute_failed_step_stops(self, monkeypatch):
        class FakeRegistry:
            def execute(self, name, params):
                return type('R', (), {'ok': name != 'kb_lookup', 'data': None})()
        out = PlanAgent().execute_plan(self._steps(), 'x', tool_registry=FakeRegistry())
        assert out['executed'] == 0 and out['failed'] == 1
        assert out['steps'][0]['status'] == 'failed'
        assert out['steps'][1]['status'] == 'pending'  # 后续未执行

    def test_execute_continue_on_error(self):
        class FakeRegistry:
            def execute(self, name, params):
                return type('R', (), {'ok': False, 'data': None})()
        out = PlanAgent().execute_plan(self._steps(), 'x', tool_registry=FakeRegistry(),
                                       continue_on_error=True)
        # tool 步全部失败；llm 汇总步（规则实现）不依赖工具，仍成功
        assert out['executed'] == 1 and out['failed'] == 1
        assert out['steps'][0]['status'] == 'failed'
        assert out['steps'][1]['status'] == 'done'

    def test_execute_empty(self):
        out = PlanAgent().execute_plan([], '')
        assert out['ok'] is False

    def test_prev_injection(self):
        class FakeRegistry:
            def execute(self, name, params):
                return type('R', (), {'ok': True, 'data': {'$prev_seen': params.get('$prev')}})()
        steps = [PlanStep(seq=1, goal='a', action='tool', target='x', params={}, outputs_name='p1'),
                 PlanStep(seq=2, goal='b', action='tool', target='y',
                          params={'$prev': 'p1'}, outputs_name='p2')]
        out = PlanAgent().execute_plan(steps, 't', tool_registry=FakeRegistry())
        assert out['ok'] and out['executed'] == 2

    def test_skill_step(self):
        from src.skills.executor import SkillExecutor
        steps = [PlanStep(seq=1, goal='技能', action='skill', target='no-such-skill',
                          params={}, outputs_name='sk')]
        out = PlanAgent().execute_plan(steps, 't', skill_executor=SkillExecutor())
        # 技能不存在 -> ok=False（不抛异常）
        assert out['steps'][0]['status'] == 'failed'
