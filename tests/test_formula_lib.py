# -*- coding: utf-8 -*-
"""公式库测试：P4 扩展的不确定度/环境监测/环评计算公式计算正确性。"""
from __future__ import annotations

import math

import pytest

from src.compute.engine import FormulaEngine


def _val(r: dict) -> float:
    return float(r["value"])


class TestFormulaLibrary:
    def test_formula_count(self):
        eng = FormulaEngine()
        assert len(eng.formulas) >= 22

    def test_formulas_ids_unique(self):
        eng = FormulaEngine()
        ids = [f["id"] for f in eng.formulas]
        assert len(ids) == len(set(ids))


class TestUncertainty:
    def test_std_uncertainty_a(self):
        r = FormulaEngine().calc("通用", "不确定度",
                                 {"s": {"value": 0.5, "unit": ""}, "n": {"value": 4, "unit": ""}})
        assert math.isclose(_val(r), 0.25, abs_tol=1e-9)

    def test_combined_uncertainty(self):
        r = FormulaEngine().calc("通用", "不确定度", {"ui": [3, 4]})
        assert math.isclose(_val(r), 5.0, abs_tol=1e-9)

    def test_expanded_uncertainty(self):
        r = FormulaEngine().calc("通用", "不确定度",
                                 {"uc": {"value": 5, "unit": ""}, "k": {"value": 2, "unit": ""}})
        assert math.isclose(_val(r), 10.0, abs_tol=1e-9)

    def test_relative_uncertainty(self):
        r = FormulaEngine().calc("通用", "不确定度",
                                 {"u": {"value": 0.2, "unit": ""}, "x": {"value": 10, "unit": ""}})
        assert math.isclose(_val(r), 2.0, abs_tol=1e-9)


class TestMonitoring:
    def test_spike_recovery(self):
        r = FormulaEngine().calc("通用", "回收率", {
            "C1": {"value": 0.55, "unit": "mg/L"},
            "C0": {"value": 0.30, "unit": "mg/L"},
            "Cs": {"value": 0.25, "unit": "mg/L"},
        })
        assert math.isclose(_val(r), 100.0, abs_tol=1e-6)

    def test_sample_stddev(self):
        r = FormulaEngine().calc("通用", "精密度", {"xi": [1, 2, 3, 4, 5]})
        assert math.isclose(_val(r), math.sqrt(2.5), abs_tol=1e-4)  # 引擎输出保留 6 位

    def test_rsd(self):
        r = FormulaEngine().calc("通用", "精密度",
                                 {"s": {"value": 0.5, "unit": ""}, "xbar": {"value": 10, "unit": ""}})
        assert math.isclose(_val(r), 5.0, abs_tol=1e-9)

    def test_relative_deviation(self):
        r = FormulaEngine().calc("通用", "精密度",
                                 {"x1": {"value": 10, "unit": ""}, "x2": {"value": 12, "unit": ""}})
        assert math.isclose(_val(r), abs(10 - 12) / 11 * 100, abs_tol=1e-6)

    def test_mdl(self):
        r = FormulaEngine().calc("通用", "检出限",
                                 {"t": {"value": 3.143, "unit": ""}, "s": {"value": 0.5, "unit": ""}})
        assert math.isclose(_val(r), 1.5715, abs_tol=1e-6)

    def test_removal_efficiency(self):
        r = FormulaEngine().calc("通用", "去除率",
                                 {"Cin": {"value": 100, "unit": "mg/L"},
                                  "Cout": {"value": 10, "unit": "mg/L"}})
        assert math.isclose(_val(r), 90.0, abs_tol=1e-9)

    def test_flue_gas_corrected(self):
        r = FormulaEngine().calc("通用", "折算浓度", {
            "Cp": {"value": 80, "unit": "mg/m3"},
            "alphas": {"value": 1.8, "unit": ""},
            "alpha": {"value": 1.5, "unit": ""},
        })
        assert math.isclose(_val(r), 96.0, abs_tol=1e-9)


class TestEIA:
    def test_noise_distance(self):
        r = FormulaEngine().calc("通用", "噪声预测", {
            "Lp1": {"value": 80, "unit": ""},
            "r1": {"value": 10, "unit": "m"},
            "r2": {"value": 100, "unit": "m"},
        })
        assert math.isclose(_val(r), 60.0, abs_tol=1e-9)

    def test_leq(self):
        r = FormulaEngine().calc("通用", "噪声", {"Li": [60, 60, 60]})
        assert math.isclose(_val(r), 60.0, abs_tol=1e-6)

    def test_mixing_model(self):
        r = FormulaEngine().calc("通用", "水环境影响", {
            "Q1": {"value": 10, "unit": "m3/s"}, "C1": {"value": 5, "unit": "mg/L"},
            "Q2": {"value": 2, "unit": "m3/s"}, "C2": {"value": 50, "unit": "mg/L"},
        })
        assert math.isclose(_val(r), 12.5, abs_tol=1e-9)

    def test_pollutant_load(self):
        r = FormulaEngine().calc("通用", "排放量", {
            "C": {"value": 100, "unit": "mg/L"},
            "Q": {"value": 10, "unit": "m3/h"},
            "T": {"value": 24, "unit": "h"},
        })
        assert math.isclose(_val(r), 0.024, abs_tol=1e-9)

    def test_equivalent_load(self):
        r = FormulaEngine().calc("通用", "等标排放",
                                 {"Qi": {"value": 10, "unit": "kg/h"},
                                  "Coi": {"value": 0.1, "unit": "mg/m3"}})
        assert math.isclose(_val(r), 1e11, abs_tol=1e-3)


class TestListFilter:
    def test_filter_by_calc_type(self):
        from v2_bridge import formulas_list
        unc = formulas_list("通用", "不确定度")
        assert len(unc) == 6
        assert all(f["calc_type"] == "不确定度" for f in unc)
        mon = formulas_list("通用", "回收率")
        assert any(f["id"] == "spike-recovery" for f in mon)


# ---------------------------------------------------------------- 全领域扩展公式算例
EXT_CASES = [
    # (formula_id, calc_type, data, 期望值, 容差)
    # 水环境
    ("do-saturation", "水环境",
     {"DO": {"value": 5, "unit": "mg/L"}, "DOs": {"value": 9, "unit": "mg/L"}}, 55.5556, 1e-3),
    ("do-saturation-conc", "水环境", {"T": {"value": 20, "unit": "℃"}}, 468 / 51.6, 1e-3),
    ("river-1d-decay", "水环境影响",
     {"C0": {"value": 10, "unit": "mg/L"}, "K": {"value": 0.2, "unit": "1/d"},
      "t": {"value": 5, "unit": "d"}}, 10 * math.exp(-1), 1e-3),
    ("dilution-ratio", "水环境影响",
     {"Q1": {"value": 10, "unit": "m3/s"}, "Q2": {"value": 2, "unit": "m3/s"}}, 6.0, 1e-9),
    ("water-quality-index", "水环境", {"Pi": [1, 2, 3]}, 2.0, 1e-9),
    ("water-capacity", "水环境",
     {"Q": {"value": 10, "unit": "m3/s"}, "Cs": {"value": 40, "unit": "mg/L"},
      "C0": {"value": 10, "unit": "mg/L"}}, 300.0, 1e-6),
    ("bod-decay", "水环境影响",
     {"L0": {"value": 100, "unit": "mg/L"}, "K": {"value": 0.23, "unit": "1/d"},
      "t": {"value": 5, "unit": "d"}}, 100 * (1 - math.exp(-1.15)), 1e-3),
    ("bod-cod-ratio", "水环境",
     {"BOD": {"value": 30, "unit": "mg/L"}, "COD": {"value": 60, "unit": "mg/L"}}, 0.5, 1e-9),
    # 大气
    ("gaussian-plume", "大气预测",
     {"Q": {"value": 10, "unit": "g/s"}, "u": {"value": 3, "unit": "m/s"},
      "sy": {"value": 50, "unit": "m"}, "sz": {"value": 30, "unit": "m"},
      "H": {"value": 20, "unit": "m"}},
     10 / (math.pi * 3 * 50 * 30) * math.exp(-400 / 1800), 1e-6),
    ("plume-rise-holland", "大气预测",
     {"v": {"value": 10, "unit": "m/s"}, "d": {"value": 1, "unit": "m"},
      "u": {"value": 5, "unit": "m/s"}, "P": {"value": 1013, "unit": "hPa"},
      "Ts": {"value": 400, "unit": "K"}, "Ta": {"value": 293, "unit": "K"}},
     2 * (1.5 + 2.68e-3 * 1013 * 107 / 400), 1e-3),
    ("standard-gas-flow", "折算浓度",
     {"Q": {"value": 10000, "unit": "m3/h"}, "t": {"value": 150, "unit": "℃"},
      "Pa": {"value": 101.325, "unit": "kPa"}},
     10000 * (273 / 423), 1e-2),
    ("excess-air-ratio", "折算浓度", {"O2": {"value": 10, "unit": "%"}}, 21 / 11, 1e-6),
    ("baseline-o2", "折算浓度",
     {"Cp": {"value": 80, "unit": "mg/m3"}, "O2b": {"value": 6, "unit": "%"},
      "O2": {"value": 15, "unit": "%"}}, 200.0, 1e-6),
    ("stokes-settling", "大气预测",
     {"d": {"value": 1e-5, "unit": "m"}, "rp": {"value": 2000, "unit": "kg/m3"},
      "ra": {"value": 1.2, "unit": "kg/m3"}, "mu": {"value": 1.8e-5, "unit": "Pa·s"}},
     1e-10 * 1998.8 * 9.81 / (18 * 1.8e-5), 1e-7),
    ("so2-emission", "排放量",
     {"B": {"value": 1000, "unit": "t"}, "S": {"value": 1, "unit": "%"},
      "eta": {"value": 0.9, "unit": "-"}}, 160.0, 1e-6),
    ("ventilation-rate", "大气预测",
     {"G": {"value": 1000, "unit": "mg/h"}, "Cstd": {"value": 10, "unit": "mg/m3"},
      "Cbg": {"value": 2, "unit": "mg/m3"}}, 125.0, 1e-6),
    # 噪声
    ("sound-sum", "噪声", {"Li": [60, 60]}, 10 * math.log10(2e6), 1e-6),
    ("leq", "噪声", {"Li": [60, 60]}, 60.0, 1e-6),
    ("ldn", "噪声", {"Ld": {"value": 60, "unit": "-"}, "Ln": {"value": 50, "unit": "-"}}, 60.0, 1e-6),
    ("air-absorption", "噪声",
     {"alpha": {"value": 0.005, "unit": "dB/m"}, "r": {"value": 100, "unit": "m"}}, 0.5, 1e-9),
    ("power-level", "噪声",
     {"Lp": {"value": 90, "unit": "-"}, "S": {"value": 4, "unit": "m2"}}, 96.0206, 1e-3),
    # 固废/土壤
    ("waste-moisture", "固废",
     {"m1": {"value": 50, "unit": "g"}, "m2": {"value": 30, "unit": "g"}}, 40.0, 1e-9),
    ("waste-reduction", "固废",
     {"V1": {"value": 100, "unit": "m3"}, "V2": {"value": 40, "unit": "m3"}}, 60.0, 1e-9),
    ("soil-enrichment", "土壤",
     {"Ci": {"value": 0.5, "unit": "mg/kg"}, "Cr": {"value": 0.1, "unit": "mg/kg"}}, 5.0, 1e-9),
    # 辐射
    ("dose-equivalent", "辐射",
     {"D": {"value": 1, "unit": "Gy"}, "Q": {"value": 1, "unit": "-"}}, 1.0, 1e-9),
    ("radioactive-decay", "辐射",
     {"A0": {"value": 1000, "unit": "Bq"}, "lam": {"value": 0.1, "unit": "1/d"},
      "t": {"value": 10, "unit": "d"}}, 1000 * math.exp(-1), 1e-2),
    ("half-life", "辐射", {"lam": {"value": 0.1, "unit": "1/d"}}, math.log(2) / 0.1, 1e-6),
    # 通用统计
    ("measurement-lower-limit", "检出限", {"MDL": {"value": 0.5, "unit": "-"}}, 2.0, 1e-9),
    ("relative-error", "准确度",
     {"x": {"value": 10.2, "unit": "-"}, "x0": {"value": 10, "unit": "-"}}, 2.0, 1e-9),
    ("compliance-rate", "统计",
     {"npass": {"value": 95, "unit": "-"}, "n": {"value": 100, "unit": "-"}}, 95.0, 1e-9),
    ("weighted-mean", "统计",
     {"wi": [1, 2], "xi": [10, 20]}, 16.6667, 1e-3),
    ("geometric-mean", "统计", {"xi": [2, 8]}, 4.0, 1e-9),
    ("median", "统计", {"xi": [3, 1, 2]}, 2.0, 1e-9),
    ("median", "统计", {"xi": [1, 2, 3, 4]}, 2.5, 1e-9),
    # 生态
    ("shannon-index", "生态", {"Pi": [0.5, 0.5]}, 0.693147, 1e-4),
    ("evenness-index", "生态",
     {"H": {"value": 1.5, "unit": "-"}, "S": {"value": 10, "unit": "-"}}, 1.5 / math.log(10), 1e-5),
    ("dominance-index", "生态", {"Pi": [0.5, 0.5]}, 0.5, 1e-9),
    ("vegetation-coverage", "生态",
     {"NDVI": {"value": 0.5, "unit": "-"}, "min_v": {"value": 0.2, "unit": "-"},
      "max_v": {"value": 0.8, "unit": "-"}}, 50.0, 1e-9),
    # 概率统计 / 离群值
    ("coefficient-variation", "统计",
     {"s": {"value": 0.5, "unit": "-"}, "xbar": {"value": 10, "unit": "-"}}, 5.0, 1e-9),
    ("standard-error", "统计",
     {"s": {"value": 4, "unit": "-"}, "n": {"value": 16, "unit": "-"}}, 1.0, 1e-9),
    ("ci-upper", "统计",
     {"xbar": {"value": 10, "unit": "-"}, "t": {"value": 1.96, "unit": "-"},
      "s": {"value": 4, "unit": "-"}, "n": {"value": 16, "unit": "-"}}, 11.96, 1e-6),
    ("ci-lower", "统计",
     {"xbar": {"value": 10, "unit": "-"}, "t": {"value": 1.96, "unit": "-"},
      "s": {"value": 4, "unit": "-"}, "n": {"value": 16, "unit": "-"}}, 8.04, 1e-6),
    ("z-score", "概率",
     {"x": {"value": 12, "unit": "-"}, "mu": {"value": 10, "unit": "-"},
      "sigma": {"value": 2, "unit": "-"}}, 1.0, 1e-9),
    ("normal-cdf", "概率", {"z": {"value": 1.96, "unit": "-"}}, 0.9750, 1e-4),
    ("normal-pdf", "概率",
     {"x": {"value": 0, "unit": "-"}, "mu": {"value": 0, "unit": "-"},
      "sigma": {"value": 1, "unit": "-"}}, 0.398942, 1e-5),
    ("normal-inv", "概率", {"p": {"value": 0.975, "unit": "-"}}, 1.959964, 1e-5),
    ("poisson-prob", "概率",
     {"lam": {"value": 2, "unit": "-"}, "k": {"value": 2, "unit": "-"}},
     0.2706706, 1e-6),
    ("binomial-prob", "概率",
     {"n": {"value": 5, "unit": "-"}, "k": {"value": 3, "unit": "-"},
      "p": {"value": 0.5, "unit": "-"}}, 0.3125, 1e-9),
    ("exponential-prob", "概率",
     {"lam": {"value": 0.1, "unit": "1/h"}, "x": {"value": 10, "unit": "h"}},
     0.367879, 1e-5),
    ("grubbs-stat", "离群值", {"xi": [1, 2, 3, 4, 10]}, 1.697056, 1e-4),
    ("grubbs-test", "离群值", {"xi": [1, 2, 3, 4, 12], "alpha": {"value": 0.05, "unit": "-"}}, 1.0, 1e-9),
    ("dixon-q", "离群值", {"xi": [0.1, 0.2, 0.3, 0.4, 1.0]}, 0.666667, 1e-4),
    ("dixon-test", "离群值",
     {"xi": [0.1, 0.2, 0.3, 0.4, 1.0], "qc": {"value": 0.6, "unit": "-"}}, 1.0, 1e-9),
    # 声屏障 / 统计声级 / 防护距离
    ("fresnel-number", "噪声预测",
     {"a": {"value": 3, "unit": "m"}, "b": {"value": 3, "unit": "m"},
      "d": {"value": 2, "unit": "m"}, "f": {"value": 500, "unit": "Hz"}},
     2 * 4 / (340 / 500), 1e-3),
    ("barrier-attenuation", "噪声预测", {"N": {"value": 3, "unit": "-"}},
     10 * math.log10(63), 1e-3),
    ("L10", "噪声", {"Li": [50, 55, 60, 65, 70, 75, 80, 85, 90, 95]}, 54.5, 1e-6),
    ("L50", "噪声", {"Li": [50, 55, 60, 65, 70, 75, 80, 85, 90, 95]}, 72.5, 1e-6),
    ("L90", "噪声", {"Li": [50, 55, 60, 65, 70, 75, 80, 85, 90, 95]}, 90.5, 1e-6),
    ("protection-distance", "防护距离",
     {"Qc": {"value": 5, "unit": "kg/h"}, "Cm": {"value": 0.5, "unit": "mg/m3"},
      "u": {"value": 2, "unit": "m/s"}, "k": {"value": 1, "unit": "-"}},
     5 ** (1 / 1.7), 1e-3),
    # 土壤修复风险评估
    ("soil-oral-dose", "土壤风险评估",
     {"C": {"value": 100, "unit": "mg/kg"}, "IR": {"value": 200, "unit": "mg/d"},
      "EF": {"value": 350, "unit": "d/年"}, "ED": {"value": 6, "unit": "年"},
      "BW": {"value": 15, "unit": "kg"}, "AT": {"value": 2190, "unit": "d"}},
     100 * 200 * 350 * 6 / (15 * 2190) * 1e-6, 1e-6),
    ("soil-dermal-dose", "土壤风险评估",
     {"C": {"value": 100, "unit": "mg/kg"}, "SA": {"value": 2000, "unit": "cm2"},
      "AF": {"value": 0.2, "unit": "mg/cm2"}, "EF": {"value": 350, "unit": "d/年"},
      "ED": {"value": 6, "unit": "年"}, "BW": {"value": 15, "unit": "kg"},
      "AT": {"value": 2190, "unit": "d"}},
     100 * 2000 * 0.2 * 350 * 6 / (15 * 2190) * 1e-6, 1e-6),
    ("soil-inhalation-dose", "土壤风险评估",
     {"C": {"value": 100, "unit": "mg/kg"}, "PM10": {"value": 0.2, "unit": "mg/m3"},
      "IR": {"value": 7.5, "unit": "m3/d"}, "EF": {"value": 350, "unit": "d/年"},
      "ED": {"value": 6, "unit": "年"}, "BW": {"value": 15, "unit": "kg"},
      "AT": {"value": 2190, "unit": "d"}, "PEF": {"value": 1.36e9, "unit": "m3/kg"}},
     100 * 0.2 * 7.5 * 350 * 6 / (15 * 2190 * 1.36e9), 1e-12),
    ("carcinogenic-risk", "土壤风险评估",
     {"LADD": {"value": 0.001, "unit": "mg/(kg·d)"}, "SF": {"value": 0.1, "unit": "kg·d/mg"}},
     1e-4, 1e-9),
    ("hazard-quotient", "土壤风险评估",
     {"ADD": {"value": 0.02, "unit": "mg/(kg·d)"}, "RfD": {"value": 0.02, "unit": "mg/(kg·d)"}},
     1.0, 1e-9),
    ("risk-cleanup-target", "土壤风险评估",
     {"TR": {"value": 1e-6, "unit": "-"}, "SF": {"value": 0.1, "unit": "kg·d/mg"},
      "IF": {"value": 0.005, "unit": "kg·d/mg"}}, 0.002, 1e-9),
    ("hazard-cleanup-target", "土壤风险评估",
     {"THQ": {"value": 1, "unit": "-"}, "RfD": {"value": 0.02, "unit": "mg/(kg·d)"},
      "IADD": {"value": 0.0001, "unit": "-"}}, 200.0, 1e-6),
    # 地下水
    ("darcy-law", "地下水",
     {"K": {"value": 10, "unit": "m/d"}, "A": {"value": 100, "unit": "m2"},
      "I": {"value": 0.01, "unit": "-"}}, 10.0, 1e-9),
    ("dispersion-1d", "地下水",
     {"C0": {"value": 100, "unit": "mg/L"}, "x": {"value": 10, "unit": "m"},
      "v": {"value": 1, "unit": "m/d"}, "DL": {"value": 10, "unit": "m2/d"},
      "t": {"value": 5, "unit": "d"}},
     100 / 2 * math.erfc(5 / (2 * math.sqrt(50))), 1e-2),
    ("theis-u", "地下水",
     {"r": {"value": 100, "unit": "m"}, "S": {"value": 0.001, "unit": "-"},
      "T": {"value": 500, "unit": "m2/d"}, "t": {"value": 1, "unit": "d"}}, 0.005, 1e-9),
    ("theis-well-function", "地下水", {"u": {"value": 0.005, "unit": "-"}}, 4.7261, 1e-3),
    ("theis-drawdown", "地下水",
     {"Q": {"value": 1000, "unit": "m3/d"}, "T": {"value": 500, "unit": "m2/d"},
      "u": {"value": 0.005, "unit": "-"}},
     1000 * 4.7261 / (4 * math.pi * 500), 1e-3),
    # 恶臭 / 生态 / 辐射
    ("odor-concentration", "恶臭", {"n": {"value": 5, "unit": "-"}}, 32.0, 1e-9),
    ("odor-dilution", "恶臭", {"xi": [10, 20, 40]}, 20.0, 1e-6),
    ("margalef-index", "生态",
     {"S": {"value": 10, "unit": "-"}, "N": {"value": 50, "unit": "-"}},
     9 / math.log(50), 1e-4),
    ("pielou-evenness", "生态",
     {"H": {"value": 1.5, "unit": "-"}, "S": {"value": 10, "unit": "-"}},
     1.5 / math.log(10), 1e-5),
    ("diversity-t", "生态",
     {"H1": {"value": 2.5, "unit": "-"}, "H2": {"value": 2.0, "unit": "-"},
      "VH1": {"value": 0.01, "unit": "-"}, "VH2": {"value": 0.01, "unit": "-"}},
     0.5 / math.sqrt(0.02), 1e-4),
    ("hvl", "辐射", {"mu": {"value": 0.693, "unit": "1/cm"}},
     math.log(2) / 0.693, 1e-6),
    ("inverse-square", "辐射",
     {"I0": {"value": 10, "unit": "uSv/h"}, "d0": {"value": 1, "unit": "m"},
      "d": {"value": 5, "unit": "m"}}, 0.4, 1e-9),
]


# 同 calc_type 内输入参数完全相同的公式（自动匹配按出现顺序取首者，无法按参数区分）
# 这类公式自动匹配通道仅断言可执行，精确性由 formula_id 通道保证（前端可下拉选择具体公式）
AMBIGUOUS_AUTO = {"median", "sound-sum", "dominance-index",
                  "ci-lower", "normal-pdf", "dixon-q",
                  "pielou-evenness", "L10", "L50", "L90"}


class TestExtendedLibrary:
    @pytest.mark.parametrize("fid,ctype,data,exp,tol", EXT_CASES,
                             ids=[c[0] for c in EXT_CASES])
    def test_extended_formula(self, fid, ctype, data, exp, tol):
        eng = FormulaEngine()
        # 通道 1：按 formula_id 精确调用，断言精确值
        r1 = eng.calc("通用", ctype, data, formula_id=fid)
        assert math.isclose(float(r1["value"]), exp, abs_tol=tol), f"{fid}: {r1}"
        # 通道 2：按 calc_type 自动匹配；同输入歧义公式仅断言可执行
        r2 = eng.calc("通用", ctype, data)
        if fid in AMBIGUOUS_AUTO:
            assert r2.get("ok") is True
        else:
            assert math.isclose(float(r2["value"]), exp, abs_tol=tol), f"{fid} 自动匹配: {r2}"

    def test_total_count(self):
        eng = FormulaEngine()
        assert len(eng.formulas) >= 97

    def test_all_findable(self):
        eng = FormulaEngine()
        for f in eng.formulas:
            assert eng.find("通用", f["calc_type"]), f"不可达: {f['id']}"


class TestAdvancedFormulas:
    """声屏障双峰细算 / 非稳定流数值解 / 蒙特卡洛不确定度传播。"""

    def test_kurze_anderson(self):
        r = FormulaEngine().calc("通用", "噪声预测", {"N": {"value": 3, "unit": "-"}},
                                 formula_id="kurze-anderson-il")
        assert math.isclose(float(r["value"]), 10 * math.log10(60), abs_tol=1e-6)

    def test_barrier_refined_cap(self):
        eng = FormulaEngine()
        # N=100 时 10lg(2000)=33 超过 cap=24，取上限（双峰效应修正）
        r = eng.calc("通用", "噪声预测",
                     {"N": {"value": 100, "unit": "-"}, "cap": {"value": 24, "unit": "dB"}},
                     formula_id="barrier-il-refined")
        assert math.isclose(float(r["value"]), 24.0, abs_tol=1e-9)
        # N=3 时 17.78 < cap，正常计算
        r2 = eng.calc("通用", "噪声预测",
                      {"N": {"value": 3, "unit": "-"}, "cap": {"value": 24, "unit": "dB"}},
                      formula_id="barrier-il-refined")
        assert math.isclose(float(r2["value"]), 10 * math.log10(60), abs_tol=1e-6)

    def test_gw_explicit_uniform(self):
        # 无梯度初始水头：稳态不变
        H0 = [10.0] * 11
        r = FormulaEngine().calc("通用", "地下水",
                                 {"H0": H0, "T": {"value": 50, "unit": "m2/d"},
                                  "S": {"value": 0.01, "unit": "-"},
                                  "L": {"value": 100, "unit": "m"},
                                  "t_total": {"value": 0.5, "unit": "d"},
                                  "nx": {"value": 11, "unit": "-"},
                                  "nt": {"value": 500, "unit": "-"}},
                                 formula_id="groundwater-nonsteady")
        assert math.isclose(float(r["value"]), 10.0, abs_tol=1e-6)

    def test_gw_explicit_linear(self):
        # 线性水头剖面 10 -> 5，边界固定，中点向稳态 7.5 演化（r=0.2 稳定）
        H0 = [10 - 0.25 * i for i in range(21)]  # 10..5
        r = FormulaEngine().calc("通用", "地下水",
                                 {"H0": H0, "T": {"value": 50, "unit": "m2/d"},
                                  "S": {"value": 0.01, "unit": "-"},
                                  "L": {"value": 100, "unit": "m"},
                                  "t_total": {"value": 0.5, "unit": "d"},
                                  "nx": {"value": 21, "unit": "-"},
                                  "nt": {"value": 500, "unit": "-"}},
                                 formula_id="groundwater-nonsteady")
        assert 6.5 < float(r["value"]) < 9.0

    def test_monte_carlo_range(self):
        # a*b，a=10±0.1、b=2±0.05：mean≈20，u95≈2*0.5385≈1.077
        r = FormulaEngine().calc("通用", "不确定度", {
            "expr": "a * b",
            "params": {"a": [10, 0.1], "b": [2, 0.05]},
            "n": {"value": 20000, "unit": "-"},
            "k": {"value": 2, "unit": "-"},
        }, formula_id="monte-carlo")
        v = r["value"]
        assert 19.5 < v["mean"] < 20.5
        assert 0.95 < v["u95"] < 1.20
        assert v["n"] == 20000

    def test_monte_carlo_reproducible(self):
        eng = FormulaEngine()
        d1 = {"expr": "a + b", "params": {"a": [5, 0.2], "b": [3, 0.1]},
              "n": {"value": 5000, "unit": "-"}, "k": {"value": 2, "unit": "-"}}
        r1 = eng.calc("通用", "不确定度", d1, formula_id="monte-carlo")
        r2 = eng.calc("通用", "不确定度", d1, formula_id="monte-carlo")
        assert r1["value"] == r2["value"]  # 固定 seed 可复现


class TestImplicitAdiSensitivity:
    """隐式差分 / 二维 ADI / MC 多分布 / 灵敏度分析。"""

    # ---- 隐式格式（无条件稳定） ----
    def test_implicit_uniform(self):
        H0 = [10.0] * 11
        r = FormulaEngine().calc("通用", "地下水",
                                 {"H0": H0, "T": {"value": 50, "unit": "m2/d"},
                                  "S": {"value": 0.01, "unit": "-"},
                                  "L": {"value": 100, "unit": "m"},
                                  "t_total": {"value": 0.5, "unit": "d"},
                                  "nx": {"value": 11, "unit": "-"},
                                  "nt": {"value": 500, "unit": "-"}},
                                 formula_id="groundwater-implicit")
        assert math.isclose(float(r["value"]), 10.0, abs_tol=1e-6)

    def test_implicit_stable_large_r(self):
        # r = 10000*0.05/25 = 20 >> 0.5：显式格式会振荡，隐式仍稳定收敛
        H0 = [10.0] * 21
        r = FormulaEngine().calc("通用", "地下水",
                                 {"H0": H0, "T": {"value": 100, "unit": "m2/d"},
                                  "S": {"value": 0.01, "unit": "-"},
                                  "L": {"value": 100, "unit": "m"},
                                  "t_total": {"value": 0.5, "unit": "d"},
                                  "nx": {"value": 21, "unit": "-"},
                                  "nt": {"value": 10, "unit": "-"}},
                                 formula_id="groundwater-implicit")
        assert math.isclose(float(r["value"]), 10.0, abs_tol=1e-3)

    def test_implicit_linear_converges(self):
        H0 = [10 - 0.25 * i for i in range(21)]  # 10..5
        r = FormulaEngine().calc("通用", "地下水",
                                 {"H0": H0, "T": {"value": 50, "unit": "m2/d"},
                                  "S": {"value": 0.01, "unit": "-"},
                                  "L": {"value": 100, "unit": "m"},
                                  "t_total": {"value": 0.5, "unit": "d"},
                                  "nx": {"value": 21, "unit": "-"},
                                  "nt": {"value": 500, "unit": "-"}},
                                 formula_id="groundwater-implicit")
        assert 6.5 < float(r["value"]) < 9.0

    # ---- 二维 ADI ----
    def test_adi_uniform(self):
        H0 = [[10.0] * 11 for _ in range(11)]
        r = FormulaEngine().calc("通用", "地下水",
                                 {"H0": H0, "Tx": {"value": 50, "unit": "m2/d"},
                                  "Ty": {"value": 50, "unit": "m2/d"},
                                  "S": {"value": 0.01, "unit": "-"},
                                  "Lx": {"value": 100, "unit": "m"},
                                  "Ly": {"value": 100, "unit": "m"},
                                  "t_total": {"value": 0.5, "unit": "d"},
                                  "nx": {"value": 11, "unit": "-"},
                                  "ny": {"value": 11, "unit": "-"},
                                  "nt": {"value": 50, "unit": "-"}},
                                 formula_id="groundwater-adi")
        assert math.isclose(float(r["value"]), 10.0, abs_tol=1e-6)

    def test_adi_linear_x(self):
        # x 向线性 10->5、y 向均匀：中点向稳态 7.5 演化
        H0 = [[10 - 0.5 * i for i in range(11)] for _ in range(11)]
        r = FormulaEngine().calc("通用", "地下水",
                                 {"H0": H0, "Tx": {"value": 50, "unit": "m2/d"},
                                  "Ty": {"value": 50, "unit": "m2/d"},
                                  "S": {"value": 0.01, "unit": "-"},
                                  "Lx": {"value": 100, "unit": "m"},
                                  "Ly": {"value": 100, "unit": "m"},
                                  "t_total": {"value": 0.5, "unit": "d"},
                                  "nx": {"value": 11, "unit": "-"},
                                  "ny": {"value": 11, "unit": "-"},
                                  "nt": {"value": 50, "unit": "-"}},
                                 formula_id="groundwater-adi")
        assert 6.5 < float(r["value"]) < 9.0

    # ---- MC 多分布 ----
    def test_mc_uniform(self):
        # a ~ U(1,3)：mean=2，sd=(3-1)/sqrt(12)=0.5774，u95≈1.1547
        r = FormulaEngine().calc("通用", "不确定度", {
            "expr": "a",
            "params": {"a": {"dist": "uniform", "low": 1, "high": 3}},
            "n": {"value": 20000, "unit": "-"},
            "k": {"value": 2, "unit": "-"},
        }, formula_id="monte-carlo")
        v = r["value"]
        assert 1.85 < v["mean"] < 2.15
        assert 1.05 < v["u95"] < 1.30

    def test_mc_triangular(self):
        # a ~ Tri(0,1,2)：mean=1，sd=sqrt(1/6)=0.4082，u95≈0.8165
        r = FormulaEngine().calc("通用", "不确定度", {
            "expr": "a",
            "params": {"a": {"dist": "triangular", "low": 0, "mode": 1, "high": 2}},
            "n": {"value": 20000, "unit": "-"},
            "k": {"value": 2, "unit": "-"},
        }, formula_id="monte-carlo")
        v = r["value"]
        assert 0.92 < v["mean"] < 1.08
        assert 0.70 < v["u95"] < 0.95

    # ---- 灵敏度分析 ----
    def test_sensitivity_product(self):
        # f = a*b：dc_a = b = 2，dc_b = a = 10；贡献率 b > a
        r = FormulaEngine().calc("通用", "不确定度", {
            "expr": "a * b",
            "params": {"a": [10, 0.1], "b": [2, 0.05]},
            "n": {"value": 5000, "unit": "-"},
            "k": {"value": 2, "unit": "-"},
        }, formula_id="mc-sensitivity")
        v = r["value"]
        sens = v["sensitivity"]
        assert 1.8 < sens["a"]["dc"] < 2.2
        assert 9.0 < sens["b"]["dc"] < 11.0
        assert math.isclose(v["base"], 20.0, abs_tol=1e-6)
        assert sens["b"]["contrib_pct"] > sens["a"]["contrib_pct"]

    def test_sensitivity_reproducible(self):
        eng = FormulaEngine()
        d = {"expr": "a / b", "params": {"a": [10, 0.2], "b": [2, 0.1]},
             "n": {"value": 3000, "unit": "-"}, "k": {"value": 2, "unit": "-"}}
        r1 = eng.calc("通用", "不确定度", d, formula_id="mc-sensitivity")
        r2 = eng.calc("通用", "不确定度", d, formula_id="mc-sensitivity")
        assert r1["value"] == r2["value"]


class TestGrubbsTable:
    """GB/T 4883-2008 Grubbs 临界值表内置正确性。"""

    def test_table_values(self):
        from src.compute.engine import gb4883_grubbs
        assert gb4883_grubbs(3, 0.05) == 1.155
        assert gb4883_grubbs(5, 0.05) == 1.715
        assert gb4883_grubbs(7, 0.01) == 2.139
        assert gb4883_grubbs(10, 0.01) == 2.482
        assert gb4883_grubbs(30, 0.05) == 2.908
        assert gb4883_grubbs(30, 0.01) == 3.236

    def test_out_of_range(self):
        from src.compute.engine import gb4883_grubbs
        assert gb4883_grubbs(2, 0.05) is None
        assert gb4883_grubbs(100, 0.05) is None

    def test_grubbs_test_detects_outlier(self):
        from src.compute.engine import grubbs_stat
        # 10.2 明显离群：G 应超过 n=10 的 0.05 临界值 2.290
        xi = [4.1, 4.2, 4.1, 4.3, 4.2, 4.1, 4.3, 4.2, 4.1, 10.2]
        assert grubbs_stat(xi) > 2.290
