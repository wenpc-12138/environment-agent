# -*- coding: utf-8 -*-
"""P3 审核-重写闭环：report_rewrite 规则重写 / LLM 回调 / 复审闭环 / 计算验证。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import report_rewrite as rr
from src.review.engine import ReviewEngine, ReviewFeedback, ReviewIssue


def _issue(**kw):
    base = {"severity": "P1", "type": "", "description": "", "suggested_fix": "",
            "auto_fixable": False, "location": "", "row_id": ""}
    base.update(kw)
    return ReviewIssue(**base)


def _sec(name, content):
    return SimpleNamespace(name=name, content=content)


class TestRuleRewrite:
    def test_unit_consistency(self):
        text, notes = rr.rule_rewrite_section(
            "监测结果：COD 35 mgL，氨氮 2.1 mgL",
            [_issue(type="unit_inconsistent", description='浓度单位写法不一致："mgL" 应为 "mg/L"',
                    suggested_fix="统一为 mg/L", auto_fixable=True)])
        assert "mg/L" in text and "mgL" not in text
        assert any("单位统一" in n for n in notes)

    def test_significant_figure(self):
        text, notes = rr.rule_rewrite_section(
            "数据按保留2位小数报出：1.234、5.678",
            [_issue(type="significant_figure", severity="P2",
                    description="数据 1.234 小数位 3 超过声明精度 2 位",
                    suggested_fix="按 2 位小数修约", location="监测结果")])
        assert "1.23" in text and "5.68" in text
        assert any("修约" in n for n in notes)

    def test_standard_invalid_mark(self):
        text, notes = rr.rule_rewrite_section(
            "执行标准：GB 3838-2002",
            [_issue(type="standard_invalid", severity="P1",
                    description="引用的标准已废止：GB 3838-2002（已废止）",
                    suggested_fix="替换为现行有效版本", row_id="GB 3838-2002")])
        assert "已废止" in text
        assert any("待替换" in n for n in notes)

    def test_hallucination_kept(self):
        text, notes = rr.rule_rewrite_section(
            "结论：本项目对周边环境影响很小。",
            [_issue(type="hallucination", severity="P1",
                    description="断言无知识库支撑（疑似幻觉）：本项目对周边环境影响很小")])
        assert text == "结论：本项目对周边环境影响很小。"
        assert any("待人工复核" in n for n in notes)


class TestRewriteLoop:
    def test_pass_after_rewrite(self):
        secs = [_sec("results", "浓度 mgL 超标")]
        calls = {"n": 0}

        def review_fn(text):
            calls["n"] += 1
            if calls["n"] == 1:
                return ReviewFeedback(summary="发现 P1",
                                      issues=[_issue(type="unit_inconsistent",
                                                     description='写法不一致："mgL" 应为 "mg/L"',
                                                     suggested_fix="统一为 mg/L", auto_fixable=True,
                                                     location="监测结果")])
            return ReviewFeedback(summary="未发现问题，通过审核", issues=[])

        res = rr.rewrite_loop(secs, review_fn)
        assert res["passed"] is True
        assert res["rounds"] == 1
        assert "mg/L" in secs[0].content
        assert res["rewrites"]

    def test_max_rounds_no_pass(self):
        secs = [_sec("results", "内容")]

        def review_fn(text):
            return ReviewFeedback(summary="持续 P1",
                                  issues=[_issue(type="hallucination", severity="P1",
                                                 description="断言无知识库支撑（疑似幻觉）：某断言文本")])

        res = rr.rewrite_loop(secs, review_fn, max_rounds=3)
        assert res["passed"] is False
        assert res["rounds"] == 3
        assert res["remaining"]

    def test_llm_caller_used(self):
        secs = [_sec("results", "原文内容")]
        calls = {"llm": 0}

        def review_fn(text):
            return ReviewFeedback(summary="P1", issues=[
                _issue(type="hallucination", severity="P1", description="断言无支撑：原文内容")])

        def caller(messages):
            calls["llm"] += 1
            return "修订后的内容"

        res = rr.rewrite_loop(secs, review_fn, caller=caller, max_rounds=2)
        # LLM 返回后内容变化；但复审仍 hard → 终止；确认 caller 被调用
        assert calls["llm"] >= 1
        assert res["rounds"] >= 1


class TestCalcVerify:
    def test_ok(self):
        res = rr.calc_verify("单项污染指数：Pi = 0.35/0.35 = 1.0")
        assert res["checked"] >= 1
        assert res["ok"] is True

    def test_error_detected(self):
        res = rr.calc_verify("Pi = 1.0/0.5 = 3.0")  # 实际应为 2.0
        assert res["ok"] is False
        assert res["errors"]


class TestOrchestratorIntegration:
    def test_rewrite_step_appears(self, monkeypatch):
        from src.review.engine import ReviewEngine as RE
        calls = {"n": 0}

        def fake_review(self, report):
            calls["n"] += 1
            if calls["n"] == 1:
                return ReviewFeedback(summary="发现 P1", issues=[
                    _issue(type="unit_inconsistent", severity="P1",
                           description='写法不一致："mgL" 应为 "mg/L"',
                           suggested_fix="统一为 mg/L", auto_fixable=True, location="监测结果")])
            return ReviewFeedback(summary="未发现问题，通过审核", issues=[])

        monkeypatch.setattr(RE, "review", fake_review)
        import report_orchestrator as orch
        res = orch.run("帮我做一份监测报告", project_id="P-T", task_id=None)
        actions = [s.get("action", "") for s in res["steps"]]
        assert any("重写" in a for a in actions)
        assert calls["n"] >= 2  # 初审 + 复审
