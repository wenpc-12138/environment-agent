# -*- coding: utf-8 -*-
"""P4 报告流水线集成计算。

R4 编制：按引用标准自动取公式计算（单项污染指数/超标倍数/达标判定/算术均值/
内梅罗综合指数），计算结果随数据行填充结果章节（消除"待填写"）；
R5 审核：用 FormulaEngine 重算并核对报告声明（达标判定/指数一致性），
不一致记审核发现，供 P3 重写或人工处理。
"""
from __future__ import annotations

import re
from typing import Any

from src.compute.engine import FormulaEngine

# 计算类型标签（对齐 formulas.json）
T_POLLUTION = "污染指数"       # 单项污染指数 Pi = Ci/Si
T_EXCEED = "超标倍数"          # K = Ci/Si - 1
T_COMPLIANCE = "达标判定"      # 1 达标 / 0 超标
T_MEAN = "均值"                # 算术均值
T_NEMEAN = "综合污染指数"      # 内梅罗综合污染指数


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compute_row(row: dict[str, Any], engine: FormulaEngine | None = None) -> dict[str, Any]:
    """对单个监测数据行计算：单项污染指数 Pi / 超标倍数 / 达标判定。

    row：{point, item, value, unit, limit}；返回增强行（新增 pi/multiple/pass，异常置 None）。
    """
    engine = engine or FormulaEngine()
    value = _num(row.get("value"))
    limit = _num(row.get("limit"))
    if value is None or limit is None or limit <= 0:
        return {**row, "pi": None, "multiple": None, "pass": None}
    unit = row.get("unit") or ""
    try:
        r = engine.calc("GB 3838-2002", T_POLLUTION, {
            "Ci": {"value": value, "unit": unit},
            "Si": {"value": limit, "unit": unit or "mg/L"},
        })
        pi = float(r["value"])
    except Exception:
        pi = value / limit
    return {
        **row,
        "pi": round(pi, 4),
        "multiple": round(pi - 1, 4),
        "pass": 1 if pi <= 1.0 else 0,
    }


def compute_all(data_rows: list[dict[str, Any]],
                engine: FormulaEngine | None = None) -> dict[str, Any]:
    """批量计算并汇总（均值/内梅罗综合指数），返回 {rows, summary, used_formulas}。"""
    engine = engine or FormulaEngine()
    rows = [compute_row(r, engine) for r in data_rows]
    used: list[str] = []
    summary: dict[str, Any] = {"n": len(rows), "exceeded": 0}
    pis = [r["pi"] for r in rows if r.get("pi") is not None]
    if pis:
        summary["exceeded"] = sum(1 for p in pis if p > 1.0)
        # 算术均值（用各实测值）
        vals = [_num(r.get("value")) for r in rows]
        vals = [v for v in vals if v is not None]
        if vals:
            try:
                m = engine.calc("通用", T_MEAN, {"Ci": vals})
                summary["mean"] = round(float(m["value"]), 4)
                used.append(m["formula_id"])
            except Exception:
                pass
        # 内梅罗综合污染指数（用单项指数序列）
        try:
            nm = engine.calc("通用", T_NEMEAN, {"Ci": pis})
            summary["nemean"] = round(float(nm["value"]), 4)
            used.append(nm["formula_id"])
        except Exception:
            pass
        if "std-index-single" not in used:
            used.append("std-index-single")
    return {"rows": rows, "summary": summary, "used_formulas": used}


def calc_fill(sections: list[Any], data_rows: list[dict[str, Any]],
              engine: FormulaEngine | None = None) -> dict[str, Any]:
    """R4：批量计算后用增强行填充结果章节（value 拼单位、带指数列）。"""
    res = compute_all(data_rows, engine)
    filled = []
    for r in res["rows"]:
        row = dict(r)
        if row.get("unit") and row.get("value") is not None:
            row["value"] = f"{row['value']} {row['unit']}"
        filled.append(row)
    try:
        # 用生成器静态方法重建 results 章节内容（保留 pi 指数列）
        from src.report.generator import ReportGenerator
        for sec in sections:
            if sec.name == "results":
                sec.content = ReportGenerator._results({}, filled)
    except Exception:
        pass
    return {"filled": len(filled), "summary": res["summary"],
            "used_formulas": res["used_formulas"]}


def verify_calcs(text: str, data_rows: list[dict[str, Any]] | None = None,
                 engine: FormulaEngine | None = None) -> dict[str, Any]:
    """R5：用 FormulaEngine 重算并核对报告声明。

    核对项：超标声明一致性（重算超标 vs 文本"超标"）、
    综合污染指数/均值声明值一致性。返回 {checked, ok, errors, results}。
    """
    engine = engine or FormulaEngine()
    errors: list[str] = []
    results: list[dict[str, Any]] = []
    rows = list(data_rows or [])
    if not rows:
        import materials_check as mc
        rows = mc._parse_data_rows(text)
    checked = 0
    # 1) 逐行重算达标判定
    calc_exceeded: list[str] = []
    for r in rows:
        if r.get("limit") in (None, ""):
            continue
        cr = compute_row(r, engine)
        results.append(cr)
        checked += 1
        if cr.get("pi") is not None and cr["pi"] > 1.0:
            calc_exceeded.append(f"{r.get('point', '')}-{r.get('item', '')}")
    has_exceed_text = "超标" in text or "超标项" in text
    if calc_exceeded and not has_exceed_text:
        errors.append(f"监测数据存在超标（{len(calc_exceeded)} 项），但报告未声明超标")
    elif not calc_exceeded and has_exceed_text and rows:
        errors.append("报告声明超标，但重算监测数据均达标")
    # 2) 综合污染指数声明核对
    m_nemean = re.search(r"(?:综合污染指数|内梅罗)[^\d]{0,8}(\d+(?:\.\d+)?)", text)
    pis = [c["pi"] for c in results if c.get("pi") is not None]
    if m_nemean and len(pis) >= 2:
        try:
            nm = engine.calc("通用", T_NEMEAN, {"Ci": pis})
            calc = round(float(nm["value"]), 2)
            if abs(calc - float(m_nemean.group(1))) > 0.05:
                errors.append(f"综合污染指数声明 {m_nemean.group(1)}，重算应为 {calc}")
            checked += 1
        except Exception:
            pass
    # 3) 均值声明核对
    m_mean = re.search(r"(?:算术均值|均值)[^\d]{0,8}(\d+(?:\.\d+)?)", text)
    vals = [_num(r.get("value")) for r in rows if r.get("limit") not in (None, "")]
    vals = [v for v in vals if v is not None]
    if m_mean and vals:
        try:
            mm = engine.calc("通用", T_MEAN, {"Ci": vals})
            calc = round(float(mm["value"]), 2)
            if abs(calc - float(m_mean.group(1))) > 0.05:
                errors.append(f"算术均值声明 {m_mean.group(1)}，重算应为 {calc}")
            checked += 1
        except Exception:
            pass
    return {"checked": checked, "ok": not errors, "errors": errors, "results": results}
