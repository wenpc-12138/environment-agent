# -*- coding: utf-8 -*-
"""Agent 侧 OCR/PDF 客户端 - 独立进程隔离调用 (镜像 searxng_mcp.py)

主程序唯一入口: 本文件不 import pymupdf / rapidocr_onnxruntime,
只经 ocr_launcher.ensure_running() 拉起/复用 ocr_worker 独立进程后走 HTTP。
因此主程序不引入 AGPL 依赖, 许可证隔离与 SearXNG 完全一致。
"""
import json
import os

import ocr_launcher


def _post(route, path, dpi, max_pages):
    st = ocr_launcher.ensure_running()
    if not st.get("ready") or not st.get("url"):
        return ""
    try:
        import requests
        # OCR worker 在本机：绕过系统代理，避免 127.0.0.1 请求被代理转发而超时
        from src.core.net import ensure_local_no_proxy

        ensure_local_no_proxy()
        r = requests.post(
            st["url"] + route,
            json={"path": os.path.abspath(path), "dpi": dpi, "max_pages": max_pages},
            timeout=600,
        )
        data = r.json()
        return data.get("text") if data.get("ok") else ""
    except Exception:
        return ""


def extract_pdf_md(path, dpi=200, max_pages=300):
    """PDF -> Markdown(文字层/表格/标题 + <200字符自动 OCR 兜底), 失败返回空串"""
    return _post("/extract_pdf", path, dpi, max_pages)


def ocr_pdf(path, dpi=200, max_pages=300):
    """扫描版 PDF 纯 OCR 文本, 失败返回空串"""
    return _post("/ocr_pdf", path, dpi, max_pages)


def convert_pdf_rapid(path, dpi=160, max_pages=300):
    """路径A RapidAI 全家桶: PDF -> Markdown (RapidLayout+RapidOCR+RapidTable+RapidLaTeXOCR)。
    纯本地免 VLM; 默认 160 dpi(扫描正文足够, 速度约为 216dpi 的 2 倍); 返回 (md, meta), 失败返回 ("", {})"""
    st = ocr_launcher.ensure_running()
    if not st.get("ready") or not st.get("url"):
        return "", {}
    try:
        import requests
        r = requests.post(
            st["url"] + "/convert_rapid",
            json={"path": os.path.abspath(path), "dpi": dpi, "max_pages": max_pages},
            timeout=1800,
        )
        data = r.json()
        if data.get("ok"):
            return data.get("text") or "", data.get("meta") or {}
        return "", {}
    except Exception:
        return "", {}


def probe_pdf(path, max_pages=300):
    """VLM 六步管线 Step 0 探测: 每页文字层字符密度判定。
    返回 {"ok":True,"pages":[{"idx","chars","type"}],"total","image_pages","hybrid_pages","text_pages"}
    失败返回 None (主进程回退 RapidOCR 或文字层)"""
    st = ocr_launcher.ensure_running()
    if not st.get("ready") or not st.get("url"):
        return None
    try:
        import requests
        r = requests.post(
            st["url"] + "/probe",
            json={"path": os.path.abspath(path), "max_pages": max_pages},
            timeout=120,
        )
        data = r.json()
        return data if data.get("ok") else None
    except Exception:
        return None


def probe_rich_pdf(path, max_pages=300):
    """轻量富内容探测: 返回含表格/公式/图片的页数(worker 侧 fitz 启发式, 秒级)。
    返回 int rich_pages; worker 不可用/失败返回 None(调用方按无富内容处理)。"""
    st = ocr_launcher.ensure_running()
    if not st.get("ready") or not st.get("url"):
        return None
    try:
        import requests
        r = requests.post(
            st["url"] + "/probe_rich",
            json={"path": os.path.abspath(path), "max_pages": max_pages},
            timeout=120,
        )
        data = r.json()
        if data.get("ok"):
            return int(data.get("rich_pages") or 0)
        return None
    except Exception:
        return None


def render_pdf(path, out_dir, pages=None, dpi=144, max_pages=300):
    """VLM 六步管线 Step 1 渲染: 指定页渲染为 PNG(近似 dpi, 默认144)到 out_dir。
    返回 [{"idx","png"}] 渲染成功页列表, 失败返回 []"""
    st = ocr_launcher.ensure_running()
    if not st.get("ready") or not st.get("url"):
        return []
    try:
        import requests
        r = requests.post(
            st["url"] + "/render",
            json={
                "path": os.path.abspath(path),
                "out_dir": os.path.abspath(out_dir),
                "pages": pages or [],
                "dpi": dpi,
                "max_pages": max_pages,
            },
            timeout=600,
        )
        data = r.json()
        return (data.get("images") or []) if data.get("ok") else []
    except Exception:
        return []
