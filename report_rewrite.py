# -*- coding: utf-8 -*-
"""P3 审核-重写闭环：auto_fix 扩展 + LLM 按审核意见重写 + 复审 + 计算验证。

规则重写（离线可靠，确定性）：
- unit_inconsistent  单位统一（mgL→mg/L、ug→μg、mg/m3→mg/m³），扩展 auto_fix 到全文
- significant_figure 按"保留 N 位小数"声明修约
- standard_invalid   标注已废止并标记待替换
- hallucination      不自动改写（保留原文 + 标记待人工复核）

LLM 重写（可选）：`caller` 可注入（providers 聚合流式），按章节重写；失败自动降级规则。

闭环：初审 -> 重写 -> 复审，直至无 P0/P1 或达 max_rounds；
数据类问题用 FormulaEngine 做轻量计算验证（P4 报告集成计算的前置）。
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

# ---------------------------------------------------------------- 工具


def join_sections(sections: list[Any]) -> str:
    return "\n".join((s.content or "") for s in sections)


def _issue_json(issue: Any) -> dict:
    if hasattr(issue, "model_dump"):
        return issue.model_dump()
    return dict(issue)


# ---------------------------------------------------------------- 规则重写


def rule_rewrite_section(text: str, issues: list[Any]) -> tuple[str, list[str]]:
    """按问题清单对单个章节做确定性规则重写，返回 (新文本, 重写说明列表)。"""
    new_text = text
    rewrites: list[str] = []
    for issue in issues:
        d = _issue_json(issue)
        itype = d.get("type", "")
        desc = d.get("description", "")
        if itype == "unit_inconsistent" and d.get("auto_fixable"):
            m = re.search(r'"([^"]+)"', desc)
            target = str(d.get("suggested_fix", "")).replace("统一为", "").strip()
            if m and target and m.group(1) in new_text:
                new_text = new_text.replace(m.group(1), target)
                rewrites.append(f"单位统一：{m.group(1)} → {target}")
        elif itype == "significant_figure":
            decl = re.search(r"保留(\d)位小数", new_text)
            if decl:
                n = int(decl.group(1))
                before = new_text
                new_text = re.sub(
                    r"(?<![A-Za-z])(\d+\.\d+)(?![\d])",
                    lambda mm: f"{float(mm.group(1)):.{n}f}", new_text)
                if new_text != before:
                    rewrites.append(f"有效数字修约：按声明保留 {n} 位小数")
        elif itype == "standard_invalid":
            code = d.get("row_id") or ""
            if code and code in new_text and "已废止" not in new_text:
                new_text = new_text.replace(
                    code, f"{code}（已废止，待替换为现行有效版本）")
                rewrites.append(f"标准标注：{code} 已废止，待替换")
        elif itype == "hallucination":
            rewrites.append("反幻觉问题：无法自动改写，保留原文待人工复核")
        else:
            if desc and not rewrites:
                rewrites.append(f"其他问题未自动改写：{desc[:40]}")
    return new_text, rewrites


# ---------------------------------------------------------------- LLM 重写


def llm_rewrite_section(caller: Callable[[list[dict]], str], name: str,
                        text: str, issues: list[Any]) -> str:
    """调用 LLM 按审核意见重写章节；异常或空结果返回原文。"""
    prompt = (
        "你是生态环境报告编制员，请按审核意见重写以下报告章节。\n"
        "要求：只输出修订后的正文（保留章节标题行），不要解释、不要输出审核意见。\n"
        f"章节：{name}\n"
        f"审核问题：{json.dumps([_issue_json(i) for i in issues], ensure_ascii=False)}\n"
        f"原文：\n{text}"
    )
    try:
        out = (caller([{"role": "user", "content": prompt}]) or "").strip()
        return out if out and out != text else text
    except Exception:
        return text


# ---------------------------------------------------------------- 计算验证（轻量，P4 前置）


def calc_verify(text: str) -> dict:
    """用 FormulaEngine 对文本中可解析的监测数据做轻量计算验证。

    当前验证项：单项污染指数/均值类计算式若出现在文本中（如
    "Pi = 0.35/0.35 = 1.0"），重算对比声明值；无法解析返回 {'checked': 0}。
    """
    try:
        from src.compute.engine import FormulaEngine
    except Exception:
        return {"checked": 0, "ok": True, "error": "engine 不可用"}
    engine = FormulaEngine()
    checked, errors = 0, []
    # 单项污染指数式：Ci / Si = Pi
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*=\s*(\d+(?:\.\d+)?)",
                         text):
        try:
            a, b, expect = float(m.group(1)), float(m.group(2)), float(m.group(3))
            if b == 0:
                continue
            calc = round(a / b, 4)
            if abs(calc - expect) > 0.05:
                errors.append(f"{a}/{b} 应为 {calc}，文本写 {expect}")
            checked += 1
        except (TypeError, ValueError):
            continue
    return {"checked": checked, "ok": not errors, "errors": errors}


# ---------------------------------------------------------------- 重写闭环


def rewrite_loop(sections: list[Any], review_fn: Callable[[str], Any],
                 caller: Callable[[list[dict]], str] | None = None,
                 max_rounds: int = 3) -> dict:
    """审核-重写闭环：复审直至无 P0/P1 或达轮次上限。

    review_fn(text) -> 含 issues（P0/P1/P2）的对象（如 ReviewFeedback）。
    返回 {rounds, passed, hard_before, hard_after, rewrites, history, verified, remaining}。
    """
    history: list[dict[str, Any]] = []
    rewrites: list[str] = []
    current = join_sections(sections)

    def _hard(fb: Any) -> list[Any]:
        if isinstance(fb, dict):
            issues = fb.get("issues") or []
        else:
            issues = getattr(fb, "issues", None) or []
        return [i for i in issues
                if (i.get("severity") if isinstance(i, dict)
                    else getattr(i, "severity", "")) in ("P0", "P1")]

    hard_before = _hard(review_fn(current))
    for round_i in range(1, max_rounds + 1):
        if not hard_before:
            break
        # 逐节重写：命中问题的章节才处理
        round_notes: list[str] = []
        for sec in sections:
            text = sec.content or ""
            if not text:
                continue
            sec_issues = [i for i in hard_before if _hit_section(i, sec.name, text)]
            if not sec_issues:
                continue
            if caller:
                new_text = llm_rewrite_section(caller, sec.name, text, sec_issues)
                if new_text != text:
                    sec.content = new_text
                    round_notes.append(f"{sec.name}：LLM 重写")
                    continue
            new_text, notes = rule_rewrite_section(text, sec_issues)
            if new_text != text:
                sec.content = new_text
                round_notes.extend(notes)

        current = join_sections(sections)
        fb = review_fn(current)
        hard_after = _hard(fb)
        history.append({
            "round": round_i,
            "hard_before": [str(i) for i in hard_before],
            "hard_after": [str(i) for i in hard_after],
            "notes": round_notes,
        })
        rewrites.extend(round_notes)
        if not hard_after:
            hard_before = []
            break
        hard_before = hard_after

    remaining = [str(i) for i in hard_before]
    verified = calc_verify(current)
    return {
        "rounds": len(history),
        "passed": not remaining,
        "hard_before": [str(i) for i in history[0]["hard_before"]] if history else [],
        "hard_after": remaining,
        "rewrites": rewrites,
        "history": history,
        "verified": verified,
        "remaining": remaining,
    }


def _hit_section(issue: Any, sec_name: str, text: str) -> bool:
    """问题是否命中该章节（按 location 关键词或描述文本粗匹配）。"""
    d = _issue_json(issue)
    loc = d.get("location", "")
    desc = d.get("description", "")
    hit = False
    if sec_name == "results" and ("结果" in loc or "监测" in loc or "数据" in loc):
        hit = True
    elif sec_name in ("project_overview", "conclusion") and "结果" not in loc and "数据" not in loc and "单位" not in loc:
        hit = bool(desc and any(k in desc for k in ("标准", "依据")))
    else:
        hit = bool(loc and any(k in loc for k in (sec_name, "监测")))
    # 兜底：描述文本出现在该章节则命中
    if not hit and desc:
        snippet = desc.split("：")[-1][:20]
        hit = snippet and snippet in text
    return hit
