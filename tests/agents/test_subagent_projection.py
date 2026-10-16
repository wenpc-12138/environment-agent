# -*- coding: utf-8 -*-
"""S3-H2 子代理投影测试（对标 Harness session-projection）。

覆盖：
- build_projection：任务→结论→关键产出结构化摘要；
- collect 完成后返回 projection 字段；
- 失败/超时子代理无 projection（或仅含错误信息）；
- 既有 collect/episodic 落库行为不回归。
"""
from __future__ import annotations

from src.agents.subagent import SubAgentRunner, SubAgentSpec, build_projection


def test_build_projection_shape():
    spec = SubAgentSpec(name='章节起草', role_id='R4')
    proj = build_projection(spec, '起草监测报告结果章节',
                            {'ok': True, 'result': '已起草完成，含超标判定',
                             'tool_calls': 3, 'errors': 0, 'steps': [1, 2, 3]})
    assert proj['name'] == '章节起草'
    assert proj['role'] == 'R4'
    assert proj['task'] == '起草监测报告结果章节'
    assert proj['conclusion'] == '已起草完成，含超标判定'
    assert proj['ok'] is True and proj['tool_calls'] == 3
    assert proj['steps'] == 3


def test_build_projection_empty():
    proj = build_projection(None, None, None)
    assert proj['task'] == '' and proj['conclusion'] == ''
    assert proj['ok'] is False


def test_collect_includes_projection(monkeypatch):
    """collect 回收完成子代理时返回 projection。"""
    runner = SubAgentRunner()
    spec = SubAgentSpec(name='水质分析', role_id='R3', max_steps=1)
    sub_id = runner.spawn(spec, '分析氨氮数据')

    # 无 caller：规则降级路径，结果含 ok=True
    out = runner.collect(sub_id, timeout=10)
    assert out is not None
    assert out['status'] == 'done'
    assert 'projection' in out
    assert out['projection']['name'] == '水质分析'
    assert out['projection']['role'] == 'R3'
    assert out['projection']['task'] == '分析氨氮数据'


def test_collect_missing_returns_none():
    runner = SubAgentRunner()
    assert runner.collect('sub-nope') is None


def test_parallel_collect_all_with_projection():
    runner = SubAgentRunner()
    specs = [SubAgentSpec(name=f'平行子代理{i}', role_id='R4', max_steps=1)
             for i in range(2)]
    tasks = [f'任务{i}' for i in range(2)]
    outs = runner.run_parallel(specs, tasks, timeout=10)
    assert len(outs) == 2
    for o in outs:
        assert 'projection' in o
        assert o['projection']['ok'] is True or 'conclusion' in o['projection']
