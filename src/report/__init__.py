# -*- coding: utf-8 -*-
"""M10 报告服务：生成 / docx/pdf 渲染 / 标准引用。"""
from .generator import ReportGenerator, ReportSection
from .exporter import DOCX_EXPORTER, PDF_EXPORTER, docx, pdf
from .service import ReportService
from .templates import BUILTIN_TEMPLATES, get_template

__all__ = [
    'ReportGenerator', 'ReportSection', 'DOCX_EXPORTER', 'PDF_EXPORTER',
    'docx', 'pdf', 'ReportService', 'BUILTIN_TEMPLATES', 'get_template',
]
