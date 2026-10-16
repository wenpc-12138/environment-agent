# -*- coding: utf-8 -*-
"""G6 多模态输入（对话可见图）：图片附件 -> 视觉理解注入对话上下文。

技术路线（复用既有视觉能力栈，零新增依赖）：
1. **VLM 直读**：配置多模态 Provider（gpt-4o/gemini/qwen-vl/glm-4v 等）时，
   经 `vlm_convert.vlm_transcribe_page`（image_url base64 内联）带问题分析；
2. **RapidOCR 兜底**：无 VLM 时经 `ocr_client.convert_pdf_rapid`（独立进程
   ocr_launcher 许可证隔离，RapidOCR 直接读图提文字）；
3. **均不可用**：返回明确提示（不静默）。

`inject_image_attachments(content)`：解析消息中 `[附件: 名称 已保存到 path]` 的
图片附件，自动分析并把 `[图片识别: 名称] 内容...` 注入消息文本，使 agent 能"看懂"。
"""
from __future__ import annotations

import base64
import os
import re

# 轻量代理模块（VLM 视觉管线 / OCR 独立进程客户端），调用时才触发真实服务
import ocr_client  # noqa: E402
from src.llm import providers  # noqa: E402
import vlm_convert  # noqa: E402

_IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff')
_ATTACH_RE = re.compile(r'\[附件:\s*(.+?)\s*已保存到\s*(.+?)\]')


def is_image_path(path: str) -> bool:
    return (path or '').lower().endswith(_IMG_EXT)


def analyze_image(path: str, question: str = '') -> dict:
    """分析单张图片：VLM 读图（带问题）优先，RapidOCR 文字提取兜底。

    返回 {'ok', 'text', 'method', 'error'}，method: vlm / ocr / none。
    """
    path = (path or '').strip()
    if not path or not os.path.isfile(path):
        return {'ok': False, 'text': '', 'method': 'none', 'error': '图片文件不存在'}
    if not is_image_path(path):
        return {'ok': False, 'text': '', 'method': 'none', 'error': '非图片文件'}
    try:
        # 路线1：VLM 直读（带问题分析）
        if vlm_convert.supports_vlm():
            prov = vlm_convert.get_active_provider()
            q = (question or '').strip() or '请识别并描述这张图片的内容，提取其中关键信息。'
            messages = [
                {'role': 'system', 'content': '你是生态环境领域的图片分析助手。'
                 '识别图片中的文字、数据、图表、场景，按问题要求给出结构化回答。'},
                {'role': 'user', 'content': [
                    {'type': 'text', 'text': q},
                    {'type': 'image_url',
                     'image_url': {'url': vlm_convert._png_data_url(path)}},
                ]},
            ]
            text, _usage = providers.chat_text(prov, messages, temperature=0.1, timeout=240)
            if text and text.strip():
                return {'ok': True, 'text': text.strip(), 'method': 'vlm', 'error': ''}
    except Exception as exc:  # noqa: BLE001 VLM 失败降级 OCR
        vlm_err = f'{type(exc).__name__}: {exc}'
    else:
        vlm_err = ''
    try:
        # 路线2：RapidOCR 文字提取（独立进程，许可证隔离）
        text, _meta = ocr_client.convert_pdf_rapid(path, dpi=160, max_pages=1)
        if text and text.strip():
            return {'ok': True, 'text': text.strip(), 'method': 'ocr',
                    'error': vlm_err or ''}
        return {'ok': False, 'text': '', 'method': 'none',
                'error': vlm_err or 'OCR 未识别到文字（图片可能无文本内容）'}
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'text': '', 'method': 'none',
                'error': f'VLM: {vlm_err or "不可用"}; OCR: {type(exc).__name__}: {exc}'}


def extract_image_attachments(content: str) -> list[dict]:
    """解析消息中的图片附件引用 -> [{'name','path'}]（去重）。"""
    out: list[dict] = []
    seen: set[str] = set()
    for m in _ATTACH_RE.finditer(content or ''):
        name = m.group(1).strip()
        path = m.group(2).strip()
        if path in seen or not is_image_path(path):
            continue
        seen.add(path)
        out.append({'name': name, 'path': path})
    return out


def inject_image_attachments(content: str, max_chars: int = 4000) -> tuple[str, list[dict]]:
    """把消息中图片附件自动识别为文本并注入。

    返回 (新 content, 注入记录 [{name, path, method, text}] )。
    注入格式：`\n[图片识别: name (method)] 识别内容...`
    """
    items = extract_image_attachments(content or '')
    if not items:
        return content or '', []
    injected: list[str] = []
    records: list[dict] = []
    for it in items:
        r = analyze_image(it['path'])
        records.append({'name': it['name'], 'path': it['path'],
                        'method': r['method'], 'ok': r['ok'],
                        'text': r['text'][:max_chars], 'error': r['error']})
        if r['ok']:
            injected.append(f"[图片识别: {it['name']} ({r['method']})]\n{r['text'][:max_chars]}")
        else:
            injected.append(f"[图片识别: {it['name']} 失败 - {r['error'][:200]}]")
    new_content = (content or '') + '\n\n' + '\n\n'.join(injected)
    return new_content, records
