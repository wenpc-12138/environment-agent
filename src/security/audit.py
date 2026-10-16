# -*- coding: utf-8 -*-
"""M14 安全审计（contracts.md §3.M14；UPGRADE_PLAN §M14）。

SHA-256 哈希链审计日志，防篡改：
- 每条 `AuditLogEntry.hash = sha256(seq|who|action|input_hash|output_hash|prev_hash|ts)`；
- `prev_hash` 指向前一条摘要（首条为 GENESIS），任意中间篡改都会被
  `verify_chain` 检出。

双契约兼容：
- 契约测试骨架：`AuditLogEntry{who,action,input_hash,output_hash,prev_hash,ts}`、
  `AuditLogger.log(who, action, input=..., output=...)`、`verify_chain(since_seq)`；
- contracts.md §3.M14：`append/chain_verify/query`（AuditEntry 语义）。

`AuditLogEntry` 复用 src/models/core.py 的 AuditEntry（共享业务类型）。

S1-W2 持久化（2026-08-20）：
- `AuditLogger(storage='memory'|'db')`——memory 为默认（纯内存，行为不变）；
  db 模式把哈希链持久化到 `audit_log` 表（迁移 0014），跨进程可校验；
  `append/log/verify_chain/query/entries/clear/size` 全部走 DB 后端。
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from ..models.core import AuditEntry as AuditLogEntry


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _entry_hash(entry: AuditLogEntry) -> str:
    payload = '|'.join([
        str(entry.seq), entry.who, entry.action,
        entry.input_hash, entry.output_hash, entry.prev_hash, entry.ts,
    ])
    return _sha256(payload)


def _norm(obj) -> str:
    """规范化输入/输出对象为哈希输入串。"""
    if obj is None:
        return ''
    if isinstance(obj, bytes):
        return obj.decode('utf-8', errors='replace')
    return str(obj)


class AuditLogger:
    """哈希链审计日志器（memory 内存链 / db 持久化到 audit_log 表）。"""

    def __init__(self, entries: list[AuditLogEntry] | None = None,
                 storage: str = 'memory'):
        """storage: 'memory'（默认，纯内存） | 'db'（落 audit_log 表，跨进程可校验）。"""
        if storage not in ('memory', 'db'):
            raise ValueError(f"storage 仅支持 'memory'|'db'，收到: {storage!r}")
        self._storage = storage
        self._entries: list[AuditLogEntry] = list(entries or [])

    # ---- DB 后端（S1-W2）----
    @staticmethod
    def _conn():
        from ..core.db import get_conn
        return get_conn()

    def _db_last(self) -> AuditLogEntry | None:
        row = self._conn().execute(
            'SELECT * FROM audit_log ORDER BY seq DESC LIMIT 1').fetchone()
        return self._row_to_entry(row) if row else None

    @staticmethod
    def _row_to_entry(row) -> AuditLogEntry:
        return AuditLogEntry(
            seq=int(row['seq']), who=row['who'] or '', action=row['action'] or '',
            input_hash=row['input_hash'] or '', output_hash=row['output_hash'] or '',
            prev_hash=row['prev_hash'] or 'GENESIS', ts=row['ts'] or '',
            hash=row['hash'] or '')

    def _db_insert(self, entry: AuditLogEntry) -> None:
        conn = self._conn()
        cur = conn.execute(
            'INSERT INTO audit_log(seq, who, action, input_hash, output_hash,'
            ' prev_hash, ts, hash, ok) VALUES (?,?,?,?,?,?,?,?,1)',
            (entry.seq, entry.who, entry.action, entry.input_hash, entry.output_hash,
             entry.prev_hash, entry.ts, entry.hash))
        conn.commit()
        if not entry.seq:
            entry.seq = int(cur.lastrowid)

    def _db_rows(self, since_seq: int = 0) -> list[AuditLogEntry]:
        if since_seq > 0:
            rows = self._conn().execute(
                'SELECT * FROM audit_log WHERE seq >= ? ORDER BY seq', (since_seq,)).fetchall()
        else:
            rows = self._conn().execute('SELECT * FROM audit_log ORDER BY seq').fetchall()
        return [self._row_to_entry(r) for r in rows]

    # ---- contracts.md §3.M14 ----

    def append(self, who: str, action: str, input_hash: str = '',
               output_hash: str = '', ts: str | None = None) -> str:
        """追加审计条目（给定哈希值），返回本条摘要（链头）。"""
        if self._storage == 'db':
            last = self._db_last()
            prev_hash = last.hash if last else 'GENESIS'
            seq = (last.seq + 1) if last else 1
        else:
            prev_hash = self._entries[-1].hash if self._entries else 'GENESIS'
            seq = len(self._entries) + 1
        entry = AuditLogEntry(
            seq=seq,
            who=who,
            action=action,
            input_hash=input_hash,
            output_hash=output_hash,
            prev_hash=prev_hash,
            ts=ts or datetime.now(UTC).isoformat(),
        )
        entry.hash = _entry_hash(entry)
        if self._storage == 'db':
            self._db_insert(entry)
        else:
            self._entries.append(entry)
        return entry.hash

    # 契约测试入口：由输入/输出对象计算哈希后入链
    def log(self, who: str, action: str, input=None, output=None) -> AuditLogEntry:
        """记录一条审计（自动计算输入/输出哈希），返回该条目。"""
        self.append(
            who=who,
            action=action,
            input_hash=_sha256(_norm(input)),
            output_hash=_sha256(_norm(output)),
        )
        if self._storage == 'db':
            return self._db_last()  # type: ignore[return-value]
        return self._entries[-1]

    # 契约测试入口：链完整性校验（自 since_seq 起）
    def verify_chain(self, since_seq: int = 0) -> bool:
        """验证 from since_seq（序号，1 起）起的哈希链完整性；篡改返回 False。

        since_seq=0/1 校验全链；since_seq=n 从第 n 条起校验。
        """
        return self.chain_verify(since_seq=since_seq)

    def chain_verify(self, since_seq: int | None = None) -> bool:
        """contracts.md：验证链完整性（默认全链；since_seq 为条目序号，1 起）。"""
        since = int(since_seq or 0)
        idx = max(since - 1, 0)  # 序号 → 列表索引
        if self._storage == 'db':
            entries = self._db_rows(since_seq=since)
        else:
            entries = self._entries
        if idx >= len(entries):
            return True
        # 统一校验：内存模式 seq==index+1；db 模式 _db_rows 已按 since_seq 截取，
        # 首条序号==max(since,1)，等价于 seq==i+1（idx 已对位）。
        for i in range(idx, len(entries)):
            e = entries[i]
            if e.seq != i + 1 or e.hash != _entry_hash(e):
                return False
            if i == 0:
                if since <= 1 and e.prev_hash != 'GENESIS':
                    return False
            else:
                prev = entries[i - 1]
                if e.prev_hash != prev.hash:
                    return False
        return True

    def query(self, filters: dict | None = None) -> list[AuditLogEntry]:
        """按条件查询审计条目（filters 支持 who/action/seq 精确匹配）。"""
        filters = filters or {}
        if self._storage == 'db':
            sql = 'SELECT * FROM audit_log'
            where, args = [], []
            if 'seq' in filters:
                where.append('seq = ?')
                args.append(int(filters['seq']))
            if 'who' in filters:
                where.append('who = ?')
                args.append(filters['who'])
            if 'action' in filters:
                where.append('action = ?')
                args.append(filters['action'])
            if where:
                sql += ' WHERE ' + ' AND '.join(where)
            sql += ' ORDER BY seq'
            return [self._row_to_entry(r) for r in self._conn().execute(sql, args).fetchall()]
        out: list[AuditLogEntry] = []
        for e in self._entries:
            ok = True
            for key, value in filters.items():
                if key == 'seq' and e.seq != int(value):
                    ok = False
                    break
                if key in ('who', 'action') and getattr(e, key, '') != value:
                    ok = False
                    break
            if ok:
                out.append(e)
        return out

    def entries(self) -> list[AuditLogEntry]:
        if self._storage == 'db':
            return self._db_rows()
        return list(self._entries)

    def clear(self) -> None:
        if self._storage == 'db':
            self._conn().execute('DELETE FROM audit_log')
            self._conn().commit()
        self._entries = []

    @property
    def size(self) -> int:
        if self._storage == 'db':
            row = self._conn().execute('SELECT COUNT(*) AS n FROM audit_log').fetchone()
            return int(row['n'])
        return len(self._entries)


__all__ = ['AuditLogger', 'AuditLogEntry']
