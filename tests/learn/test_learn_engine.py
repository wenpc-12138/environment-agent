# -*- coding: utf-8 -*-
"""M13 OercrEngine 行为测试：observe → reflect → crystallize → reuse 闭环。"""
from __future__ import annotations

from src.core import config
from src.learn.engine import OercrEngine
from src.learn.learner import Learner


def _db(tmp_path, monkeypatch, name: str = 'oercr.db'):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / name))
    config.get_settings.cache_clear()
    from src.core import db as core_db
    core_db.run_migrations()


def test_observe_creates_observation() -> None:
    eng = OercrEngine()
    obs = eng.observe({'episode_id': 'ep-001', 'task': '编制废水监测报告', 'domain': 'D2',
                       'outcome': 'failed', 'feedback': '数据单位错误'})
    assert obs.obs_id.startswith('obs-')
    assert obs.episode_id == 'ep-001'
    assert obs.domain == 'D2'
    assert obs.outcome == 'failed'
    assert obs.user_feedback == '数据单位错误'
    assert 'ep-001' in eng._episodes


def test_reflect_negative_feedback_yields_priority() -> None:
    eng = OercrEngine(learner=Learner())
    obs = eng.observe({'episode_id': 'ep-002', 'task': '验收报告编制', 'domain': 'D3',
                       'outcome': 'failed', 'feedback': '超限，须修正'})
    refls = eng.reflect(obs)
    assert refls, '负面反馈必须产出反思'
    assert any(r.severity in ('P0', 'P1') for r in refls)


def test_reflect_high_confidence_pattern_yields_p2() -> None:
    eng = OercrEngine(learner=Learner())
    obs = eng.observe({'episode_id': 'ep-003', 'task': '采样任务', 'domain': 'D1',
                       'outcome': 'done', 'feedback': 'ok 通过'})
    refls = eng.reflect(obs, baseline={'threshold': 0.7})
    # 正面反馈样本模式置信度 0.85 ≥ 0.7 → P2 沉淀
    assert any(r.severity == 'P2' for r in refls)


def test_crystallize_writes_skill_and_dedup(tmp_path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    try:
        eng = OercrEngine(learner=Learner())
        obs = eng.observe({'episode_id': 'ep-004', 'task': '环评编制', 'domain': 'D4',
                           'outcome': 'failed', 'feedback': '章节缺失'})
        refls = eng.reflect(obs)
        skills = eng.crystallize(refls)
        assert skills, '反思应沉淀为技能'
        s = skills[0]
        assert s.id.startswith('sk-oerc-')
        assert s.status == 'pending_review'  # 待 R8 审核
        assert s.created_by == 'agent_oercr'
        assert s.role == 'R8'
        # 同 (domain, gap) 不重复结晶（防循环）
        again = eng.crystallize(refls)
        assert again == []
    finally:
        config.get_settings.cache_clear()


def test_reuse_only_active_skills(tmp_path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    try:
        eng = OercrEngine(learner=Learner())
        obs = eng.observe({'episode_id': 'ep-005', 'task': '排放核查', 'domain': 'D2',
                           'outcome': 'failed', 'feedback': '限值错误'})
        eng.crystallize(eng.reflect(obs))
        # pending_review 技能不参与 best_match（仅 active）
        assert eng.reuse('排放核查', 'D2') is None
    finally:
        config.get_settings.cache_clear()


def test_approve_pending_activates_oercr_skills(tmp_path, monkeypatch) -> None:
    """第 8 波：R8 审核激活 OERCR 结晶产物后 reuse 命中。"""
    _db(tmp_path, monkeypatch)
    try:
        eng = OercrEngine(learner=Learner())
        obs = eng.observe({'episode_id': 'ep-006', 'task': '废水监测', 'domain': 'D2',
                           'outcome': 'failed', 'feedback': '方法选择错误'})
        skills = eng.crystallize(eng.reflect(obs))
        assert skills and skills[0].status == 'pending_review'
        # 非 R8 审核人无法激活
        assert eng.approve_pending(reviewer='R4') == []
        # R8 批量激活
        activated = eng.approve_pending(reviewer='R8')
        assert len(activated) == 1
        assert activated[0].id == skills[0].id
        assert activated[0].status == 'active'
        # 激活后可复用命中
        hit = eng.reuse('废水监测', 'D2')
        assert hit is not None and hit.id == skills[0].id
    finally:
        config.get_settings.cache_clear()
