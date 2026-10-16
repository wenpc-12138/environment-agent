# -*- coding: utf-8 -*-
"""OCR/PDF 独立服务进程 - 许可证隔离的核心

本进程运行在独立 venv (runtime/ocr/venv), 是唯一允许 import 以下库的进程:
- pymupdf (fitz):      AGPL-3.0, 文字层提取 + 表格还原 + 扫描件渲染
- rapidocr_onnxruntime: Apache-2.0, 扫描版 PDF 逐页 OCR

Agent 主进程(kb_pipeline.py)不再 import 这两个库, 只经本进程 HTTP 接口调用,
与 SearXNG 模式一致 => 主程序不构成 AGPL 派生产品。

接口:
    GET  /health?quick=1  存活探测(quick 不加载 OCR 模型, 秒回)
    GET  /health          完整健康检查(加载模型确认可用, 较慢)
    POST /extract_pdf     {path, dpi?, max_pages?} -> {ok, text, char_count}
                          文字层+表格+标题 -> Markdown, <200字符自动 OCR 兜底
    POST /ocr_pdf         {path, dpi?, max_pages?} -> {ok, text, char_count}
                          纯逐页 OCR(扫描件), 文字层提取一律忽略
    POST /probe           {path, max_pages?} -> {ok, pages:[{idx,chars,type}], ...}
                          VLM 六步管线 Step 0: 每页文字层字符密度判定
                          type: text(>=50字) / hybrid(10-49) / image(<10)
    POST /probe_rich      {path, max_pages?} -> {ok, rich_pages}
                          轻量富内容探测: 含表格/公式/图片的页数(不加载模型, 秒级),
                          供主进程快速通道判断是否跳过 AI 结构化管线
    POST /render          {path, pages:[idx...], out_dir, dpi?} -> {ok, images:[{idx,png}]}
                          VLM 六步管线 Step 1: 指定页渲染 PNG(近似 dpi, 默认144), 许可证隔离
                          (fitz 渲染仅在本进程执行, 主进程不接触 AGPL 代码)
    POST /convert_rapid   {path, dpi?, max_pages?} -> {ok, text, char_count, meta}
                          路径A RapidAI 全家桶: RapidLayout 版面分析 -> RapidOCR 文字
                          -> RapidTable 表格结构 -> RapidLaTeXOCR 公式识别 -> Markdown 拼装
                          纯本地免 VLM, 适用于扫描版 PDF 转 MD 存档

用法:
    runtime\\ocr\\venv\\Scripts\\python.exe ocr_worker.py --port 8891
"""
import argparse
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_engine = None
_engine_lock = threading.Lock()

# RapidAI 全家桶懒加载引擎缓存 (RapidLayout / RapidTable / LaTeXOCR)
_rapid_engines = {}
_rapid_lock = threading.Lock()


def _get_ocr_engine():
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from rapidocr_onnxruntime import RapidOCR
                _engine = RapidOCR()
    return _engine


def _get_layout_engine():
    """RapidLayout 版面分析引擎(懒加载, 模型首次自动下载)"""
    key = "layout"
    if key not in _rapid_engines:
        with _rapid_lock:
            if key not in _rapid_engines:
                from rapid_layout import ModelType, RapidLayout, RapidLayoutInput
                _rapid_engines[key] = RapidLayout(
                    RapidLayoutInput(model_type=ModelType.PP_LAYOUT_CDLA)
                )
    return _rapid_engines[key]


def _get_table_engine():
    """RapidTable 表格结构引擎(懒加载, 模型首次自动下载)"""
    key = "table"
    if key not in _rapid_engines:
        with _rapid_lock:
            if key not in _rapid_engines:
                from rapid_table import ModelType, RapidTable, RapidTableInput
                _rapid_engines[key] = RapidTable(
                    RapidTableInput(model_type=ModelType.SLANETPLUS)
                )
    return _rapid_engines[key]


def _get_latex_engine():
    """RapidLaTeXOCR 公式识别引擎(懒加载, 模型首次自动下载)"""
    key = "latex"
    if key not in _rapid_engines:
        with _rapid_lock:
            if key not in _rapid_engines:
                from rapid_latex_ocr import LatexOCR
                engine = LatexOCR()
                _patch_latex_resizer(engine)
                _rapid_engines[key] = engine
    return _rapid_engines[key]


def _patch_latex_resizer(engine):
    """修复 rapid_latex_ocr 0.0.6 在 onnxruntime>=1.28 下的兼容 bug:
    image_resizer 输出 shape 为 (1, N), 原库 np.argmax(..., axis=-1) 得 1 维数组,
    int() 报 'only 0-dimensional arrays can be converted to Python scalars'。
    覆写 loop_image_resizer, 将 argmax 结果展平后取首个元素。"""
    orig = engine.loop_image_resizer

    def fixed(self, img):
        try:
            return orig(img)
        except TypeError:
            import numpy as np

            from PIL import Image

            pillow_img = Image.fromarray(img)
            pad_img = self.pre_pro.pad(pillow_img)
            input_image = self.pre_pro.minmax_size(pad_img).convert("RGB")
            r, w, h = 1, input_image.size[0], input_image.size[1]
            for _ in range(10):
                h = int(h * r)
                final_img, pad_img = self.pre_process(input_image, r, w, h)
                resizer_res = self.image_resizer([final_img.astype(np.float32)])[0]
                argmax_idx = int(np.argmax(resizer_res, axis=-1).reshape(-1)[0])
                w = (argmax_idx + 1) * 32
                if w == pad_img.size[0]:
                    break
                r = w / pad_img.size[0]
            return final_img

    engine.loop_image_resizer = lambda img: fixed(engine, img)
    return engine


def _rows_to_md_table(rows):
    rows = [[(c or "").strip().replace("\n", " ") for c in r] for r in rows]
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return ""
    w = max(len(r) for r in rows)
    lines = []
    for i, r in enumerate(rows):
        cells = (r + [""] * (w - len(r)))[:w]
        lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            lines.append("| " + " | ".join("---" for _ in range(w)) + " |")
    return "\n".join(lines)


def _ocr_pdf(path, dpi, max_pages):
    """扫描版 PDF 逐页渲染 + RapidOCR 识别, 失败页跳过"""
    import fitz
    import numpy as np
    engine = _get_ocr_engine()
    doc = fitz.open(path)
    pages = []
    try:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            try:
                pix = page.get_pixmap(dpi=dpi)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                if pix.n == 4:
                    img = img[:, :, :3]
                res, _ = engine(img)
                lines = [ln[1] for ln in (res or [])]
                if lines:
                    pages.append("\n".join(lines))
            except Exception:
                continue
    finally:
        doc.close()
    return "\n\n".join(pages).strip()


def _probe_pdf(path, max_pages):
    """VLM 六步管线 Step 0: 每页文字层字符密度判定。
    技术路线标准: >50字/页 纯文本(text) / 10-50 混合(hybrid) / <10 图像型(image)"""
    import fitz
    doc = fitz.open(path)
    pages = []
    try:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            try:
                chars = len((page.get_text() or "").strip())
            except Exception:
                chars = 0
            if chars >= 50:
                ptype = "text"
            elif chars >= 10:
                ptype = "hybrid"
            else:
                ptype = "image"
            pages.append({"idx": i, "chars": chars, "type": ptype})
    finally:
        doc.close()
    return pages


# 公式符号字体提示(Word/MathType 公式常以 Symbol/MT Extra/Euclid 等嵌入字体渲染,
# 文字层提取后符号错位成乱码, 必须走 RapidLaTeXOCR 渲染识别)
_MATH_FONT_HINTS = ("symbol", "mt extra", "mtextra", "euclid", "cambria math",
                    "stix", "latin modern math", "texgyre", "mathematica", "mathtype")


def _page_math_fonts(page):
    """页面含公式符号字体的字体名集合(Symbol/MT Extra/Euclid 等, 文字层提取后符号错位)"""
    fonts = set()
    try:
        d = page.get_text("dict")
        for b in d.get("blocks", []):
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    font = (span.get("font") or "").lower()
                    if any(k in font for k in _MATH_FONT_HINTS):
                        fonts.add(span.get("font"))
    except Exception:  # noqa: BLE001
        pass
    return fonts


def _page_has_rich_content(page):
    """轻量富内容检测: 表格(fitz 内置检测)/图片(插图或图片型公式)/公式符号字体。
    命中任一 => 页面需走 AI 结构化管线(RapidTable/RapidLaTeXOCR), 不能文字层直取。
    纯启发式, 不加载任何模型, 毫秒级返回。"""
    try:
        if page.find_tables().tables:
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        if page.get_images(full=True):
            return True
    except Exception:  # noqa: BLE001
        pass
    return bool(_page_math_fonts(page))


def _page_md_blocks(page):
    """页面内容块(表格 MD + 表格外文字行)按 y 坐标排序, 保留版面阅读顺序。
    标题行(size>=15 且短)加 ## 前缀, 与 _extract_pdf_md 规则一致。
    返回 (blocks, table_count)"""
    import fitz
    try:
        ft = page.find_tables().tables or []
    except Exception:  # noqa: BLE001
        ft = []
    boxes = [t.bbox for t in ft]
    blocks = []
    for t in ft:
        md = _rows_to_md_table(t.extract())
        if md:
            blocks.append((t.bbox.y0, md, True))
    try:
        d = page.get_text("dict")
        for b in d.get("blocks", []):
            if b.get("type") != 0:
                continue
            for line in b.get("lines", []):
                r = fitz.Rect(line.get("bbox") or (0, 0, 0, 0))
                if any(r.intersects(bx) for bx in boxes):
                    continue
                spans = line.get("spans", []) or []
                text = "".join(s.get("text", "") for s in spans).strip()
                if not text:
                    continue
                size = max((s.get("size", 0) for s in spans), default=0)
                # 与 _extract_pdf_md 一致: 排除单字竖排封面字与"发 布"式装饰字
                if size >= 15 and len(text) < 80 and not re.fullmatch(
                        r"[\u4e00-\u9fff]|[\u4e00-\u9fff][\s　]{1,}[\u4e00-\u9fff]", text):
                    text = "## " + text
                blocks.append((r.y0, text, False))
    except Exception:  # noqa: BLE001
        pass
    blocks.sort(key=lambda x: (x[0], x[2]))
    return [b[1] for b in blocks], sum(1 for b in blocks if b[2])


def _probe_rich_pdf(path, max_pages):
    """轻量富内容探测: 返回含表格/公式/图片的页数(供主进程快速通道判断)。
    只做启发式检测, 不加载任何 AI 模型, 秒级返回。"""
    import fitz
    doc = fitz.open(path)
    rich = 0
    try:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            try:
                if _page_has_rich_content(page):
                    rich += 1
            except Exception:  # noqa: BLE001
                continue
    finally:
        doc.close()
    return rich


def _render_pdf_pages(path, page_indexes, out_dir, dpi):
    """VLM 六步管线 Step 1: 指定页渲染为 PNG(近似 dpi, 默认144 = Matrix(2.0,2.0))。
    PNG 无损 + RGB 不透明, 供多模态 VLM 视觉理解直接读图。"""
    import fitz
    os.makedirs(out_dir, exist_ok=True)
    scale = max(dpi / 72.0, 0.5)
    matrix = fitz.Matrix(scale, scale)
    doc = fitz.open(path)
    imgs = []
    try:
        for idx in page_indexes:
            try:
                page = doc[idx]
                pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)
                png = os.path.join(out_dir, "page_%04d.png" % (idx + 1))
                pix.save(png)
                imgs.append({"idx": idx, "png": png})
            except Exception:
                continue
    finally:
        doc.close()
    return imgs


# CDLA 版面标签 -> 内容类别 (rapid_layout PP_LAYOUT_CDLA)
_LAYOUT_TITLE = {"title"}
_LAYOUT_TABLE = {"table"}
_LAYOUT_EQUATION = {"equation", "formula"}
_LAYOUT_TEXT = {
    "text", "paragraph", "content", "abstract", "keywords", "list", "reference",
    "toc", "author", "date", "caption", "note",
}
_LAYOUT_SKIP = {"footer", "header", "page_number", "seal", "stamp", "figure", "image"}


def _html_table_to_md(html):
    """RapidTable 输出的 <html><table>... -> Markdown 表格。
    解析 tr/td/th, 处理 rowspan/colspan 基本场景, 失败返回 None。"""
    try:
        m = re.search(r"<table[^>]*>(.*?)</table>", html, re.S | re.I)
        if not m:
            return None
        rows_html = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S | re.I)
        rows = []
        for rh in rows_html:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", rh, re.S | re.I)
            row = []
            for c in cells:
                rs = re.search(r'rowspan\s*=\s*"?(\d+)"?', c, re.I)
                cs = re.search(r'colspan\s*=\s*"?(\d+)"?', c, re.I)
                rowspan = int(rs.group(1)) if rs else 1
                colspan = int(cs.group(1)) if cs else 1
                txt = re.sub(r"<[^>]+>", "", c)
                txt = re.sub(r"\s+", " ", txt).strip()
                for _ in range(colspan):
                    row.append(txt)
            rows.append(row)
        rows = [r for r in rows if any(c for c in r)]
        if not rows:
            return None
        w = max(len(r) for r in rows)
        lines = []
        for i, r in enumerate(rows):
            cells = (r + [""] * (w - len(r)))[:w]
            lines.append("| " + " | ".join(cells) + " |")
            if i == 0:
                lines.append("| " + " | ".join("---" for _ in range(w)) + " |")
        return "\n".join(lines)
    except Exception:  # noqa: BLE001
        return None


def _text_garbled(s):
    """文字层乱码检测: � 替换符/不可打印控制符占比 >=10% 视为乱码(字体无 ToUnicode 映射, 需走 OCR)"""
    if not s:
        return True
    bad = sum(1 for ch in s if ch == "\ufffd" or (ord(ch) < 32 and ch not in "\n\t"))
    return bad / len(s) >= 0.10


def _full_page_ocr(img):
    """整页 OCR: 一次调用识别整页文字。单栏正文扫描件比分区 OCR 更快、行序更稳。"""
    engine = _get_ocr_engine()
    res, _ = engine(img)
    lines = [ln[1] for ln in (res or [])]
    lines = [ln.strip() for ln in lines if ln and ln.strip()]
    return "\n".join(lines) if lines else ""


def _full_page_ocr_lines(img):
    """整页 OCR -> [(text, 4点box), ...] (已去空白行), 失败返回 []。供表格页文字区域按坐标裁剪复用。"""
    engine = _get_ocr_engine()
    res, _ = engine(img)
    out = []
    for r in (res or []):
        txt = (r[1] or "").strip()
        if txt:
            out.append((txt, r[0]))
    return out


def _region_text_from_lines(ocr_lines, x1, y1, x2, y2):
    """从整页 OCR 行中取中心点落在 [x1,y1,x2,y2] 区域内的行, 按 y 排序拼为一行。"""
    hits = []
    for txt, box in ocr_lines:
        try:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
        except Exception:  # noqa: BLE001
            continue
        if x1 - 2 <= cx <= x2 + 2 and y1 - 2 <= cy <= y2 + 2:
            hits.append((cy, txt))
    hits.sort(key=lambda t: t[0])
    return " ".join(t[1] for t in hits) if hits else ""


def _convert_rapid_md(path, dpi, max_pages):
    """路径A RapidAI 全家桶: 逐页渲染 -> RapidLayout 版面分析 -> 分区处理
    (title/text OCR / table RapidTable / equation RapidLaTeXOCR) -> MD 拼装。
    纯本地免 VLM; 单页失败跳过, 返回 (markdown, stats)。

    加速优化(针对半扫描/纯扫描件):
    1) 文字层直取: 页文字层 >=50 字符且非乱码 -> 直接使用, 跳过全部 AI 推理(秒级);
    2) 整页 OCR: 版面分析无表格/公式的页 -> 一次整页 RapidOCR, 替代多区域分区 OCR(约快 2 倍)。"""
    import fitz
    import numpy as np

    doc = fitz.open(path)
    stats = {"pages": 0, "tables": 0, "equations": 0, "skipped": 0, "ocr": 0, "text": 0}
    out_pages = []
    try:
        for pno, page in enumerate(doc):
            if pno >= max_pages:
                break
            try:
                # 0) 文字层直取(需有真实文字层且非乱码, 且页面无表格/公式/图片,
                #    否则直取会丢失表格结构与公式符号, 必须走 AI 结构化管线)
                tl = (page.get_text("text") or "").strip()
                if (len(tl) >= 50 and not _text_garbled(tl)
                        and not _page_has_rich_content(page)):
                    out_pages.append(tl)
                    stats["text"] += 1
                    stats["pages"] += 1
                    continue
                # 0.5) 富内容页 fitz 表格保底: 有文字层、无公式符号字体、且几何检测到表格
                #      -> 直接用 fitz find_tables 提取表格 MD + 表格外文字层。
                #      RapidLayout 常把线框表格误判为 text, 此分支保证表格结构不丢失, 且免 AI 推理。
                if len(tl) >= 50 and not _text_garbled(tl) and not _page_math_fonts(page):
                    try:
                        _blocks, _n_tbl = _page_md_blocks(page)
                    except Exception:  # noqa: BLE001
                        _blocks, _n_tbl = [], 0
                    if _blocks:
                        joined = "\n\n".join(_blocks)
                        if joined:
                            out_pages.append(joined)
                            stats["tables"] += _n_tbl
                            stats["pages"] += 1
                            continue
                pix = page.get_pixmap(dpi=dpi)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                    pix.height, pix.width, pix.n
                )
                if pix.n == 4:
                    img = img[:, :, :3]
                elif pix.n == 1:
                    img = np.stack([img] * 3, axis=-1)
                layout = _get_layout_engine()(img)
                if not layout.boxes or not layout.class_names:
                    continue
                # 0.5) 无表格/公式页 -> 整页 OCR(单栏正文更快更稳), 跳过分区处理
                classes = set(layout.class_names)
                if not (classes & (_LAYOUT_TABLE | _LAYOUT_EQUATION)):
                    txt = _full_page_ocr(img)
                    if txt:
                        out_pages.append(txt)
                        stats["ocr"] += 1
                        stats["pages"] += 1
                    continue
                # 页面内区域: 分类收集
                regions = []
                for box, cls in zip(layout.boxes, layout.class_names):
                    x1, y1, x2, y2 = [int(v) for v in box]
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(img.shape[1], x2), min(img.shape[0], y2)
                    if x2 - x1 < 8 or y2 - y1 < 8:
                        continue
                    regions.append((cls, x1, y1, x2, y2))
                if not regions:
                    continue
                regions.sort(key=lambda r: (r[2], r[1]))  # 先 y 后 x
                # 含表/公式页: 整页 OCR 一次, 文字区域按坐标裁剪, 避免逐区域多次 OCR(大幅提速)
                ocr_lines = _full_page_ocr_lines(img)
                blocks = []
                for cls, x1, y1, x2, y2 in regions:
                    try:
                        if cls in _LAYOUT_SKIP:
                            continue
                        if cls in _LAYOUT_TABLE:
                            crop = img[y1:y2, x1:x2]
                            if crop.size == 0:
                                continue
                            md = _table_region_to_md(crop)
                            if md:
                                blocks.append(("table", md))
                                stats["tables"] += 1
                            continue
                        if cls in _LAYOUT_EQUATION:
                            crop = img[y1:y2, x1:x2]
                            if crop.size == 0:
                                continue
                            latex = _equation_region_to_latex(crop)
                            if latex:
                                blocks.append(("equation", latex))
                                stats["equations"] += 1
                            continue
                        # 文字区域 (title/text/...): 优先用整页 OCR 结果按坐标裁剪, 失败回退分区 OCR
                        text = _region_text_from_lines(ocr_lines, x1, y1, x2, y2) if ocr_lines else ""
                        if not text:
                            crop = img[y1:y2, x1:x2]
                            if crop.size == 0:
                                continue
                            text = _text_region_to_text(crop)
                        if text:
                            if cls in _LAYOUT_TITLE:
                                blocks.append(("title", text))
                            else:
                                blocks.append(("text", text))
                    except Exception:  # noqa: BLE001
                        stats["skipped"] += 1
                        continue
                # 同页合并成 MD
                page_md = []
                prev_kind = None
                for kind, content in blocks:
                    if kind in ("title", "text"):
                        sep = "\n" if prev_kind == kind else "\n\n"
                    elif kind == "table":
                        sep = "\n\n"
                    else:
                        sep = "\n\n"
                    page_md.append(sep + content)
                    prev_kind = kind
                joined = "".join(page_md).strip()
                if joined:
                    out_pages.append(joined)
                    stats["pages"] += 1
            except Exception:  # noqa: BLE001
                stats["skipped"] += 1
                continue
    finally:
        doc.close()
    # 按 PDF 原始页分页: 页边界插入分隔线 + 页码注释, 渲染时可见分页、检索可定位页码
    parts = []
    for i, pmd in enumerate(out_pages, 1):
        if i > 1:
            parts.append("---\n\n<!-- PDF 第 %d 页 -->" % i)
        parts.append(pmd)
    return "\n\n".join(parts).strip(), stats


def _text_region_to_text(crop):
    """文字区域 -> RapidOCR 逐行文本(空格连接)"""
    engine = _get_ocr_engine()
    res, _ = engine(crop)
    lines = [ln[1] for ln in (res or [])]
    lines = [ln.strip() for ln in lines if ln and ln.strip()]
    return " ".join(lines) if lines else ""


def _table_region_to_md(crop):
    """表格区域 -> RapidTable(区域 OCR 结果) -> HTML -> Markdown"""
    from rapid_table import ModelType, RapidTable, RapidTableInput

    ocr_engine = _get_ocr_engine()
    res, _ = ocr_engine(crop)
    if not res:
        return ""
    boxes = [r[0] for r in res]
    txts = [r[1] for r in res]
    scores = [r[2] for r in res]
    table = _get_table_engine()
    out = table(crop, ocr_results=[(boxes, txts, scores)])
    if not out.pred_htmls:
        return ""
    md = _html_table_to_md(out.pred_htmls[0])
    return md or ""


def _equation_region_to_latex(crop):
    """公式区域 -> RapidLaTeXOCR -> $$ LaTeX $$"""
    engine = _get_latex_engine()
    latex, _ = engine(crop)
    latex = (latex or "").strip()
    if not latex:
        return ""
    return "$$\n" + latex + "\n$$"


def _extract_pdf_md(path, dpi, max_pages):
    """文字层提取(表格/标题/段落) -> Markdown, <200字符自动 OCR 兜底"""
    import fitz
    doc = fitz.open(path)
    out = []
    try:
        for pno, page in enumerate(doc, 1):
            page_items = []
            try:
                for t in (page.find_tables().tables or []):
                    md = _rows_to_md_table(t.extract())
                    if md:
                        page_items.append(md)
            except Exception:
                pass
            for b in page.get_text("dict").get("blocks", []):
                if b.get("type") != 0:
                    continue
                for line in b.get("lines", []):
                    spans = line.get("spans", []) or []
                    text = "".join(s.get("text", "") for s in spans).strip()
                    if not text:
                        continue
                    size = max((s.get("size", 0) for s in spans), default=0)
                    # 标题判定: 字号大且为真实短语; 仅排除单字竖排封面字(如"生/态/环/境/部")
                    # 与"发 布"式装饰字, 保留"水质""测定"等 2 字真标题, 保证 MD 字体渲染一致
                    if size >= 15 and len(text) < 80 and not re.fullmatch(
                            r"[\u4e00-\u9fff]|[\u4e00-\u9fff][\s　]{1,}[\u4e00-\u9fff]", text):
                        page_items.append("## " + text)
                    else:
                        page_items.append(text)
            # 按 PDF 原始页分页: 页边界插入分隔线 + 页码注释
            if pno > 1:
                out.append("---\n\n<!-- PDF 第 %d 页 -->" % pno)
            out.extend(page_items)
    finally:
        doc.close()
    md = "\n\n".join(out).strip()
    # OCR 兜底判定: 剔除页面分隔注释后真实文本过少(扫描件文字层为空, 只剩页标记)才触发 OCR
    _real = re.sub(r"<!-- PDF 第 \d+ 页 -->|---", "", md).strip()
    if len(_real) < 200:
        try:
            ocr = _ocr_pdf(path, dpi, max_pages)
            if ocr and len(ocr) > len(_real):
                md = ocr
        except Exception:
            pass
    return md


class Handler(BaseHTTPRequestHandler):
    server_version = "OCRWorker/1.0"

    def log_message(self, fmt, *args):  # 静默访问日志
        return

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?", 1)[0] != "/health":
            self._send({"ok": False, "error": "not found"}, 404)
            return
        quick = self.path.split("?", 1)[1] if "?" in self.path else ""
        if quick and "quick=1" in quick:
            self._send({"ok": True, "pid": os.getpid(), "quick": True})
            return
        try:
            _get_ocr_engine()
            self._send({"ok": True, "pid": os.getpid(), "model": "rapidocr", "engine": "ready"})
        except Exception as e:  # noqa: BLE001
            self._send({"ok": False, "pid": os.getpid(), "error": str(e)}, 503)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            self._send({"ok": False, "error": "bad request"}, 400)
            return
        path = data.get("path") or ""
        if not path or not os.path.isfile(path):
            self._send({"ok": False, "error": f"file not found: {path}"}, 404)
            return
        dpi = int(data.get("dpi") or 200)
        max_pages = int(data.get("max_pages") or 300)
        route = self.path.split("?", 1)[0]
        try:
            if route == "/extract_pdf":
                text = _extract_pdf_md(path, dpi, max_pages)
            elif route == "/ocr_pdf":
                text = _ocr_pdf(path, dpi, max_pages)
            elif route == "/probe":
                pages = _probe_pdf(path, max_pages)
                self._send({
                    "ok": True, "pages": pages, "total": len(pages),
                    "image_pages": sum(1 for p in pages if p["type"] == "image"),
                    "hybrid_pages": sum(1 for p in pages if p["type"] == "hybrid"),
                    "text_pages": sum(1 for p in pages if p["type"] == "text"),
                })
                return
            elif route == "/probe_rich":
                rich = _probe_rich_pdf(path, max_pages)
                self._send({"ok": True, "rich_pages": rich})
                return
            elif route == "/render":
                out_dir = data.get("out_dir") or ""
                pages = [int(x) for x in (data.get("pages") or [])]
                if not out_dir or not pages:
                    self._send({"ok": False, "error": "out_dir 与 pages 必填"}, 400)
                    return
                if len(pages) > max_pages:
                    pages = pages[:max_pages]
                imgs = _render_pdf_pages(path, pages, out_dir, dpi)
                self._send({"ok": True, "images": imgs})
                return
            elif route == "/convert_rapid":
                text, meta = _convert_rapid_md(path, dpi, max_pages)
                self._send({
                    "ok": True, "text": text, "char_count": len(text), "meta": meta,
                })
                return
            else:
                self._send({"ok": False, "error": "not found"}, 404)
                return
            self._send({"ok": True, "text": text, "char_count": len(text)})
        except Exception as e:  # noqa: BLE001
            self._send({"ok": False, "error": str(e)}, 500)


def _warmup_engines():
    """后台预热: 预加载 RapidOCR + RapidLayout 模型(冷启动约 1-2 分钟),
    避免用户首次上传扫描件时等待模型加载; 失败静默, 请求仍按懒加载兜底。"""
    try:
        _get_ocr_engine()
        _get_layout_engine()
    except Exception:  # noqa: BLE001
        pass


def main():
    ap = argparse.ArgumentParser(description="OCR/PDF 独立服务进程")
    ap.add_argument("--port", type=int, default=8891)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    # 启动即后台预热 OCR/Layout 模型, 不阻塞服务端口响应
    threading.Thread(target=_warmup_engines, daemon=True).start()
    print(f"[ocr_worker] listening on {args.host}:{args.port} pid={os.getpid()}",
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
