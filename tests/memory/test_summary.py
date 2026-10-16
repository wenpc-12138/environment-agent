# -*- coding: utf-8 -*-
"""M5 三层摘要：规则摘要 / LLM 摘要 / 落盘。"""
from __future__ import annotations

import pytest

from src.core import config, db as core_db
from src.memory import summary

MSGS = [
    {'role': 'user', 'content': '要求生成一份废水监测报告，执行标准 GB 3838-2002'},
    {'role': 'assistant', 'content': '已完成报告初稿，结论：各指标达标'},
    {'role': 'tool', 'content': 'kb_retrieve 检索到 3 条标准'},
    {'role': 'user', 'content': '结论：需要补充点位数据'},
    {'role': 'assistant', 'content': '已修复并完成最终报告'},
]


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'summary.db'))
    config.get_settings.cache_clear()
    core_db.run_migrations()
    yield


class TestRuleSummary:
    def test_abstract_extracts_key_lines(self, _db):
        res = summary.summarize_task_messages(MSGS, caller=None)
        assert res['abstract'], 'L1 精要不为空'
        assert any('监测报告' in a or '达标' in a or '点位' in a for a in res['abstract'].splitlines())

    def test_overview_structured(self, _db):
        res = summary.summarize_task_messages(MSGS, caller=None)
        ov = res['overview']
        assert '用户需求' in ov and '执行结果' in ov

    def test_empty(self, _db):
        res = summary.summarize_task_messages([], caller=None)
        assert res['abstract'] == '' and res['overview'] == ''


class TestLlmSummary:
    def test_llm_parses(self, _db):
        def caller(messages):
            return ('ABSTRACT: 用户要求生成监测报告；已完成并补充点位。\n'
                    'OVERVIEW: ## 用户需求\n- 生成监测报告\n## 执行结果\n- 已完成')
        res = summary.summarize_task_messages(MSGS, caller=caller)
        assert '监测报告' in res['abstract']
        assert '用户需求' in res['overview']

    def test_llm_garbage_falls_back(self, _db):
        def caller(messages):
            return 'not parseable'
        res = summary.summarize_task_messages(MSGS, caller=caller)
        assert res['abstract']  # 回退规则

    def test_llm_no_overview_marker(self, _db):
        def caller(messages):
            return 'ABSTRACT: only abstract'
        res = summary.summarize_task_messages(MSGS, caller=caller)
        assert res['abstract'] == 'only abstract'
        assert res['overview']


class TestSave:
    def test_save_writes_files(self, _db):
        import db as root_db
        # 根 db.py 用模块级 DB_PATH（env 在 import 时已绑定隔离路径），init_db 建表
        root_db.init_db()
        tid = root_db.create_task('摘要测试')
        root_db.task_output_save(tid, 'chat.md', '# chat')
        res = summary.save_task_summaries(tid, MSGS)
        assert res['abstract']
        # 输出目录存在两级摘要文件
        import os
        d = root_db.task_output_dir(tid)
        assert os.path.exists(os.path.join(d, 'abstract.md'))
        assert os.path.exists(os.path.join(d, 'overview.md'))
