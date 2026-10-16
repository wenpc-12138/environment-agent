# -*- coding: utf-8 -*-
"""G5 记忆知识图谱（对齐 Neo4j Agent Memory 实体关系 + 推理记忆思路，实现完全自研）。

- `add_relation(entity_a, rel, entity_b, source, note)`：写入关系（同三元组幂等累加权）。
- `extract_entities(text)`：规则抽取实体（标准号/地名/企业/指标等）。
- `link_from_facts()`：从 memory_facts 自动构建实体 ->(attr)-> value 关系。
- `trace_decision(entity, context, source)`：记录决策痕迹（rel='decision_trace'，对齐 reasoning memory）。
- `query(entity)`：图谱展开——出/入边 + 关联事实 + 知识库命中 + 画像 + 技能（与 M6 意图路由检索源合并互补）。
"""
from __future__ import annotations

import re
from typing import Any

from ..core.db import get_conn
from ..core.utils import now_iso

# 实体规则：标准号 / 中文地名/企业（2-6字 前缀含"市/县/厂/公司/区/河/湖"等）/ 指标
_STD_RE = re.compile(r'\b[A-Z]{1,4}\s*[-/]?\s*\d{3,5}(?:\.\d+)?(?:\s*[-–—]\s*\d{4})?\b')
_PLACE_RE = re.compile(r'[\u4e00-\u9fff]{2,8}(?:市|县|区|镇|河|湖|水库|断面|厂|公司|园区|地块)')
_INDICATOR_RE = re.compile(r'(?:COD|氨氮|总磷|总氮|pH|溶解氧|BOD|SS|PM2\.5|PM10|SO2|NO2|CO|O3|铅|镉|汞|砷|铬|挥发酚|氰化物)')

_MAX_NEIGHBORS = 50


def _row(r: Any) -> dict:
    return {'id': r['id'], 'entity_a': r['entity_a'], 'rel': r['rel'],
            'entity_b': r['entity_b'], 'source': r['source'], 'weight': r['weight'],
            'note': r['note'], 'created_at': r['created_at']}


# ---- 写入 ----
def add_relation(entity_a: str, rel: str, entity_b: str,
                 source: str = '', note: str = '') -> dict:
    """写入关系；同 (entity_a, rel, entity_b) 幂等：weight+1、刷新 note。"""
    if not entity_a or not entity_b:
        raise ValueError('关系两端实体不能为空')
    conn = get_conn()
    row = conn.execute(
        'SELECT id, weight FROM memory_relations'
        ' WHERE entity_a=? AND rel=? AND entity_b=?',
        (entity_a, rel, entity_b)).fetchone()
    ts = now_iso()
    if row:
        conn.execute(
            'UPDATE memory_relations SET weight=weight+1, note=COALESCE(?, note), source=COALESCE(?, source)'
            ' WHERE id=?', (note or None, source or None, row['id']))
        rid, weight = row['id'], (row['weight'] or 0) + 1
    else:
        cur = conn.execute(
            'INSERT INTO memory_relations(entity_a,rel,entity_b,source,weight,note,created_at)'
            ' VALUES(?,?,?,?,1,?,?)',
            (entity_a, rel, entity_b, source or '', note or '', ts))
        rid, weight = cur.lastrowid, 1
    conn.commit()
    return {'id': rid, 'entity_a': entity_a, 'rel': rel, 'entity_b': entity_b,
            'weight': weight, 'note': note, 'created_at': ts}


def trace_decision(entity: str, context: str, source: str = 'agent') -> dict:
    """决策痕迹（reasoning memory）：entity 的决策记录（entity_b=决策摘要）。"""
    summary = re.sub(r'\s+', ' ', (context or ''))[:200]
    return add_relation(entity, 'decision_trace', summary or '（无摘要）',
                        source=source, note='decision trace')


# ---- 实体抽取 ----
def extract_entities(text: str, top_k: int = 10) -> list[str]:
    """规则抽取实体（标准号/地名/企业/指标），按出现顺序去重。"""
    out: list[str] = []
    seen: set[str] = set()
    for pat in (_STD_RE, _PLACE_RE, _INDICATOR_RE):
        for m in pat.finditer(text or ''):
            e = m.group(0).strip()
            key = e.upper()
            if key in seen:
                continue
            seen.add(key)
            out.append(e)
            if len(out) >= top_k:
                return out
    return out


# ---- 从事实自动建图 ----
def link_from_facts(active_only: bool = True) -> int:
    """把 memory_facts 中有效事实转换为关系（entity -attr-> value），返回新建数。"""
    from . import facts as facts_mod
    conn = get_conn()
    rows = conn.execute(
        'SELECT entity, attr, value, ftype, source FROM memory_facts'
        ' WHERE (valid_until IS NULL AND status=?)' if active_only else
        'SELECT entity, attr, value, ftype, source FROM memory_facts',
        ('active',) if active_only else ()).fetchall()
    n = 0
    for r in rows:
        entity = (r['entity'] or '').strip()
        attr = (r['attr'] or '').strip()
        value = (r['value'] or '').strip()
        if not entity or not value:
            continue
        rel = attr or r['ftype'] or 'related'
        # 幂等：已存在同三元组则跳过（不累加，避免全量重建时权重虚增）
        hit = conn.execute(
            'SELECT id FROM memory_relations WHERE entity_a=? AND rel=? AND entity_b=?',
            (entity, rel, value)).fetchone()
        if hit:
            continue
        add_relation(entity, rel, value, source=r['source'] or 'facts')
        n += 1
    return n


# ---- 图谱展开 ----
def query(entity: str, top_k: int = 10) -> dict:
    """实体图谱展开：出/入边 + 关联事实 + 知识库命中 + 画像 + 技能。"""
    entity = (entity or '').strip()
    if not entity:
        return {'entity': '', 'relations': [], 'facts': [], 'kb_hits': [],
                'profile': [], 'skills': [], 'decision_traces': []}
    conn = get_conn()
    like = f'%{entity}%'
    out_edges = [dict(r) for r in conn.execute(
        'SELECT * FROM memory_relations WHERE entity_a LIKE ? ORDER BY weight DESC LIMIT ?',
        (like, _MAX_NEIGHBORS)).fetchall()]
    in_edges = [dict(r) for r in conn.execute(
        'SELECT * FROM memory_relations WHERE entity_b LIKE ? ORDER BY weight DESC LIMIT ?',
        (like, _MAX_NEIGHBORS)).fetchall()]
    rel_rows = [r for r in out_edges + in_edges
                if r['rel'] != 'decision_trace'][:top_k * 4]
    traces = [r for r in out_edges if r['rel'] == 'decision_trace'][:top_k]

    # 关联事实（当前有效）
    facts: list[dict] = []
    try:
        from . import facts as facts_mod
        facts = [f.model_dump() for f in facts_mod.query_facts(entity=entity)][:top_k]
    except Exception:  # noqa: BLE001
        pass
    # 知识库命中（根 db，静默）
    kb_hits: list[dict] = []
    try:
        from src.core import db_v12 as v12_db
        kb_hits = v12_db.kb_search(entity, top_n=top_k) or []
    except Exception:  # noqa: BLE001
        pass
    # 画像（用户偏好/属性）
    profile: list[dict] = []
    try:
        profile = [dict(r) for r in conn.execute(
            'SELECT * FROM memory_profile WHERE value LIKE ? OR attr LIKE ? ORDER BY weight DESC LIMIT ?',
            (like, like, top_k)).fetchall()]
    except Exception:  # noqa: BLE001
        pass
    # 技能（定义/名称含实体）
    skills: list[dict] = []
    try:
        skills = [dict(r) for r in conn.execute(
            'SELECT id,name,domain,version,status FROM v2_skills'
            ' WHERE name LIKE ? OR definition LIKE ? LIMIT ?',
            (like, like, top_k)).fetchall()]
    except Exception:  # noqa: BLE001
        pass
    return {'entity': entity,
            'relations': rel_rows[:top_k * 2],
            'decision_traces': traces,
            'facts': facts, 'kb_hits': kb_hits,
            'profile': profile, 'skills': skills}


def neighbors(entity: str, depth: int = 1, max_nodes: int = 20) -> dict:
    """BFS 邻居展开（depth 层），返回 {nodes: [{id,label}], edges: [{from,to,rel}]}。"""
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    frontier = [entity]
    seen: set[str] = set()
    for _ in range(max(1, min(depth, 3))):
        nxt: list[str] = []
        for cur in frontier:
            if cur in seen:
                continue
            seen.add(cur)
            nodes.setdefault(cur, {'id': cur, 'label': cur})
            for r in _outgoing(cur):
                nb = r['entity_b']
                edges.append({'from': cur, 'to': nb, 'rel': r['rel']})
                if nb not in nodes:
                    nodes.setdefault(nb, {'id': nb, 'label': nb})
                    nxt.append(nb)
                if len(nodes) >= max_nodes:
                    return {'nodes': list(nodes.values())[:max_nodes], 'edges': edges[:max_nodes * 3]}
        frontier = nxt
        if not frontier:
            break
    return {'nodes': list(nodes.values())[:max_nodes], 'edges': edges[:max_nodes * 3]}


def _outgoing(entity: str) -> list[dict]:
    try:
        return [dict(r) for r in get_conn().execute(
            'SELECT entity_b, rel FROM memory_relations WHERE entity_a=? ORDER BY weight DESC LIMIT 20',
            (entity,)).fetchall()]
    except Exception:  # noqa: BLE001
        return []
