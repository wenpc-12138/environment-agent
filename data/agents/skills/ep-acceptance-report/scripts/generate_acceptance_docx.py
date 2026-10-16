#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_acceptance_docx.py
---------------------------
将结构化 JSON 数据渲染为《建设项目竣工环境保护验收报告》Word(.docx) 文件。
依据标准八章结构 + 验收意见章节，参考污染影响类技术指南（生态环境部公告2018年第9号）。
支持自动插入图件（附图/附件/现场照片），图片缺失时渲染占位框并登记待补充。

用法:
    python generate_acceptance_docx.py --data acceptance_data.json --out 验收报告.docx

依赖: python-docx  (托管 venv 中: pip install python-docx)
"""
import argparse
import json
import os
import re
import sys
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# 必备三件套校验（与 check_materials.py 共用同一套检测逻辑）
try:
    from check_materials import check_essentials
except Exception:
    check_essentials = None

NAVY = RGBColor(0x1A, 0x36, 0x5D)
GOLD = RGBColor(0xD4, 0xA8, 0x53)
INK = RGBColor(0x1F, 0x27, 0x33)
GRAY = RGBColor(0x5B, 0x66, 0x75)
PLACE_GRAY = RGBColor(0x8A, 0x94, 0xA6)
SONG = "宋体"
HEI = "黑体"

PLACEHOLDER_RE = re.compile(r"【待补充[:：][^】]*】")

# 全局占位符收集
placeholders = set()


def set_run_font(run, name=SONG, size=12, bold=False, color=INK, eastasia=True):
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    run.font.color.rgb = color
    if eastasia:
        rpr = run._element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        rfonts.set(qn("w:eastAsia"), name)
        rfonts.set(qn("w:ascii"), name)
        rfonts.set(qn("w:hAnsi"), name)


def set_default_font(doc):
    style = doc.styles["Normal"]
    style.font.name = SONG
    style.font.size = Pt(12)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), SONG)
    style.element.rPr.rFonts.set(qn("w:ascii"), SONG)
    style.element.rPr.rFonts.set(qn("w:hAnsi"), SONG)


def add_para(doc, text, size=12, bold=False, color=INK, align=None,
             font=SONG, space_after=4, space_before=2):
    if text is None:
        text = ""
    str_text = str(text)
    # 登记占位符
    for ph in PLACEHOLDER_RE.findall(str_text):
        placeholders.add(ph)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.space_before = Pt(space_before)
    if align:
        p.alignment = align
    first = True
    for line in str_text.split("\n"):
        if not first:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(space_after)
            p.paragraph_format.space_before = Pt(0)
            if align:
                p.alignment = align
        run = p.add_run(line if line else " ")
        set_run_font(run, name=font, size=size, bold=bold, color=color)
        first = False
    return p


def add_title(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(120)
    p.paragraph_format.space_after = Pt(20)
    run = p.add_run(text)
    set_run_font(run, name=HEI, size=18, bold=True, color=NAVY)
    return p


def add_h1(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run(text)
    set_run_font(run, name=HEI, size=15, bold=True, color=NAVY)
    return p


def add_h2(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    set_run_font(run, name=HEI, size=13, bold=True, color=INK)
    return p


def add_bullets(doc, items, size=12):
    if not items:
        return
    for it in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(2)
        run = p.add_run(str(it))
        set_run_font(run, name=SONG, size=size)
        for ph in PLACEHOLDER_RE.findall(str(it)):
            placeholders.add(ph)


def set_table_borders(table):
    tbl = table._tbl
    tblPr = tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "999999")
        borders.append(el)
    tblPr.append(borders)


def _shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


def add_table(doc, headers, rows, col_widths=None):
    if not rows:
        return
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    set_table_borders(table)
    hdr = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = ""
        p = hdr[i].paragraphs[0]
        run = p.add_run(h)
        set_run_font(run, name=HEI, size=10.5, bold=True, color=NAVY)
        _shade(hdr[i], "EAF0F8")
    for row in rows:
        cells = table.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            run = p.add_run("" if val is None else str(val))
            set_run_font(run, name=SONG, size=10.5)
            for ph in PLACEHOLDER_RE.findall(str(val or "")):
                placeholders.add(ph)
    if col_widths:
        for i, w in enumerate(col_widths):
            for r in table.rows:
                r.cells[i].width = Inches(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return table


# ============================== 图片 / 图件支持 ==============================

def _usable_width_in(doc):
    sec = doc.sections[0]
    # page_width / margins are EMU (int); 1 inch = 914400 EMU
    usable_emu = (sec.page_width - sec.left_margin - sec.right_margin)
    usable_in = usable_emu / 914400.0
    return max(3.0, usable_in * 0.95)


def add_image_placeholder(doc, label):
    """图片缺失时渲染带边框的占位框，并登记待补充。"""
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(tbl)
    cell = tbl.cell(0, 0)
    cell.width = Inches(5.8)
    _shade(cell, "F2F4F8")
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(label)
    set_run_font(run, name=SONG, size=11, bold=True, color=PLACE_GRAY)
    # 占位框高度（用空行撑开）
    for _ in range(3):
        ep = cell.add_paragraph()
        ep.paragraph_format.space_after = Pt(2)
        er = ep.add_run(" ")
        set_run_font(er, size=10, color=PLACE_GRAY)
    placeholders.add(label)
    doc.add_paragraph().paragraph_format.space_after = Pt(4)


def add_image(doc, path, caption=None, width_in=None):
    """插入一张图片（居中），下方可选图注；path 缺失时渲染占位框。"""
    if width_in is None:
        width_in = _usable_width_in(doc)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    if path and os.path.exists(path):
        try:
            run = p.add_run()
            run.add_picture(path, width=Inches(width_in))
        except Exception as e:
            add_image_placeholder(doc, f"图片读取失败：{os.path.basename(str(path))}（{e}）")
            return
    else:
        label = "【图片待补充】"
        if caption:
            label = f"【{caption} —— 图片待补充】"
        add_image_placeholder(doc, label)
        return
    if caption:
        cp = doc.add_paragraph()
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cp.paragraph_format.space_after = Pt(8)
        run = cp.add_run(caption)
        set_run_font(run, name=SONG, size=9, color=GRAY)


def add_figures(doc, figures):
    """渲染 附图 章节：figures 为 [{title, path, caption, width_in}] 列表。"""
    if not figures:
        return
    doc.add_page_break()
    add_h1(doc, "附图")
    for i, fig in enumerate(figures, 1):
        title = fig.get("title") or f"附图{i}"
        add_h2(doc, f"附图{i}　{title}")
        add_image(doc, fig.get("path"), fig.get("caption"), fig.get("width_in"))


def add_appendices(doc, appendices):
    """渲染 附件 章节：appendices 为 [{title, path, caption}] 列表（通常为扫描件图片）。"""
    if not appendices:
        return
    doc.add_page_break()
    add_h1(doc, "附件")
    for i, ap in enumerate(appendices, 1):
        title = ap.get("title") or f"附件{i}"
        add_h2(doc, f"附件{i}　{title}")
        add_image(doc, ap.get("path"), ap.get("caption"), ap.get("width_in"))


def add_photo_block(doc, photos, heading="现场照片"):
    """在一章内插入一组现场照片（含图注）。photos 为 [{path, caption}] 列表。"""
    if not photos:
        return
    add_h2(doc, heading)
    for ph in photos:
        add_image(doc, ph.get("path"), ph.get("caption"), ph.get("width_in"))


# ============================== 正文渲染 ==============================

def build(data, out_path):
    doc = Document()
    # A4 页边距
    for s in doc.sections:
        s.top_margin = Inches(1.0)
        s.bottom_margin = Inches(1.0)
        s.left_margin = Inches(1.1)
        s.right_margin = Inches(1.1)
    set_default_font(doc)

    meta = data.get("meta", {})
    title = meta.get("report_title", "建设项目竣工环境保护验收报告")
    add_title(doc, title)
    # 元信息行
    sub = (f"建设单位：{meta.get('build_unit','【待补充：建设单位】')}　"
           f"编制单位：{meta.get('prepared_by', meta.get('build_unit',''))}　"
           f"日期：{meta.get('date','【待补充：报告日期】')}")
    add_para(doc, sub, size=11, bold=False, color=INK,
             align=WD_ALIGN_PARAGRAPH.CENTER)
    if meta.get("source_note"):
        add_para(doc, meta.get("source_note"), size=9, color=GRAY,
                 align=WD_ALIGN_PARAGRAPH.CENTER)

    # ===== 一、工程建设基本情况 =====
    s1 = data.get("section1_basic", {})
    add_h1(doc, "一、工程建设基本情况")
    add_h2(doc, "1、建设地点、规模、主要建设内容")
    basic_lines = []
    if s1.get("location"):
        basic_lines.append(f"建设地点：{s1.get('location')}")
    if s1.get("industry"):
        basic_lines.append(f"行业/主要产品：{s1.get('industry')}")
    if s1.get("total_capacity"):
        basic_lines.append(f"总设计产能：{s1.get('total_capacity')}")
    if s1.get("phase_capacity"):
        basic_lines.append(f"本次验收（一期）规模：{s1.get('phase_capacity')}")
    for k, label in [("land_area", "用地面积"), ("building_area", "建筑面积"),
                     ("employees", "员工人数"), ("workdays", "年工作天数"),
                     ("workschedule", "生产班次/时间"), ("has_canteen_dorm", "宿舍/食堂")]:
        if s1.get(k):
            basic_lines.append(f"{label}：{s1.get(k)}")
    add_para(doc, "\n".join(basic_lines) if basic_lines else "【待补充：工程基本情况】")

    comp = s1.get("project_components_table")
    if comp:
        add_para(doc, "项目工程组成见下表。", size=11)
        add_table(doc, ["工程类别", "工程名称", "环评建设内容和规模", "备注"],
                  [[c.get("category"), c.get("name"), c.get("ep_content"), c.get("remark")] for c in comp],
                  col_widths=[1.0, 1.3, 3.2, 1.2])

    # 1.2 审批
    app = s1.get("approval", {})
    add_h2(doc, "2、建设过程、环保审批、竣工环境保护验收情况")
    app_lines = []
    if app.get("eia_unit"):
        app_lines.append(f"建设单位委托{app.get('eia_unit')}编制了环境影响报告书（表）。")
    if app.get("eia_approve_dept") or app.get("eia_approve_no"):
        app_lines.append(f"审批部门：{app.get('eia_approve_dept', '')}；审批文号：{app.get('eia_approve_no', '')}；审批日期：{app.get('eia_approve_date', '')}。")
    if app.get("permit_no"):
        app_lines.append(f"排污许可证编号：{app.get('permit_no')}；取得日期：{app.get('permit_date', '')}。")
    if app.get("completion_date"):
        app_lines.append(f"竣工日期：{app.get('completion_date')}；调试起止：{app.get('debug_start', '')} 至 {app.get('debug_end', '')}。")
    if app.get("monitor_unit"):
        app_lines.append(f"验收监测单位：{app.get('monitor_unit')}；监测日期：{app.get('monitor_date', '')}；监测报告：{app.get('monitor_report_name', '')}。")
    add_para(doc, "\n".join(app_lines) if app_lines else "【待补充：审批与验收过程】")

    # 1.3 投资
    inv = s1.get("investment", {})
    add_h2(doc, "3、投资情况")
    add_para(doc, f"项目总投资 {inv.get('total', '【待补充】')} 万元，其中环保投资 {inv.get('env', '【待补充】')} 万元。")

    # 1.4 验收范围 + 三表
    add_h2(doc, "4、验收范围")
    if s1.get("acceptance_scope"):
        add_para(doc, s1.get("acceptance_scope"))
    prod = s1.get("product_table")
    if prod:
        add_para(doc, "验收产品如下表。", size=11)
        add_table(doc, ["产品名称", "环评及批复设计产能", "一期验收规模", "剩余规模"],
                  [[p.get("name"), p.get("eia_capacity"), p.get("phase_capacity"), p.get("remaining")] for p in prod],
                  col_widths=[1.6, 2.0, 1.8, 1.3])
    mat = s1.get("material_table")
    if mat:
        add_para(doc, "主要原辅材料如下表。", size=11)
        add_table(doc, ["序号", "名称", "环评申报规模", "一期验收规模", "剩余规模"],
                  [[m.get("no"), m.get("name"), m.get("eia_scale"), m.get("phase_scale"), m.get("remaining")] for m in mat],
                  col_widths=[0.6, 1.8, 1.8, 1.8, 1.5])
    eq = s1.get("equipment_table")
    if eq:
        add_para(doc, "验收生产设备如下表。", size=11)
        add_table(doc, ["序号", "设备名称", "设备型号", "数量", "本次验收数量", "未验收数量"],
                  [[e.get("no"), e.get("name"), e.get("model"), e.get("qty"), e.get("accepted"), e.get("unaccepted")] for e in eq],
                  col_widths=[0.6, 1.8, 1.4, 0.9, 1.3, 1.2])

    # 平面布置 / 现场照片（可选，紧贴建设情况之后）
    if s1.get("layout_photos"):
        add_photo_block(doc, s1.get("layout_photos"), heading="附：厂区平面布置及现场照片")

    # ===== 二、工程变动情况 =====
    add_h1(doc, "二、工程变动情况")
    add_para(doc, data.get("section2_change", "无变动。"))

    # ===== 三、环保设施建设情况 =====
    s3 = data.get("section3_facilities", {})
    add_h1(doc, "三、环境保护设施建设情况")
    add_h2(doc, "（一）废水")
    add_bullets(doc, s3.get("wastewater") or ["【待补充：废水治理措施】"])
    add_h2(doc, "（二）废气")
    add_bullets(doc, s3.get("wastegas") or ["【待补充：废气治理措施】"])
    add_h2(doc, "（三）噪声")
    add_para(doc, s3.get("noise") or "【待补充：噪声治理措施】")
    add_h2(doc, "（四）固体废物")
    add_para(doc, s3.get("solidwaste") or "【待补充：固废治理措施】")
    add_h2(doc, "（五）其他环境保护设施")
    other = s3.get("other", {})
    add_h2(doc, "1. 环境风险防范措施")
    add_para(doc, other.get("risk") or "【待补充：风险防范措施】")
    add_h2(doc, "2. 在线监测装置")
    add_para(doc, other.get("onlinemonitor") or "无。")
    add_h2(doc, "3. 其他设施")
    add_para(doc, other.get("others") or "无。")

    # 环保设施现场照片（可选）
    if data.get("facility_photos"):
        add_photo_block(doc, data.get("facility_photos"), heading="附：环境保护设施现场照片")

    # ===== 四、调试效果 =====
    s4 = data.get("section4_debug", {})
    add_h1(doc, "四、环境保护设施调试效果")
    eff = s4.get("efficiency", {})
    add_h2(doc, "（一）环保设施处理效率")
    for label, key in [("1、废水", "wastewater"), ("2、废气", "wastegas"), ("3、噪声", "noise"), ("4、固体废物", "solidwaste")]:
        add_h2(doc, label)
        add_para(doc, eff.get(key) or "无。")
    em = s4.get("emission", {})
    add_h2(doc, "（二）污染物排放情况")
    for label, key in [("1、废水", "wastewater"), ("2、废气", "wastegas"), ("3、噪声", "noise"), ("4、固体废物", "solidwaste")]:
        add_h2(doc, label)
        add_para(doc, em.get(key) or "【待补充：排放达标说明】")
    add_h2(doc, "5、污染物排放总量")
    add_para(doc, em.get("total") or "【待补充：总量核算】")

    # ===== 五、环境影响 =====
    add_h1(doc, "五、工程建设对环境的影响")
    add_para(doc, data.get("section5_impact") or "【待补充：对环境的影响概述】")

    # ===== 六、制度落实 =====
    s6 = data.get("section6_system", {})
    add_h1(doc, "六、制度落实情况")
    add_h2(doc, "1、环保组织机构及规章制度")
    add_para(doc, s6.get("org") or "【待补充：组织机构】")
    add_h2(doc, "2、环境风险防范措施")
    add_para(doc, s6.get("risk_plan") or "【待补充：应急预案及备案】")
    add_h2(doc, "3、环境监测计划")
    add_para(doc, s6.get("monitor_plan") or "【待补充：监测计划】")

    # ===== 七、验收结论 =====
    add_h1(doc, "七、验收结论")
    add_para(doc, data.get("section7_conclusion") or "【待补充：验收结论】")

    # ===== 八、后续要求 =====
    add_h1(doc, "八、后续要求")
    add_bullets(doc, data.get("section8_followup") or ["【待补充：后续要求】"])

    # 署名
    so = data.get("signoff", {})
    add_para(doc, so.get("build_unit_seal", "建设单位（盖章）："), size=12,
             space_before=16)
    add_para(doc, so.get("date", "日期："), size=12)

    # ===== 附图（图件，自动插入） =====
    add_figures(doc, data.get("figures"))

    # ===== 附件（扫描件，自动插入） =====
    add_appendices(doc, data.get("appendices"))

    # ===== 验收意见（独立章节） =====
    ao = data.get("acceptance_opinion")
    if ao:
        doc.add_page_break()
        add_title(doc, (meta.get("report_title", "").split("竣工")[0] + "竣工环境保护验收意见")
                  if "竣工" in meta.get("report_title", "") else "竣工环境保护验收意见")
        add_para(doc, f"验收意见日期：{ao.get('date', '【待补充】')}", size=11)
        intro = ao.get("group_intro") or "由建设单位、环保咨询单位、验收检测单位和专家组成的验收组"
        add_para(doc, f"{intro}进行了现场勘察，听取建设单位介绍，审阅并核实有关资料，经认真讨论，形成验收意见如下：")
        add_h1(doc, "一、工程建设基本情况")
        add_para(doc, ao.get("basic") or data.get("section1_basic", {}).get("phase_capacity") or "【待补充】")
        add_h1(doc, "二、工程变动情况")
        add_para(doc, ao.get("change") or data.get("section2_change", "无变动。"))
        add_h1(doc, "三、环境保护设施建设情况")
        add_para(doc, ao.get("facilities") or "【待补充】")
        add_h1(doc, "四、环境保护设施调试效果")
        add_para(doc, ao.get("debug") or "【待补充】")
        add_h1(doc, "五、工程建设对环境的影响")
        add_para(doc, ao.get("impact") or data.get("section5_impact") or "【待补充】")
        add_h1(doc, "六、验收结论")
        add_para(doc, ao.get("conclusion") or "验收组同意项目通过环境保护验收。")
        add_h1(doc, "七、后续要求")
        add_bullets(doc, ao.get("followup") or data.get("section8_followup") or ["【待补充】"])
        if ao.get("group_members"):
            add_para(doc, "验收组成员：", size=11, space_before=12)
            for m in ao.get("group_members"):
                add_para(doc, m, size=11)

    # 待补充清单
    if placeholders:
        doc.add_page_break()
        add_h1(doc, "待补充材料清单")
        add_para(doc, "以下项目在生成时标记为待补充，请用户提供正式资料后替换：", size=11)
        for ph in sorted(placeholders):
            add_para(doc, f"· {ph}", size=11)

    doc.save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="生成竣工环境保护验收报告 Word 文件")
    ap.add_argument("--data", required=True, help="结构化 JSON 数据文件路径")
    ap.add_argument("--out", required=True, help="输出 .docx 文件路径")
    ap.add_argument("--require-essentials", action="store_true",
                    help="必备三件套（环评/环评批复/CMA监测报告）缺失时拒绝生成并退出(退出码2)")
    args = ap.parse_args()

    if not os.path.exists(args.data):
        sys.exit(f"数据文件不存在: {args.data}")
    with open(args.data, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 必备三件套门控（环评 / 环评批复 / CMA 验收监测报告）
    if check_essentials is not None:
        ess = check_essentials(data)
        missing = [name for _k, name, ok, _h in ess if not ok]
        if missing and args.require_essentials:
            print("错误：以下必备材料缺失，无法生成正式验收报告：")
            for m in missing:
                print(f"  - {m}")
            print("请用户上传上述资料补齐后重试；或去掉 --require-essentials 仅生成带占位的草稿。")
            sys.exit(2)
        # 非门控模式：把必备缺失登记到待补清单，并明确标注"必备"
        for _k, name, ok, _h in ess:
            if not ok:
                placeholders.add(f"【必备材料缺失：{name} —— 待用户上传补齐】")

    out = build(data, args.out)
    print(f"已生成验收报告: {out}")
    if placeholders:
        print(f"提示：共 {len(placeholders)} 处待补充项，详见报告末页。")


if __name__ == "__main__":
    main()
