# -*- coding: utf-8 -*-
"""M10 报告生成契约测试（contracts.md §3.M10）。

src/report/ 未实现时自动 skip；实现后自动激活。
"""
from __future__ import annotations

import inspect

import pytest


def test_report_section_fields() -> None:
    """ReportSection 字段与契约一致。"""
    gen = pytest.importorskip('src.report.generator', reason='M10 ReportGenerator 未实现')
    assert {'name', 'content', 'refs'} <= set(gen.ReportSection.model_fields)


def test_report_generator_signatures() -> None:
    """ReportGenerator.generate / export。"""
    gen = pytest.importorskip('src.report.generator', reason='M10 ReportGenerator 未实现')
    gen_sig = inspect.signature(gen.ReportGenerator.generate)
    assert list(gen_sig.parameters)[:4] == ['self', 'plan', 'data', 'context']
    export = inspect.signature(gen.ReportGenerator.export)
    assert list(export.parameters)[:2] == ['self', 'report']


def test_report_exporter_signatures() -> None:
    """Reporter（导出）支持 docx / pdf。"""
    exporter = pytest.importorskip('src.report.exporter', reason='M10 ReportExporter 未实现')
    assert hasattr(exporter, 'docx') or hasattr(exporter, 'DOCX_EXPORTER')
    assert hasattr(exporter, 'pdf') or hasattr(exporter, 'PDF_EXPORTER')
