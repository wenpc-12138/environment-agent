# -*- coding: utf-8 -*-
"""P5 文档学习管线：章节解析 / 数据要求提炼 / 模式归纳 / R4 集成。"""
from __future__ import annotations

import pytest

import report_learning as rl

SAMPLE = """# 某污水处理厂监测报告

## 项目概况
项目名称：某污水处理厂提标改造工程
委托方：某某环保科技有限公司

## 监测点位
1# 进水口、2# 出水口，共 2 个监测点

## 监测结果
| 点位 | 项目 | 结果 | 限值 | 判定 |
|------|------|------|------|------|
| 1# | COD | 35 mg/L | 40 mg/L | 达标 |

执行标准：GB 18918-2002

## 结论与建议
各项目均达标，建议加强日常运维。
"""


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "DATA_FILE", str(tmp_path / "rl.json"))


class TestExtractSections:
    def test_markdown_and_numbered(self):
        text = ("## 项目概况\n内容\n"
                "## 监测点位\n点位内容\n"
                "1. 监测结果\n结果内容\n"
                "2.1 结论\n结论内容")
        secs = rl.extract_sections(text)
        names = [s["name"] for s in secs]
        assert "项目概况" in names and "监测点位" in names
        assert "监测结果" in names and "结论" in names

    def test_content_attached(self):
        secs = rl.extract_sections(SAMPLE)
        proj = next(s for s in secs if s["name"] == "项目概况")
        assert "某污水处理厂" in proj["content"]

    def test_skip_toc(self):
        secs = rl.extract_sections("## 目录\n...\n## 正文\nx")
        assert not any(s["name"] == "目录" for s in secs)


class TestExtractDataReqs:
    def test_sample(self):
        secs = rl.extract_sections(SAMPLE)
        reqs = {s["name"]: rl.extract_data_reqs(s["content"]) for s in secs}
        assert reqs["监测结果"]["has_table"] == 1
        assert reqs["监测结果"]["has_data"] >= 1
        assert reqs["监测结果"]["has_standard"] == 1
        assert reqs["监测点位"]["has_points"] >= 1


class TestLearnPattern:
    def test_learn_accumulates(self):
        r1 = rl.learn("monitoring", SAMPLE, source="样本A")
        r2 = rl.learn("monitoring", SAMPLE.replace("进水口", "排放口"), source="样本B")
        assert r1["samples"] == 1 and r2["samples"] == 2
        pat = rl.pattern("monitoring")
        assert pat["source_count"] == 2
        proj = next(s for s in pat["sections"] if s["name"] == "项目概况")
        assert proj["hits"] == 2
        pts = next(s for s in pat["sections"] if s["name"] == "监测点位")
        assert 50 <= pts["data_reqs"]["has_points"] <= 100

    def test_pattern_empty(self):
        pat = rl.pattern("eia")
        assert pat["sections"] == [] and pat["source_count"] == 0


class TestGuideAndExtras:
    def test_extra_sections(self):
        rl.learn("monitoring", SAMPLE)
        pat = rl.pattern("monitoring")
        extras = rl.extra_sections(pat)
        names = [e["name"] for e in extras]
        assert "项目概况" not in names and "监测点位" not in names
        assert "结论" not in names

    def test_render_guide(self):
        rl.learn("monitoring", SAMPLE)
        text = rl.render_guide(rl.pattern("monitoring"))
        assert "文档学习" in text and "项目概况" in text

    def test_apply_learned(self):
        rl.learn("monitoring", SAMPLE)
        learned = rl.apply_learned(rl.pattern("monitoring"))
        assert "data" in learned["learned_reqs"] or "standard" in learned["learned_reqs"]


class TestOrchestratorIntegration:
    def test_learned_step_appears(self):
        rl.learn("monitoring", SAMPLE)
        import report_orchestrator as orch
        res = orch.run("帮我做一份监测报告", project_id="P-L", task_id=None)
        actions = [s.get("action", "") for s in res["steps"]]
        assert any("文档学习" in a for a in actions)
        step = next(s for s in res["steps"] if "文档学习" in s.get("action", ""))
        assert step["learned"]["sections"] >= 1
        # 学习章节已附加到报告
        assert any(s.name.startswith("learned_") for s in res["report_sections"])

    def test_no_learned_no_step(self):
        import report_orchestrator as orch
        res = orch.run("帮我做一份监测报告", project_id="P-L2", task_id=None)
        actions = [s.get("action", "") for s in res["steps"]]
        assert not any("文档学习" in a for a in actions)
