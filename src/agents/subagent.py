# -*- coding: utf-8 -*-
"""G2 动态子代理（SubAgent as Tool，对齐 Claude Code Subagents 思路，实现完全自研）。

- `SubAgentSpec`：角色化子代理定义（复用 M08 R1-R8 角色体系 + RBAC 权限）。
- `SubAgentRunner.spawn()`：后台线程执行（独立上下文，不污染主窗口）；`collect()` 回收并落 episodic。
- `run_agent_task()`：核心执行体——注入 caller 做 LLM 调用 + 工具循环（tools.execute_tool 统一出口）。
  caller 返回 JSON 动作协议：`{"action":"tool","name":..,"params":..}` / `{"action":"final","text":..}`。
- 角色权限闸门：子代理只能调用其角色 permissions 允许的工具（对齐 R8 RBAC 理念）。
- `run_parallel()`：多子代理并行（报告章节并行起草等）。

零新增依赖；caller 为 None 时降级规则执行（不循环工具）。
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

# 角色 -> 允许工具白名单（对齐 M08 R1-R8 permissions 语义）
_ROLE_TOOL_ALLOW: dict[str, set[str]] = {
    'R1': {'kb_lookup', 'kb_stats', 'locate'},
    'R2': {'kb_lookup', 'kb_hybrid', 'calc_formula', 'web_search', 'locate'},
    'R3': {'calc_formula', 'kb_lookup', 'kb_hybrid'},
    'R4': {'kb_lookup', 'kb_hybrid', 'kb_save', 'calc_formula', 'web_search', 'web_fetch', 'locate'},
    'R5': {'kb_lookup', 'kb_stats', 'kb_hybrid', 'calc_formula', 'locate'},
    'R6': {'kb_lookup', 'kb_stats', 'kb_hybrid', 'locate'},
    'R7': {'kb_lookup', 'kb_hybrid', 'kb_stats', 'web_search', 'locate'},
    'R8': {'kb_lookup', 'kb_stats', 'kb_audit', 'kb_backup', 'locate'},
}
_FALLBACK_ROLE = 'R1'


@dataclass
class SubAgentSpec:
    """子代理规格（role_id 对齐 R1-R8；tools 缺省按角色白名单）。"""

    name: str = 'subagent'
    role_id: str = 'R4'
    max_steps: int = 6
    tools: list[str] = field(default_factory=list)
    system_extra: str = ''   # 追加角色指令

    def allowed_tools(self) -> set[str]:
        if self.tools:
            return set(self.tools)
        return _ROLE_TOOL_ALLOW.get(self.role_id, _ROLE_TOOL_ALLOW[_FALLBACK_ROLE])


def _role_name(role_id: str) -> str:
    try:
        from ..roles.registry import RoleRegistry
        bp = RoleRegistry().get(role_id)
        return bp.name if bp else role_id
    except Exception:  # noqa: BLE001
        return role_id


def _role_permissions(role_id: str) -> list[str]:
    try:
        from ..roles.registry import RoleRegistry
        bp = RoleRegistry().get(role_id)
        return list(bp.permissions) if bp else []
    except Exception:  # noqa: BLE001
        return []


def build_system_prompt(spec: SubAgentSpec, task: str) -> str:
    """子代理系统提示：角色职责 + 允许工具 + 输出协议。"""
    perms = '、'.join(_role_permissions(spec.role_id)) or 'read_data'
    tools = '、'.join(sorted(spec.allowed_tools())) or '无'
    extra = f'\n补充指令：{spec.system_extra}' if spec.system_extra else ''
    return (
        f'你是子代理「{spec.name}」（角色 {spec.role_id} {_role_name(spec.role_id)}）。\n'
        f'角色职责权限：{perms}\n'
        f'可调用工具：{tools}\n'
        '任务：' + task[:2000] + '\n'
        '执行协议：每次输出一行 JSON，两种动作之一：\n'
        '  {"action":"tool","name":"工具名","params":{...}}  调用工具后我会回传结果\n'
        '  {"action":"final","text":"最终结果"}              完成任务并结束\n'
        '最多执行 6 轮工具调用；直接给结论时用 final。' + extra)


def run_agent_task(spec: SubAgentSpec, task: str,
                   caller: Callable[[list[dict]], str] | None = None,
                   max_steps: int | None = None,
                   ctx: dict | None = None,
                   ctrl: dict | None = None) -> dict:
    """执行一个子代理任务（同步；可放入线程并行）。

    返回 {'ok', 'name', 'role', 'result', 'steps', 'tool_calls', 'errors'}。
    caller=None 时降级：不调工具，直接返回规则提示（供无 LLM 环境测试/降级）。

    H4 实时操控（对齐 Hermes subagent steering）：`ctrl` 为共享控制对象
    （SubAgentRunner holder 传入），承载：
    - state：当前状态快照（queued/running/stopped），由运行线程维护；
    - round：当前轮次（实时可见）；
    - partial：已产出文本累计（stop_partial 可回收部分结果）；
    - steer_queue：纠偏指令队列（steer() 追加，每轮前消费注入）；
    - stop：停止标志（stop_partial() 置位，线程尽快结束保留 partial）。
    ctrl=None 时保持原行为（无操控能力）。
    """
    max_steps = max(1, min(max_steps or spec.max_steps, 12))
    system = build_system_prompt(spec, task)
    messages: list[dict] = [{'role': 'system', 'content': system},
                            {'role': 'user', 'content': task[:3000]}]
    steps: list[dict] = []
    tool_calls = 0
    errors = 0
    result = ''
    partial = ''

    def _ctrl_update(**kw):
        if ctrl is not None:
            try:
                ctrl.update(kw)
            except Exception:  # noqa: BLE001
                pass

    def _consume_steer() -> None:
        """消费纠偏指令队列：有指令则作为 user 消息注入（下一轮生效）。"""
        if ctrl is None:
            return
        try:
            q = ctrl.get('steer_queue') or []
            if q:
                ctrl['steer_queue'] = []
                for ins in q:
                    messages.append({'role': 'user',
                                     'content': f'[纠偏指令] {str(ins)[:400]}'})
        except Exception:  # noqa: BLE001
            pass

    if caller is None:
        # 规则降级：给出角色执行提示（不循环）
        result = (f'[子代理 {spec.name}] 无 LLM caller，未执行工具。'
                  f'角色 {spec.role_id}，允许工具：{", ".join(sorted(spec.allowed_tools()))}。')
        _ctrl_update(state='done')
        return {'ok': True, 'name': spec.name, 'role': spec.role_id,
                'result': result, 'steps': [], 'tool_calls': 0, 'errors': 0}

    _ctrl_update(state='running', round=0)
    allowed = spec.allowed_tools()
    for i in range(max_steps):
        if ctrl is not None and ctrl.get('stop'):
            steps.append({'round': i + 1, 'action': 'stopped',
                          'note': '用户停止（保留部分结果）'})
            result = partial or '[子代理] 已被用户停止，未产出完整结论。'
            _ctrl_update(state='stopped', round=i)
            break
        _consume_steer()
        _ctrl_update(round=i + 1)
        try:
            raw = (caller(messages) or '').strip()
        except Exception as exc:  # noqa: BLE001
            errors += 1
            steps.append({'round': i + 1, 'error': f'{type(exc).__name__}: {exc}'})
            if errors >= 3:
                break
            continue
        decision = _parse_decision(raw)
        if decision is None:
            steps.append({'round': i + 1, 'decision': raw[:120], 'note': '无法解析动作协议，尝试 final'})
            result = raw[:2000]
            break
        # 记录部分产出（caller 文本里含最终结论的候选片段，供 stop_partial 回收）
        try:
            _partial_txt = str(decision.get('text') or '')
            if _partial_txt:
                partial = _partial_txt[:4000]
                _ctrl_update(partial=partial)
        except Exception:  # noqa: BLE001
            pass
        if decision['action'] == 'final':
            result = str(decision.get('text') or '')[:4000]
            steps.append({'round': i + 1, 'action': 'final', 'text': result[:300]})
            break
        # tool
        name = str(decision.get('name') or '')
        if name not in allowed:
            errors += 1
            steps.append({'round': i + 1, 'action': 'tool', 'tool': name,
                          'error': f'工具 {name} 不在角色 {spec.role_id} 权限白名单'})
            messages.append({'role': 'user', 'content': f'工具 {name} 无权限，请用 final 结束或改用允许工具。'})
            continue
        try:
            from ..tools._v12 import execute_tool
            ok, out = execute_tool(name, decision.get('params') or {})
        except Exception as exc:  # noqa: BLE001
            ok, out = False, f'{type(exc).__name__}: {exc}'
        tool_calls += 1
        if not ok:
            errors += 1
        steps.append({'round': i + 1, 'action': 'tool', 'tool': name, 'ok': ok,
                      'output': str(out)[:300]})
        messages.append({'role': 'tool', 'tool_call_id': str(i), 'content': str(out)[:4000]})
        messages.append({'role': 'user', 'content': '工具已执行，继续（或 final 结束）。'})

    if not result:
        result = '[子代理] 达到最大步骤数未产出最终结论。'
    _ctrl_update(state='done')
    return {'ok': errors == 0 and bool(result), 'name': spec.name, 'role': spec.role_id,
            'result': result, 'steps': steps, 'tool_calls': tool_calls, 'errors': errors}


def _parse_decision(raw: str) -> dict | None:
    """解析 caller 输出的单行 JSON 动作；宽松提取第一个 {...}。"""
    if not raw:
        return None
    start, end = raw.find('{'), raw.rfind('}')
    if start >= 0 and end > start:
        try:
            d = json.loads(raw[start:end + 1])
            if isinstance(d, dict) and d.get('action') in ('tool', 'final'):
                return d
        except (ValueError, TypeError):
            pass
    # 容错：形如 [tool:name] params 的简化协议（无 action 字段的 JSON 也走到这里）
    m = re.search(r'\[tool:([a-z_0-9]+)\](.*)', raw, re.S)
    if m:
        return {'action': 'tool', 'name': m.group(1).strip(),
                'params': _loose_params(m.group(2))}
    if 'final' in raw or '结果' in raw[:20]:
        return {'action': 'final', 'text': raw}
    return None


def _loose_params(text: str) -> dict:
    try:
        d = json.loads(text.strip() or '{}')
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


# ---------------- 异步 spawn / collect ----------------

def build_projection(spec: SubAgentSpec | None, task: str | None,
                     result: dict | None) -> dict:
    """S3-H2 子代理投影：把「任务 → 结论 → 关键产出」压成结构化摘要。

    对齐 Harness session-projection：主代理回收子代理结果时，无需翻原始
    输出即可引用其结论与产出（tool_calls 数量、失败数、步骤摘要）。
    """
    result = result or {}
    return {
        'name': getattr(spec, 'name', 'subagent') if spec else 'subagent',
        'role': getattr(spec, 'role_id', '') if spec else '',
        'task': (task or '')[:300],
        'conclusion': str(result.get('result') or '')[:800],
        'ok': bool(result.get('ok')),
        'tool_calls': int(result.get('tool_calls') or 0),
        'errors': int(result.get('errors') or 0),
        'steps': len(result.get('steps') or []),
    }


class SubAgentRunner:
    """子代理调度：spawn 后台线程 + collect 回收 + run_parallel 并行。"""

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def spawn(self, spec: SubAgentSpec, task: str, caller: Callable | None = None,
              ctx: dict | None = None) -> str:
        """后台线程执行；返回 sub_id。线程内异常捕获，不污染主链路。

        H4 实时操控（对齐 Hermes subagent steering）：holder 内置 ctrl 控制对象
        （state/round/partial/steer_queue/stop），供 running()/steer()/stop_partial()
        读取与写入；caller 提供时子代理循环会响应纠偏与停止。
        """
        sub_id = f'sub-{uuid.uuid4().hex[:8]}'
        ctrl: dict[str, Any] = {'state': 'queued', 'round': 0, 'partial': '',
                                'steer_queue': [], 'stop': False}
        holder: dict[str, Any] = {'id': sub_id, 'status': 'running', 'result': None,
                                  'done': threading.Event(), 'spec': spec, 'task': task,
                                  'ctrl': ctrl}

        def _run() -> None:
            try:
                holder['result'] = run_agent_task(spec, task, caller=caller, ctx=ctx,
                                                  ctrl=ctrl)
                holder['status'] = 'done' if not ctrl.get('stop') else 'stopped'
                # 结果落 episodic（entity=sub:<name>，供检索复用）
                try:
                    from ..memory.episodic import EpisodicMemory
                    EpisodicMemory().add(
                        entity=f'sub:{spec.name}',
                        event='subagent-completed',
                        payload={'role': spec.role_id, 'task': task[:200],
                                 'result': holder['result'].get('result', '')[:500],
                                 'tool_calls': holder['result'].get('tool_calls', 0)})
                except Exception:  # noqa: BLE001
                    pass
            except Exception as exc:  # noqa: BLE001
                holder['status'] = 'error'
                holder['result'] = {'ok': False, 'name': spec.name, 'role': spec.role_id,
                                    'result': f'{type(exc).__name__}: {exc}', 'errors': 1}
            finally:
                holder['done'].set()

        with self._lock:
            self._jobs[sub_id] = holder
        th = threading.Thread(target=_run, name=f'ea-sub-{spec.name}', daemon=True)
        th.start()
        return sub_id

    def running(self) -> list[dict]:
        """H4：运行中子代理状态快照（id/name/role/round/partial 预览）。"""
        with self._lock:
            out = []
            for k, v in self._jobs.items():
                if v.get('status') != 'running':
                    continue
                ctrl = v.get('ctrl') or {}
                spec = v.get('spec')
                out.append({
                    'id': k,
                    'name': getattr(spec, 'name', 'subagent') if spec else 'subagent',
                    'role': getattr(spec, 'role_id', '') if spec else '',
                    'state': ctrl.get('state', 'running'),
                    'round': int(ctrl.get('round') or 0),
                    'partial': str(ctrl.get('partial') or '')[:200],
                })
            return out

    def steer(self, sub_id: str, instruction: str) -> dict:
        """H4：向运行中子代理追加纠偏指令（下一轮生效）。"""
        with self._lock:
            holder = self._jobs.get(sub_id)
        if holder is None:
            return {'ok': False, 'error': f'子代理不存在: {sub_id}'}
        ctrl = holder.get('ctrl') or {}
        try:
            q = ctrl.setdefault('steer_queue', [])
            q.append(str(instruction)[:400])
            return {'ok': True, 'id': sub_id}
        except Exception as exc:  # noqa: BLE001
            return {'ok': False, 'error': str(exc)}

    def stop_partial(self, sub_id: str) -> dict:
        """H4：停止运行中子代理，保留部分结果（collect 可回收）。"""
        with self._lock:
            holder = self._jobs.get(sub_id)
        if holder is None:
            return {'ok': False, 'error': f'子代理不存在: {sub_id}'}
        ctrl = holder.get('ctrl')
        if ctrl is not None:
            ctrl['stop'] = True
        return {'ok': True, 'id': sub_id, 'partial': str((ctrl or {}).get('partial') or '')[:200]}

    def collect(self, sub_id: str, timeout: float = 60.0) -> dict | None:
        """回收子代理结果（阻塞 timeout 秒）；不存在返回 None。

        S3-H2 投影（对标 Harness session-projection）：返回结果附
        `projection` 字段——「任务 → 结论 → 关键产出」结构化摘要，
        供主会话直接引用（避免"派出去就忘了"）。
        H4：stopped 状态（stop_partial 触发）也返回 projection 与部分结果。
        """
        with self._lock:
            holder = self._jobs.get(sub_id)
        if holder is None:
            return None
        holder['done'].wait(timeout)
        status = holder['status']
        if status == 'running':
            status = 'timeout'
        out: dict[str, Any] = {'id': sub_id, 'status': status, 'result': holder['result']}
        if status in ('done', 'stopped'):
            out['projection'] = build_projection(holder.get('spec'), holder.get('task'),
                                                 holder['result'])
        return out

    def collect_all(self, sub_ids: list[str], timeout: float = 60.0) -> list[dict]:
        return [self.collect(sid, timeout) for sid in sub_ids]

    def list(self) -> list[dict]:
        with self._lock:
            return [{'id': k, 'status': v['status']} for k, v in self._jobs.items()]

    def run_parallel(self, specs: list[SubAgentSpec], tasks: list[str],
                     caller: Callable | None = None,
                     timeout: float = 60.0) -> list[dict]:
        """多子代理并行执行（对齐报告章节并行起草场景）。"""
        sub_ids = [self.spawn(spec, task, caller=caller) for spec, task in zip(specs, tasks)]
        return self.collect_all(sub_ids, timeout)


# 模块级单例
_runner: SubAgentRunner | None = None


def get_runner() -> SubAgentRunner:
    global _runner
    if _runner is None:
        _runner = SubAgentRunner()
    return _runner
