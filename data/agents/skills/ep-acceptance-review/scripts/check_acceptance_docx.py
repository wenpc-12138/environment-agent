#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_acceptance_docx.py
------------------------
竣工环境保护验收报告 Word(.docx) 程序化审核脚本（ep-acceptance-review 技能配套）。

检查范围（可程序化判定的部分）：
  1. 章节完整性（八章 + 附图/附件/验收意见）
  2. 占位符残留（【待补充】【图片待补充】等）
  3. 附图/附件编号连续性
  4. 内嵌图片有效性与章节分布
  5. 四张关键表结构（工程组成/验收产品/原辅材料/设备）
  6. 字体抽查（标题黑体/正文宋体）
  7. 页面设置（A4、页边距）
  8. JSON 源数据与正文关键字段一致性（可选 --data）

输出：--out 指定 JSON 问题清单；控制台摘要；退出码 0=无P0/P1, 1=有P1, 2=有P0。

用法:
    python check_acceptance_docx.py --docx 验收报告.docx [--data acceptance_data.json] [--out issues.json]

依赖: python-docx
"""
import argparse
import json
import os
import re
import sys
import zipfile
from docx import Document

# 章节标题锚点（顺序敏感）
CHAPTER_ANCHORS = [
    ("一、工程建设基本情况", "chapter1"),
    ("二、工程变动情况", "chapter2"),
    ("三、环境保护设施建设情况", "chapter3"),
    ("四、环境保护设施调试效果", "chapter4"),
    ("五、工程建设对环境的影响", "chapter5"),
    ("六、制度落实情况", "chapter6"),
    ("七、验收结论", "chapter7"),
    ("八、后续要求", "chapter8"),
]
APPENDIX_ANCHORS = ["附图", "附件", "验收意见"]

PLACEHOLDER_PATTERNS = [
    r"【待补充[:：][^】]*】",
    r"【图片待补充】",
    r"【必备材料缺失[^】]*】",
    r"【待补充材料清单】",
    r"【待补充】",
]

FIG_NUM_RE = re.compile(r"附图\s*(\d+)")
ATT_NUM_RE = re.compile(r"附件\s*(\d+)")

EXPECTED_TABLE_HEADERS = [
    ("工程组成", ["工程类别", "工程名称", "环评建设内容和规模", "备注"]),
    ("验收产品", ["产品名称", "环评及批复设计产能", "一期验收规模", "剩余规模"]),
    ("原辅材料", ["序号", "名称", "环评申报规模", "一期验收规模", "剩余规模"]),
    ("设备", ["序号", "设备名称", "设备型号", "数量", "本次验收数量", "未验收数量"]),
]

# 与生成脚本一致的格式约定（用于抽查）
NAVY_HEX = "1A365D"
A4_W_EMU = 11906  # A4 210mm
A4_H_EMU = 16838  # A4 297mm


def docx_media_entries(path):
    """返回 zip 内 word/media/ 下的文件名列表（不存在则空）。"""
    try:
        with zipfile.ZipFile(path) as z:
            return [n for n in z.namelist() if n.startswith("word/media/")]
    except Exception:
        return []


def media_signature_ok(zf, name):
    """按文件头判断图片是否损坏（JPEG/PNG/GIF/BMP/WMF/EMF）。"""
    try:
        head = zf.read(name)[:16]
    except Exception:
        return False
    if head[:3] == b"\xff\xd8\xff":  # JPEG
        return True
    if head[:8] == b"\x89PNG\r\n\x1a\n":  # PNG
        return True
    if head[:6] in (b"GIF87a", b"GIF89a"):  # GIF
        return True
    if head[:2] == b"BM":  # BMP
        return True
    if head[:4] in (b"\xd7\xcd\xc6\x9a", b"\x01\x00\x00\x00"):  # WMF/EMF
        return True
    return False


def iter_paragraphs_with_index(doc):
    """遍历 body 级段落（含表格内段落），返回 (序号, 文本, 所在表格标记)。"""
    results = []
    body = doc.element.body
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    pidx = 0
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            p = Paragraph(child, doc)
            results.append((pidx, p.text.strip(), None))
            pidx += 1
        elif child.tag.endswith("}tbl"):
            t = Table(child, doc)
            for row in t.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        results.append((pidx, p.text.strip(), "table"))
                        pidx += 1
    return results


def check_chapters(paras):
    """检查八章 + 附图/附件/验收意见 是否存在及顺序。"""
    issues = []
    found = []
    for idx, text, _tag in paras:
        for anchor, key in CHAPTER_ANCHORS:
            if text.startswith(anchor) and key not in found:
                found.append(key)
        for anchor in APPENDIX_ANCHORS:
            if text.startswith(anchor) and anchor not in found:
                found.append(anchor)
    for anchor, key in CHAPTER_ANCHORS:
        if key not in found:
            issues.append({"level": "P1", "code": "P1-8", "location": "章节",
                           "desc": f"缺少章节：{anchor}", "suggestion": f"补充章节「{anchor}」",
                           "source": "脚本"})
    for anchor in APPENDIX_ANCHORS:
        if anchor not in found:
            if anchor == "附图" or anchor == "附件":
                issues.append({"level": "P2", "code": "P2-8", "location": "章节",
                               "desc": f"未检测到「{anchor}」章节（如项目无需附图/附件可忽略）",
                               "suggestion": "确认该项目是否确无附图/附件需求", "source": "脚本"})
            else:
                issues.append({"level": "P1", "code": "P1-12", "location": "章节",
                               "desc": "缺少「验收意见」章节", "suggestion": "补充独立验收意见章节",
                               "source": "脚本"})
    return issues


def check_placeholders(paras):
    """扫描占位符残留。"""
    issues = []
    combined = re.compile("|".join(PLACEHOLDER_PATTERNS))
    for idx, text, _tag in paras:
        for m in combined.finditer(text):
            issues.append({"level": "P1", "code": "P1-9", "location": f"段落#{idx}",
                           "desc": f"占位符残留：{m.group(0)}",
                           "suggestion": "提供正式资料后重新生成，替换该占位内容", "source": "脚本"})
    return issues


def check_figure_numbering(paras):
    """附图/附件编号连续性。"""
    issues = []
    for kind, rx in (("附图", FIG_NUM_RE), ("附件", ATT_NUM_RE)):
        nums = []
        for _idx, text, _tag in paras:
            m = rx.search(text)
            if m:
                nums.append(int(m.group(1)))
        if not nums:
            continue
        nums = sorted(set(nums))
        expected = list(range(1, max(nums) + 1))
        missing = [n for n in expected if n not in nums]
        if missing:
            issues.append({"level": "P1", "code": "P1-6", "location": f"{kind}编号",
                           "desc": f"{kind}编号跳号，缺失：{kind}{'、'.join(map(str, missing))}",
                           "suggestion": "检查编号连续性并补齐", "source": "脚本"})
        if len(nums) != len(set(nums)):
            issues.append({"level": "P1", "code": "P1-6", "location": f"{kind}编号",
                           "desc": f"{kind}编号存在重复", "suggestion": "修正重复编号", "source": "脚本"})
    return issues


def check_images(doc, path):
    """检查内嵌图片：数量、损坏、空文件、章节分布。"""
    issues = []
    entries = docx_media_entries(path)
    # 损坏/空文件检测
    if entries:
        with zipfile.ZipFile(path) as zf:
            for name in entries:
                try:
                    info = zf.getinfo(name)
                except Exception:
                    continue
                if info.file_size == 0:
                    issues.append({"level": "P1", "code": "P1-3", "location": name,
                                   "desc": f"图片文件为空：{os.path.basename(name)}",
                                   "suggestion": "替换有效图片后重新生成", "source": "脚本"})
                elif not media_signature_ok(zf, name):
                    issues.append({"level": "P1", "code": "P1-3", "location": name,
                                   "desc": f"图片文件头无法识别（可能损坏）：{os.path.basename(name)}",
                                   "suggestion": "检查图片文件完整性后重新生成", "source": "脚本"})
    # 章节图片分布（docx 内联图片所在段落的章节归属）
    from docx.oxml.ns import qn
    body = doc.element.body
    current_section = "封面/前部"
    sec_counts = {}
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            texts = "".join(t.text or "" for t in child.iter(qn("w:t")))
            stripped = texts.strip()
            for anchor, _key in CHAPTER_ANCHORS:
                if stripped.startswith(anchor):
                    current_section = anchor
            for anchor in APPENDIX_ANCHORS:
                if stripped.startswith(anchor):
                    current_section = anchor
            if child.findall(".//" + qn("w:drawing")) or child.findall(".//" + qn("w:pict")):
                sec_counts[current_section] = sec_counts.get(current_section, 0) + 1
        elif child.tag.endswith("}tbl"):
            pass
    if not entries:
        issues.append({"level": "P1", "code": "P1-7", "location": "全文",
                       "desc": "报告未包含任何内嵌图片（可能整本无图或图片全部缺失）",
                       "suggestion": "确认报告是否应含附图/附件/现场照片", "source": "脚本"})
    # 附图/附件章节应有图；若章节存在但无图则提示
    for sec in ("附图", "附件"):
        if sec in sec_counts and sec_counts[sec] == 0:
            issues.append({"level": "P1", "code": "P1-7", "location": sec,
                           "desc": f"「{sec}」章节存在但未检测到图片（可能全是占位框）",
                           "suggestion": "检查该章节图片是否全部缺失", "source": "脚本"})
    return issues, sec_counts


def _header_similarity(h, expected):
    """表头相似度：按列顺序比对，命中列数 / 期望列数。"""
    if not h:
        return 0.0
    n = len(expected)
    if n == 0:
        return 0.0
    matches = sum(1 for a, b in zip(h, expected) if a and a == b)
    return matches / n


def check_tables(doc):
    """检查四张关键表的表头结构。相似度>=0.9 视为存在；0.4~0.9 报结构不符(P2-3)；<0.4 报缺失(P1-10)。"""
    issues = []
    found_headers = []
    for table in doc.tables:
        if not table.rows:
            continue
        header = [c.text.strip() for c in table.rows[0].cells]
        found_headers.append(header)
    for name, expected in EXPECTED_TABLE_HEADERS:
        best = max((_header_similarity(h, expected) for h in found_headers), default=0.0)
        if best >= 0.9:
            continue
        if best >= 0.4:
            matched = next(h for h in found_headers
                           if _header_similarity(h, expected) == best)
            issues.append({"level": "P2", "code": "P2-3", "location": f"{name}表",
                           "desc": f"{name}表头与标准结构不一致：{matched}",
                           "suggestion": f"核对表头是否为：{' | '.join(expected)}", "source": "脚本"})
        else:
            issues.append({"level": "P1", "code": "P1-10", "location": f"{name}表",
                           "desc": f"未检测到{name}表（表头匹配失败）",
                           "suggestion": f"检查是否缺失{name}表，表头应为：{' | '.join(expected)}",
                           "source": "脚本"})
    return issues


def check_fonts(doc):
    """字体抽查：统计非宋体/黑体 run 比例，检测标题是否深蓝。"""
    issues = []
    from docx.oxml.ns import qn
    counts = {"song": 0, "hei": 0, "other": 0, "navy": 0, "other_color": 0}
    for p in doc.paragraphs:
        for r in p.runs:
            rpr = r._element.rPr
            name = None
            color = None
            if rpr is not None:
                rf = rpr.find(qn("w:rFonts"))
                if rf is not None:
                    name = rf.get(qn("w:eastAsia")) or rf.get(qn("w:ascii"))
                c = rpr.find(qn("w:color"))
                if c is not None:
                    color = c.get(qn("w:val"))
            base = (name or "").lower()
            if "宋" in base or base in ("simsun", "song"):
                counts["song"] += 1
            elif "黑" in base or base in ("simhei", "hei"):
                counts["hei"] += 1
            else:
                counts["other"] += 1
            if color:
                if color.upper() == NAVY_HEX:
                    counts["navy"] += 1
                else:
                    counts["other_color"] += 1
    total = counts["song"] + counts["hei"] + counts["other"]
    if total and counts["other"] / total > 0.3:
        issues.append({"level": "P2", "code": "P2-1", "location": "全文",
                       "desc": f"非宋体/黑体 run 占比 {counts['other']/total:.0%}（抽查），字体可能不统一",
                       "suggestion": "正文统一宋体、标题黑体", "source": "脚本"})
    return issues


def check_page_setup(doc):
    """页面设置：A4、页边距。"""
    issues = []
    for i, s in enumerate(doc.sections):
        w, h = s.page_width, s.page_height
        if abs(w - A4_W_EMU) > 200 or abs(h - A4_H_EMU) > 200:
            issues.append({"level": "P2", "code": "P2-2", "location": f"节{i+1}",
                           "desc": f"页面非 A4（{w}x{h} EMU）", "suggestion": "设置为 A4 纵向",
                           "source": "脚本"})
        lm, rm, tm, bm = s.left_margin, s.right_margin, s.top_margin, s.bottom_margin
        if lm == 0 or rm == 0:
            issues.append({"level": "P2", "code": "P2-2", "location": f"节{i+1}",
                           "desc": "左右页边距为 0，疑似异常", "suggestion": "设置标准页边距", "source": "脚本"})
    return issues


def check_json_consistency(doc, data_path):
    """JSON 源数据与正文关键字段一致性（粗比对：关键数字串是否出现在正文中）。"""
    issues = []
    if not data_path or not os.path.exists(data_path):
        return issues
    try:
        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        issues.append({"level": "P2", "code": "P2-9", "location": "源数据",
                       "desc": f"无法读取 --data 文件：{e}", "suggestion": "检查 JSON 格式", "source": "脚本"})
        return issues
    full_text = "\n".join(p.text for p in doc.paragraphs)
    for tbl in doc.tables:
        for row in tbl.rows:
            for c in row.cells:
                full_text += "\n" + c.text
    checks = []
    inv = data.get("section1_basic", {}).get("investment", {})
    if inv.get("total"):
        checks.append(("总投资", str(inv.get("total"))))
    if inv.get("env"):
        checks.append(("环保投资", str(inv.get("env"))))
    s1 = data.get("section1_basic", {})
    if s1.get("total_capacity"):
        checks.append(("总设计产能", str(s1.get("total_capacity"))))
    if s1.get("phase_capacity"):
        checks.append(("验收规模", str(s1.get("phase_capacity"))))
    if s1.get("location"):
        checks.append(("建设地点", str(s1.get("location"))[:20]))
    for label, val in checks:
        if not val or val.startswith("【"):
            continue
        if val not in full_text:
            issues.append({"level": "P1", "code": "P1-11", "location": f"{label}",
                           "desc": f"源数据中的{label}（{val}）未在报告正文中找到",
                           "suggestion": "核对报告是否遗漏该数据或与源数据不一致", "source": "脚本"})
    return issues


def main():
    # Windows 控制台 UTF-8 输出（避免 GBK 终端中文乱码）
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="验收报告程序化审核")
    ap.add_argument("--docx", required=True, help="待审核的 .docx 报告路径")
    ap.add_argument("--data", default=None, help="可选：acceptance_data.json 源数据")
    ap.add_argument("--out", default=None, help="可选：问题清单 JSON 输出路径")
    args = ap.parse_args()

    if not os.path.exists(args.docx):
        sys.exit(f"报告文件不存在: {args.docx}")

    doc = Document(args.docx)
    paras = iter_paragraphs_with_index(doc)

    all_issues = []
    all_issues += check_chapters(paras)
    all_issues += check_placeholders(paras)
    all_issues += check_figure_numbering(paras)
    img_issues, sec_counts = check_images(doc, args.docx)
    all_issues += img_issues
    all_issues += check_tables(doc)
    all_issues += check_fonts(doc)
    all_issues += check_page_setup(doc)
    all_issues += check_json_consistency(doc, args.data)

    # 去重（同 code+location+desc）
    seen = set()
    uniq = []
    for it in all_issues:
        key = (it["level"], it["code"], it["location"], it["desc"])
        if key not in seen:
            seen.add(key)
            uniq.append(it)
    uniq.sort(key=lambda x: ({"P0": 0, "P1": 1, "P2": 2}[x["level"]], x["code"]))

    result = {
        "report": args.docx,
        "source_data": args.data,
        "image_sections": sec_counts,
        "issue_count": {"P0": sum(1 for i in uniq if i["level"] == "P0"),
                        "P1": sum(1 for i in uniq if i["level"] == "P1"),
                        "P2": sum(1 for i in uniq if i["level"] == "P2")},
        "issues": uniq,
    }

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    n0 = result["issue_count"]["P0"]
    n1 = result["issue_count"]["P1"]
    n2 = result["issue_count"]["P2"]
    print(f"审核完成：{args.docx}")
    print(f"  P0 致命: {n0}   P1 严重: {n1}   P2 一般: {n2}")
    for it in uniq:
        print(f"  [{it['level']}] {it['code']} {it['location']}: {it['desc']}")
    if n0:
        print("结论：打回重做（存在 P0 致命项）")
        sys.exit(2)
    if n1:
        print("结论：修改后复审（存在 P1 严重项）")
        sys.exit(1)
    print("结论：无 P0/P1，可进入人工/AI 复核")
    sys.exit(0)


if __name__ == "__main__":
    main()
