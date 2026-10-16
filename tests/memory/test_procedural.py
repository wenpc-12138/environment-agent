# -*- coding: utf-8 -*-
"""ProceduralMemory 行为测试：create/update/best_match/mark_deprecated。"""
from __future__ import annotations

from src.core import config
from src.core.db import get_conn
from src.memory.procedural import ProceduralMemory
from src.models.core import SkillDef


def _skill(**kw) -> SkillDef:
    base = dict(
        id='sk-tst-001', name='报告编制', level=2, role='R4',
        domain='D1', version='1.0.0', status='active',
        definition='步骤：收集数据、编制报告',
    )
    base.update(kw)
    return SkillDef(**base)


def test_create_and_best_match(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'proc.db'))
    config.get_settings.cache_clear()
    try:
        from src.core import db as core_db
        core_db.run_migrations()
        pm = ProceduralMemory()
        assert pm.create_skill(_skill()) == 'sk-tst-001'
        hit = pm.best_match('帮我编制监测报告')
        assert hit is not None
        assert hit.id == 'sk-tst-001'
        assert pm.best_match('完全无关内容') is None
    finally:
        config.get_settings.cache_clear()


def test_domain_filter(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'proc2.db'))
    config.get_settings.cache_clear()
    try:
        from src.core import db as core_db
        core_db.run_migrations()
        pm = ProceduralMemory()
        pm.create_skill(_skill(id='sk-tst-002', name='采样', domain='D2'))
        hit = pm.best_match('采样任务', domain='D2')
        assert hit is not None and hit.id == 'sk-tst-002'
        assert pm.best_match('采样任务', domain='D1') is None
    finally:
        config.get_settings.cache_clear()


def test_update_skill(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'proc3.db'))
    config.get_settings.cache_clear()
    try:
        from src.core import db as core_db
        core_db.run_migrations()
        pm = ProceduralMemory()
        pm.create_skill(_skill())
        updated = _skill(version='1.1.0', definition='新步骤')
        assert pm.update_skill('sk-tst-001', updated, reviewer='R8') is True
        assert pm.update_skill('sk-nope-999', updated, reviewer='R8') is False
        hit = pm.best_match('新步骤')
        assert hit is not None and hit.version == '1.1.0'
    finally:
        config.get_settings.cache_clear()


def test_mark_deprecated(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'proc4.db'))
    config.get_settings.cache_clear()
    try:
        from src.core import db as core_db
        core_db.run_migrations()
        pm = ProceduralMemory()
        pm.create_skill(_skill(definition='引用 HJ 166-2026 条款'))
        pm.create_skill(_skill(id='sk-tst-011', name='另一个', definition='无关'))
        affected = pm.mark_deprecated('HJ 166-2026')
        assert 'sk-tst-001' in affected
        assert 'sk-tst-011' not in affected
        # 置废后 best_match 不应命中
        assert pm.best_match('HJ 166-2026') is None
    finally:
        config.get_settings.cache_clear()


# ---- 第 8 波：R8 审核→技能激活联动 ----

def _pending_skill(**kw) -> SkillDef:
    base = dict(
        id='sk-oerc-001', name='OERCR 结晶技能', level=2, role='R8',
        domain='D1', version='1.0.0', status='pending_review',
        created_by='agent_oercr', definition='步骤：自动生成',
    )
    base.update(kw)
    return SkillDef(**base)


def test_approve_and_reject_skill(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'proc5.db'))
    config.get_settings.cache_clear()
    try:
        from src.core import db as core_db
        core_db.run_migrations()
        pm = ProceduralMemory()
        pm.create_skill(_pending_skill())
        pm.create_skill(_pending_skill(id='sk-oerc-002', name='另一个待审'))
        # R8 审核通过
        assert pm.approve_skill('sk-oerc-001', reviewer='R8') is True
        # 通过后技能可被 best_match 命中
        hit = pm.best_match('OERCR 结晶')
        assert hit is not None and hit.id == 'sk-oerc-001'
        assert hit.status == 'active'
        # 非 R8 审核人被拒
        assert pm.approve_skill('sk-oerc-002', reviewer='R4') is False
        assert pm.list_skills(status='pending_review') != []
        # 已激活技能不可重复激活
        assert pm.approve_skill('sk-oerc-001', reviewer='R8') is False
        # 驳回
        assert pm.reject_skill('sk-oerc-002', reviewer='R8') is True
        rejected = pm.list_skills(status='rejected')
        assert [s.id for s in rejected] == ['sk-oerc-002']
        # 驳回后不参与 best_match
        assert pm.best_match('另一个待审') is None
        # 非 R8 驳回被拒
        assert pm.reject_skill('sk-oerc-002', reviewer='R4') is False
    finally:
        config.get_settings.cache_clear()


def test_update_skill_requires_r8_and_live(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'proc6.db'))
    config.get_settings.cache_clear()
    try:
        from src.core import db as core_db
        core_db.run_migrations()
        pm = ProceduralMemory()
        pm.create_skill(_skill())
        # 非 R8 无法更新
        assert pm.update_skill('sk-tst-001', _skill(version='9.9.9'), reviewer='R4') is False
        # rejected 技能不可通过 update 复活
        pm.create_skill(_pending_skill(id='sk-oerc-010', name='被拒技能'))
        assert pm.reject_skill('sk-oerc-010', reviewer='R8') is True
        assert pm.update_skill('sk-oerc-010', _pending_skill(version='2.0.0'), reviewer='R8') is False
        # 待审技能允许 R8 修订（不改变待审状态）
        pm.create_skill(_pending_skill(id='sk-oerc-011', name='待修订'))
        assert pm.update_skill(
            'sk-oerc-011', _pending_skill(id='sk-oerc-011', version='1.1.0'), reviewer='R8'
        ) is True
        assert pm.list_skills(status='pending_review') != []
    finally:
        config.get_settings.cache_clear()
