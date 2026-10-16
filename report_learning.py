# -*- coding: utf-8 -*-
"""P5 文档学习管线：从真实报告语料学习章节模式与数据要求，增强 R4 编制。

流水线：报告语料入库（对话/上传）-> 章节骨架解析 -> 数据要求提炼
（表格/点位/数值单位/标准号）-> 章节模式归纳（频次统计）-> 落盘
data/report_learning.json -> R4 编制时按学习模式增强监测方案并附加学习章节。

替代硬编码模板的渐进路径：语料越多，学习章节越完整（M19 持久化后可进 DB）。
"""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from typing import Any

DATA_FILE = os.path.join('data', 'report_learning.json')

# 硬编码 5 节的中文别名（用于判定"额外学习章节"）
_CORE_ALIASES = {
    'project_overview': ('项目概况', '项目信息', '工程概况', '项目基本情况'),
    'monitoring_plan': ('监测方案', '监测点位', '监测项目', '点位布设', '采样方案', '监测内容'),
    'qaqc': ('质量控制', '质量保证', '质控', '质量保证与控制'),
    'results': ('监测结果', '检测结果', '结果与评价', '数据分析', '监测结果与评价'),
    'conclusion': ('结论', '结论与建议', '评价结论', '建议'),
}
_SKIP_TITLES = {'目录', '目次', '前言', '参考文献', '引言', '附录', '附件', '封底'}

# 章节标题行：markdown 标题（#）或编号标题（1. / 1.1 / 一、）
_TITLE_RE = re.compile(r'^(#{1,4}\s*|(\d+(?:\.\d+)*)[、.．\s]+|[一二三四五六七八九十]+、)(.{1,40})$')
_DATA_RE = re.compile(
    r'\d+(?:\.\d+)?\s*(?:mg/L|mg/l|g/L|mg/m3|mg/m³|ug/m3|μg/m3|µg/m3|ug/L|μg/L|µg/L|dB|个/L|MPN/L|mg/kg|%)')
_POINT_RE = re.compile(r'(点位|测点|断面|采样点|监测点|厂界|排放口|排气筒|井)')
_STD_RE = re.compile(r'\b[A-Z]{1,4}\s*[-/]?\s*\d{3,5}(?:\.\d+)?\b')
_TABLE_RE = re.compile(r'\|.*\|')


def extract_sections(text: str) -> list[dict]:
    """解析报告章节骨架：返回 [{name, content, level}]（标题行与其后内容）。"""
    if not text:
        return []
    out: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        m = _TITLE_RE.match(stripped)
        if m:
            title = m.group(3).strip()
            if (len(title) >= 2 and title not in _SKIP_TITLES
                    and not re.search(r'[。．:：；;]', title)):
                cur = {'name': title, 'content': '', 'level': m.group(1).count('#') + 1}
                out.append(cur)
                continue
        if cur is not None:
            cur['content'] += line + '\n'
    return out


def extract_data_reqs(text: str) -> dict:
    """数据要求提炼：{has_table, has_points, has_data, has_standard}（计数）。"""
    if not text:
        return {'has_table': 0, 'has_points': 0, 'has_data': 0, 'has_standard': 0}
    return {
        'has_table': 1 if _TABLE_RE.search(text) else 0,
        'has_points': len(_POINT_RE.findall(text)),
        'has_data': len(_DATA_RE.findall(text)),
        'has_standard': 1 if _STD_RE.search(text) else 0,
    }


def _load() -> dict:
    try:
        with open(DATA_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def learn(report_type: str, text: str, source: str = '') -> dict:
    """学习一份报告语料：解析章节、提炼数据要求并累计模式。"""
    if not report_type or report_type not in ('monitoring', 'acceptance', 'eia'):
        report_type = 'monitoring'
    data = _load()
    bucket = data.setdefault(report_type, {})
    bucket['samples'] = bucket.get('samples', 0) + 1
    secs = bucket.setdefault('sections', {})
    sections = extract_sections(text)
    learned = 0
    for s in sections:
        reqs = extract_data_reqs(s['content'])
        entry = secs.setdefault(s['name'], {'hits': 0,
                                            'reqs': {'has_table': 0, 'has_points': 0,
                                                     'has_data': 0, 'has_standard': 0}})
        entry['hits'] += 1
        for k in reqs:
            if reqs[k]:
                entry['reqs'][k] += 1
        learned += 1
    bucket['last'] = {'ts': datetime.now(UTC).isoformat(), 'source': source,
                      'learned_sections': learned}
    _save(data)
    return {'report_type': report_type, 'samples': bucket['samples'],
            'learned_sections': learned, 'total_sections': len(secs)}


def pattern(report_type: str, min_hits: int = 1) -> dict:
    """学习到的章节模式（按频次降序）；data_reqs 为出现率百分比。"""
    data = _load()
    bucket = data.get(report_type)
    if not bucket:
        return {'report_type': report_type, 'sections': [], 'source_count': 0}
    sections = []
    for name, e in bucket.get('sections', {}).items():
        if e['hits'] < min_hits:
            continue
        reqs = e['reqs']
        sections.append({
            'name': name, 'hits': e['hits'],
            'data_reqs': {k: round(100 * v / e['hits']) for k, v in reqs.items()},
        })
    sections.sort(key=lambda s: -s['hits'])
    return {'report_type': report_type, 'sections': sections,
            'source_count': bucket.get('samples', 0)}


def _map_core(name: str) -> str | None:
    """章节名映射到硬编码 5 节；无法映射返回 None（学习到的额外章节）。"""
    for core, aliases in _CORE_ALIASES.items():
        if any(a in name for a in aliases):
            return core
    return None


def extra_sections(pat: dict) -> list[dict]:
    """硬编码 5 节之外的高频学习章节（供 R4 附加生成）。"""
    return [s for s in pat.get('sections', []) if _map_core(s['name']) is None]


def render_guide(pat: dict, max_n: int = 8) -> str:
    """生成编制要点文本（对话输出）：高频章节 + 数据要求。"""
    secs = pat.get('sections', [])
    if not secs:
        return ''
    lines = [f"[文档学习] 已从 {pat.get('source_count', 0)} 份同类报告语料学习到章节模式："]
    for s in secs[:max_n]:
        reqs = '、'.join(k.replace('has_', '') for k, v in s['data_reqs'].items() if v >= 60)
        lines.append(f"- {s['name']}（{s['hits']} 次" + (f"，常含 {reqs}" if reqs else '') + "）")
    return '\n'.join(lines)


def apply_learned(pat: dict) -> dict:
    """从学习模式提炼 plan 增强项：高频数据要求（供监测方案章节引用）。"""
    reqs: set[str] = set()
    for s in pat.get('sections', []):
        for k, v in s['data_reqs'].items():
            if v >= 60:
                reqs.add(k.replace('has_', ''))
    return {'learned_reqs': sorted(reqs)}


def learned_extra_content(s: dict) -> str:
    """学习章节的正文生成：按数据要求给出编制指引（不写"待填写"占位）。"""
    reqs = [k.replace('has_', '') for k, v in s['data_reqs'].items() if v >= 60]
    guide = '；'.join(reqs) if reqs else '章节结构与要点'
    return f"{s['name']}\n编制要点：依据 {s['hits']} 份同类报告语料，本节应包含{guide}。"
