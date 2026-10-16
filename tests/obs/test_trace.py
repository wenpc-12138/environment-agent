# -*- coding: utf-8 -*-
"""G3 链路追踪：span 嵌套/落盘/查询/聚合。"""
from __future__ import annotations

import pytest

from src.obs import trace as tr


@pytest.fixture()
def _tmp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, '_traces_dir', lambda: tmp_path)
    yield tmp_path


class TestTracerSpan:
    def test_begin_end_trace(self, _tmp_dir):
        t = tr.Tracer()
        tid = t.begin_trace(task_id=42, title='测试任务')
        assert tid and t.current_trace()['task_id'] == 42
        summary = t.end_trace()
        assert summary['type'] == 'trace'
        assert summary['span_count'] == 0

    def test_span_nested(self, _tmp_dir):
        t = tr.Tracer()
        t.begin_trace(task_id=1)
        with t.span('llm', 'round 1', model='deepseek', in_tokens=100, out_tokens=50):
            with t.span('tool', 'kb_lookup'):
                pass
        summary = t.end_trace()
        assert summary['span_count'] == 2
        # 成本按启发式价格估算（deepseek 0.014/0.028 元每1K）
        assert summary['cost'] > 0

    def test_span_without_trace_noop(self, _tmp_dir):
        t = tr.Tracer()
        with t.span('llm', 'x'):
            pass  # 无 begin_trace 时空转不报错

    def test_span_error_records_status(self, _tmp_dir):
        t = tr.Tracer()
        t.begin_trace(task_id=1)
        with pytest.raises(RuntimeError):
            with t.span('tool', 'boom'):
                raise RuntimeError('boom')
        summary = t.end_trace()
        assert summary['span_count'] == 1

    def test_flush_span_fields(self, _tmp_dir):
        t = tr.Tracer()
        t.begin_trace(task_id=1)
        with t.span('llm', 'r1') as r:
            rec = r
        assert rec['cost'] == 0  # 未给 tokens 时无成本
        t.flush_span(rec['span_id'], in_tokens=1000, out_tokens=500, model='gpt-4')
        summary = t.end_trace()
        assert summary['cost'] > 0


class TestPersistence:
    def test_query_trace_restores_tree(self, _tmp_dir):
        t = tr.Tracer()
        t.begin_trace(task_id=7, title='树')
        with t.span('llm', 'r1') as r1:
            with t.span('tool', 'kb_lookup'):
                pass
        tid = t.current_trace()['trace_id']
        t.end_trace()
        hit = tr.query_trace(tid)
        assert hit is not None and hit['count'] == 2
        assert len(hit['roots']) == 1
        assert hit['roots'][0]['children'][0]['name'] == 'kb_lookup'

    def test_query_trace_missing(self, _tmp_dir):
        assert tr.query_trace('nope') is None

    def test_query_task(self, _tmp_dir):
        t = tr.Tracer()
        t.begin_trace(task_id=7, title='a')
        t.end_trace()
        t.begin_trace(task_id=7, title='b')
        t.end_trace()
        t.begin_trace(task_id=8, title='c')
        t.end_trace()
        rows = tr.query_task(7)
        assert len(rows) == 2 and all(r['task_id'] == 7 for r in rows)

    def test_aggregate(self, _tmp_dir):
        t = tr.Tracer()
        t.begin_trace(task_id=1)
        for i in range(3):
            with t.span('llm', f'r{i}', model='deepseek', in_tokens=100, out_tokens=50):
                pass
        t.end_trace()
        agg = tr.aggregate()
        assert agg['span_count'] == 3
        assert agg['by_type'].get('llm') == 3
        assert agg['total_cost'] > 0
        assert agg['errors'] == 0
        assert len(agg['slowest']) == 3

    def test_aggregate_filter_type(self, _tmp_dir):
        t = tr.Tracer()
        t.begin_trace(task_id=1)
        with t.span('llm', 'r1'):
            pass
        with t.span('tool', 'kb_lookup'):
            pass
        t.end_trace()
        agg = tr.aggregate(span_type='tool')
        assert agg['span_count'] == 1 and agg['by_type'].get('tool') == 1


class TestHeuristicCost:
    def test_price_lookup(self):
        assert tr._heuristic_cost('deepseek-chat', 1000, 1000) > 0
        assert tr._heuristic_cost('unknown-model', 1000, 1000) > 0
        assert tr._heuristic_cost('deepseek-chat', 0, 0) == 0.0
