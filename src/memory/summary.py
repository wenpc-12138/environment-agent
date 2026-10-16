# -*- coding: utf-8 -*-
"""M5 三层摘要（自主实现，仅借鉴"分层摘要按需加载"概念，不引用 AGPL 代码）。

对齐字节 OpenViking 的 L0/L1/L2 概念，但实现完全自主：
- L0 全文（原始对话/输出，已有 chat.md）
- L1 `.abstract.md`（精要，~100 token）：对话要点、关键决策、待办、异常
- L2 `.overview.md`（概览，~2K token）：完整结构化摘要（用户需求/执行过程/结果/技能沉淀）

触发：任务结束 export_task_chat 后自动生成两级摘要到任务输出目录；
LLM 可注入（默认离线规则，基于消息结构提取），保证离线可用且低噪。
"""
from __future__ import annotations

import re
from typing import Any, Callable

# L1 精要抽取规则（规则版：从消息文本提取关键行）
_KEY_LINE_RE = re.compile(
    r'(?:要求|结论|结果|完成|失败|错误|待办|建议|标准|采用|决定|方案)[:：]\s*[^\n]{2,80}')
_ACTION_RE = re.compile(r'(?:已|正在|需(?:要)?)(?:完成|生成|处理|审核|执行|修复|编写)[^\n]{2,60}')


def summarize_task_messages(msgs: list[dict], caller: Callable[[list[dict]], str] | None = None) -> dict:
    """对任务消息生成两级摘要，返回 {abstract, overview}。

    msgs：db.get_messages 结构（含 role/content）。
    """
    if not msgs:
        return {'abstract': '', 'overview': ''}
    # 组装文本（按角色归并）
    lines = []
    for m in msgs:
        role = m.get('role', '')
        content = str(m.get('content') or '').strip()
        if not content:
            continue
        if role == 'user':
            lines.append(f'U: {content[:400]}')
        elif role == 'assistant':
            lines.append(f'A: {content[:400]}')
        elif role == 'tool':
            lines.append(f'T: {content[:200]}')
    text = '\n'.join(lines)
    if caller is not None:
        try:
            return _llm_summary(text, caller)
        except Exception:
            pass
    return _rule_summary(text)


def _rule_summary(text: str) -> dict:
    """规则摘要：L1 关键行抽取，L2 结构化（用户需求/执行过程/结果/技能沉淀）。"""
    # L1 精要：关键决策/结论/待办行
    keys = []
    seen = set()
    for m in _KEY_LINE_RE.finditer(text):
        line = m.group(0).strip()
        if line not in seen and len(keys) < 12:
            seen.add(line)
            keys.append(line)
    if not keys:
        keys = [l[3:] for l in text.splitlines() if len(l) > 8][:5]

    # L2 概览：用户需求 + 执行过程 + 结果/产出 + 技能
    user_reqs = [l[3:] for l in text.splitlines() if l.startswith('U:') and len(l) > 5][:6]
    results = [l[3:] for l in text.splitlines()
               if l.startswith('A:') and any(k in l for k in ('完成', '生成', '结论', '结果'))][:6]
    tools = [l[3:] for l in text.splitlines() if l.startswith('T:') and len(l) > 5][:8]
    skills = [l[3:] for l in text.splitlines()
              if l.startswith('A:') and any(k in l for k in ('技能', 'OERCR', '学习'))][:4]

    overview = []
    if user_reqs:
        overview.append('## 用户需求')
        overview += [f'- {r}' for r in user_reqs]
    if results:
        overview.append('## 执行结果')
        overview += [f'- {r}' for r in results]
    if tools:
        overview.append('## 使用工具')
        overview += [f'- {t}' for t in tools]
    if skills:
        overview.append('## 技能沉淀')
        overview += [f'- {s}' for s in skills]
    overview.append('## 摘要')
    overview += [f'- {k}' for k in keys]

    return {'abstract': '\n'.join(keys), 'overview': '\n'.join(overview)}


def _llm_summary(text: str, caller: Callable[[list[dict]], str]) -> dict:
    """LLM 版两级摘要（注入 provider 时启用，输出结构化 markdown）。"""
    prompt = (
        '你是摘要器。对以下对话生成两级摘要，仅输出两段，第一段以"ABSTRACT:"开头（精要≤8行），'
        '第二段以"OVERVIEW:"开头（结构化：用户需求/执行过程/结果/技能沉淀）。\n'
        '只基于给定内容，不臆造。\n' + text[:4000])
    raw = (caller([{'role': 'user', 'content': prompt}]) or '').strip()
    abstract = overview = ''
    if 'OVERVIEW:' in raw:
        abstract = raw.split('OVERVIEW:')[0].replace('ABSTRACT:', '').strip()
        overview = raw.split('OVERVIEW:', 1)[1].strip()
    elif 'ABSTRACT:' in raw:
        abstract = raw.replace('ABSTRACT:', '').strip()
        overview = abstract
    else:
        return _rule_summary(text)
    return {'abstract': abstract, 'overview': overview or abstract}


def save_task_summaries(tid: int, msgs: list[dict], caller: Callable[[list[dict]], str] | None = None) -> dict:
    """任务结束生成两级摘要并落盘 data/task_outputs/<tid>/（L1 abstract.md / L2 overview.md）。

    升级（对标 TencentDB L2 场景记忆）：
    - 摘要同时写入 task_summaries 索引表，可被 M6 检索路由召回；
    - 登记为 summary 类型记忆资产（含可见性/使用统计）。
    """
    res = summarize_task_messages(msgs, caller)
    from src.core import db_v12 as db
    db.task_output_save(tid, 'abstract.md', f'# 任务精要\n\n{res["abstract"] or "(无)"}')
    db.task_output_save(tid, 'overview.md', f'# 任务概览\n\n{res["overview"] or "(无)"}')
    # L2 场景记忆落库 + 资产登记（失败静默，不影响主流程）
    try:
        title = ''
        for m in msgs:
            if m.get('role') == 'user':
                title = str(m.get('content') or '')[:60]
                break
        conn = db.get_conn()
        with conn:
            conn.execute(
                """INSERT INTO task_summaries(task_id, title, abstract, overview)
                   VALUES (?,?,?,?)
                   ON CONFLICT(task_id) DO UPDATE SET
                     title=excluded.title, abstract=excluded.abstract, overview=excluded.overview,
                     created_at=datetime('now','localtime')""",
                (str(tid), title, res['abstract'], res['overview']),
            )
        from src.memory import assets
        assets.register('summary', str(tid), title=title or f'任务#{tid}',
                        content=res['overview'], visibility='private', owner='local')
    except Exception:
        pass
    return res
