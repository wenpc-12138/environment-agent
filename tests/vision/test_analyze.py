# -*- coding: utf-8 -*-
"""G6 多模态输入：图片附件解析 / VLM 与 OCR 双路线 / 注入链路。"""
from __future__ import annotations

import pytest

from src.vision import analyze


class TestIsImage:
    @pytest.mark.parametrize('p, expect', [
        ('a.png', True), ('a.JPG', True), ('b.webp', True),
        ('c.pdf', False), ('d.txt', False), ('', False),
    ])
    def test_ext(self, p, expect):
        assert analyze.is_image_path(p) is expect


class TestExtractAttachments:
    def test_extract_images_only(self):
        content = ('[附件: 现场照片1.png 已保存到 C:\\data\\uploads\\a.png]\n'
                   '[附件: 报告.docx 已保存到 C:\\data\\uploads\\b.docx]\n'
                   '[附件: 报表.jpg 已保存到 C:\\data\\uploads\\c.jpg]')
        items = analyze.extract_image_attachments(content)
        assert len(items) == 2
        assert items[0]['name'] == '现场照片1.png'
        assert items[1]['name'] == '报表.jpg'

    def test_no_attach(self):
        assert analyze.extract_image_attachments('普通消息') == []

    def test_dedup(self):
        content = ('[附件: a.png 已保存到 x.png]\n[附件: 同名.png 已保存到 x.png]')
        assert len(analyze.extract_image_attachments(content)) == 1


class TestAnalyzeImage:
    def test_missing_file(self):
        r = analyze.analyze_image('no/such/file.png')
        assert r['ok'] is False and '不存在' in r['error']

    def test_not_image(self, tmp_path):
        f = tmp_path / 'note.txt'
        f.write_text('hello', encoding='utf-8')
        r = analyze.analyze_image(str(f))
        assert r['ok'] is False and '非图片' in r['error']

    def test_vlm_route(self, tmp_path, _fake_vision):
        img = tmp_path / 'shot.png'
        img.write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 64)
        _fake_vision(vlm_supported=True, vlm_text='监测点位布置图')
        r = analyze.analyze_image(str(img), '这是什么？')
        assert r['ok'] and r['method'] == 'vlm' and '点位' in r['text']

    def test_ocr_fallback_when_no_vlm(self, tmp_path, _fake_vision):
        img = tmp_path / 'scan.png'
        img.write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 64)
        _fake_vision(vlm_supported=False, ocr_text='COD 35 mg/L')
        r = analyze.analyze_image(str(img))
        assert r['ok'] and r['method'] == 'ocr' and 'COD' in r['text']

    def test_vlm_fail_then_ocr(self, tmp_path, _fake_vision):
        img = tmp_path / 'a.png'
        img.write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 64)
        _fake_vision(vlm_supported=True, vlm_raises=True, ocr_text='氨氮 2.5 mg/L')
        r = analyze.analyze_image(str(img))
        assert r['ok'] and r['method'] == 'ocr'

    def test_both_unavailable(self, tmp_path, _fake_vision):
        img = tmp_path / 'a.png'
        img.write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 64)
        _fake_vision(vlm_supported=False, ocr_text='')
        r = analyze.analyze_image(str(img))
        assert r['ok'] is False and r['method'] == 'none'


class TestInject:
    def test_inject_vlm(self, tmp_path, _fake_vision):
        img = tmp_path / 'rpt.png'
        img.write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 64)
        content = f'请分析这张报告图\n[附件: 报告.png 已保存到 {img}]'
        _fake_vision(vlm_supported=True, vlm_text='表格：COD 35mg/L')
        new, records = analyze.inject_image_attachments(content)
        assert len(records) == 1 and records[0]['method'] == 'vlm'
        assert '[图片识别: 报告.png (vlm)]' in new
        assert 'COD' in new

    def test_inject_no_image(self):
        new, records = analyze.inject_image_attachments('普通文本')
        assert new == '普通文本' and records == []

    def test_inject_failed_recorded(self, tmp_path, _fake_vision):
        img = tmp_path / 'x.png'
        img.write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 64)
        content = f'[附件: x.png 已保存到 {img}]'
        _fake_vision(vlm_supported=False, ocr_text='')
        new, records = analyze.inject_image_attachments(content)
        assert records[0]['ok'] is False
        assert '失败' in new


class _FakeVlm:
    """mock vlm_convert 模块。"""

    def __init__(self, supported=True, raises=False):
        self._supported = supported
        self._raises = raises

    def supports_vlm(self):
        return self._supported

    def get_active_provider(self):
        return {'model': 'gpt-4o'}

    def _png_data_url(self, path):
        return 'data:image/png;base64,AA=='


class _FakeProviders:
    """mock providers.chat_text（VLM 直读终点）。"""

    def __init__(self, text='', raises=False):
        self._text = text
        self._raises = raises

    def chat_text(self, prov, messages, temperature=0.1, timeout=240):
        if self._raises:
            raise RuntimeError('vlm boom')
        return self._text, {}


class _FakeOcr:
    """mock ocr_client 模块。"""

    def __init__(self, text):
        self._text = text

    def convert_pdf_rapid(self, path, dpi=160, max_pages=1):
        return self._text, {}


@pytest.fixture()
def _fake_vision(monkeypatch):
    """统一视觉链路 mock：vlm_convert + providers.chat_text + ocr_client。"""

    def _apply(vlm_supported=True, vlm_text='', vlm_raises=False, ocr_text=''):
        monkeypatch.setattr('src.vision.analyze.vlm_convert',
                            _FakeVlm(supported=vlm_supported, raises=vlm_raises))
        monkeypatch.setattr('src.vision.analyze.providers',
                            _FakeProviders(text=vlm_text, raises=vlm_raises))
        monkeypatch.setattr('src.vision.analyze.ocr_client', _FakeOcr(ocr_text))

    return _apply
