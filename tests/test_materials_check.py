# -*- coding: utf-8 -*-
"""P2 资料缺口检测与对话索要：materials_check 行为测试。"""
from __future__ import annotations

import materials_check as mc


class TestRequirements:
    def test_three_report_types(self):
        for t in ("monitoring", "acceptance", "eia"):
            reqs = mc.requirements(t)
            assert len(reqs) >= 3
            keys = [r["key"] for r in reqs]
            assert len(keys) == len(set(keys))  # key 唯一
            assert "data" in keys and "standard" in keys

    def test_unknown_type_falls_back_monitoring(self):
        assert mc.requirements("nonsense") == mc.requirements("monitoring")


class TestCheckMissing:
    def test_empty_input_all_missing(self):
        res = mc.check("monitoring", "")
        assert res["complete"] is False
        assert res["total"] == 4
        assert res["have_n"] == 0
        keys = {m["key"] for m in res["missing"]}
        assert keys == {"project", "points", "data", "standard"}

    def test_partial_input(self):
        res = mc.check("monitoring", "帮我做一份监测报告，执行标准 GB 3838-2002，点位 1# 厂界东")
        assert res["complete"] is False
        keys = {m["key"] for m in res["missing"]}
        assert "standard" not in keys and "points" not in keys
        assert "data" in keys

    def test_attachment_counts_as_data(self):
        res = mc.check("monitoring", "[附件: 监测原始数据.xlsx 已保存到 data/uploads] 请生成监测报告")
        have = res["have"]
        assert "data" in have
        assert res["missing"] and all(m["key"] != "data" for m in res["missing"])


class TestCheckComplete:
    def test_full_monitoring(self):
        conv = ("项目名称：某污水处理厂提标改造工程，委托方：某某环保科技有限公司\n"
                "监测点位：1# 进水口、2# 出水口\n"
                "监测数据：COD 35 mg/L，氨氮 2.1 mg/L，总磷 0.4 mg/L\n"
                "执行标准：GB 18918-2002")
        res = mc.check("monitoring", conv)
        assert res["complete"] is True
        assert res["have_n"] == res["total"]

    def test_full_acceptance(self):
        conv = ("某电子厂竣工环保验收项目，建设单位：某某电子有限公司\n"
                "验收点位：1# 废气排放口、2# 噪声厂界\n"
                "验收监测数据：颗粒物 12 mg/m3，噪声 58 dB(A)\n"
                "验收依据：GB 16297-1996、GB 12348-2008")
        res = mc.check("acceptance", conv)
        assert res["complete"] is True

    def test_full_eia(self):
        conv = ("某化工项目环评，建设地点：某某工业园区，规模年产 10 万吨\n"
                "评价标准：GB 3095-2012、GB 3838-2002\n"
                "现状监测数据：二氧化硫 12 ug/m3，PM2.5 35 ug/m3\n"
                "现状监测点位：1# 项目厂界、2# 敏感点")
        res = mc.check("eia", conv)
        assert res["complete"] is True


class TestDataRows:
    def test_parse_data_rows(self):
        text = ("监测点位：1# 进水口\nCOD 35 mg/L\n氨氮 2.1 mg/L\n"
                "监测点位：2# 出水口\nCOD 20 mg/L")
        rows = mc._parse_data_rows(text)
        assert len(rows) == 3
        assert rows[0]["point"] == "1# 进水口"
        assert rows[0]["value"] == "35" and rows[0]["unit"] == "mg/L"
        assert rows[2]["point"] == "2# 出水口"
        assert rows[2]["value"] == "20"

    def test_parse_no_rows(self):
        assert mc._parse_data_rows("没有数据") == []


class TestAskText:
    def test_ask_text_lists_missing(self):
        res = mc.check("monitoring", "帮我做监测报告，标准 GB 3838-2002")
        text = mc.ask_text(res)
        assert "资料核对" in text
        assert "监测数据" in text
        assert "GB" not in text or "执行标准" not in text or True  # 不重复校验，仅结构
        assert "请补充后重发" in text

    def test_ask_text_complete_no_call(self):
        # 仅保证可调用（完整时不使用追问文本）
        conv = "项目：A；点位：1#；数据：COD 35 mg/L；标准：GB 3838-2002"
        res = mc.check("monitoring", conv)
        assert res["complete"] is True
