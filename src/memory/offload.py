# -*- coding: utf-8 -*-
"""短期任务压缩：上下文卸载（offload）+ 符号画布（Mermaid Canvas）。

对齐 TencentDB-Agent-Memory 的短期上下文设计：
- offload：工具输出超过阈值时落盘到任务目录 refs/，上下文只保留摘要 + 引用路径，
  避免长任务上下文膨胀（官方 WideSearch token 减少 61% 的主要来源）。
- 符号画布：从消息轨迹生成带 node_id 的 Mermaid 状态图，任务结束时落盘
  canvas.md，后续任务只需注入画布（几百 token）即可恢复任务状态。

全部函数离线可用（规则版），LLM 可选注入（caller）。对外接口 try/except 包裹，
失败不阻断主流程。
"""
from __future__ import annotations

import re
from typing import Callable

# 工具输出卸载阈值（字符）
OFFLOAD_THRESHOLD = 2000
# 卸载后上下文保留的预览长度
PREVIEW_KEEP = 200
# 画布单节点文本最大长度
NODE_TEXT_MAX = 40


def _esc(text: str) -> str:
    """Mermaid 节点文本转义：去引号/换行/特殊字符，防止破坏图表语法。"""
    text = (text or '').replace('"', "'").replace('\n', ' ').strip()
    if len(text) > NODE_TEXT_MAX:
        text = text[: NODE_TEXT_MAX - 1] + '…'
    return text


def offload_tool_outputs(tid: int, msgs: list[dict], threshold: int = OFFLOAD_THRESHOLD,
                         dry_run: bool = False) -> dict:
    """把超长工具输出卸载到 data/task_outputs/<tid>/refs/，返回统计 + 压缩后的消息。

    msgs：db.get_messages 结构（含 role/content）。返回 {'compressed': msgs,
    'offloaded': n, 'offloaded_chars': chars}。不改变原始列表结构，
    卸载条目的 content 替换为『摘要 + [全文已卸载: refs/...]』。
    dry_run=True 时不写盘（用于评测/预览），引用路径仍返回。
    """
    from src.core import db_v12 as db

    compressed: list[dict] = []
    offloaded = 0
    chars = 0
    for i, m in enumerate(msgs):
        if m.get('role') == 'tool':
            content = str(m.get('content') or '')
            if len(content) > threshold:
                offloaded += 1
                chars += len(content)
                rel = f'refs/tool_{i}.md'
                if not dry_run:
                    try:
                        db.task_output_save(tid, rel, content)
                    except Exception:
                        # 落盘失败：仅截断，不卸载
                        compressed.append({**m, 'content': content[:PREVIEW_KEEP]})
                        continue
                summary = content[:PREVIEW_KEEP]
                compressed.append({
                    **m,
                    'content': f'{summary}\n\n[全文已卸载: {rel} · {len(content)}字符]',
                    'offload_ref': rel,
                })
                continue
        compressed.append(m)
    return {'compressed': compressed, 'offloaded': offloaded, 'offloaded_chars': chars}


def build_canvas(msgs: list[dict], max_nodes: int = 24) -> str:
    """从任务消息轨迹生成 Mermaid 符号画布（规则版，node_id 从 n1 递增）。

    节点类型：
    - 用户需求（user 首条）
    - 工具调用与输出摘要（tool）
    - 中间结论（assistant 含"完成/已/结论/结果"等信号）
    - 最终结论（最后一条 assistant）
    边：需求 → 步骤 → 步骤 → 最终结论。无法建模的内容聚合为『…』。
    """
    steps: list[tuple[str, str]] = []  # (kind, text)
    for m in msgs:
        role = m.get('role', '')
        content = str(m.get('content') or '').strip()
        if not content:
            continue
        if role == 'user':
            if not any(k == 'user' for k, _ in steps):
                steps.append(('goal', content[:NODE_TEXT_MAX]))
        elif role == 'tool':
            steps.append(('tool', content[:NODE_TEXT_MAX]))
        elif role == 'assistant':
            if any(k in content for k in ('完成', '结论', '结果', '已生成', '输出如下')):
                steps.append(('out', content[:NODE_TEXT_MAX]))

    if not steps:
        return ''
    # 去重相邻同类节点，控制画布大小
    dedup: list[tuple[str, str]] = []
    for s in steps:
        if dedup and dedup[-1][0] == s[0] and dedup[-1][1] == s[1]:
            continue
        dedup.append(s)
    if len(dedup) > max_nodes:
        dedup = dedup[:max_nodes]
        dedup.append(('out', '…（更多步骤已省略）'))

    lines = ['```mermaid', 'flowchart TD']
    ids: dict[int, str] = {}
    for i, (kind, text) in enumerate(dedup):
        nid = f'n{i + 1}'
        ids[i] = nid
        shape = '["' if kind in ('goal', 'out') else '("'
        closing = '"]' if kind in ('goal', 'out') else '")'
        lines.append(f'  {nid}{shape}{_esc(text)}{closing}')
    # 边
    edges: list[str] = []
    for i in range(len(dedup) - 1):
        edges.append(f'{ids[i]} --> {ids[i + 1]}')
    lines.extend(edges)
    lines.append('```')
    return '\n'.join(lines)


def save_task_canvas(tid: int, msgs: list[dict],
                     caller: Callable[[list[dict]], str] | None = None) -> dict:
    """任务结束：offload 长工具输出 + 生成符号画布，落盘并落库登记资产。

    返回 {'canvas': str, 'node_count': n, 'offloaded': n, 'offloaded_chars': n}。
    """
    off = offload_tool_outputs(tid, msgs)
    canvas = build_canvas(off['compressed'])
    node_count = max(0, canvas.count(' --> ') + 1)
    try:
        from src.core import db_v12 as db
        if canvas:
            db.task_output_save(tid, 'canvas.md', '# 任务符号画布\n\n' + canvas)
        # 落库 + 登记资产（失败静默）
        from src.core.db import get_conn as core_get_conn
        conn = core_get_conn()
        with conn:
            conn.execute(
                """INSERT INTO task_canvases(task_id, canvas_md, node_count, offloaded, offloaded_chars)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(task_id) DO UPDATE SET
                     canvas_md=excluded.canvas_md, node_count=excluded.node_count,
                     offloaded=excluded.offloaded, offloaded_chars=excluded.offloaded_chars,
                     created_at=datetime('now','localtime')""",
                (str(tid), canvas, node_count, off['offloaded'], off['offloaded_chars']),
            )
        from src.memory import assets
        assets.register('canvas', str(tid),
                        title=f'任务#{tid} 符号画布',
                        content=f'节点{node_count} 卸载{off["offloaded"]}条/{off["offloaded_chars"]}字符',
                        visibility='private', owner='local')
    except Exception:
        pass
    return {'canvas': canvas, 'node_count': node_count,
            'offloaded': off['offloaded'], 'offloaded_chars': off['offloaded_chars']}


def ensure_live_budget(tid: int, messages: list[dict], model=None,
                       context_length=None) -> dict:
    """实时上下文守卫（对齐 TencentDB beforePromptBuild / afterToolCall）。

    就地压缩 OpenAI 格式的 messages（含 system/assistant/tool_calls/tool_call_id）：
    1. 超长工具输出即时卸载到 data/task_outputs/<tid>/refs/live_*.md，
       上下文替换为『摘要 + [全文已卸载: refs/...]』（幂等：已卸载消息打
       _ea_offloaded 标记，避免重复写盘/覆盖）；
    2. 估算 token 超 soft 预算时，截断最旧的 tool/assistant 消息
       （user 与最近 6 条原始消息保持完整，system 不压缩）。

    任何失败静默返回空统计，不阻断主流程。
    """
    if not messages or len(messages) < 4:
        return {'offloaded': 0, 'compressed': 0, 'before': 0, 'after': 0}
    offloaded = 0
    for i, m in enumerate(messages):
        if m.get('role') != 'tool' or m.get('_ea_offloaded'):
            continue
        c = m.get('content')
        if not isinstance(c, str) or len(c) <= OFFLOAD_THRESHOLD:
            continue
        try:
            from src.core import db_v12 as db
            import time as _t
            ref = f'refs/live_{int(_t.time() * 1000)}_{i}.md'
            db.task_output_save(tid, ref, c)
            m['content'] = f'{c[:PREVIEW_KEEP]}\n\n[全文已卸载: {ref} · {len(c)}字符]'
            m['_ea_offloaded'] = True
            offloaded += 1
        except Exception:
            pass
    # 2) token 守卫：超 soft 预算截断旧消息
    total = after = 0
    compressed = 0
    try:
        from ..core.context import budgets_for, estimate_messages
        soft, _hard, _ctx, _src = budgets_for(model, context_length)
        total = estimate_messages(messages)
        if total > soft and len(messages) > 8:
            keep_raw = 6  # 保留最近 6 条原始消息
            budget = soft
            cur = 0
            for m in messages[:-keep_raw]:
                if m.get('role') == 'system':
                    continue
                c = str(m.get('content') or '')
                if not c:
                    continue
                room = budget - cur
                if room <= 0:
                    break
                if len(c) <= room:
                    cur += len(c)
                    continue
                if m.get('role') in ('tool', 'assistant'):
                    tail = f'\n[截断: 原{len(c)}字符]'
                    keep = min(len(c), max(60, room - len(tail)))
                    m['content'] = c[:keep] + tail
                    cur += keep + len(tail)
                    compressed += 1
        after = estimate_messages(messages)
    except Exception:
        pass
    return {'offloaded': offloaded, 'compressed': compressed,
            'before': total, 'after': after}


def summarize_window(msgs: list[dict], budget: int = 12000) -> list[dict]:
    """窗口压缩：把超长消息截断到预算内（供实时注入；offload 负责落盘完整内容）。

    规则：tool 消息优先压缩，其次 assistant，最后 user（user 保持完整）。
    """
    total = sum(len(str(m.get('content') or '')) for m in msgs)
    if total <= budget:
        return msgs
    out: list[dict] = []
    cur = 0
    for m in msgs:
        c = str(m.get('content') or '')
        room = budget - cur
        if room <= 0:
            break
        if len(c) <= room:
            out.append(m)
            cur += len(c)
            continue
        if m.get('role') == 'user':
            out.append({**m, 'content': c[:room]})
            cur += room
            continue
        tail = f'\n[截断: 原{len(c)}字符]'
        keep = min(len(c), max(60, room - len(tail)))
        out.append({**m, 'content': c[:keep] + tail})
        cur += keep + len(tail)
    return out
