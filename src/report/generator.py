# -*- coding: utf-8 -*-
"""M10 报告生成器（contracts.md §3.M10；复用 v1.2 report-writing 技能流程）。

- `ReportGenerator.generate(plan, data, context)`：按规范结构输出 5 节
  （项目概况 / 监测方案 / QA/QC / 监测结果与达标判定 / 结论与建议），返回 `list[ReportSection]`。
- 达标判定规则（report-writing SKILL.md §4）：任一测点任一项目超标即判"超标"，注明超标倍数与位置；
  数据缺失处以"待填写"占位，不编造监测数据。
"""
from __future__ import annotations

import re
from typing import Any

from ..models.core import Report, ReportSection

_SECTION_ORDER = ('project_overview', 'monitoring_plan', 'qaqc', 'results', 'conclusion')


class ReportGenerator:
    """按 plan/data/context 生成报告章节，并支持导出。"""

    def __init__(self) -> None:
        self._sections: dict[str, list[ReportSection]] = {}

    # ---- 生成 ----
    def generate(self, plan: dict, data: Any, context: dict) -> list[ReportSection]:
        """生成 5 节报告结构。

        plan：项目名称 / 委托方 / 点位 / 监测项目 / 执行标准（standards: list[str]）。
        data：监测结果（list[dict]：测点/项目/结果/限值/单位）。
        context：编制日期 / 编制人 / 报告类型等。
        """
        plan = plan or {}
        data = data or []
        context = context or {}

        standards = [str(s) for s in plan.get('standards', [])]
        sections: list[ReportSection] = [
            ReportSection(name='project_overview', content=self._overview(plan, context), refs=standards),
            ReportSection(name='monitoring_plan', content=self._monitoring_plan(plan), refs=standards),
            ReportSection(name='qaqc', content=self._qaqc(plan), refs=[]),
            ReportSection(name='results', content=self._results(plan, data), refs=standards),
            ReportSection(name='conclusion', content=self._conclusion(data), refs=standards),
        ]
        key = str(plan.get('_report_id', 'default'))
        self._sections[key] = sections
        return sections

    # ---- 各节渲染 ----
    @staticmethod
    def _overview(plan: dict, context: dict) -> str:
        name = plan.get('name', '待填写')
        client = plan.get('client') or context.get('client') or '待填写'
        purpose = context.get('purpose', '环境质量监测')
        return (
            f'项目名称：{name}\n'
            f'委托方：{client}\n'
            f'目的：{purpose}\n'
            f'依据：执行标准见报告引用列表，检测方法按现行有效标准执行。'
        )

    @staticmethod
    def _monitoring_plan(plan: dict) -> str:
        points = plan.get('points') or '待填写'
        items = plan.get('items') or '待填写'
        freq = plan.get('frequency') or '待填写'
        return (
            f'监测点位：{points}\n'
            f'监测项目：{items}\n'
            f'监测频次：{freq}\n'
            f'采样方法、分析方法与检出限按相关标准执行，具体仪器型号见原始记录。'
        )

    @staticmethod
    def _qaqc(plan: dict) -> str:
        qc = plan.get('qaqc', '空白样、平行样、质控样按质控要求执行')
        return f'质量控制：{qc}\n空白、平行样、质控样数据满足质控要求时结果方可报出。'

    @staticmethod
    def _results(plan: dict, data: Any) -> str:
        if not data:
            return '监测结果：待填写（数据缺失，请补充原始记录）。'
        if isinstance(data, dict):
            data = [data]
        # P4：数据行含 pi（单项污染指数）时增加"指数"列（FormulaEngine 计算填充）
        has_pi = any(row.get('pi') is not None for row in data)
        head = ['测点', '项目', '结果', '限值']
        if has_pi:
            head.append('指数')
        head.append('判定')
        lines = ['监测结果与达标判定：', '',
                 '| ' + ' | '.join(head) + ' |',
                 '|' + '------|' * len(head)]
        for row in data:
            point = row.get('point', '')
            item = row.get('item', '')
            value = row.get('value', '待填写')
            limit = row.get('limit', '')
            exceed = _is_exceed(row)
            verdict = '超标' if exceed else ('达标' if limit != '' else '待判定')
            cells = [point, item, value, limit]
            if has_pi:
                pi = row.get('pi')
                cells.append('' if pi is None else f'{pi:.2f}')
            cells.append(verdict)
            lines.append('| ' + ' | '.join(str(c) for c in cells) + ' |')
        return '\n'.join(lines)

    @staticmethod
    def _conclusion(data: Any) -> str:
        if not data:
            return '结论：待填写（数据缺失）。'
        rows = data if isinstance(data, list) else [data]
        exceeded = [r for r in rows if _is_exceed(r)]
        if exceeded:
            detail = '、'.join(f'{r.get("point")}-{r.get("item")}' for r in exceeded)
            return f'结论：存在超标项（{detail}），需注明超标倍数与位置并分析原因。'
        return '结论：各监测项目结果均满足相应标准限值要求。'

    # ---- 导出 ----
    def export(self, report: Report) -> str:
        """将报告章节导出为 docx，返回文件路径。"""
        from .exporter import docx

        sections = self._sections.get(report.id, [])
        return docx(sections, _output_path(report.id, 'docx'))


def _to_num(v: Any) -> float | None:
    """提取数值：支持纯数字与带单位字符串（如 "2.1 mg/L"）。"""
    if v in (None, '', '待填写'):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r'-?\d+(?:\.\d+)?', str(v))
    return float(m.group()) if m else None


def _is_exceed(row: dict) -> bool:
    value = _to_num(row.get('value'))
    limit = _to_num(row.get('limit'))
    return value is not None and limit is not None and value > limit


def _output_path(report_id: str, ext: str) -> str:
    from pathlib import Path

    out = Path('data') / 'reports'
    out.mkdir(parents=True, exist_ok=True)
    return str(out / f'{report_id}.{ext}')
