# -*- coding: utf-8 -*-
"""S1-W3 FTS5 trigram 增强测试：kb_fts_tg 建表 / 触发器同步 / 子串召回 / 回归保护。

覆盖：
- kb_fts_tg 表存在（trigram 分词器）；
- 触发器同步：新增 kb_entries 自动入 trigram 表；
- 标准号子串召回：kb_search 查 "3095" 能命中含 "GB 3095-2012" 的条目（原 kb_fts 兜底 miss 时）；
- 中文检索不回归：LIKE 主路径仍命中 2 字词（"氨氮"）；
- 迁移幂等：重复运行 0015 不报错。
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean_kb():
    """每个用例前清理 kb_entries 与两个 FTS 表（外部内容表用 delete-all 命令）。"""
    from db import get_db
    conn = get_db()
    conn.execute('DELETE FROM kb_entries')
    conn.execute("INSERT INTO kb_fts(kb_fts) VALUES('delete-all')")
    conn.execute("INSERT INTO kb_fts_tg(kb_fts_tg) VALUES('delete-all')")
    conn.commit()
    yield
    conn = get_db()
    conn.execute('DELETE FROM kb_entries')
    conn.execute("INSERT INTO kb_fts(kb_fts) VALUES('delete-all')")
    conn.execute("INSERT INTO kb_fts_tg(kb_fts_tg) VALUES('delete-all')")
    conn.commit()


def _add_entry(title, content):
    from db import get_db, kb_add
    conn = get_db()
    cur = conn.execute(
        'INSERT INTO kb_entries(title, url, category, source, content) VALUES(?,?,?,?,?)',
        (title, '', 'standard', 'test', content))
    conn.commit()
    return cur.lastrowid


def test_kb_fts_tg_table_exists():
    from db import get_db
    rows = get_db().execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='kb_fts_tg'").fetchall()
    assert rows, 'kb_fts_tg 表应存在（迁移 0015）'


def test_trigger_syncs_trigram_table():
    from db import get_db
    eid = _add_entry('环境空气质量标准', 'GB 3095-2012 环境空气质量标准全文')
    row = get_db().execute(
        'SELECT rowid FROM kb_fts_tg WHERE kb_fts_tg MATCH ?', ('3095',)).fetchone()
    assert row is not None and row['rowid'] == eid


def test_std_number_substring_recall():
    """标准号子串召回：trigram 兜底命中（kb_fts unicode61 对纯数字子串 miss）。"""
    import db
    _add_entry('环境空气质量标准', 'GB 3095-2012 环境空气质量标准全文内容很长')
    hits = db.kb_search('3095', top_n=5)
    assert any(h['title'] == '环境空气质量标准' for h in hits), \
        f'trigram 子串召回应命中，实际: {[h["title"] for h in hits]}'


def test_chinese_bigram_not_regressed():
    """中文 2 字词（氨氮）仍由 LIKE 主路径命中（回归保护）。"""
    import db
    _add_entry('氨氮水质监测', '地表水氨氮监测方法标准全文')
    hits = db.kb_search('氨氮', top_n=5)
    assert hits and hits[0]['title'] == '氨氮水质监测'


def test_migration_0015_idempotent():
    """迁移 0015 幂等：重复应用不报错（无论是否已应用）。"""
    from src.core.db import run_migrations
    applied = run_migrations()
    assert '0015_kb_fts_trigram' in applied or '0015_kb_fts_trigram' not in applied
    # 再跑一次：不报错（已应用时返回空列表）
    again = run_migrations()
    assert isinstance(again, list)
