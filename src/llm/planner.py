# -*- coding: utf-8 -*-
"""G1 显式规划器（Plan-Execute，对齐 LangGraph Plan 范式，实现完全自研）。

- `PlanAgent.plan(text, domain, mode_hint)`：规则拆解任务 -> `list[PlanStep]`
  （领域模板 + 目标定制；LLM 规划器可经 caller 注入，失败降级规则）。
- `PlanAgent.execute_plan(steps, ...)`：逐布执行——tool 走 ToolRegistry / skill 走 SkillExecutor，
  步骤 params 中 `$prev` 由上一步 outputs 注入；失败步骤标记 failed 并可中断。
- 计划可落 episodic（entity=任务主题），与 M5 摘要、P9 审核闸门互补。

与 plan 模式关系：plan 模式只输出计划不执行（对齐现有 MODE_HINTS）；
interactive/craft 可手动执行（execute=True）。
"""
from __future__ import annotations

import re
from typing import Any, Callable

from ..models.core import PlanStep
from .intent import IntentRouter

# 领域 -> 建议技能（plan 模板中作为可选技能步骤目标）
_DOMAIN_SKILLS: dict[str, str] = {
    'D1': 'water-monitoring',
    'D2': 'air-monitoring',
    'D3': 'noise-monitoring',
    'D4': 'soil-monitoring',
    'D5': 'self-monitoring',
    'D6': 'eia-report',
}
# 报告/方案/评估类关键词 -> 报告技能
_REPORT_KW = ('报告', '方案', '评估', '环评', '验收', '监测计划', '编制')
_CALC_KW = ('计算', '指数', '限值', '超标', '均值', '回收率', '浓度', '排放量', '达标')
_QA_KW = ('审核', '检查', '质控', '合规', '核对', '验证')


class PlanAgent:
    """任务 -> 结构化步骤 -> 顺序执行。"""

    def __init__(self, planner_caller: Callable[[str], str] | None = None) -> None:
        self._planner_caller = planner_caller

    # ---- 计划生成 ---------------------------------------------------
    def plan(self, text: str, domain: str = '', mode_hint: str = '') -> list[PlanStep]:
        """规则拆解任务为步骤；LLM 规划器可注入（planner_caller），失败降级规则。"""
        if self._planner_caller is not None:
            try:
                llm_steps = self._plan_with_llm(text, domain)
                if llm_steps:
                    return llm_steps
            except Exception:  # noqa: BLE001 降级规则
                pass
        return self._plan_rules(text, domain)

    def _plan_rules(self, text: str, domain: str = '') -> list[PlanStep]:
        """规则模板：情报检索 -> (计算) -> (技能) -> (审核) -> 整理交付。"""
        steps: list[PlanStep] = []
        d = domain or IntentRouter().analyze(text).domain
        skill_id = _DOMAIN_SKILLS.get(d, '')

        def add(goal: str, action: str, target: str, params: dict | None = None,
                outputs: str = '', note: str = '') -> None:
            steps.append(PlanStep(
                seq=len(steps) + 1, goal=goal, action=action, target=target,
                params=params or {}, outputs_name=outputs, note=note))

        q = _strip_query(text)
        add('检索相关标准与本地知识', 'tool', 'kb_lookup',
            {'query': q, 'top_n': 5}, 'kb', '获取标准依据/限值/方法')
        if any(k in text for k in _CALC_KW):
            add('按引用标准计算关键指标', 'tool', 'calc_formula',
                {'standard': '', 'calc_type': _pick_calc_type(text), 'data': {}}, 'calc',
                '污染指数/超标倍数/均值等计算')
        if skill_id:
            add('调用领域技能执行标准流程', 'skill', skill_id,
                {'query': q}, 'skill', f'技能 {skill_id}（{d}）')
        if any(k in text for k in _QA_KW):
            add('核对结果与标准符合性', 'tool', 'kb_lookup',
                {'query': q + ' 审核要点', 'top_n': 3}, 'check', '复核关键点')
        add('汇总步骤结果形成交付', 'llm', 'summarize',
            {'$prev': 'all'}, 'summary', '综合检索/计算/技能结果输出结论')
        return steps

    def _plan_with_llm(self, text: str, domain: str = '') -> list[PlanStep] | None:
        """LLM 规划器（caller 注入）：返回步骤 JSON 数组，解析失败返回 None。"""
        import json
        prompt = (
            '你是任务规划器。把用户任务拆解为 3-6 个有序执行步骤，'
            '仅输出 JSON 数组，每项 {"goal","action","target","params","outputs_name","note"}。'
            'action 取 tool/skill/llm；tool 可从 kb_lookup/calc_formula/web_search/web_fetch/kb_harvest '
            '中选择，skill 目标可空；params 为对象（可含 $prev 引用上一步）。\n任务：' + text[:2000])
        raw = (self._planner_caller(prompt) or '').strip()
        start, end = raw.find('['), raw.rfind(']')
        if start < 0 or end < start:
            return None
        items = json.loads(raw[start:end + 1])
        steps: list[PlanStep] = []
        for it in items:
            steps.append(PlanStep(
                seq=len(steps) + 1,
                goal=str(it.get('goal') or ''),
                action=it.get('action') if it.get('action') in ('tool', 'skill', 'llm') else 'tool',
                target=str(it.get('target') or ''),
                params=it.get('params') or {},
                outputs_name=str(it.get('outputs_name') or ''),
                note=str(it.get('note') or '')))
        return steps or None

    # ---- 执行 -------------------------------------------------------
    def execute_plan(self, steps: list[PlanStep], text: str = '',
                     context: dict | None = None,
                     tool_registry=None, skill_executor=None,
                     continue_on_error: bool = False) -> dict:
        """顺序执行步骤；返回 {'steps', 'ok', 'executed', 'failed', 'summary'}。

        - tool 步骤：ToolRegistry.execute(target, params)
        - skill 步骤：SkillExecutor.run(target, params, ctx)
        - llm 步骤：规则汇总前序 outputs（无 LLM 依赖）
        - `$prev` 注入：params['$prev'] = 上一步 outputs（'all'=全部汇总）
        """
        if not steps:
            return {'steps': [], 'ok': False, 'executed': 0, 'failed': 0, 'summary': ''}
        if tool_registry is None:
            from ..tools.registry import ToolRegistry
            tool_registry = ToolRegistry()
        if skill_executor is None:
            from ..skills.executor import SkillExecutor
            skill_executor = SkillExecutor()
        ctx = dict(context or {})
        executed = failed = 0
        prev_outputs: dict[str, Any] = {}
        collected: list[str] = []

        for st in steps:
            st.status = 'running'
            params = self._resolve_params(st, prev_outputs)
            ok, out = False, None
            try:
                if st.action == 'tool':
                    r = tool_registry.execute(st.target, params)
                    ok, out = r.ok, r.data
                elif st.action == 'skill':
                    r = skill_executor.run(st.target, params, {'prev': collected, **ctx})
                    ok, out = r.ok, r.outputs
                else:  # llm：规则汇总（无 LLM 依赖）
                    parts = []
                    if prev_outputs:
                        for k, v in prev_outputs.items():
                            parts.append(f'{k}: {str(v)[:400]}')
                    out = ('已汇总前序步骤结果。\n' + '\n'.join(parts)) if parts else '（无前序产出）'
                    ok = True
            except Exception as exc:  # noqa: BLE001 单步失败不抛
                ok, out = False, f'{type(exc).__name__}: {exc}'
            st.status = 'done' if ok else 'failed'
            st.result = out
            if ok:
                executed += 1
                prev_outputs[st.outputs_name or f'step{st.seq}'] = out
                collected.append(str(out)[:500])
            else:
                failed += 1
                if not continue_on_error:
                    break
        # 摘要
        summary = _build_summary(steps, executed, failed)
        # 落 episodic（可选，静默）
        try:
            if text:
                from ..memory.episodic import EpisodicMemory
                EpisodicMemory().add(entity='plan:' + text[:30], event='plan-executed',
                                     payload={'goal': text[:200], 'steps': len(steps),
                                              'ok': executed > 0, 'failed': failed})
        except Exception:  # noqa: BLE001
            pass
        return {'steps': [s.model_dump() for s in steps], 'ok': executed > 0,
                'executed': executed, 'failed': failed, 'summary': summary}

    def _resolve_params(self, st: PlanStep, prev_outputs: dict) -> dict:
        params = dict(st.params or {})
        if '$prev' in params:
            pv = params.pop('$prev')
            if pv == 'all':
                merged: dict[str, Any] = {}
                for v in prev_outputs.values():
                    if isinstance(v, dict):
                        merged.update(v)
                params.update(merged)
            else:
                params['$prev'] = prev_outputs.get(str(pv), '')
        return params


# ---- 工具函数 --------------------------------------------------------

def _strip_query(text: str) -> str:
    """任务描述 -> 检索关键词（去语气词/标点，取前 40 字）。"""
    q = re.sub(r'[，。；、！？!?,\s]+', ' ', (text or '')).strip()
    for kw in ('请', '帮我', '需要', '麻烦', '生成', '编制', '出具', '做一份'):
        q = q.replace(kw, '')
    return q[:40] or (text or '')[:40]


def _pick_calc_type(text: str) -> str:
    for kw, ct in (('超标', '超标倍数'), ('综合', '综合污染指数'), ('均值', '算术均值'),
                   ('回收率', '加标回收率'), ('排放', '排放速率'), ('指数', '污染指数')):
        if kw in text:
            return ct
    return '污染指数'


def _build_summary(steps: list[PlanStep], executed: int, failed: int) -> str:
    lines = [f'计划共 {len(steps)} 步，成功 {executed} 步，失败 {failed} 步。']
    for st in steps:
        mark = 'PASS' if st.status == 'done' else ('FAIL' if st.status == 'failed' else 'SKIP')
        lines.append(f'[{mark}] {st.seq}. {st.goal}（{st.target}）')
    return '\n'.join(lines)
