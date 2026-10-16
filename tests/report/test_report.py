# -*- coding: utf-8 -*-
"""M10 报告系统行为测试：生成五节 / 达标判定 / service 全流程 / 标准有效性标注 / docx/pdf 导出。"""
from __future__ import annotations

from pathlib import Path

from src.models.core import StandardRef, ValidityInfo
from src.report import ReportGenerator, ReportService, docx, pdf
from src.report.generator import _SECTION_ORDER


def test_generate_five_sections() -> None:
    gen = ReportGenerator()
    sections = gen.generate(
        {'name': '某地表水监测', 'client': '甲方', 'points': 'A1', 'items': 'pH,COD',
         'standards': ['GB 3838-2002'], 'frequency': '1次/日'},
        [{'point': 'A1', 'item': 'pH', 'value': 7.0, 'limit': 9}],
        {'purpose': '地表水环境质量监测'},
    )
    assert [s.name for s in sections] == list(_SECTION_ORDER)
    assert all(s.content for s in sections)
    assert 'GB 3838-2002' in sections[0].refs


def test_exceed_verdict_in_conclusion() -> None:
    gen = ReportGenerator()
    data = [
        {'point': 'A1', 'item': 'COD', 'value': 45, 'limit': 40},
        {'point': 'A2', 'item': 'pH', 'value': 7.2, 'limit': 9},
    ]
    sections = gen.generate({'name': 'x'}, data, {})
    results = next(s for s in sections if s.name == 'results')
    assert '超标' in results.content and 'COD' in results.content
    conclusion = next(s for s in sections if s.name == 'conclusion')
    assert '超标' in conclusion.content


def test_missing_data_placeholder() -> None:
    gen = ReportGenerator()
    sections = gen.generate({'name': 'x'}, [], {})
    results = next(s for s in sections if s.name == 'results')
    assert '待填写' in results.content
    assert '不编造' not in results.content  # 占位而非虚构
    conclusion = next(s for s in sections if s.name == 'conclusion')
    assert '待填写' in conclusion.content


def test_service_generate_creates_report() -> None:
    svc = ReportService()
    rpt = svc.generate('monitoring', 'prj-20260806-001')
    assert rpt.id.startswith('rpt-')
    assert rpt.type == 'monitoring'
    assert rpt.status == 'drafting' and rpt.version == 1
    assert rpt.created_by == 'R4'
    assert svc.get(rpt.id) is rpt


def test_service_generate_unknown_type() -> None:
    # P1 泛化（2026-08）：report_type 不再限定三枚举，未知类型由模板库/内置兜底，
    # 不抛错，生成草稿报告
    svc = ReportService()
    rpt = svc.generate('nope', 'prj-20260806-001')
    assert rpt.type == 'nope'
    assert rpt.status == 'drafting'


def test_render_docx_writes_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    svc = ReportService()
    rpt = svc.generate('monitoring', 'prj-20260806-001')
    svc.fill_table(rpt.id, [{'point': 'A1', 'item': 'COD', 'value': 30, 'limit': 40}])
    path = svc.render_docx(rpt)
    assert Path(path).exists() and path.endswith('.docx')
    assert rpt.docx_path == path


def test_fill_table_updates_results(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    svc = ReportService()
    rpt = svc.generate('acceptance', 'prj-20260806-001', template='acceptance')
    svc.fill_table(rpt.id, [{'point': 'B1', 'item': 'NH3-N', 'value': 1.2, 'limit': 1.0}])
    cited = svc.citations(rpt.id)  # 触发 citations 结构
    assert cited == []
    rpt2 = svc.get(rpt.id)
    assert rpt2 is not None and rpt2.type == 'acceptance'


def test_cite_standard_validity_flag(monkeypatch) -> None:
    from src.kb.standards import StandardKB

    monkeypatch.setattr(
        StandardKB, 'check_validity',
        lambda self, code: ValidityInfo(code=code, status='已废止', note='已由新版替代'),
    )
    svc = ReportService()
    rpt = svc.generate('monitoring', 'prj-20260806-001')
    ref = StandardRef(code='GB 1234-1999', clause='5.1', valid=True)
    svc.cite_standard(rpt.id, ref)
    cited = svc.citations(rpt.id)
    assert len(cited) == 1
    assert cited[0].valid is False, '已废止标准必须标注无效'


def test_cite_standard_valid_keeps_true(monkeypatch) -> None:
    from src.kb.standards import StandardKB

    monkeypatch.setattr(
        StandardKB, 'check_validity',
        lambda self, code: ValidityInfo(code=code, status='现行有效'),
    )
    svc = ReportService()
    rpt = svc.generate('eia', 'prj-20260806-001')
    ref = StandardRef(code='HJ 166-2026')
    svc.cite_standard(rpt.id, ref)
    assert svc.citations(rpt.id)[0].valid is True


def test_exporter_docx_and_pdf(tmp_path: Path) -> None:
    from src.models.core import ReportSection

    sections = [ReportSection(name='results', content='| A1 | COD | 30 | 40 | 达标 |', refs=['GB 3838-2002'])]
    dp = docx(sections, str(tmp_path / 'r.docx'))
    assert Path(dp).exists() and dp.endswith('.docx')
    pp = pdf(sections, str(tmp_path / 'r.pdf'))
    assert Path(pp).exists() and pp.endswith('.pdf')
