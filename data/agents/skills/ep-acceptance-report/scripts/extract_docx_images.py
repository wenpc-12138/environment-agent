#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_docx_images.py
-----------------------
从既有验收报告 .docx 模板中提取内嵌图片，按"标题 + 序号"命名保存到输出目录，
并打印 图片 → 所在标题 的映射，便于将其映射到生成器的 figures/appendices/photos 字段。

用法:
    python extract_docx_images.py --doc 模板.docx --out images_dir

说明:
    - 图片按文档顺序编号，文件名形如 03_附图4_厂区总平面布置图.png（扩展名按原图）。
    - 控制台同时输出映射表，可直接复制到 acceptance_data.json 的 figures/appendices 中。
"""
import argparse
import os
import re
import sys
from docx import Document
from docx.oxml.ns import qn

HEAD_RE = re.compile(r"^(附图\d+|附件\d+|图\d+|附[:：].*|项目.{0,6}图|公示|营业执照|环评批复)")


def main():
    ap = argparse.ArgumentParser(description="从 docx 提取内嵌图片并映射标题")
    ap.add_argument("--doc", required=True, help="源 docx 模板路径")
    ap.add_argument("--out", required=True, help="图片输出目录")
    args = ap.parse_args()

    if not os.path.exists(args.doc):
        sys.exit(f"文件不存在: {args.doc}")
    os.makedirs(args.out, exist_ok=True)

    doc = Document(args.doc)
    current_heading = "(文档开头)"
    idx = 0
    mapping = []
    for p in doc.paragraphs:
        txt = p.text.strip()
        if txt:
            current_heading = txt
        # 查找该段落中的图片
        for el in p._element.iter():
            if el.tag == qn("a:blip"):
                rId = el.get(qn("r:embed"))
                if not rId:
                    continue
                part = doc.part.related_parts.get(rId)
                if part is None:
                    continue
                idx += 1
                blob = part.blob
                ext = os.path.splitext(str(part.partname))[1].lstrip(".").lower() or "png"
                safe_head = re.sub(r"[\\/:*?\"<>|]", "_", current_heading)[:40]
                fname = f"{idx:02d}_{safe_head}.{ext}"
                fpath = os.path.join(args.out, fname)
                with open(fpath, "wb") as f:
                    f.write(blob)
                mapping.append((fname, current_heading))

    print(f"已提取 {len(mapping)} 张图片到: {args.out}\n")
    print("图片 → 所在标题 映射（复制 path 到 JSON 的 figures/appendices）：")
    for fname, head in mapping:
        print(f"  {fname}\t← {head}")
    if not mapping:
        print("  （未发现内嵌图片，模板可能以链接方式引用图片）")


if __name__ == "__main__":
    main()
