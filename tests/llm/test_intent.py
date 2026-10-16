# -*- coding: utf-8 -*-
"""IntentRouter 行为测试：三档置信度映射 + context 强制档位 + 空输入。"""
from __future__ import annotations

from src.llm import IntentRouter, RouteResult


def test_high_confidence_auto() -> None:
    r: RouteResult = IntentRouter().analyze('制定地表水水质监测方案并按计划安排实施')
    assert r.mode == 'auto'
    assert r.confidence >= 0.85
    assert r.domain == 'D1'
    assert r.skill_ids, 'auto 档应附带建议技能'


def test_mid_confidence_interactive() -> None:
    r: RouteResult = IntentRouter().analyze('查询废气排放标准号是什么')
    assert r.mode == 'interactive'
    assert 0.50 <= r.confidence < 0.85
    assert r.domain == 'D2'


def test_low_confidence_manual() -> None:
    r: RouteResult = IntentRouter().analyze('你好')
    assert r.mode == 'manual'
    assert r.confidence < 0.50
    assert r.domain == ''


def test_empty_text_manual() -> None:
    r: RouteResult = IntentRouter().analyze('   ')
    assert r.mode == 'manual'
    assert r.confidence == 0.0
    assert r.skill_ids == []


def test_context_mode_hint_override() -> None:
    r: RouteResult = IntentRouter().analyze('你好', {'mode_hint': 'auto'})
    assert r.mode == 'auto'
    assert r.confidence >= 0.85


def test_plan_intent_skips_manual() -> None:
    r: RouteResult = IntentRouter().analyze('做一个噪声监测方案')
    assert r.mode in ('auto', 'interactive')
    assert r.domain == 'D3'


# ---- 定位扩展（生态环境大类）：D7 辐射 / D8 碳 / D9 应急 / D10 清洁生产 ----

def test_domain_d7_radiation() -> None:
    r: RouteResult = IntentRouter().analyze('计算辐射剂量当量并编制辐射监测方案')
    assert r.domain == 'D7'
    assert 'radiation-monitoring' in r.skill_ids


def test_domain_d8_carbon() -> None:
    r: RouteResult = IntentRouter().analyze('核算企业年度碳排放并输出温室气体清单')
    assert r.domain == 'D8'
    assert 'carbon-accounting' in r.skill_ids


def test_domain_d9_emergency() -> None:
    r: RouteResult = IntentRouter().analyze('编制突发环境事件应急预案')
    assert r.domain == 'D9'
    assert 'env-emergency' in r.skill_ids


def test_domain_d10_cleaner_production() -> None:
    r: RouteResult = IntentRouter().analyze('清洁生产审核报告编制')
    assert r.domain == 'D10'
    assert 'cleaner-production' in r.skill_ids


def test_domain_d5_ecology_skill() -> None:
    r: RouteResult = IntentRouter().analyze('编制生态现状评价并计算香农多样性指数')
    assert r.domain == 'D5'
    assert 'ecology-evaluation' in r.skill_ids


def test_domain_d2_odor_merged() -> None:
    """恶臭并入大气：'恶臭' 触发 D2。"""
    r: RouteResult = IntentRouter().analyze('恶臭监测与嗅辨评价')
    assert r.domain == 'D2'
    assert 'air-monitoring' in r.skill_ids


def test_domain_regression_d1_d6_unchanged() -> None:
    """兼容性：D1-D6 编号与语义不变。"""
    assert IntentRouter().analyze('水质监测报告').domain == 'D1'
    assert IntentRouter().analyze('大气废气监测').domain == 'D2'
    assert IntentRouter().analyze('噪声敏感点评价').domain == 'D3'
    assert IntentRouter().analyze('土壤污染状况调查').domain == 'D4'
    assert IntentRouter().analyze('CMA 质控内审').domain == 'D6'
