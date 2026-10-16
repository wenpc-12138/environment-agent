# -*- coding: utf-8 -*-
"""P2 资料缺口检测与对话索要。

专家团流水线（report_orchestrator）每步前校验必需资料（监测数据/点位/标准等），
缺失时对话追问用户补充，替代报告生成阶段的"待填写"占位。

检测来源：
- 当前消息 + 该任务历史 user 消息（db.get_messages）
- 任务记忆（db.memory_list，用户交代过的项目事实）
- 附件标记（消息中的 `[附件: ...]`，视为数据载体）
"""
from __future__ import annotations

import re
from typing import Any

# 常见浓度/噪声单位（检测监测数据用）
_DATA_UNITS = (
    "mg/L|mg/l|g/L|kg/L|mg/m³|mg/m3|ug/m³|ug/m3|μg/m³|μg/m3|µg/m3|µg/L|ug/L|μg/L|µg/L|"
    "dB\\(A\\)|dB|个/L|MPN/L|mg/kg|mg/m2|μg/kg|%"
)
# 常见监测项目名（无单位场景兜底）
_ITEM_NAMES = ("cod|氨氮|总磷|总氮|溶解氧|bod|高锰酸盐|ss|浊度|氯化物|硝酸盐|亚硝酸盐|"
               "ph|水温|电导率|挥发酚|氰化物|六价铬|铅|镉|砷|汞|噪声|噪声值|等效声级|"
               "浓度|排放|均值|结果|超标倍数")

# 附件标记（BASE_SYSTEM 约定格式：`[附件: 文件名 已保存到 本地路径]`）
_ATTACH_RE = re.compile(r"\[附件[:：]?\s*([^\]]+?)\]")
# 点位相关词
_POINT_KWS = ("点位", "测点", "断面", "采样点", "监测点", "厂界", "上风向", "下风向",
              "排放口", "排气筒", "入水口", "出水口", "井", "号点", "监测井", "布点")

# ---------------------------------------------------------------- 需求注册表
# 每项：key 唯一 / name 显示名 / hint 补充指引 / keywords 文本关键词 / patterns 正则。
# 报告类型映射 _infer_type：monitoring / acceptance / eia。
REQUIREMENTS: dict[str, list[dict[str, Any]]] = {
    "monitoring": [
        {"key": "project", "name": "项目概况",
         "hint": "项目名称、委托方/建设单位、监测目的",
         "keywords": ("项目", "委托", "建设", "监测站", "目的", "单位", "概况"),
         "patterns": []},
        {"key": "points", "name": "监测点位",
         "hint": "点位名称/编号、位置、监测项目（如 1# 厂界东、上游 500m 断面）",
         "keywords": _POINT_KWS,
         "patterns": [r"[0-9＃#]+\s*号?点位?", r"\d+[#＃]"]},
        {"key": "data", "name": "监测数据",
         "hint": "各点位监测结果，含数值、单位与限值（如 COD 35 mg/L、噪声 58 dB(A)）",
         "keywords": (_ITEM_NAMES,),
         "patterns": [r"\d+(?:\.\d+)?\s*(?:" + _DATA_UNITS + r")",
                      r"(?:" + _ITEM_NAMES + r")\s*[:：=]?\s*\d+(?:\.\d+)?"]},
        {"key": "standard", "name": "执行标准",
         "hint": "标准号，如 GB 3838-2002、HJ 828-2017、DB 44/26-2001",
         "keywords": ("标准", "限值", "执行标准", "依据", "gb", "hj", "db", "cj", "环评"),
         "patterns": [r"\b[A-Z]{1,4}\s*[-/]?\s*\d{3,5}(?:\.\d+)?(?:\s*[-–—]\s*\d{4})?\b"]},
    ],
    "acceptance": [
        {"key": "project", "name": "项目概况",
         "hint": "项目名称、建设单位、验收范围",
         "keywords": ("项目", "验收", "建设", "单位", "概况", "范围"),
         "patterns": []},
        {"key": "points", "name": "监测点位",
         "hint": "点位名称/编号、位置、监测项目（如 1# 废气排放口、厂界噪声 4 个点）",
         "keywords": _POINT_KWS,
         "patterns": [r"[0-9＃#]+\s*号?点位?", r"\d+[#＃]"]},
        {"key": "data", "name": "监测数据",
         "hint": "验收监测结果，含数值、单位与限值（如 颗粒物 12 mg/m3、噪声 58 dB(A)）",
         "keywords": (_ITEM_NAMES,),
         "patterns": [r"\d+(?:\.\d+)?\s*(?:" + _DATA_UNITS + r")",
                      r"(?:" + _ITEM_NAMES + r")\s*[:：=]?\s*\d+(?:\.\d+)?"]},
        {"key": "standard", "name": "验收依据/标准",
         "hint": "验收执行标准，如 GB 16297-1996、GB 12348-2008",
         "keywords": ("标准", "验收", "依据", "限值", "gb", "hj", "db"),
         "patterns": [r"\b[A-Z]{1,4}\s*[-/]?\s*\d{3,5}(?:\.\d+)?(?:\s*[-–—]\s*\d{4})?\b"]},
    ],
    "eia": [
        {"key": "project", "name": "项目概况（工程分析）",
         "hint": "项目名称、建设内容、地点、规模",
         "keywords": ("项目", "建设", "工程", "规模", "地点", "概况", "单位"),
         "patterns": []},
        {"key": "standard", "name": "评价标准",
         "hint": "环境质量与排放评价标准，如 GB 3095-2012、GB 3838-2002",
         "keywords": ("标准", "评价", "限值", "gb", "hj", "db", "环评"),
         "patterns": [r"\b[A-Z]{1,4}\s*[-/]?\s*\d{3,5}(?:\.\d+)?(?:\s*[-–—]\s*\d{4})?\b"]},
        {"key": "data", "name": "现状/类比监测数据",
         "hint": "环境质量现状监测或类比数据（数值+单位，如 二氧化硫 12 ug/m3）",
         "keywords": (_ITEM_NAMES,),
         "patterns": [r"\d+(?:\.\d+)?\s*(?:" + _DATA_UNITS + r")",
                      r"(?:" + _ITEM_NAMES + r")\s*[:：=]?\s*\d+(?:\.\d+)?"]},
        {"key": "points", "name": "监测点位",
         "hint": "现状监测点位名称/编号、位置（如 1# 项目厂界、2# 敏感点）",
         "keywords": _POINT_KWS,
         "patterns": [r"[0-9＃#]+\s*号?点位?", r"\d+[#＃]"]},
    ],
}


def requirements(report_type: str) -> list[dict[str, Any]]:
    return REQUIREMENTS.get(report_type, REQUIREMENTS["monitoring"])


# ---------------------------------------------------------------- 证据收集
def _history_text(task_id: int | None, current: str = "") -> str:
    """拼接当前消息 + 历史 user 消息 + 任务记忆。"""
    parts = [current or ""]
    if task_id:
        try:
            import db
            for m in db.get_messages(task_id):
                if m.get("role") == "user" and m.get("content"):
                    parts.append(str(m["content"]))
            for m in db.memory_list():
                parts.append(f"{m.get('key', '')}: {str(m.get('content', ''))[:300]}")
        except Exception:
            pass
    return "\n".join(parts)


def _extract_attachments(text: str) -> list[str]:
    return [m.group(1).strip() for m in _ATTACH_RE.finditer(text)]


def _match_item(item: dict[str, Any], text: str) -> str | None:
    """返回命中证据（原文片段），未命中返回 None。"""
    t = text
    low = t.lower()
    for kw in item.get("keywords", ()):
        if isinstance(kw, str) and kw and kw.lower() in low:
            # 提取该关键词附近的片段作为证据
            idx = low.find(kw.lower())
            return t[max(0, idx - 40): idx + len(kw) + 40].replace("\n", " ")
    for pat in item.get("patterns", ()):
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            return t[max(0, m.start() - 20): m.end() + 20].replace("\n", " ")
    return None


# ---------------------------------------------------------------- 数据解析（best effort）
_ITEM_PREFIX_STRIP = re.compile(r"^(?:数据|监测结果|监测|结果|数值|指标)[:：]?\s*")
_POINT_PREFIX_STRIP = re.compile(r"^(?:监测点位|点位|采样点|测点|断面|厂界)[:：]?\s*")


def _parse_data_rows(text: str) -> list[dict]:
    """从文本中提取监测数据行（point/item/value/unit/limit 尽量），供报告 fill_table。

    支持按换行/分号/顿号分段，同一点位下的多行数据共享最近点位上下文。
    """
    rows: list[dict[str, Any]] = []
    current_point = ""
    unit_pat = re.compile(r"(\d+(?:\.\d+)?)\s*(" + _DATA_UNITS + r")", re.IGNORECASE)
    for seg in re.split(r"[\n；;]+", text or ""):
        seg = seg.strip(" |,，、\t")
        if not seg:
            continue
        if any(k in seg for k in _POINT_KWS):
            current_point = _POINT_PREFIX_STRIP.sub("", seg)[:24]
        m = unit_pat.search(seg)
        if m:
            value = m.group(1)
            unit = m.group(2)
            prefix = seg[: m.start()].strip("| -—:：,，、")
            item = _ITEM_PREFIX_STRIP.sub("", prefix)
            if not item or len(item) > 16:
                item = "监测项目"
            rows.append({"point": current_point or "点位待定", "item": item,
                         "value": value, "unit": unit, "limit": ""})
    return rows


# ---------------------------------------------------------------- 主入口
def check(report_type: str = "", conversation: str = "", task_id: int | None = None) -> dict:
    """校验必需资料，返回 {report_type, total, have_n, complete, missing, have}。

    missing: [{'key','name','hint'}] 缺失项；have: {key: 证据文本/行数}。
    """
    rtype = report_type or "monitoring"
    reqs = requirements(rtype)
    text = _history_text(task_id, conversation)
    attachments = _extract_attachments(text)

    have: dict[str, Any] = {}
    missing: list[dict[str, Any]] = []
    for item in reqs:
        ev = _match_item(item, text)
        if ev:
            have[item["key"]] = ev
            continue
        # 附件兜底：存在附件时视为数据载体（data 满足）
        if item["key"] == "data" and attachments:
            have[item["key"]] = f"附件 {len(attachments)} 个（已上传，待解析）"
            continue
        missing.append({"key": item["key"], "name": item["name"], "hint": item["hint"]})

    # 数据行解析（供报告 fill_table，消除"待填写"）
    if "data" in have:
        rows = _parse_data_rows(text)
        if rows:
            have["data_rows"] = rows

    return {
        "report_type": rtype,
        "total": len(reqs),
        "have_n": sum(1 for r in reqs if r["key"] in have),
        "complete": not missing,
        "missing": missing,
        "have": have,
        "attachments": attachments,
    }


def ask_text(res: dict) -> str:
    """生成对话追问文本（供 agent_core 输出）。"""
    missing = res.get("missing") or []
    have = res.get("have") or {}
    have_names = []
    for r in requirements(res.get("report_type", "monitoring")):
        if r["key"] in have:
            have_names.append(r["name"])
    lines = [
        f"[资料核对] 已识别为「{res.get('report_type', 'monitoring')}」类报告任务，"
        f"必需资料 {res.get('total', 0)} 项，当前具备 {len(have_names)} 项。",
    ]
    if have_names:
        lines.append("已有：" + "、".join(have_names))
    lines.append(f"仍缺 {len(missing)} 项，请补充后重发（可直接粘贴内容或上传附件）：")
    for i, m in enumerate(missing, 1):
        lines.append(f"{i}. {m['name']} —— {m['hint']}")
    return "\n".join(lines)
