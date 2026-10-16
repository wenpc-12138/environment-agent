# -*- coding: utf-8 -*-
"""错误页/失效页识别测试：站点用 200 包装 404 的内容不得入库。

背景：HJ 834 等标准 PDF 链接失效时 mee.gov.cn 返回 200 但正文为
"抱歉，您访问的地址有错或页面不存在"错误页；此前 web_fetch 把错误页当
全文入库（垃圾条目）。本测试锁定 _is_error_page 判定 + fetch_text 拦截。

覆盖：
- _is_error_page 对错误页文本返回 True；
- 正常标准文本返回 False；
- fetch_text 对错误页 PDF 抛 RuntimeError（不再返回垃圾全文）；
- fetch_document（_is_doc_url 路径）对错误页也拦截。
"""
from __future__ import annotations

import sys
import tempfile

import pytest

from src.tools import websearch

_ERROR_TEXT = (
    "热门搜索：邮箱 EN 点击进入\n"
    "抱歉，您访问的地址有错或页面不存在。"
    "如您是在地址栏输入网址的，请确认其拼写正确，并注意网址的大小写字母区分。"
)
_NORMAL_TEXT = (
    "GB 3838-2002 地表水环境质量标准：Ⅲ类水 COD ≤ 20 mg/L，"
    "氨氮 ≤ 1.0 mg/L，总磷(湖库)≤ 0.05 mg/L。"
)


def _write_tmp(text, suffix='.pdf'):
    p = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    p.write(text.encode('utf-8'))
    p.close()
    return p.name


class _FakeKP:
    @staticmethod
    def extract_markdown(path):
        return open(path, encoding='utf-8').read()

    @staticmethod
    def extract_text(path):
        return open(path, encoding='utf-8').read()


def test_is_error_page_detects():
    assert websearch._is_error_page(_ERROR_TEXT) is True


def test_is_error_page_normal_false():
    assert websearch._is_error_page(_NORMAL_TEXT) is False


def test_is_error_page_short_false():
    assert websearch._is_error_page("抱歉") is False  # 太短，特征不足


def test_fetch_pdf_text_error_page_raises(monkeypatch):
    """_fetch_pdf_text 对错误页 PDF 抛 RuntimeError（不再返回垃圾全文）。"""

    def fake_fetch_pdf(url, save_dir=None, timeout=30):
        return _write_tmp(_ERROR_TEXT)

    monkeypatch.setattr(websearch, '_fetch_pdf', fake_fetch_pdf)
    monkeypatch.setitem(sys.modules, 'kb_pipeline', _FakeKP())
    with pytest.raises(RuntimeError, match='错误页'):
        websearch._fetch_pdf_text('https://example.com/std.pdf')


def test_fetch_document_error_page_raises(monkeypatch):
    """fetch_document（_is_doc_url 路径）对错误页也拦截。"""

    def fake_download_file(url, save_dir=None, timeout=60, max_size=0):
        return _write_tmp(_ERROR_TEXT)

    monkeypatch.setattr(websearch, 'download_file', fake_download_file)
    monkeypatch.setitem(sys.modules, 'kb_pipeline', _FakeKP())
    with pytest.raises(RuntimeError, match='错误页'):
        websearch.fetch_document('https://example.com/doc.pdf')


def test_fetch_document_normal_ok(monkeypatch):
    """正常文档不被误伤（回归保护）。"""

    def fake_download_file(url, save_dir=None, timeout=60, max_size=0):
        return _write_tmp(_NORMAL_TEXT, suffix='.txt')

    monkeypatch.setattr(websearch, 'download_file', fake_download_file)
    monkeypatch.setitem(sys.modules, 'kb_pipeline', _FakeKP())
    res = websearch.fetch_document('https://example.com/std.txt')
    assert 'GB 3838-2002' in res['text']


# ---- 公告页自动提取 PDF 附件（HJ 834 修复） ----

def test_extract_pdf_links_markdown_and_html():
    """_extract_pdf_links 支持 Markdown 与 HTML 两种链接格式。"""
    md_links = websearch._extract_pdf_links(
        '[标准全文](W020170724583254045900.pdf)', 'https://example.com/a/b.html')
    assert md_links and md_links[0][1].endswith('/a/W020170724583254045900.pdf')

    html_links = websearch._extract_pdf_links(
        '<a href="./W020170724583254045900.pdf">土壤和沉积物 半挥发性有机物的测定(HJ 834-2017)</a>',
        'https://example.com/a/b.html')
    assert html_links
    assert html_links[0][1].endswith('/a/W020170724583254045900.pdf')
    assert 'HJ 834' in html_links[0][0]


def test_maybe_auto_pdf_uses_html_fallback(monkeypatch):
    """正文 Markdown 丢失链接时，从原始 HTML 补提 PDF 附件。"""
    body = '2017-09-01 实施\n为贯彻《环境保护法》制定本标准。'  # 正文无链接
    html = ('<div class="TRS_Editor"><p align="center">'
            '<a oldsrc="W020170724583254045900.pdf" href="./W020170724583254045900.pdf">'
            '土壤和沉积物 半挥发性有机物的测定 气相色谱-质谱法(HJ 834-2017)</a></p></div>')

    def fake_fetch_pdf_text(url, max_chars=30000, save_dir=None):
        return f'来源: {url}\n格式: PDF 全文\n内容:\n标准全文...'

    monkeypatch.setattr(websearch, '_fetch_pdf_text', fake_fetch_pdf_text)
    out = websearch._maybe_auto_pdf(body, 'https://example.com/a/b.html',
                                    '标准公告', max_chars=30000, html=html)
    assert out and '标准全文' in out


def test_maybe_auto_pdf_no_html_no_links():
    """无 HTML 且正文无链接时返回 None。"""
    out = websearch._maybe_auto_pdf('简介文本', 'https://example.com/a.html', '标题',
                                    max_chars=30000)
    assert out is None
