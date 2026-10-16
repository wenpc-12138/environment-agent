# -*- coding: utf-8 -*-
"""P4 报告流水线集成计算：report_calc 计算填充 + FormulaEngine 验证。"""
from __future__ import annotations

from types import SimpleNamespace

import report_calc as rc
from src.report.generator import ReportGenerator

ROW_OK = {"point": "1# 进水口", "item": "COD", "value": "35", "unit": "mg/L", "limit": "40"}
ROW_OVER = {"point": "1# 进水口", "item": "氨氮", "value": "2.1", "unit": "mg/L", "limit": "1.0"}
ROW_NO_LIMIT = {"point": "2# 出水口", "item": "pH", "value": "7.2", "unit": "", "limit": ""}


class TestComputeRow:
    def test_comply(self):
        r = rc.compute_row(ROW_OK)
        assert r["pi"] is not None and r["pi"] <= 1.0
        assert r["pass"] == 1

    def test_exceed(self):
        r = rc.compute_row(ROW_OVER)
        assert r["pi"] == 2.1
        assert r["multiple"] == 1.1
        assert r["pass"] == 0

    def test_no_limit(self):
        r = rc.compute_row(ROW_NO_LIMIT)
        assert r["pi"] is None and r["pass"] is None


class TestComputeAll:
    def test_summary(self):
        res = rc.compute_all([ROW_OK, ROW_OVER])
        assert res["summary"]["n"] == 2
        assert res["summary"]["exceeded"] == 1
        assert res["summary"]["mean"] is not None
        assert res["summary"]["nemean"] is not None
        assert "std-index-single" in res["used_formulas"]

    def test_no_data(self):
        res = rc.compute_all([])
        assert res["summary"]["n"] == 0


class TestCalcFill:
    def _sec(self, name, content):
        return SimpleNamespace(name=name, content=content)

    def test_fill_results_with_pi(self):
        sections = [
            self._sec("results", "待填写"),
            self._sec("conclusion", "结论：待填写（数据缺失）。"),
        ]
        res = rc.calc_fill(sections, [ROW_OK, ROW_OVER])
        assert res["filled"] == 2
        results = sections[0].content
        assert "| 指数 |" in results          # 指数列已加
        assert "35 mg/L" in results
        assert "2.10" in results or "2.1" in results  # 氨氮 pi=2.1
        assert "超标" in results


class TestGeneratorResultsPi:
    def test_pi_column(self):
        rows = [{**ROW_OVER, "value": "2.1", "pi": 2.1}]
        out = ReportGenerator._results({}, rows)
        assert "指数" in out and "2.10" in out


class TestVerifyCalcs:
    def test_ok_when_consistent(self):
        text = "监测结果：COD 35 mg/L（达标）\n结论：氨氮 2.1 mg/L 超标 1.1 倍"
        res = rc.verify_calcs(text, data_rows=[ROW_OK, ROW_OVER])
        assert res["ok"] is True

    def test_error_undeclared_exceed(self):
        # 数据超标但文本无"超标"声明
        text = "监测结果：氨氮 2.1 mg/L（达标）"
        res = rc.verify_calcs(text, data_rows=[ROW_OVER])
        assert res["ok"] is False
        assert any("超标" in e for e in res["errors"])

    def test_error_false_exceed(self):
        # 文本声明超标但重算均达标
        text = "监测结果：COD 35 mg/L（超标）"
        res = rc.verify_calcs(text, data_rows=[ROW_OK])
        assert res["ok"] is False

    def test_nemean_declaration(self):
        text = "综合污染指数为 5.00"
        res = rc.verify_calcs(text, data_rows=[ROW_OVER, ROW_OVER])
        # 两个 pi=2.1 的内梅罗指数不等于 5.00 → 应报错
        assert res["ok"] is False


class TestOrchestratorIntegration:
    def test_p4_steps(self):
        import report_orchestrator as orch
        materials = {"data_rows": [ROW_OK, ROW_OVER]}
        res = orch.run("帮我做一份监测报告", project_id="P-T", task_id=None, materials=materials)
        actions = [s.get("action", "") for s in res["steps"]]
        assert any("计算" in a for a in actions)          # R4 计算填充
        assert any("计算验证" in a for a in actions)      # R5 计算验证
        calc_step = next(s for s in res["steps"] if "自动计算" in s.get("action", ""))
        assert "超标 1 项" in calc_step["summary"]
        # 计算验证已并入 R5 初审（action 含"计算验证"），数据一致时不应产生 calc_verify 问题
        first = next(s for s in res["steps"] if "计算验证" in s.get("action", ""))
        assert not any(i.get("type") == "calc_verify" for i in first.get("issues", []))
