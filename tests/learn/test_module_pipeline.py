# -*- coding: utf-8 -*-
"""M15 ModulePipeline 行为测试：材料解析 / 法规检索 / 模块生成落库。"""
from __future__ import annotations

from src.core import config
from src.learn.module_pipeline import ModulePipeline
from src.roles.registry import RoleRegistry


def _db(tmp_path, monkeypatch, name: str = 'mod.db'):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / name))
    config.get_settings.cache_clear()
    from src.core import db as core_db
    core_db.run_migrations()


def _write(tmp_path, name: str, content: str) -> str:
    p = tmp_path / name
    p.write_text(content, encoding='utf-8')
    return str(p)


def test_ingest_md_detects_title_and_sections(tmp_path) -> None:
    path = _write(tmp_path, '标准.md', '# HJ 168-2020 环境监测分析方法\n\n## 第一章 范围\n\n正文内容\n\n## 第二章 术语')
    docs = ModulePipeline().ingest_materials([path])
    assert len(docs) == 1
    d = docs[0]
    assert d.title == 'HJ 168-2020 环境监测分析方法'
    assert d.doc_type == 'md'
    assert '范围' in d.content
    assert len(d.sections) >= 2


def test_ingest_missing_file_returns_missing(tmp_path) -> None:
    docs = ModulePipeline().ingest_materials([str(tmp_path / 'nope.docx')])
    assert len(docs) == 1
    assert docs[0].doc_type == 'missing'
    assert docs[0].content == ''


def test_search_regulations_offline_fallback() -> None:
    """无网/未配置 MCP 时降级返回内置官方源。"""
    hits = ModulePipeline().search_regulations('D3')
    assert hits, 'D3 应返回官方源法规'
    assert all(h.source == 'official' for h in hits)
    assert any('验收' in h.title or '竣工' in h.title for h in hits)
    assert any(h.code for h in hits)


def test_run_generates_blueprint(tmp_path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    try:
        conv = [
            {'role': 'user', 'content': '需要建设竣工环保验收模块，验收报告按验收暂行办法编制'},
            {'role': 'assistant', 'content': '将按 D3 领域生成验收审核流程'},
        ]
        md = _write(tmp_path, '验收依据.md', '# 验收暂行办法\n\n## 验收条件\n\n对照环评批复逐项核查')
        bp = ModulePipeline().run(conv, [md])
        assert bp.domain == 'D3'
        assert bp.status == 'pending_r8_review'
        assert bp.roles and bp.roles[0].name == '验收审核专员'
        assert bp.roles[0].status == 'pending_r8_review'
        assert bp.skills and bp.skills[0].status == 'pending_review'
        assert bp.skills[0].created_by == 'agent_oercr'
        assert bp.workflow_template['state_machine']['initial'] == 'drafting'
        assert any(r.startswith('ref:') for r in bp.knowledge_base)  # 法规引用
    finally:
        config.get_settings.cache_clear()


def test_run_writes_role_and_skill(tmp_path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    try:
        conv = [{'role': 'user', 'content': '建设环境监测模块，含采样与数据分析'}]
        bp = ModulePipeline().run(conv, [])
        # 角色已入注册表，R8 审核后可激活
        reg = RoleRegistry()
        role = bp.roles[0]
        assert reg.define(role) == role.id
        assert reg.activate(role.id, 'R8') is True
        assert reg.activate(role.id, 'R1') is False  # 非 R8 不可激活
        # 技能已写入 ProceduralMemory（pending_review）
        from src.memory.procedural import ProceduralMemory
        pm = ProceduralMemory()
        assert pm.best_match('环境监测') is None  # pending 不参与复用
    finally:
        config.get_settings.cache_clear()


def test_approve_blueprint_activates_all(tmp_path, monkeypatch) -> None:
    """第 8 波：R8 一次性审批蓝图——批量激活角色 + 技能。"""
    _db(tmp_path, monkeypatch)
    try:
        conv = [{'role': 'user', 'content': '建设竣工环保验收模块，含验收审核流程'}]
        bp = ModulePipeline().run(conv, [])
        assert bp.status == 'pending_r8_review'
        # 非 R8 无法审批
        assert ModulePipeline().approve_blueprint(bp, reviewer='R4') is False
        assert bp.status == 'pending_r8_review'
        # 已激活蓝图不可重复审批
        assert ModulePipeline().approve_blueprint(bp, reviewer='R8') is True
        assert bp.status == 'active'
        assert ModulePipeline().approve_blueprint(bp, reviewer='R8') is False
        # 角色与技能均已激活（RoleBlueprint 对象由 activate 原位修改为 active）
        assert bp.roles[0].status == 'active'
        from src.memory.procedural import ProceduralMemory
        pm = ProceduralMemory()
        for skill in bp.skills:
            assert pm.list_skills(status='active')  # 技能已 active
            break
        # 激活后的技能可参与复用
        hit = pm.best_match(bp.skills[0].name)
        assert hit is not None and hit.status == 'active'
    finally:
        config.get_settings.cache_clear()
