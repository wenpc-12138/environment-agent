# -*- coding: utf-8 -*-
"""自动技能沉淀（SkillForge）：从任务轨迹提取可复用流程，生成技能草稿。

对齐 TencentDB-Agent-Memory 的自动技能生成 pipeline（轨迹 → 通用方案 → SOP）：
- 规则版（离线可用）：提取用户目标、工具步骤序列、最终结论，组装 YAML 定义；
- 产出技能写入 v2_skills 且 status='pending_review'，需 R8 审核激活（防噪音污染）；
- 登记为 skill 类型记忆资产，可被 best_match 后续召回。

触发条件（防止低价值任务噪音）：
- 工具步骤 ≥ 3；
- 有明确用户目标；
- 同源任务尚未产出过相同技能（按 name 去重）。
"""
from __future__ import annotations

import re
from typing import Callable

from ..core.db import get_conn

_MIN_STEPS = 3
_SKILL_PREFIX = 'sk-auto'
_TITLE_RE = re.compile(r'[^\s，。；、]{4,40}')


def _next_skill_id() -> str:
    """生成 sk-auto-### 序号 id（兼容 SkillDef 命名模式 sk-[a-z]{3,6}-\\d{3}）。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(id, 9) AS INTEGER)) AS m FROM v2_skills WHERE id LIKE 'sk-auto-%'"
    ).fetchone()
    n = (row['m'] if row and row['m'] else 0) + 1
    return f'{_SKILL_PREFIX}-{n:03d}'


def _extract_trace(msgs: list[dict]) -> dict:
    """规则提取轨迹要素：goal / tools / outcomes / conclusion。"""
    goal = ''
    tools: list[str] = []
    outcomes: list[str] = []
    conclusion = ''
    for m in msgs:
        role = m.get('role', '')
        content = str(m.get('content') or '').strip()
        if not content:
            continue
        if role == 'user' and not goal:
            goal = content[:60]
        elif role == 'tool':
            # 工具输出：取首行/关键词前缀作为工具摘要
            head = re.sub(r'\s+', ' ', content)[:40]
            tools.append(head or '工具输出')
        elif role == 'assistant':
            if any(k in content for k in ('完成', '结论', '结果', '已生成', '输出如下')):
                outcomes.append(content[:40])
                conclusion = content[:120]
    return {'goal': goal, 'tools': tools, 'outcomes': outcomes, 'conclusion': conclusion}


def _build_yaml(trace: dict, tid: int) -> str:
    """组装技能 YAML 定义（含来源任务与自动沉淀标记）。"""
    steps = []
    for i, t in enumerate(trace['tools'], 1):
        steps.append(f'  - {i}. {t}')
    if trace['outcomes']:
        steps.append(f'  - {len(trace["tools"]) + 1}. 汇总结果: {trace["outcomes"][-1]}')
    yaml = [
        f'name: {trace["goal"]}',
        'level: 2',
        'trigger: 用户请求涉及该主题或工具链时',
        'steps:',
        *(steps or ['  - (无可复用步骤)']),
        f'expected: {trace["conclusion"] or "(见步骤输出)"}',
        f'source_task: #{tid}',
        'forge_mode: auto_trace',
    ]
    return '\n'.join(yaml)


def forge_skill_from_trace(tid: int, msgs: list[dict],
                           caller: Callable[[list[dict]], str] | None = None) -> dict | None:
    """从任务轨迹自动沉淀技能草稿（pending_review）。

    返回 {'skill_id', 'name', 'definition'}；不满足条件或失败返回 None。
    """
    try:
        if not msgs:
            return None
        trace = _extract_trace(msgs)
        if not trace['goal'] or len(trace['tools']) < _MIN_STEPS:
            return None
        name = re.sub(r'[\n\r]+', ' ', trace['goal'])[:40]
        # 同源技能去重（按 name）
        dup = get_conn().execute(
            'SELECT id FROM v2_skills WHERE name=? LIMIT 1', (name,)).fetchone()
        if dup is not None:
            return None
        defn = _build_yaml(trace, tid)
        sid = _next_skill_id()
        conn = get_conn()
        with conn:
            conn.execute(
                """INSERT INTO v2_skills(id, name, level, role, domain, version, status, definition, created_by)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (sid, name, 2, 'R8', 'auto', '1.0.0', 'pending_review', defn, 'agent_oercr'),
            )
        from src.memory import assets
        assets.register('skill', sid, title=name, content=defn,
                        visibility='private', owner='local')
        return {'skill_id': sid, 'name': name, 'definition': defn}
    except Exception:
        return None
