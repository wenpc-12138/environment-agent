# -*- coding: utf-8 -*-
"""M07 SkillExecutor：技能执行器（v2_skills 表 / SKILL.md 双源加载）。

契约（contracts.md §3.M07）：
- `run(skill_id, params, context) -> SkillResult`：执行单个技能
- `run_dag(skill_ids, params) -> list[SkillResult]`：L3 顺序编排，前序输出注入后序 context

加载顺序：`v2_skills` 表（M05 ProceduralMemory 登记）优先，其次
`data/agents/skills/<id>/SKILL.md`（front-matter + body 格式）。definition 支持
JSON 步骤表（steps: [{tool, args}]）或纯文本提示词。工具调用链路随 M04 工具层落地。
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from ..core.config import get_settings
from ..core.db import get_conn
from ..core.utils import now_iso
from ..models.core import SkillResult

_FRONT_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n(.*)$', re.DOTALL)


class SkillExecutor:
    """技能执行器：加载定义、执行步骤、返回结构化结果。"""

    def run(self, skill_id: str, params: dict, context: dict) -> SkillResult:
        """执行单个技能。skill 不存在返回 ok=False（不抛异常，便于编排容错）。"""
        trace_id = uuid.uuid4().hex[:16]
        spec = self._load(skill_id)
        if spec is None:
            return SkillResult(
                ok=False,
                outputs={'skill_id': skill_id, 'error': '技能不存在'},
                trace_id=trace_id,
                usage_tokens=None,
            )
        status = spec.get('status', 'active')
        if status != 'active':
            # 第 8 波：pending_review / rejected / deprecated 硬拒绝，不执行步骤
            return SkillResult(
                ok=False,
                outputs={
                    'skill_id': skill_id,
                    'name': spec.get('name', skill_id),
                    'error': f'技能状态为 {status}，禁止执行（仅 active 技能可运行）',
                    'status': status,
                    'executed_at': now_iso(),
                },
                trace_id=trace_id,
                usage_tokens=None,
            )
        definition = spec['definition']
        steps = self._parse_steps(definition)
        outputs: dict[str, Any] = {
            'skill_id': skill_id,
            'name': spec.get('name', skill_id),
            'role': spec.get('role', ''),
            'steps': steps,
            'executed_at': now_iso(),
        }
        if steps:
            outputs['tool_calls'] = [s.get('tool') for s in steps if isinstance(s, dict)]
        return SkillResult(
            ok=True,
            outputs=outputs,
            trace_id=trace_id,
            usage_tokens=None,
        )

    def run_dag(self, skill_ids: list[str], params: dict) -> list[SkillResult]:
        """L3 顺序编排：串行执行，将前序 outputs 并入后序 context['prev']。"""
        results: list[SkillResult] = []
        ctx: dict[str, Any] = dict(params)
        for sid in skill_ids:
            res = self.run(sid, params, {'prev': [r.outputs for r in results], **ctx})
            results.append(res)
            ctx['last_outputs'] = res.outputs
        return results

    # ---- 内部 ----
    def _load(self, skill_id: str) -> dict[str, Any] | None:
        """按加载顺序取技能定义：v2_skills 表 -> data/agents/skills/<id>/SKILL.md。"""
        try:
            row = get_conn().execute(
                'SELECT * FROM v2_skills WHERE id=?', (skill_id,)
            ).fetchone()
        except Exception:
            row = None
        if row is not None:
            return {
                'name': row['name'], 'level': row['level'], 'role': row['role'],
                'domain': row['domain'], 'status': row['status'],
                'definition': row['definition'] or '',
            }
        return self._load_skill_md(skill_id)

    def _load_skill_md(self, skill_id: str) -> dict[str, Any] | None:
        """解析 data/agents/skills/<id>/SKILL.md（front-matter YAML 子集 + body）。"""
        root = get_settings().data_dir_path / 'agents' / 'skills' / skill_id
        md = root / 'SKILL.md'
        if not md.is_file():
            return None
        text = md.read_text(encoding='utf-8', errors='replace')
        m = _FRONT_RE.match(text)
        meta: dict[str, str] = {}
        body = text
        if m:
            for line in m.group(1).splitlines():
                if ':' in line:
                    k, _, v = line.partition(':')
                    meta[k.strip()] = v.strip()
            body = m.group(2).strip()
        return {
            'name': meta.get('name', skill_id),
            'level': meta.get('level', '1'),
            'role': meta.get('role', ''),
            'domain': meta.get('domain', ''),
            'status': 'active',
            'definition': body,
        }

    def _parse_steps(self, definition: str) -> list[Any]:
        """解析 definition：JSON 步骤表（[{tool,args}]）或纯文本提示词拆行。"""
        if not definition:
            return []
        try:
            data = json.loads(definition)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and isinstance(data.get('steps'), list):
                return data['steps']
        except (json.JSONDecodeError, ValueError):
            pass
        return [ln.strip() for ln in definition.splitlines() if ln.strip()][:20]
