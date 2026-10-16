# -*- coding: utf-8 -*-
"""短期任务压缩：offload 卸载 / 符号画布 / 窗口压缩。"""
from __future__ import annotations

import pytest

from src.core import config, db as core_db
from src.memory import offload

MSGS = [
    {'role': 'user', 'content': '要求解读 GB 37822-2019 的排放限值'},
    {'role': 'tool', 'content': 'kb_retrieve 返回标准全文（限值表如下）' + 'x' * 3000},
    {'role': 'assistant', 'content': '已完成解读，结论：NMHC 限值 10mg/m3'},
    {'role': 'tool', 'content': '检索到 2 条地方标准'},
]


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'offload.db'))
    config.get_settings.cache_clear()
    core_db.run_migrations()
    yield


class TestOffload:
    def test_offload_long_tool_output(self, _db):
        import db as root_db
        root_db.init_db()
        tid = root_db.create_task('offload 测试')
        res = offload.offload_tool_outputs(tid, MSGS)
        assert res['offloaded'] == 1
        assert res['offloaded_chars'] >= 3000
        # 落盘文件存在
        import os
        d = root_db.task_output_dir(tid)
        refs = os.path.join(d, 'refs')
        assert os.path.isdir(refs) and os.listdir(refs)
        # 压缩后消息含引用
        comp = res['compressed']
        tool_msg = next(m for m in comp if m['role'] == 'tool' and 'refs/' in m.get('content', ''))
        assert '全文已卸载' in tool_msg['content']

    def test_short_output_not_offloaded(self, _db):
        short = [{'role': 'tool', 'content': '短输出'}]
        res = offload.offload_tool_outputs(1, short)
        assert res['offloaded'] == 0

    def test_offload_keeps_order(self, _db):
        res = offload.offload_tool_outputs(1, MSGS)
        roles = [m['role'] for m in res['compressed']]
        assert roles == ['user', 'tool', 'assistant', 'tool']


class TestCanvas:
    def test_canvas_contains_nodes(self, _db):
        canvas = offload.build_canvas(MSGS)
        assert canvas.startswith('```mermaid')
        assert 'flowchart TD' in canvas
        assert 'n1' in canvas and ' --> ' in canvas

    def test_canvas_escapes_quotes(self, _db):
        msgs = [{'role': 'user', 'content': '他说"重要"的规范'}]
        canvas = offload.build_canvas(msgs)
        assert "'重要'" in canvas or '重要' in canvas
        assert '他说' in canvas

    def test_canvas_empty(self, _db):
        assert offload.build_canvas([]) == ''

    def test_save_task_canvas(self, _db):
        import db as root_db
        root_db.init_db()
        tid = root_db.create_task('canvas 测试')
        res = offload.save_task_canvas(tid, MSGS)
        assert res['node_count'] >= 2
        assert res['offloaded'] == 1
        # 落库
        row = core_db.get_conn().execute(
            'SELECT * FROM task_canvases WHERE task_id=?', (str(tid),)).fetchone()
        assert row and row['offloaded'] == 1
        # 资产登记
        row2 = core_db.get_conn().execute(
            "SELECT * FROM memory_assets WHERE asset_id=?",
            (f'canvas:{tid}',)).fetchone()
        assert row2 is not None


class TestWindow:
    def test_within_budget_unchanged(self, _db):
        msgs = [{'role': 'assistant', 'content': '短内容'}]
        out = offload.summarize_window(msgs, budget=12000)
        assert out == msgs

    def test_overflow_truncates(self, _db):
        msgs = [{'role': 'tool', 'content': 'y' * 10000}]
        out = offload.summarize_window(msgs, budget=500)
        assert len(out[0]['content']) <= 500
        assert '截断' in out[0]['content']


class TestLiveBudget:
    """实时上下文守卫（对齐 TencentDB beforePromptBuild / afterToolCall）。"""

    def test_offload_long_tool_in_place(self, _db):
        import db as root_db
        root_db.init_db()
        tid = root_db.create_task('live offload 测试')
        msgs = [
            {'role': 'system', 'content': '你是环保专家'},
            {'role': 'user', 'content': '要求解读 GB 37822-2019'},
            {'role': 'assistant', 'content': '开始检索', 'tool_calls': [{'id': 'c1'}]},
            {'role': 'tool', 'content': '检索结果' + 'x' * 3000, 'tool_call_id': 'c1'},
        ]
        res = offload.ensure_live_budget(tid, msgs)
        assert res['offloaded'] == 1
        assert '全文已卸载' in msgs[3]['content']
        assert msgs[3].get('_ea_offloaded') is True
        # 幂等：第二次不再重复写盘
        res2 = offload.ensure_live_budget(tid, msgs)
        assert res2['offloaded'] == 0
        # 落盘文件存在
        import os
        d = root_db.task_output_dir(tid)
        refs = os.path.join(d, 'refs')
        assert os.path.isdir(refs) and os.listdir(refs)

    def test_short_no_change(self, _db):
        msgs = [
            {'role': 'system', 'content': 's'},
            {'role': 'user', 'content': 'u'},
            {'role': 'assistant', 'content': 'a'},
            {'role': 'tool', 'content': '短输出', 'tool_call_id': '1'},
        ]
        res = offload.ensure_live_budget(1, msgs)
        assert res['offloaded'] == 0 and res['compressed'] == 0
        assert msgs[3]['content'] == '短输出'

    def test_over_budget_truncates_old(self, _db):
        # 构造超预算：12 轮旧消息（中文 tool 1999 字符，token 估算高、不触发 offload）
        msgs = [{'role': 'system', 'content': '你是环保专家'}]
        for i in range(12):
            msgs.append({'role': 'user', 'content': f'第{i}条请求'})
            msgs.append({'role': 'tool', 'content': '环' * 1999, 'tool_call_id': f't{i}'})
        msgs.append({'role': 'assistant', 'content': '最终结论'})
        res = offload.ensure_live_budget(1, msgs, model='gpt-3.5')
        assert res['compressed'] >= 1
        # 最近的保留原始，旧消息被截断
        assert msgs[-1]['content'] == '最终结论'
        assert any('[截断:' in (m.get('content') or '') for m in msgs)
        assert res['after'] <= res['before']

    def test_user_message_not_truncated(self, _db):
        # 25 条消息（>8 触发守卫），小窗口模型，超预算
        msgs = [{'role': 'system', 'content': 's'}]
        for i in range(12):
            msgs.append({'role': 'user', 'content': f'请求{i}'})
            msgs.append({'role': 'tool', 'content': '环' * 1999, 'tool_call_id': f't{i}'})
        msgs.append({'role': 'assistant', 'content': '结论'})
        offload.ensure_live_budget(1, msgs, model='gpt-3.5')
        # 所有 user 消息保持完整（不截断）
        assert all('[截断:' not in (m.get('content') or '') for m in msgs if m['role'] == 'user')
        # 至少一条 tool 被截断
        assert any('[截断:' in (m.get('content') or '') for m in msgs if m['role'] == 'tool')

    def test_empty_or_small_input(self, _db):
        assert offload.ensure_live_budget(1, [])['offloaded'] == 0
        assert offload.ensure_live_budget(1, [{'role': 'user', 'content': 'hi'}])['offloaded'] == 0
