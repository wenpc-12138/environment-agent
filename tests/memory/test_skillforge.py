# -*- coding: utf-8 -*-
"""自动技能沉淀：从任务轨迹生成技能草稿（pending_review）。"""
from __future__ import annotations

import pytest

from src.core import config, db as core_db
from src.memory import skillforge

TRACE = [
    {'role': 'user', 'content': '解读 GB 16297-1996 大气污染物综合排放标准'},
    {'role': 'tool', 'content': '检索到标准全文 20 页'},
    {'role': 'assistant', 'content': '已完成限值提取'},
    {'role': 'tool', 'content': '获取企业工艺信息'},
    {'role': 'assistant', 'content': '已匹配适用条款'},
    {'role': 'tool', 'content': '输出合规判定表'},
    {'role': 'assistant', 'content': '结论：企业排放满足限值要求'},
]

SHORT_TRACE = [
    {'role': 'user', 'content': '快速问答：限值是多少'},
    {'role': 'tool', 'content': '限值 10mg/m3'},
    {'role': 'assistant', 'content': '答案是 10mg/m3'},
]


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'forge.db'))
    config.get_settings.cache_clear()
    core_db.run_migrations()
    yield


class TestForge:
    def test_forge_creates_pending_skill(self, _db):
        res = skillforge.forge_skill_from_trace(1, TRACE)
        assert res and res['skill_id'].startswith('sk-auto-')
        assert res['name']
        # 写入 v2_skills，status=pending_review
        row = core_db.get_conn().execute(
            'SELECT * FROM v2_skills WHERE id=?', (res['skill_id'],)).fetchone()
        assert row and row['status'] == 'pending_review'
        assert 'forge_mode: auto_trace' in row['definition']
        # 资产登记
        row2 = core_db.get_conn().execute(
            'SELECT * FROM memory_assets WHERE asset_id=?', (f'skill:{res["skill_id"]}',)).fetchone()
        assert row2 is not None

    def test_short_trace_not_forged(self, _db):
        assert skillforge.forge_skill_from_trace(2, SHORT_TRACE) is None

    def test_empty_msgs_not_forged(self, _db):
        assert skillforge.forge_skill_from_trace(3, []) is None

    def test_dedup_by_name(self, _db):
        first = skillforge.forge_skill_from_trace(4, TRACE)
        assert first
        second = skillforge.forge_skill_from_trace(5, TRACE)
        assert second is None  # 同名去重

    def test_skill_id_sequential(self, _db):
        a = skillforge.forge_skill_from_trace(6, TRACE)
        b = skillforge.forge_skill_from_trace(7, [{'role': 'user', 'content': 'B 任务目标'},
                                                    {'role': 'tool', 'content': 't1'},
                                                    {'role': 'tool', 'content': 't2'},
                                                    {'role': 'tool', 'content': 't3'},
                                                    {'role': 'assistant', 'content': '结论完成'}])
        assert a and b
        assert int(a['skill_id'].split('-')[-1]) < int(b['skill_id'].split('-')[-1])
