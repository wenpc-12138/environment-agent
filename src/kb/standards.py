# -*- coding: utf-8 -*-
"""M06 StandardKB：标准知识库（kb_entries + 有效性检查）。

契约（contracts.md §3.M06）：
- `ingest(path, kind) -> int`：导入 HJ/GB/DB/法规/导则文本，返回条目 ID
- `search(query, filters=None, top_k=10) -> list[KBHit]`：混合检索
- `get_standard(code) -> StandardDoc | None`：按标准号取全文
- `check_validity(code) -> ValidityInfo`：现行/废止/即将实施

双轨共存：与 v1.2 共用 `kb_entries` 表。v1.2 既有列（title/content/std_no/validity...）
与 0001 迁移补的列（standard_code/validity_status/effective_date）通过列探测兼容。
FTS5（jieba 预分词）为可选增强；无 jieba 时用 LIKE 命中评分。
"""
from __future__ import annotations

import re
from pathlib import Path

from ..core.db import get_conn
from ..models.core import KBHit, StandardDoc, ValidityInfo

_STD_RE = re.compile(r'([A-Z]{1,4}(?:[/-][A-Z]{1,4})?(?:[/-]\d{1,4})?\s*\d{2,6}(?:\.\d+)?(?:[-\u2013]\d{4})?)')
_TOKEN_RE = re.compile(r'[A-Za-z0-9]+|[\u4e00-\u9fff]')

_KIND_ALIAS = {'HJ': 'hj', 'GB': 'gb', 'DB': 'db', '法规': 'law', '导则': 'guideline'}


def _columns(conn, table: str) -> set[str]:
    return {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}


def _norm_code(code: str) -> str:
    """标准号归一化：去空白（兼容 'HJ 166-2026' 与 'HJ166-2026'）。"""
    return (code or '').replace(' ', '').replace('\u3000', '').upper()


def _ensure_kb_table(conn) -> None:
    """kb_entries 兜底建表：v1.2 由 init_db 创建，v2 迁移只加列；临时/空库时自建最小结构。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, url TEXT, category TEXT, content TEXT, source TEXT,
            item_type TEXT, domain TEXT, source_type TEXT, validity TEXT,
            confidence REAL, status TEXT, std_no TEXT, org TEXT,
            publish_date TEXT, implement_date TEXT, metadata_json TEXT,
            standard_code TEXT, validity_status TEXT, effective_date TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()


class StandardKB:
    """标准知识库：导入 / 检索 / 全文 / 有效性。"""

    # ---- 导入 ----
    def ingest(self, path: str, kind: str) -> int:
        """导入单个文本文件（.md/.txt/.html 文本解析），返回条目 ID。

        kind：HJ / GB / DB / 法规 / 导则（归一化为小写别名）。文件首行为标题，
        从标题与正文提取标准号写入 std_no/standard_code。
        """
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f'文件不存在: {path}')
        text = p.read_text(encoding='utf-8', errors='replace')
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        title = lines[0] if lines else p.stem
        code_match = _STD_RE.search(title) or _STD_RE.search(text[:500])
        code = code_match.group(1).replace(' ', '') if code_match else ''
        category = _KIND_ALIAS.get(kind, str(kind).lower() or 'unknown')

        conn = get_conn()
        _ensure_kb_table(conn)
        cols = _columns(conn, 'kb_entries')
        has_std_code = 'standard_code' in cols
        has_validity_status = 'validity_status' in cols
        has_std_no = 'std_no' in cols
        has_validity = 'validity' in cols

        if has_std_no:
            if has_std_code:
                cur = conn.execute(
                    'INSERT INTO kb_entries(title, content, category, source, std_no, standard_code)'
                    ' VALUES(?,?,?,?,?,?)',
                    (title, text, category, 'v2.0-import', code, code),
                )
            else:
                cur = conn.execute(
                    'INSERT INTO kb_entries(title, content, category, source, std_no) VALUES(?,?,?,?,?)',
                    (title, text, category, 'v2.0-import', code),
                )
        else:
            cur = conn.execute(
                'INSERT INTO kb_entries(title, content, category, source) VALUES(?,?,?,?)',
                (title, text, category, 'v2.0-import'),
            )
        eid = cur.lastrowid
        if has_validity_status:
            conn.execute(
                'UPDATE kb_entries SET validity_status=? WHERE id=?', ('未知', eid)
            )
        elif has_validity:
            conn.execute('UPDATE kb_entries SET validity=? WHERE id=?', ('未知', eid))
        conn.commit()
        return int(eid)

    # ---- 检索 ----
    def search(self, query: str, filters: dict | None = None, top_k: int = 10) -> list[KBHit]:
        """检索知识库：LIKE 命中评分（std_no 命中 5 分、标题命中 3 分、正文命中 1 分）。

        filters 支持：`category` / `validity`（有效性状态）/ `code`（标准号包含）。
        """
        conn = get_conn()
        _ensure_kb_table(conn)
        cols = _columns(conn, 'kb_entries')
        if not query:
            return []
        tokens = [t.lower() for t in _TOKEN_RE.findall(query)]
        if not tokens:
            return []
        where, args = ['1=1'], []
        if filters:
            if filters.get('category'):
                where.append('category = ?')
                args.append(filters['category'])
            if filters.get('validity'):
                vcol = 'validity_status' if 'validity_status' in cols else 'validity'
                where.append(f'{vcol} = ?')
                args.append(filters['validity'])
            if filters.get('code'):
                where.append('(std_no LIKE ? OR standard_code LIKE ?)')
                args += [f'%{filters["code"]}%', f'%{filters["code"]}%']
        rows = conn.execute(
            f'SELECT * FROM kb_entries WHERE {" AND ".join(where)} ORDER BY id DESC LIMIT 300',
            args,
        ).fetchall()
        hits: list[KBHit] = []
        for r in rows:
            std_no = r['std_no'] if 'std_no' in r.keys() else (r['standard_code'] if 'standard_code' in r.keys() else '')
            title = r['title'] or ''
            content = r['content'] or ''
            score = 0.0
            for tok in tokens:
                if tok and std_no and tok in std_no.lower():
                    score += 5.0
                if tok in title.lower():
                    score += 3.0
                if tok in content.lower():
                    score += 1.0
            if score > 0:
                snippet = _snip(title + '：' + content, tokens)
                hits.append(KBHit(doc_id=str(r['id']), clause=None, snippet=snippet, score=score))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    # ---- 全文 ----
    def get_standard(self, code: str) -> StandardDoc | None:
        """按标准号取标准全文；未收录返回 None。"""
        conn = get_conn()
        _ensure_kb_table(conn)
        cols = _columns(conn, 'kb_entries')
        norm = _norm_code(code)
        if 'std_no' in cols:
            rows = conn.execute(
                "SELECT * FROM kb_entries WHERE std_no=? OR standard_code=? ORDER BY id LIMIT 1",
                (norm, norm),
            ).fetchall()
        else:
            rows = []
        if not rows:
            return None
        r = rows[0]
        validity = '未知'
        if 'validity_status' in cols and r['validity_status']:
            validity = r['validity_status']
        elif 'validity' in cols and r['validity']:
            validity = r['validity']
        return StandardDoc(
            code=r['std_no'] if 'std_no' in cols else code,
            title=r['title'] or '',
            content=r['content'] or '',
            category=r['category'] or '',
            validity=validity,
            effective_date=r['effective_date'] if 'effective_date' in cols else None,
            source=r['source'] or '',
        )

    # ---- 有效性 ----
    def check_validity(self, code: str) -> ValidityInfo:
        """检查标准有效性：读取 validity 字段，未收录返回'未知'。"""
        conn = get_conn()
        _ensure_kb_table(conn)
        cols = _columns(conn, 'kb_entries')
        note, status, effective_date = '', '未知', None
        norm = _norm_code(code)
        if 'std_no' in cols:
            row = conn.execute(
                "SELECT * FROM kb_entries WHERE std_no=? OR standard_code=? ORDER BY id LIMIT 1",
                (norm, norm),
            ).fetchone()
        else:
            row = None
        if row is not None:
            status = row['validity_status'] if 'validity_status' in cols and row['validity_status'] else (
                row['validity'] if 'validity' in cols and row['validity'] else '未知'
            )
            effective_date = row['effective_date'] if 'effective_date' in cols else None
            if status in ('未知', ''):
                note = '库内未登记有效性，需人工查新。'
            else:
                note = '来自本地知识库登记。'
        else:
            note = '未收录，需联网查新。'
        return ValidityInfo(code=code, status=status, effective_date=effective_date, note=note)


def _snip(text: str, tokens: list[str]) -> str:
    for tok in tokens:
        idx = text.lower().find(tok)
        if idx >= 0:
            start = max(0, idx - 40)
            end = min(len(text), idx + 80)
            return ('…' if start > 0 else '') + text[start:end] + ('…' if end < len(text) else '')
    return text[:120]
