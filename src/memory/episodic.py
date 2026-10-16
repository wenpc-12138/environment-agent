# -*- coding: utf-8 -*-
"""M05 EpisodicMemory：情景记忆（SQLite memory_episodes + 检索 + 摘要）。

契约（contracts.md §3.M05）：
- `add(entity, event, payload, ts) -> str`：记录事件，返回事件 ID（M1：自动写入向量）
- `query(q, filters=None, top_k=10, mode='hybrid') -> list[MemoryHit]`：检索
  - `hybrid`（默认）：向量余弦 TopK + LIKE 评分 RRF 融合（Reciprocal Rank Fusion）
  - `vector`：仅向量余弦检索（无语义模型时降级 LIKE）
  - `like`：原 LIKE 命中评分（完全兼容旧行为）
- `summarize(entity, since) -> str`：生成实体摘要（LLM 摘要器可注入）

M1 语义检索：复用 kb_pipeline 双轨向量（fastembed bge-small-zh 语义 + hash 词袋离线兜底），
向量存 `memory_episode_vec` 表（0002 迁移）。本模块零新增依赖，模型不可用时静默降级。
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Callable

from ..core.db import get_conn
from ..models.core import MemoryHit

# 简单分词：英文/数字按空白，中文按单字（供 LIKE 检索扩展用）
_TOKEN_RE = re.compile(r'[A-Za-z0-9]+|[\u4e00-\u9fff]')


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _embed(text: str):
    """语义向量：复用 kb_pipeline 双轨（bge-small-zh 语义，失败降级 hash 词袋）；返回 list[float] 或 None。"""
    try:
        from kb_pipeline import embed_text_semantic
        vec = embed_text_semantic(text or ' ')
        if vec is None:
            return None
        if hasattr(vec, 'tolist'):
            return vec.tolist()
        return list(vec)
    except Exception:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(v * v for v in a)) or 1.0
    nb = math.sqrt(sum(v * v for v in b)) or 1.0
    return dot / (na * nb)


def _rrf(rank: int, k: int = 60) -> float:
    """Reciprocal Rank Fusion 单源分值：1/(k + rank)。"""
    return 1.0 / (k + rank)


class EpisodicMemory:
    """事件记忆：add 落库、query 检索、summarize 摘要。"""

    def __init__(self, summarizer: Callable[[str], str] | None = None) -> None:
        self._summarizer = summarizer

    # ---- 写入 ----
    def add(self, entity: str, event: str, payload: dict | None = None, ts: str | None = None) -> str:
        """记录一条事件记忆，返回事件 ID；M1 同步写入向量（失败静默，不影响主写入）。"""
        if not entity or not event:
            raise ValueError('entity 与 event 不能为空')
        from ..core.utils import now_iso
        cur = get_conn().execute(
            'INSERT INTO memory_episodes(entity, event, payload, ts) VALUES(?,?,?,?)',
            (entity, event, json.dumps(payload or {}, ensure_ascii=False), ts or now_iso()),
        )
        eid = cur.lastrowid
        get_conn().commit()
        # M1：向量写入（懒加载 kb 向量；表不存在/模型失败均静默）
        vec = _embed(f'{entity} {event}')
        if vec:
            try:
                import struct
                blob = struct.pack(f'{len(vec)}f', *vec)
                get_conn().execute(
                    'INSERT OR REPLACE INTO memory_episode_vec(episode_id, embedding) VALUES(?,?)',
                    (eid, blob),
                )
                get_conn().commit()
            except Exception:
                pass
        # P0-2：登记为记忆资产（失败静默）
        try:
            from .assets import register
            register('episodic', str(eid), title=f'{entity} {event[:50]}',
                     content=event, visibility='private', owner='local')
        except Exception:
            pass
        return str(eid)

    # ---- 检索 ----
    def query(self, q: str, filters: dict | None = None, top_k: int = 10,
              mode: str = 'hybrid') -> list[MemoryHit]:
        """检索事件记忆。

        mode：
        - `hybrid`（默认）：向量余弦 TopK + LIKE 评分 RRF 融合（语义优先、关键词兜底）
        - `vector`：仅向量余弦（无语义模型时自动降级 LIKE）
        - `like`：原 LIKE 命中评分（entity 3 分 / event 2 分 / payload 1 分，完全兼容）

        filters 支持：`entity`（精确实体）、`since`（>=ts，ISO 字符串比较）。
        """
        conn = get_conn()
        if not q:
            return []
        tokens = _tokenize(q)
        if not tokens:
            return []
        where, args = ['1=1'], []
        if filters:
            if filters.get('entity'):
                where.append('entity = ?')
                args.append(filters['entity'])
            if filters.get('since'):
                where.append('ts >= ?')
                args.append(filters['since'])
        rows = conn.execute(
            f"SELECT * FROM memory_episodes WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT 500",
            args,
        ).fetchall()
        if not rows:
            return []

        # M1：向量分支（RRF 融合）
        if mode in ('hybrid', 'vector'):
            vec_hits = self._query_vector(q, rows, top_k=50)
            if vec_hits is not None and (mode == 'vector' or vec_hits):
                like_hits = self._query_like(q, rows, tokens) if mode == 'hybrid' else []
                return self._rrf_merge(vec_hits, like_hits, top_k)

        # 原 LIKE 检索
        return self._query_like(q, rows, tokens, top_k)

    # ---- 检索子实现 ----
    def _query_like(self, q: str, rows, tokens: list[str], top_k: int = 50) -> list[MemoryHit]:
        hits: list[MemoryHit] = []
        for r in rows:
            payload = json.loads(r['payload'] or '{}')
            score = 0.0
            snippet_parts = [r['event']]
            for tok in tokens:
                if tok.lower() in (r['entity'] or '').lower():
                    score += 3.0
                if tok.lower() in (r['event'] or '').lower():
                    score += 2.0
                if tok in json.dumps(payload, ensure_ascii=False):
                    score += 1.0
            if score > 0:
                snippet = _snippet(r['event'], tokens)
                snippet_parts.append(snippet)
                hits.append(
                    MemoryHit(entity=r['entity'], snippet=' | '.join(snippet_parts),
                              score=score, ts=r['ts'])
                )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def _query_vector(self, q: str, rows, top_k: int = 50):
        """向量余弦 TopK；返回 list[MemoryHit]（score=cos）。无向量/模型失败返回 None（降级）。"""
        import struct
        qv = _embed(q)
        if not qv:
            return None
        eids = [r['id'] for r in rows]
        if not eids:
            return None
        try:
            qmarks = ','.join('?' * len(eids))
            vrows = get_conn().execute(
                f'SELECT episode_id, embedding FROM memory_episode_vec '
                f'WHERE episode_id IN ({qmarks})', eids).fetchall()
        except Exception:
            return None
        if not vrows:
            return None
        by_id = {int(r['episode_id']): r['embedding'] for r in vrows}
        scored: list[MemoryHit] = []
        for r in rows:
            blob = by_id.get(int(r['id']))
            if not blob:
                continue
            try:
                n = len(blob) // 4
                v = list(struct.unpack(f'{n}f', bytes(blob)))
            except Exception:
                continue
            cos = _cosine(qv, v)
            if cos > 0:
                scored.append(MemoryHit(entity=r['entity'], snippet=_snippet(r['event'], []),
                                        score=cos, ts=r['ts']))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]

    def _rrf_merge(self, vec_hits: list[MemoryHit], like_hits: list[MemoryHit],
                   top_k: int) -> list[MemoryHit]:
        """Reciprocal Rank Fusion：按 (entity,ts) 归并，融合分 = Σ 1/(k+rank)。"""
        fused: dict[tuple, dict] = {}
        for hits in (vec_hits, like_hits):
            for rank, h in enumerate(hits):
                key = (h.entity, h.ts)
                entry = fused.setdefault(key, {'snippet': h.snippet, 'score': 0.0, 'ts': h.ts})
                entry['score'] += _rrf(rank)
        items = sorted(fused.values(), key=lambda e: -e['score'])[:top_k]
        out: list[MemoryHit] = []
        for key, e in fused.items():
            if e in items:
                out.append(MemoryHit(entity=key[0], snippet=e['snippet'],
                                     score=round(e['score'], 6), ts=e['ts']))
        # 保持融合分降序
        out.sort(key=lambda h: -h.score)
        return out

    # ---- 摘要 ----
    def summarize(self, entity: str, since: str | None = None) -> str:
        """生成实体摘要。注入 summarizer 时走 LLM；否则规则拼接事件（去重 TOP 事件）。"""
        conn = get_conn()
        if since:
            rows = conn.execute(
                'SELECT event, ts FROM memory_episodes WHERE entity=? AND ts>=? ORDER BY ts DESC LIMIT 50',
                (entity, since),
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT event, ts FROM memory_episodes WHERE entity=? ORDER BY ts DESC LIMIT 50',
                (entity,),
            ).fetchall()
        if not rows:
            return f'实体 {entity} 暂无事件记录。'
        events = [r['event'] for r in rows]
        raw = f'{entity} 近期事件：' + '；'.join(events)
        if self._summarizer is not None:
            return self._summarizer(raw)
        # 规则摘要：按事件文本去重合并
        seen: dict[str, int] = {}
        for ev in events:
            seen[ev] = seen.get(ev, 0) + 1
        parts = [f'{k}（x{v}）' if v > 1 else k for k, v in seen.items()]
        return f'[{entity}] ' + '；'.join(parts)


def _snippet(text: str, tokens: list[str]) -> str:
    """截取首个命中词附近的上下文片段（前后 40 字）。"""
    for tok in tokens:
        idx = text.lower().find(tok.lower())
        if idx >= 0:
            start = max(0, idx - 40)
            end = min(len(text), idx + 80)
            return ('…' if start > 0 else '') + text[start:end] + ('…' if end < len(text) else '')
    return text[:120]
