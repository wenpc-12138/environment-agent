# -*- coding: utf-8 -*-
"""P9 统一待审核中心：技能 R8 激活 + 模块蓝图审批（唯一人工闸门）。"""
from __future__ import annotations

import pytest

import v2_bridge
from src.core import config, db as core_db


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'review_center.db'))
    config.get_settings.cache_clear()
    core_db.run_migrations()
    v2_bridge._AUTO_ENGINE = None
    v2_bridge._LEARN = None
    v2_bridge._BLUEPRINT = None
    yield
    v2_bridge._BLUEPRINT = None


class TestReviewList:
    def test_empty(self, _db):
        r = v2_bridge.pending_review_list()
        assert r['count'] == 0 and r['items'] == []

    def test_skill_pending_listed(self, _db):
        v2_bridge.oercr_auto_learn('测试任务', task_id=93001,
                                   outcome='failed', feedback='数据单位错误须修正')
        r = v2_bridge.pending_review_list()
        assert r['count'] >= 1
        assert any(i['type'] == 'skill' and i['status'] == 'pending_review'
                   for i in r['items'])

    def test_blueprint_pending_listed(self, _db):
        v2_bridge.pipeline_run('开发一套土壤监测模块')
        r = v2_bridge.pending_review_list()
        assert any(i['type'] == 'blueprint' and i['status'] == 'pending_r8_review'
                   for i in r['items'])

    def test_type_filter(self, _db):
        v2_bridge.oercr_auto_learn('测试任务', task_id=93002,
                                   outcome='failed', feedback='计算错误须修正')
        v2_bridge.pipeline_run('开发一套大气模块')
        r = v2_bridge.pending_review_list(type_filter='skill')
        assert r['count'] >= 1 and all(i['type'] == 'skill' for i in r['items'])
        r2 = v2_bridge.pending_review_list(type_filter='blueprint')
        assert all(i['type'] == 'blueprint' for i in r2['items'])


class TestReviewActions:
    def test_approve_skill(self, _db):
        v2_bridge.oercr_auto_learn('测试任务', task_id=93003,
                                   outcome='failed', feedback='单位错误须修正')
        sid = v2_bridge.pending_review_list()['items'][0]['id']
        r = v2_bridge.pending_review_approve('skill', sid)
        assert r['ok'] is True
        act = [s for s in v2_bridge._procedural().list_skills('active') if s.id == sid]
        assert act

    def test_reject_skill(self, _db):
        v2_bridge.oercr_auto_learn('测试任务', task_id=93004,
                                   outcome='failed', feedback='流程错误须修正')
        sid = v2_bridge.pending_review_list()['items'][0]['id']
        r = v2_bridge.pending_review_reject('skill', sid)
        assert r['ok'] is True
        rej = [s for s in v2_bridge._procedural().list_skills('rejected') if s.id == sid]
        assert rej

    def test_approve_blueprint(self, _db):
        v2_bridge.pipeline_run('开发一套水质模块')
        r = v2_bridge.pending_review_approve('blueprint', 'blueprint')
        assert r['ok'] is True
        assert v2_bridge._BLUEPRINT is not None
        assert v2_bridge._BLUEPRINT.status == 'active'

    def test_reject_blueprint(self, _db):
        v2_bridge.pipeline_run('开发一套噪声模块')
        r = v2_bridge.pending_review_reject('blueprint', 'blueprint')
        assert r['ok'] is True
        assert v2_bridge._BLUEPRINT is None

    def test_approve_all(self, _db):
        v2_bridge.oercr_auto_learn('测试任务', task_id=93005,
                                   outcome='failed', feedback='数据错误须修正')
        v2_bridge.pipeline_run('开发一套固废模块')
        r = v2_bridge.pending_review_approve_all()
        assert r['skills'] >= 1 and r['blueprint'] is True
        assert v2_bridge.pending_review_list()['count'] == 0
