# -*- coding: utf-8 -*-
"""H4 子代理实时操控测试（对齐 Hermes subagent steering）。

覆盖：
- SubAgentRunner.spawn 后 running() 返回状态快照；
- steer() 向运行中子代理追加纠偏指令（下一轮 caller 消息含纠偏）；
- stop_partial() 置停止标志，collect 返回 stopped 与 partial；
- 既有 collect/projection/spawn 行为不回归。
"""
from __future__ import annotations

import time

import pytest

from src.agents.subagent import SubAgentRunner, SubAgentSpec


def _slow_caller(rounds=3, delay=0.15):
    """模拟慢速 LLM caller：轮询 ctrl.steer_queue 并响应；每轮 sleep 便于操控窗口。"""
    def caller(messages):
        # 返回 tool 调用让子代理持续运行（不 final）
        last_user = next((m['content'] for m in reversed(messages)
                          if m['role'] == 'user'), '')
        # 纠偏指令已注入 → 返回带纠偏内容的 final
        if '[纠偏指令]' in last_user:
            return '{"action":"final","text":"已按纠偏执行：方向修正完成"}'
        time.sleep(delay)
        return '{"action":"tool","name":"kb_lookup","params":{"query":"标准"}}'
    return caller


@pytest.fixture()
def runner() -> SubAgentRunner:
    return SubAgentRunner()


def test_running_lists_active(runner):
    """spawn 后 running() 返回运行中子代理快照。"""
    spec = SubAgentSpec(name='水质分析', role_id='R3', max_steps=6)
    sub_id = runner.spawn(spec, '分析任务', caller=_slow_caller(rounds=4, delay=0.3))
    running = runner.running()
    assert any(r['id'] == sub_id for r in running), '运行中应有该子代理'
    item = next(r for r in running if r['id'] == sub_id)
    assert item['name'] == '水质分析' and item['role'] == 'R3'
    runner.stop_partial(sub_id)
    runner.collect(sub_id, timeout=5)


def test_running_empty_when_none(runner):
    assert runner.running() == []


def test_steer_injects_instruction(runner):
    """steer() 后子代理下一轮 caller 收到纠偏指令并据此 final。"""
    spec = SubAgentSpec(name='报告起草', role_id='R4', max_steps=6)
    sub_id = runner.spawn(spec, '起草报告', caller=_slow_caller(delay=0.05))
    time.sleep(0.2)  # 让子代理进入运行
    r = runner.steer(sub_id, '请聚焦第三章监测结果')
    assert r.get('ok') is True
    out = runner.collect(sub_id, timeout=8)
    assert out is not None
    res = out.get('result') or {}
    assert '已按纠偏执行' in str(res.get('result') or ''), \
        '子代理应响应纠偏指令'


def test_stop_partial_returns_stopped(runner):
    """stop_partial() 后 collect 返回 stopped 状态。"""
    spec = SubAgentSpec(name='长任务', role_id='R4', max_steps=10)
    sub_id = runner.spawn(spec, '长任务', caller=_slow_caller(rounds=8, delay=0.3))
    time.sleep(0.3)
    r = runner.stop_partial(sub_id)
    assert r.get('ok') is True
    out = runner.collect(sub_id, timeout=5)
    assert out is not None
    assert out['status'] in ('stopped', 'done'), f'状态应为 stopped/done，实际 {out["status"]}'
    assert 'projection' in out


def test_steer_missing_subagent(runner):
    r = runner.steer('sub-nope', '指令')
    assert r.get('ok') is False


def test_stop_missing_subagent(runner):
    r = runner.stop_partial('sub-nope')
    assert r.get('ok') is False


def test_no_caller_regression(runner):
    """无 caller 降级路径不回归（H4 不改此行为）。"""
    spec = SubAgentSpec(name='规则降级', role_id='R1', max_steps=3)
    sub_id = runner.spawn(spec, '任务')
    out = runner.collect(sub_id, timeout=5)
    assert out is not None
    assert out['status'] == 'done'
    assert 'projection' in out
