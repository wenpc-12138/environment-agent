# -*- coding: utf-8 -*-
"""SkillExecutor 行为测试：run / run_dag / 双源加载（临时库）。"""
from __future__ import annotations

from src.core import config
from src.core.db import get_conn
from src.memory.procedural import ProceduralMemory
from src.models.core import SkillDef
from src.skills.executor import SkillExecutor


def test_run_from_v2_skills(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'sk.db'))
    config.get_settings.cache_clear()
    try:
        from src.core import db as core_db
        core_db.run_migrations()
        pm = ProceduralMemory()
        pm.create_skill(SkillDef(
            id='sk-tst-001', name='报告编制', level=2, role='R4', domain='D1',
            definition='[{"tool":"kb_lookup","args":{"q":"标准"}}]',
        ))
        ex = SkillExecutor()
        res = ex.run('sk-tst-001', {'project': 'P1'}, {'user': 'u1'})
        assert res.ok is True
        assert res.outputs['skill_id'] == 'sk-tst-001'
        assert res.trace_id
        assert res.outputs['tool_calls'] == ['kb_lookup']
    finally:
        config.get_settings.cache_clear()


def test_run_missing_skill(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'sk2.db'))
    config.get_settings.cache_clear()
    try:
        ex = SkillExecutor()
        res = ex.run('sk-nope-999', {}, {})
        assert res.ok is False
        assert '技能不存在' in res.outputs['error']
    finally:
        config.get_settings.cache_clear()


def test_run_from_skill_md(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'sk3.db'))
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'data'))
    config.get_settings.cache_clear()
    try:
        skill_dir = tmp_path / 'data' / 'agents' / 'skills' / 'ep-acceptance-report'
        skill_dir.mkdir(parents=True)
        (skill_dir / 'SKILL.md').write_text(
            '---\nname: 验收报告输出\nlevel: 3\nrole: R4\ndomain: D2\n---\n输出验收监测报告。',
            encoding='utf-8',
        )
        ex = SkillExecutor()
        res = ex.run('ep-acceptance-report', {}, {})
        assert res.ok is True
        assert res.outputs['name'] == '验收报告输出'
        assert '输出验收监测报告' in res.outputs['steps'][0]
    finally:
        config.get_settings.cache_clear()


def test_run_dag_sequence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'sk4.db'))
    config.get_settings.cache_clear()
    try:
        from src.core import db as core_db
        core_db.run_migrations()
        pm = ProceduralMemory()
        pm.create_skill(SkillDef(id='sk-tst-010', name='技能A', level=1, role='R1', domain='D1'))
        pm.create_skill(SkillDef(id='sk-tst-011', name='技能B', level=1, role='R1', domain='D1'))
        ex = SkillExecutor()
        results = ex.run_dag(['sk-tst-010', 'sk-tst-011'], {'seed': 1})
        assert len(results) == 2
        assert all(r.ok for r in results)
    finally:
        config.get_settings.cache_clear()


def test_run_rejects_non_active_skill(tmp_path, monkeypatch) -> None:
    """第 8 波：pending_review / rejected 技能硬拒绝，不执行步骤。"""
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'sk5.db'))
    config.get_settings.cache_clear()
    try:
        from src.core import db as core_db
        core_db.run_migrations()
        pm = ProceduralMemory()
        pm.create_skill(SkillDef(
            id='sk-oerc-001', name='待审技能', level=1, role='R8', domain='D1',
            status='pending_review', created_by='agent_oercr',
            definition='[{"tool":"kb_lookup","args":{"q":"标准"}}]',
        ))
        pm.create_skill(SkillDef(
            id='sk-oerc-002', name='被拒技能', level=1, role='R8', domain='D1',
            status='rejected', created_by='agent_oercr',
            definition='[{"tool":"kb_lookup","args":{"q":"标准"}}]',
        ))
        ex = SkillExecutor()
        res1 = ex.run('sk-oerc-001', {}, {})
        assert res1.ok is False
        assert 'pending_review' in res1.outputs['error']
        assert 'tool_calls' not in res1.outputs  # 未执行步骤
        res2 = ex.run('sk-oerc-002', {}, {})
        assert res2.ok is False
        assert 'rejected' in res2.outputs['error']
        assert 'tool_calls' not in res2.outputs
        # 激活后恢复可执行
        assert pm.approve_skill('sk-oerc-001', reviewer='R8') is True
        res3 = ex.run('sk-oerc-001', {}, {})
        assert res3.ok is True
    finally:
        config.get_settings.cache_clear()
