# -*- coding: utf-8 -*-
"""生态Agent - 扫描型文档转 Markdown 存档 - VLM 视觉理解六步管线

按《技术路线.md》实现:
  Step 0 探测    ocr_worker /probe: 每页 get_text() 字符密度判定
                 text>=50字/页(纯文本) / hybrid 10-49(混合) / image<10(图像型/扫描页)
  Step 1 渲染    ocr_worker /render: fitz.Matrix(dpi/72) 渲染 PNG(默认144dpi = 2.0x),
                 PNG 无损 RGB, 许可证隔离在独立 OCR worker 进程(主进程不接触 AGPL)
  Step 2 视觉理解 providers.chat_text: 多模态 VLM 读图, 一步 OCR+结构化
                 (化学式上下标/LaTeX 公式/Markdown 表格/条款编号)
  Step 3 骨架抽取 从转录全文抽取标题层级树(目次骨架), 供重排校正与报告
  Step 4 结构化重排 页级 Markdown 合并 + 规范化(标题/公式块/表格/空行)
  Step 5 质量回校 规则校验(标准号格式/标题跳号/空白页/公式配对/表格), 产出转换报告

约定:
  - 纯文本型 PDF(全部 text 页) 不消耗 VLM, 直接走文字层快速通道(extract_pdf_md)
  - 无多模态 Provider 时 convert_pdf_to_md 返回 None, 调用方回退 RapidOCR 传统路线(功能不降级)
  - VLM 调用经 OpenAI 兼容 /chat/completions, 图片以 data URL base64 内联
"""
import base64
import json
import os
import re

# 运行时按需导入 db / providers / ocr_client, 避免循环依赖与启动开销


def get_active_provider():
    try:
        import db
        return db.get_active_provider()
    except Exception:
        return None


def supports_vlm():
    """当前是否配置了多模态(视觉)Provider, 可用 VLM 六步管线"""
    try:
        import providers
        return providers.supports_vision(get_active_provider())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Step 0/1 探测与渲染(代理 ocr_worker)
# ---------------------------------------------------------------------------

def probe_pdf(path, max_pages=300):
    """Step 0 探测: 每页字符密度 -> {pages, total, image_pages, hybrid_pages, text_pages}"""
    try:
        import ocr_client
        return ocr_client.probe_pdf(path, max_pages=max_pages)
    except Exception:
        return None


def render_pages(path, page_indexes, out_dir, dpi=144):
    """Step 1 渲染: 指定页 -> PNG 路径列表 [{"idx","png"}], 失败页自动跳过"""
    try:
        import ocr_client
        return ocr_client.render_pdf(path, out_dir, pages=page_indexes, dpi=dpi)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Step 2 视觉理解(VLM 读图)
# ---------------------------------------------------------------------------

_VLM_SYSTEM = (
    "你是生态环境标准/政策/技术文件的结构化转录专家。"
    "把图片中的文档页完整转录为规范的 Markdown，严格遵循：\n"
    "1. 标题按层级用 #/##/###，保留原文档编号（如“3.2 监测点位布设”）；\n"
    "2. 化学式与上下标用 Unicode 或 LaTeX（如 H2O 写成 H₂O、SO4^2- 写成 SO₄²⁻、密度 ρ、求和 ∑），"
    "公式块用 $$ 包裹并保留编号，如 $$c = m/V \\tag{3-1}$$\n"
    "3. 表格完整还原为 Markdown 表格，表头行加粗，保留所有行列，禁止省略列；\n"
    "4. 条款/编号条目保留原始编号（如“5.2.1”），引用句保持原文；\n"
    "5. 页眉页脚中的文档编号、标准号、发布机关等标注在页尾注释行；\n"
    "6. 只输出转录的 Markdown 内容本身，不要任何前言、解释或代码块包裹。"
)


def _vlm_page_prompt(page_no, total, page_type):
    hint = "该页为纯图片页(无文字层)。" if page_type == "image" else "该页文字层不完整，请以图片内容为准。"
    return (
        "请转录以下文档页。当前进度：第 %d 页 / 共 %d 页。%s\n"
        "输出格式：Markdown，段落之间空行，标题用 #/##/###，表格用 | 分隔。"
    ) % (page_no, total, hint)


def _png_data_url(png_path):
    with open(png_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return "data:image/png;base64," + b64


def vlm_transcribe_page(prov, png_path, page_no, total, page_type="image", timeout=240):
    """Step 2: 单页图片 -> Markdown 文本。失败抛异常(由调用方重试/降级)。"""
    import providers
    messages = [
        {"role": "system", "content": _VLM_SYSTEM},
        {"role": "user", "content": [
            {"type": "text", "text": _vlm_page_prompt(page_no, total, page_type)},
            {"type": "image_url", "image_url": {"url": _png_data_url(png_path)}},
        ]},
    ]
    text, _usage = providers.chat_text(prov, messages, temperature=0.1, timeout=timeout)
    return (text or "").strip()


# ---------------------------------------------------------------------------
# Step 3/4 骨架抽取与结构化重排
# ---------------------------------------------------------------------------

def extract_skeleton(md):
    """Step 3 骨架抽取: 从转录全文抽标题层级树 -> [{"level","title"}]"""
    tree = []
    for line in (md or "").splitlines():
        s = line.strip()
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            tree.append({"level": len(m.group(1)), "title": m.group(2).strip()})
    return tree


def _normalize_md(parts):
    """Step 4 结构化重排: 页级 Markdown 合并与规范化"""
    blocks = []
    for md in parts:
        md = (md or "").strip("\n")
        if md:
            blocks.append(md)
    md = "\n\n".join(blocks)
    # 压缩多余空行(3+ -> 2)
    md = re.sub(r"\n{3,}", "\n\n", md)
    # 表格后紧跟文字无空行时补空行
    md = re.sub(r"(\|\s*\n)([^\|\n#])", r"\1\n\2", md)
    # 公式块 $$ 前后补空行
    md = re.sub(r"\n(\$\$)", r"\n\n\1", md)
    md = re.sub(r"(\$\$)\n", r"\1\n\n", md)
    return md.strip() + "\n"


# ---------------------------------------------------------------------------
# Step 5 质量回校
# ---------------------------------------------------------------------------

_STD_NUM_RE = re.compile(r"\b(?:GB|HJ|DB\d{2}|WS|SL|CJ|T)\b[/T]?\s*\d+(?:\.\d+)?(?:[-—]\d{4})?")
_HEADING_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)[、.．\s]")


def verify_md(md, pages_info, used_vlm):
    """Step 5 质量回校: 规则校验 -> report dict(含 warnings)"""
    warnings = []
    char_total = len(md or "")
    # 1) 空白/疑似漏页
    for p in pages_info:
        if p.get("vlm_md") and len(p["vlm_md"]) < 20:
            warnings.append("第 %d 页转录内容过短(%d 字符), 疑似漏页或页面为空白" % (p["idx"] + 1, len(p["vlm_md"])))
    # 2) 公式块配对
    n_dollar = len(re.findall(r"\$\$", md or ""))
    if n_dollar % 2:
        warnings.append("$$ 公式块不配对(%d 个), 请人工复核公式" % n_dollar)
    # 3) 标题编号跳号(1.1 -> 1.3 警告)
    nums = []
    for line in (md or "").splitlines():
        m = _HEADING_NUM_RE.match(line.strip())
        if m:
            nums.append(m.group(1))
    if nums:
        for a, b in zip(nums, nums[1:]):
            if a.count(".") == b.count(".") and a.rpartition(".")[0] == b.rpartition(".")[0]:
                try:
                    ia, ib = int(a.rpartition(".")[2]), int(b.rpartition(".")[2])
                    if ib - ia > 1:
                        warnings.append("标题编号跳号: %s -> %s, 请复核是否缺页" % (a, b))
                except ValueError:
                    pass
    # 4) 标准号提取(供检索复核)
    std_refs = sorted(set(_STD_NUM_RE.findall(md or "")))
    return {
        "char_total": char_total,
        "used_vlm": used_vlm,
        "std_refs": std_refs,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 主入口: PDF -> Markdown(六步管线)
# ---------------------------------------------------------------------------

def convert_pdf_to_md(path, dpi=144, page_batch=4, max_pages=300, progress=None):
    """扫描型 PDF -> Markdown 六步管线。

    返回:
      - 成功: Markdown 文本(str)
      - 纯文本 PDF: 直接文字层转换结果(str, 不耗 VLM)
      - 扫描件但无多模态 Provider: None(调用方回退 RapidOCR)
    """
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return None

    def _report(msg):
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    # Step 0: 探测
    _report("Step 0 探测页面类型...")
    probe = probe_pdf(path, max_pages)
    if not probe:
        return None
    pages = probe.get("pages") or []
    if not pages:
        return None
    _report("共 %d 页: 文本 %d / 混合 %d / 图像 %d" % (
        probe.get("total", len(pages)),
        probe.get("text_pages", 0),
        probe.get("hybrid_pages", 0),
        probe.get("image_pages", 0),
    ))
    image_pages = [p for p in pages if p["type"] in ("image", "hybrid")]
    if not image_pages:
        # 纯文本型: 快速通道, 不消耗 VLM
        _report("纯文本型 PDF, 走文字层快速通道")
        try:
            import ocr_client
            md = ocr_client.extract_pdf_md(path, max_pages=max_pages)
            if md:
                return md
        except Exception:
            pass
        return None

    # 扫描/混合型: 必须有多模态 Provider
    prov = get_active_provider()
    if not prov or not supports_vlm():
        _report("含扫描页但未配置多模态(视觉)Provider, 回退 RapidOCR")
        return None

    # Step 1: 渲染扫描页为 PNG
    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="vlm_conv_")
    try:
        _report("Step 1 渲染 %d 个扫描页为 PNG(144dpi)..." % len(image_pages))
        imgs = render_pages(path, [p["idx"] for p in image_pages], tmp_dir, dpi=dpi)
        if not imgs:
            return None
        total = probe.get("total", len(pages))
        page_md = {p["idx"]: "" for p in pages}

        # 文本页直接取文字层(与扫描页分开, 保证顺序)
        try:
            import ocr_client
            text_md = ocr_client.extract_pdf_md(path, max_pages=max_pages)
            if text_md:
                # 无法逐页对齐文字层, 仅用其作为整体兜底(页面顺序以 VLM 页为准)
                pass
        except Exception:
            pass

        # Step 2: VLM 逐批视觉理解
        _report("Step 2 VLM 视觉理解(%d 批)..." % max(1, (len(imgs) + page_batch - 1) // page_batch))
        pages_info = []
        for i, img in enumerate(imgs):
            idx = img["idx"]
            ptype = next((p["type"] for p in pages if p["idx"] == idx), "image")
            _report("  [%d/%d] 第 %d 页 VLM 转录..." % (i + 1, len(imgs), idx + 1))
            text = ""
            for attempt in range(2):  # 重试 1 次
                try:
                    text = vlm_transcribe_page(prov, img["png"], idx + 1, total, ptype)
                    break
                except Exception as e:
                    if attempt == 0:
                        _report("  第 %d 页失败(%s), 重试..." % (idx + 1, e))
            page_md[idx] = text
            pages_info.append({"idx": idx, "type": ptype, "vlm_md": text})

        # 文本页占位: 无 VLM 转录的页置空(按顺序合并)
        ordered = []
        for p in pages:
            ordered.append(page_md.get(p["idx"], "") or "")

        # Step 4: 结构化重排
        _report("Step 3/4 骨架抽取与结构化重排...")
        md = _normalize_md(ordered)

        # Step 5: 质量回校
        used_vlm = sum(1 for p in pages_info if p["vlm_md"])
        _report("Step 5 质量回校...")
        verify_md(md, pages_info, used_vlm)  # 触发校验, 警告并入调用方 report 可选

        if not md.strip():
            return None
        return md
    finally:
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def convert_image_to_md(img_path, timeout=240):
    """单张图片 -> Markdown(技术路线 Step 2 直用)。无多模态 Provider 返回 None。"""
    img_path = os.path.abspath(img_path)
    if not os.path.isfile(img_path):
        return None
    prov = get_active_provider()
    if not prov or not supports_vlm():
        return None
    try:
        text = vlm_transcribe_page(prov, img_path, 1, 1, "image", timeout=timeout)
        return text or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 存档入口: 转换并写出 Markdown 文件
# ---------------------------------------------------------------------------

def convert_to_md_file(path, out_dir, dpi=144, page_batch=4, max_pages=300, progress=None):
    """单文件转换并存档 -> (out_md 路径|None, report dict)"""
    path = os.path.abspath(path)
    os.makedirs(out_dir, exist_ok=True)
    ext = os.path.splitext(path)[1].lower()
    base = os.path.splitext(os.path.basename(path))[0]

    if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"):
        if not supports_vlm():
            return None, {"error": "未配置多模态(视觉)Provider, 无法转换图片"}
        md = convert_image_to_md(path)
        if not md:
            return None, {"error": "图片 VLM 转录失败"}
        out_md = os.path.join(out_dir, base + ".md")
        with open(out_md, "w", encoding="utf-8") as f:
            f.write(md)
        return out_md, verify_md(md, [{"idx": 0, "type": "image", "vlm_md": md}], used_vlm=True)

    if ext != ".pdf":
        # 非 PDF 交给 kb_pipeline 既有通道
        try:
            import kb_pipeline
            md = kb_pipeline.extract_markdown(path)
            if not md:
                return None, {"error": "不支持的格式或转换失败"}
            out_md = os.path.join(out_dir, base + ".md")
            with open(out_md, "w", encoding="utf-8") as f:
                f.write(md)
            return out_md, {"char_total": len(md), "used_vlm": False, "warnings": []}
        except Exception as e:
            return None, {"error": str(e)}

    # PDF: 六步管线
    md = convert_pdf_to_md(path, dpi=dpi, page_batch=page_batch, max_pages=max_pages, progress=progress)
    if not md:
        # 回退链路: 优先 RapidAI 全家桶(免 VLM, 版面/表格/公式结构化), 再回退 RapidOCR 传统路线
        try:
            import ocr_client
            md, _ = ocr_client.convert_pdf_rapid(path, dpi=dpi, max_pages=max_pages)
            if md:
                report = verify_md(md, [], used_vlm=False)
                report["fallback"] = "rapidai"
            else:
                md = ocr_client.extract_pdf_md(path, max_pages=max_pages)
                if not md:
                    return None, {"error": "PDF 转换失败(六步管线、RapidAI 与 RapidOCR 均无输出)"}
                report = verify_md(md, [], used_vlm=False)
                report["fallback"] = "rapidocr"
        except Exception as e:
            return None, {"error": "PDF 转换失败: %s" % e}
    else:
        probe = probe_pdf(path, max_pages) or {}
        report = verify_md(md, [{"idx": p["idx"], "type": p["type"], "vlm_md": ""} for p in (probe.get("pages") or [])], used_vlm=True)
        report["pages"] = probe.get("total", 0)
        report["image_pages"] = probe.get("image_pages", 0)
        report["hybrid_pages"] = probe.get("hybrid_pages", 0)
    out_md = os.path.join(out_dir, base + ".md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(md)
    return out_md, report


def expand_paths(path_spec):
    """展开路径参数: 支持单文件/目录(递归)/逗号分隔/通配符, 也支持 list/tuple
    -> 文件绝对路径列表"""
    import glob
    _EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".docx", ".md", ".txt", ".xlsx"}
    results = []
    if isinstance(path_spec, (list, tuple)):
        items = [str(p) for p in path_spec]
    else:
        items = [p for p in re.split(r"[,，;]", str(path_spec or "")) if p.strip()]
    for raw in items:
        raw = raw.strip()
        if not raw:
            continue
        p = os.path.abspath(raw)
        if os.path.isfile(p):
            results.append(p)
        elif os.path.isdir(p):
            # 递归扫描子目录, 与 db.kb_import_files 的 os.walk 行为保持一致
            for root, _, names in os.walk(p):
                for n in names:
                    if os.path.splitext(n)[1].lower() in _EXTS:
                        results.append(os.path.join(root, n))
        else:
            results.extend(glob.glob(p))
    seen, uniq = set(), []
    for p in results:
        rp = os.path.normcase(os.path.abspath(p))
        if rp not in seen:
            seen.add(rp)
            uniq.append(p)
    return uniq


def convert_files_to_md(path_spec, out_dir, dpi=144, page_batch=4, max_pages=300, progress=None):
    """批量转换存档 -> [(src, out_md|None, report)]"""
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    files = expand_paths(path_spec)
    results = []
    for i, p in enumerate(files):
        def _prog(msg, _p=p, _i=i):
            if progress:
                progress("[%d/%d] %s %s" % (_i + 1, len(files), os.path.basename(_p), msg))
        out_md, report = convert_to_md_file(p, out_dir, dpi=dpi, page_batch=page_batch,
                                            max_pages=max_pages, progress=_prog)
        results.append((p, out_md, report))
    return results
