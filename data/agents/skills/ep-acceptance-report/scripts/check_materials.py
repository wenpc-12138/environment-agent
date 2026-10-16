#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_materials.py
------------------
检查验收报告 JSON 数据是否具备"必备三件套"，并按项目类型提示建议补充项，
输出可读的《资料补齐清单》。供技能在生成 Word 前调用，用于提醒用户上传缺失资料。

必备三件套（缺一不可，否则不得出具正式验收报告）：
  1. 环境影响报告书（表）           —— 环评文件
  2. 环境影响评价批复               —— 审批部门批复
  3. 验收监测报告（CMA 资质出具）   —— 核心定量证据

用法:
    python check_materials.py --data acceptance_data.json
    python check_materials.py --data acceptance_data.json --project-type 污染影响类
    python check_materials.py --data acceptance_data.json --strict   # 必备缺失则退出码非0

输出标签（不使用 emoji，符合无障碍/公文观感）：
    [必备缺失]  必备材料未提供，必须补齐后才能生成正式报告
    [建议补充]  按项目类型推荐提供，缺失则以占位生成
    [已具备]    已检测到对应材料
"""

import argparse
import json
import os
import sys

# 必备三件套： (JSON 检测键, 中文名, 缺件提示)
ESSENTIALS = [
    ("eia_report", "环境影响报告书（表）", "请提供环评报告书/报告表文件（PDF/Word）"),
    ("eia_approval", "环境影响评价批复", "请提供审批部门出具的环评批复扫描件"),
    ("monitoring_report", "验收监测报告（CMA）", "请提供具备 CMA 资质机构出具的验收监测报告（须盖 CMA 章）"),
]

# 按项目类型的建议补充项： (中文名, 说明/对应报告位置)
RECOMMENDED = {
    "污染影响类": [
        ("排污许可证", "许可管理项目须持证；对应 一.2 / 其他需要说明的事项"),
        ("危废处置合同、转移联单、暂存间照片", "对应 三.（四）固废 / 六 制度落实"),
        ("突发环境事件应急预案及备案", "对应 三.（五）1 / 六.2 风险防范"),
        ("厂区总平面布置图", "对应 附图4"),
        ("监测布点示意图", "对应 附图5"),
        ("环保设施现场照片", "对应 facility_photos"),
    ],
    "生态影响类": [
        ("生态监测/调查报告", "生态影响类专项证据"),
        ("植被/土壤/水生生态现场照片", "对应 现场照片"),
        ("生态恢复措施佐证", "对应 三 环保设施建设情况"),
    ],
    "加油站/油气回收": [
        ("油气回收检测报告", "对应 三 监测证据类"),
        ("卸油/加油/储油工艺照片", "对应 facility_photos"),
        ("双层罐/防渗池佐证", "对应 三 环保设施"),
    ],
}

PROJECT_TYPES = list(RECOMMENDED.keys())


def _truthy_path(v):
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, dict):
        p = v.get("path")
        if isinstance(p, str) and p.strip():
            return True
        return bool(v.get("note") or v.get("doc_no") or v.get("no") or v.get("text"))
    return bool(v)


def detect_essential(data, key):
    """灵活检测某项必备材料是否已在 JSON 中提供（兼容多种填写位置）。"""
    d = data or {}

    # 1) 顶层专用键
    if key == "eia_report":
        if _truthy_path(d.get("eia_report")):
            return True
        # 退路：审批信息里提到了环评编制单位，视为环评已编制（但仍建议提供文件）
        app = (d.get("section1_basic") or {}).get("approval") or {}
        return bool(app.get("eia_unit"))

    if key == "eia_approval":
        if _truthy_path(d.get("eia_approval")):
            return True
        app = (d.get("section1_basic") or {}).get("approval") or {}
        if app.get("eia_approve_no") or app.get("eia_approve_dept"):
            return True
        # 退路：附件中含"批复/审批"字样
        for ap in (d.get("appendices") or []):
            t = str(ap.get("title", "") + ap.get("caption", ""))
            if "批复" in t or "审批" in t:
                return True
        return False

    if key == "monitoring_report":
        if _truthy_path(d.get("monitoring_report")):
            return True
        app = (d.get("section1_basic") or {}).get("approval") or {}
        if app.get("monitor_report_name") or app.get("monitor_unit"):
            return True
        for ap in (d.get("appendices") or []):
            t = str(ap.get("title", "") + ap.get("caption", ""))
            if "监测报告" in t or "CMA" in t.upper():
                return True
        return False

    return _truthy_path(d.get(key))


def check_essentials(data):
    """返回 [(key, 名称, 是否具备, 缺件提示)]。"""
    out = []
    for key, name, hint in ESSENTIALS:
        ok = detect_essential(data, key)
        out.append((key, name, ok, hint))
    return out


def check_recommended(data, project_type):
    """返回 [(名称, 说明, 是否具备)]，依据项目类型推荐项。"""
    items = RECOMMENDED.get(project_type, RECOMMENDED["污染影响类"])
    out = []
    for name, desc in items:
        # 简易检测：看相关字段是否出现关键词
        blob = json.dumps(data, ensure_ascii=False)
        ok = name in blob
        out.append((name, desc, ok))
    return out


def render_report(data, project_type=None, strict=False):
    lines = []
    lines.append("=" * 56)
    lines.append("        竣工环境保护验收报告 · 资料补齐清单")
    lines.append("=" * 56)

    ess = check_essentials(data)
    missing_ess = [e for e in ess if not e[2]]
    lines.append("")
    lines.append("一、必备三件套（缺失则不得出具正式报告）")
    lines.append("-" * 56)
    for key, name, ok, hint in ess:
        tag = "已具备" if ok else "必备缺失"
        lines.append(f"  [{tag}] {name}")
        if not ok:
            lines.append(f"          → {hint}")
    lines.append("")

    if project_type is None:
        # 尝试从数据推断项目类型
        pt = (data.get("meta") or {}).get("project_type") or (data.get("section1_basic") or {}).get("project_type")
        if pt in PROJECT_TYPES:
            project_type = pt
        else:
            project_type = "污染影响类"
    rec = check_recommended(data, project_type)
    lines.append(f"二、建议补充项（项目类型：{project_type}；缺失则以占位生成）")
    lines.append("-" * 56)
    for name, desc, ok in rec:
        tag = "已具备" if ok else "建议补充"
        lines.append(f"  [{tag}] {name}")
        if not ok:
            lines.append(f"          → {desc}")
    lines.append("")

    lines.append("=" * 56)
    if missing_ess:
        lines.append(f"结论：尚有 {len(missing_ess)} 项必备材料缺失，请用户上传补齐后再生成正式报告。")
        if strict:
            lines.append("（strict 模式：退出码=2，已终止生成）")
    else:
        lines.append("结论：必备三件套已齐备，可生成正式验收报告（建议项缺失将自动占位）。")
    lines.append("=" * 56)
    return "\n".join(lines), len(missing_ess)


def main():
    ap = argparse.ArgumentParser(description="检查验收报告必备材料并输出资料补齐清单")
    ap.add_argument("--data", required=True, help="结构化 JSON 数据文件路径")
    ap.add_argument("--project-type", default=None, help="项目类型：" + "/".join(PROJECT_TYPES))
    ap.add_argument("--strict", action="store_true", help="必备缺失时退出码设为 2")
    args = ap.parse_args()

    if not os.path.exists(args.data):
        sys.exit(f"数据文件不存在: {args.data}")
    with open(args.data, "r", encoding="utf-8") as f:
        data = json.load(f)

    text, n_missing = render_report(data, args.project_type, strict=args.strict)
    print(text)
    if args.strict and n_missing > 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
