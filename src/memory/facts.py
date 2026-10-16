# -*- coding: utf-8 -*-
"""M2 自动事实提取 + M4 冲突消解（结构化事实记忆）。

- `add_fact(entity, attr, value, ftype, source)`：写入事实，默认 `pending`（过 R8 审核）
- `approve_fact(id)`：激活并**冲突消解**——同 (entity,attr) 旧 active 事实自动置 `valid_until=now`
- `reject_fact(id)`：拒绝（pending → rejected）
- `query_facts(entity, ftype, q)`：返回"当前有效"事实（valid_until IS NULL 且 active）
- `extract_facts(text, caller)`：LLM 抽取结构化三元组落库（caller 可注入；返回 pending 事实）
- `_rule_extract(text)`：离线规则兜底（任务结束自动触发，低噪）

设计（对齐方案 §四）：时间维度 valid_from/valid_until + 冲突消解；事实默认 pending 过 P9 审核闸门（防幻觉污染）。
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from ..core.db import get_conn
from ..core.utils import now_iso
from ..models.core import MemoryFact

FACT_TYPES = ('fact', 'preference', 'constraint', 'conclusion')
_FTYPE_CN = {'fact': '事实', 'preference': '偏好', 'constraint': '约束', 'conclusion': '结论'}

# 规则兜底模式：类型 -> (正则, 属性名)
_RULE_PATTERNS = (
    ('preference', re.compile(r'(?:我|用户)?(?:的)?(?:偏好|喜欢|更倾向|习惯)\s*(?:是|用|使用|于|为)?\s*[:：]?\s*([^。；;]+)')),
    ('constraint', re.compile(r'(?:要求|必须|需(?:要|求)?|务必)\s*[:：]?\s*([^。；;]+)')),
    ('conclusion', re.compile(r'(?:结论|判定|结果)(?:为|是)?\s*[:：]?\s*([^。；;]+)')),
)
_STD_RE = re.compile(r'\b[A-Z]{1,4}\s*[-/]?\s*\d{3,5}(?:\.\d+)?(?:\s*[-–—]\s*\d{4})?\b')


def _row_to_fact(r: Any) -> MemoryFact:
    return MemoryFact(
        id=r['id'], entity=r['entity'], attr=r['attr'], value=r['value'],
        ftype=r['ftype'], source=r['source'], valid_from=r['valid_from'],
        valid_until=r['valid_until'], status=r['status'], created_at=r['created_at'])


# ---- 写入 ----
def add_fact(entity: str, attr: str, value: str, ftype: str = 'fact',
             source: str = '', approved: bool = False) -> MemoryFact:
    """写入一条事实记忆（默认 pending；approved=True 直接激活并消解旧事实）。"""
    if not entity or not attr or not value:
        raise ValueError('entity/attr/value 不能为空')
    if ftype not in FACT_TYPES:
        ftype = 'fact'
    ts = now_iso()
    cur = get_conn().execute(
        'INSERT INTO memory_facts(entity,attr,value,ftype,source,valid_from,valid_until,status,created_at) '
        'VALUES(?,?,?,?,?,?,?,?,?)',
        (entity, attr, value, ftype, source, ts, None, 'active' if approved else 'pending', ts),
    )
    get_conn().commit()
    fid = cur.lastrowid
    if approved:
        _supersede(entity, attr, ts, fid)
        # P0-2：激活即登记为记忆资产（失败静默）
        try:
            from .assets import register
            register('fact', str(fid), title=f'{entity} {attr}',
                     content=f'{entity}:{attr}={value}', visibility='private', owner='local')
        except Exception:
            pass
    return _get_fact(fid)


def _supersede(entity: str, attr: str, ts: str, exclude_id: int | None = None) -> None:
    """冲突消解：同 (entity,attr) 的旧 active 事实置 valid_until=ts（对齐 Mem0 冲突处理）。

    必须排除自身 id（approved 插入/审批时同 key 同状态会误伤自己）。
    """
    if exclude_id is not None:
        get_conn().execute(
            'UPDATE memory_facts SET valid_until=? '
            'WHERE entity=? AND attr=? AND valid_until IS NULL AND status=? AND id != ?',
            (ts, entity, attr, 'active', exclude_id))
    else:
        get_conn().execute(
            'UPDATE memory_facts SET valid_until=? '
            'WHERE entity=? AND attr=? AND valid_until IS NULL AND status=?',
            (ts, entity, attr, 'active'))
    get_conn().commit()


def _get_fact(fid: int) -> MemoryFact:
    row = get_conn().execute('SELECT * FROM memory_facts WHERE id=?', (fid,)).fetchone()
    if not row:
        raise ValueError(f'事实不存在: {fid}')
    return _row_to_fact(row)


# ---- 审核 ----
def approve_fact(fid: int, reviewer: str = 'R8') -> MemoryFact:
    """激活待审事实并消解同 key 旧事实（M4 冲突消解在激活时执行，保障新事实生效才切换）。"""
    row = get_conn().execute('SELECT * FROM memory_facts WHERE id=?', (fid,)).fetchone()
    if not row:
        raise ValueError(f'事实不存在: {fid}')
    if row['status'] != 'pending':
        raise ValueError(f'事实状态非 pending: {row["status"]}')
    ts = now_iso()
    get_conn().execute("UPDATE memory_facts SET status='active' WHERE id=?", (fid,))
    _supersede(row['entity'], row['attr'], ts, fid)
    get_conn().commit()
    # P0-2：审批通过后登记/更新记忆资产（失败静默）
    try:
        from .assets import register
        register('fact', str(fid), title=f"{row['entity']} {row['attr']}",
                 content=f"{row['entity']}:{row['attr']}={row['value']}",
                 visibility='private', owner='local')
    except Exception:
        pass
    return _get_fact(fid)


def approve_all_pending(reviewer: str = 'R8') -> dict:
    """V3 批量审批：一键通过全部 pending 事实（优化手动逐条审批体验）。

    返回 {approved: [fid,...], skipped: n}。仅标准/偏好/约束类可批量通过，
    结论类(conclusion)仍建议人工核对 → 跳过并保留 pending。
    """
    approved, skipped = [], 0
    for f in pending_facts():
        try:
            if f.ftype == 'conclusion':
                skipped += 1
                continue
            approve_fact(f.id, reviewer)
            approved.append(f.id)
        except Exception:
            skipped += 1
    return {'approved': approved, 'skipped': skipped}


def reject_fact(fid: int, reviewer: str = 'R8') -> MemoryFact:
    row = get_conn().execute('SELECT * FROM memory_facts WHERE id=?', (fid,)).fetchone()
    if not row or row['status'] != 'pending':
        raise ValueError('事实不存在或非 pending')
    get_conn().execute("UPDATE memory_facts SET status='rejected' WHERE id=?", (fid,))
    get_conn().commit()
    return _get_fact(fid)


# ---- 查询 ----
def query_facts(entity: str = '', ftype: str = '', q: str = '',
                active_only: bool = True) -> list[MemoryFact]:
    """查询事实；默认仅"当前有效"（valid_until IS NULL 且 active）。"""
    where, args = ['1=1'], []
    if active_only:
        where.append('valid_until IS NULL')
        where.append('status=?')
        args.append('active')
    if entity:
        where.append('entity LIKE ?')
        args.append(f'%{entity}%')
    if ftype:
        where.append('ftype=?')
        args.append(ftype)
    rows = get_conn().execute(
        f"SELECT * FROM memory_facts WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT 200", args).fetchall()
    facts = [_row_to_fact(r) for r in rows]
    if q:
        low = q.lower()
        facts = [f for f in facts
                 if low in (f.entity + f.attr + f.value).lower()]
    return facts


def pending_facts() -> list[MemoryFact]:
    rows = get_conn().execute(
        "SELECT * FROM memory_facts WHERE status='pending' ORDER BY id DESC").fetchall()
    return [_row_to_fact(r) for r in rows]


def list_all(status: str = '') -> list[MemoryFact]:
    where, args = ['1=1'], []
    if status:
        where.append('status=?')
        args.append(status)
    rows = get_conn().execute(
        f'SELECT * FROM memory_facts WHERE {" AND ".join(where)} ORDER BY id DESC LIMIT 500', args).fetchall()
    return [_row_to_fact(r) for r in rows]


# ---- 抽取 ----
def extract_facts(text: str, caller: Callable[[list[dict]], str] | None = None,
                  source: str = 'agent') -> list[MemoryFact]:
    """LLM 抽取结构化事实并落库（全部 pending，过 R8 审核）；无 caller 用规则兜底。"""
    if not text or not text.strip():
        return []
    if caller is None:
        return _rule_extract(text, source)
    prompt = (
        '你是记忆提取器。从以下对话/文本中提取确定的结构化记忆，'
        '仅输出 JSON 数组，每项 {"entity","attr","value","ftype"}，'
        f'ftype 取 {",".join(FACT_TYPES)}（fact=事实 preference=偏好 constraint=约束 conclusion=结论）。'
        '只提取明确的信息，不猜测；无内容输出 []。\n文本：\n' + text[:3000])
    try:
        raw = (caller([{'role': 'user', 'content': prompt}]) or '').strip()
        start, end = raw.find('['), raw.rfind(']')
        if start < 0 or end < start:
            return _rule_extract(text, source)
        raw = raw[start:end + 1]
        items = json.loads(raw) if raw else []
    except Exception:
        return _rule_extract(text, source)
    out = []
    for it in items:
        try:
            out.append(add_fact(str(it.get('entity') or '未知'), str(it.get('attr') or '属性'),
                                str(it.get('value') or ''), str(it.get('ftype') or 'fact'), source))
        except Exception:
            continue
    return out


def _rule_extract(text: str, source: str = 'rule') -> list[MemoryFact]:
    """离线规则兜底（低噪）：偏好/约束/结论 + 标准事实。"""
    out = []
    for ftype, pat in _RULE_PATTERNS:
        for m in pat.finditer(text or ''):
            val = m.group(1).strip()
            if len(val) < 2:
                continue
            try:
                out.append(add_fact('用户', ftype, val, ftype, source))
            except Exception:
                continue
    # 标准事实（如 "执行标准：GB 3838-2002"）：标准编号为确定性信息，V3 全自动沉淀
    # 直接激活（approved=True），避免逐条人工审批；偏好/约束仍保留审批闸门
    for m in _STD_RE.finditer(text or ''):
        code = m.group(0)
        try:
            out.append(add_fact('标准', code, '执行标准引用', 'fact', source, approved=True))
        except Exception:
            continue
    return out
