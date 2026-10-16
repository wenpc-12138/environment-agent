#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_docx_images.py
----------------------
从验收报告 docx 提取全部内嵌图片，并生成上下文映射 map.json，
供 ep-acceptance-review 技能第 3 步（AI 视觉核对）逐张读图使用。

输出目录结构：
    <out>/
    ├── images/          # 按出现顺序编号的图片（001.jpg, 002.png ...）
    └── map.json         # [{index, filename, section, context_before,
                         #    caption_candidates}]

说明：
- section：图片所在章节（按八章/附图/附件锚点归属，取最近的上一个标题，
  附图/附件精确到"附图N/附件N"小节）。
- caption_candidates：图片所在段落前后各 2 段中的非空文本（图注可能位于图片
  之前或之后），供 AI 核对"图注 ↔ 图片内容"是否匹配。
- 同一文件在不同位置重复出现会分别记录（用于检测重复插图问题）。

用法:
    python extract_docx_images.py --docx 验收报告.docx --out extracted/

依赖: python-docx
"""
import argparse
import json
import os
import re
import shutil
import sys
import zipfile
from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

CHAPTER_ANCHORS = [
    "一、工程建设基本情况", "二、工程变动情况", "三、环境保护设施建设情况",
    "四、环境保护设施调试效果", "五、工程建设对环境的影响", "六、制度落实情况",
    "七、验收结论", "八、后续要求",
]
FIG_SECTION_RE = re.compile(r"^(附图|附件)\s*\d+")


def media_basename(rid, rels, zf):
    """由 rId 解析出实际 media 文件名（兼容多种 Target 写法）。"""
    try:
        target = rels[rid]
    except Exception:
        return None
    base = os.path.basename(target)
    cands = [target, base, "word/" + base, "word/media/" + base]
    for c in cands:
        if c in zf.namelist():
            return c
    return None


def collect_paras(doc):
    """遍历 body 级段落，返回 [{text, has_img, section, elem}]。"""
    from docx.oxml.ns import qn as _qn
    body = doc.element.body
    current_section = "封面/前部"
    paras = []
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            p = Paragraph(child, doc)
            text = "".join(t.text or "" for t in child.iter(_qn("w:t"))).strip()
            if text:
                for anchor in CHAPTER_ANCHORS:
                    if text.startswith(anchor):
                        current_section = anchor
                m = FIG_SECTION_RE.match(text)
                if m:
                    current_section = text
                elif text.startswith(("附图", "附件", "验收意见")):
                    current_section = text
            has_img = bool(child.findall(".//" + _qn("w:drawing")) or
                           child.findall(".//" + _qn("w:pict")) or
                           child.findall(".//" + _qn("w:object")))
            paras.append({"text": text, "has_img": has_img,
                          "section": current_section, "elem": child})
    return paras


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="提取 docx 内嵌图片与上下文映射")
    ap.add_argument("--docx", required=True, help="验收报告 .docx 路径")
    ap.add_argument("--out", required=True, help="输出目录（将创建 images/ 与 map.json）")
    args = ap.parse_args()

    if not os.path.exists(args.docx):
        sys.exit(f"报告文件不存在: {args.docx}")

    os.makedirs(os.path.join(args.out, "images"), exist_ok=True)
    doc = Document(args.docx)
    all_paras = collect_paras(doc)

    with zipfile.ZipFile(args.docx) as zf:
        # rId -> target 映射（从 document.xml.rels 解析）
        rels = {}
        rels_path = "word/_rels/document.xml.rels"
        if rels_path in zf.namelist():
            content = zf.read(rels_path).decode("utf-8", "ignore")
            for m in re.finditer(r'Id="([^"]+)"[^>]*Target="([^"]+)"', content):
                rels[m.group(1)] = m.group(2)

        # 收集每个含图段落的图片引用（同一文件同段落只记一次，跨段落重复保留）
        pending = []  # (mname, section, para_index)
        seen = set()
        for pi, para in enumerate(all_paras):
            if not para["has_img"]:
                continue
            blips = para["elem"].findall(".//" + qn("a:blip"))
            if not blips:
                blips = para["elem"].findall(".//" + qn("v:imagedata"))
            for b in blips:
                rid = b.get(qn("r:embed")) or b.get(qn("r:id"))
                if not rid:
                    continue
                mname = media_basename(rid, rels, zf)
                if not mname:
                    continue
                key = (mname, pi)
                if key in seen:
                    continue
                seen.add(key)
                pending.append((mname, para["section"], pi))

        # 输出图片 + 构造 map
        entries = []
        for mname, section, pi in pending:
            idx = len(entries) + 1
            ext = os.path.splitext(mname)[1].lower() or ".bin"
            out_name = f"{idx:03d}{ext}"
            out_path = os.path.join(args.out, "images", out_name)
            with zf.open(mname) as src, open(out_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            before = [all_paras[j]["text"] for j in range(max(0, pi - 2), pi)
                      if all_paras[j]["text"]]
            after = [all_paras[j]["text"] for j in range(pi + 1, min(len(all_paras), pi + 3))
                     if all_paras[j]["text"]]
            captions = before[-1:] + after[:2]
            entries.append({
                "index": idx,
                "filename": out_name,
                "section": section,
                "context_before": before[-1] if before else "",
                "caption_candidates": captions,
            })

        with open(os.path.join(args.out, "map.json"), "w", encoding="utf-8") as f:
            json.dump({"docx": args.docx, "total_images": len(entries), "images": entries},
                      f, ensure_ascii=False, indent=2)

    print(f"提取完成：共 {len(entries)} 张图片（含重复位置）")
    print(f"  图片目录: {os.path.join(args.out, 'images')}")
    print(f"  映射文件: {os.path.join(args.out, 'map.json')}")
    if not entries:
        print("提示：未提取到任何内嵌图片，请确认 docx 是否包含图片。")


if __name__ == "__main__":
    main()
