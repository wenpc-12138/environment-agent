# -*- coding: utf-8 -*-
"""P7 OERCR 自动学习闭环：任务结束自动学习 / 审核反馈自动沉淀 / 复用。"""
from __future__ import annotations

import pytest

import v2_bridge
from src.core import config
from src.review.engine import ReviewIssue


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'oercr_auto.db'))
    config.get_settings.cache_clear()
    from src.core import db as core_db
    core_db.run_migrations()
    v2_bridge._AUTO_ENGINE = None  # 重置单例，绑定新库
    yield


class TestAutoLearn:
    def test_success_low_noise(self, _db):
        # 无负面反馈：不触发首要差距，低噪音
        r = v2_bridge.oercr_auto_learn('编制废水监测报告', task_id=91001, outcome='success')
        assert 'observed' in r
        assert r['crystallized'] == []

    def test_failed_crystallizes_pending(self, _db):
        r = v2_bridge.oercr_auto_learn('编制废水监测报告', task_id=91002,
                                       outcome='failed', feedback='数据单位错误，须修正')
        assert r['crystallized'], '负面反馈必须结晶待审技能'
        skills = v2_bridge.oercr_pending()['skills']
        assert skills and skills[0]['status'] == 'pending_review'


class TestLearnFromReview:
    def test_p0_p1_crystallize(self, _db):
        issues = [
            ReviewIssue(severity='P0', type='hallucination',
                        description='断言无知识库支撑（疑似幻觉）：某结论', location='结论'),
            ReviewIssue(severity='P1', type='unit_inconsistent',
                        description='单位写法不一致：mgL 应为 mg/L', location='监测结果'),
        ]
        r = v2_bridge.oercr_learn_from_review(issues)
        assert r['patterns'] >= 2
        assert len(r['crystallized']) >= 2
        pending = v2_bridge.oercr_pending()['skills']
        assert len(pending) >= 2

    def test_dedup_same_gap(self, _db):
        issues = [ReviewIssue(severity='P1', type='unit_inconsistent',
                              description='单位写法不一致：mgL 应为 mg/L', location='监测结果')]
        r1 = v2_bridge.oercr_learn_from_review(issues)
        r2 = v2_bridge.oercr_learn_from_review(issues)
        assert len(r1['crystallized']) == 1
        assert r2['crystallized'] == []  # 同 gap 去重防无限学习

    def test_empty_no_side_effect(self, _db):
        r = v2_bridge.oercr_learn_from_review([])
        assert r['patterns'] == 0 and r['crystallized'] == []


class TestReuseAfterApprove:
    def test_reuse_hits_active(self, _db):
        # 先学习 + R8 审批激活 → 相似任务自动复用命中
        v2_bridge.oercr_auto_learn('数据单位错误', task_id=91003,
                                   outcome='failed', feedback='单位错误须修正')
        act = v2_bridge._auto_engine().approve_pending('R8')
        assert act, '审批应激活待审技能'
        r = v2_bridge.oercr_reuse('数据单位错误', '')
        assert r['hit'] is not None
        assert r['hit']['status'] == 'active'


class TestOrchestratorFeedsReview:
    def test_review_feedback_learned(self, _db, monkeypatch):
        calls = {'n': 0}

        def fake_learn(issues):
            calls['n'] += 1
            return {'patterns': 1, 'crystallized': []}

        monkeypatch.setattr(v2_bridge, 'oercr_learn_from_review', fake_learn)
        import report_orchestrator as orch
        orch.run('帮我做一份监测报告', project_id='P-R', task_id=None)
        assert calls['n'] >= 1  # 初审/复审均喂 Learner
