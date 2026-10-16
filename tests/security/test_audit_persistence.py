# -*- coding: utf-8 -*-
"""S1-W2 审计链落库测试：db 模式持久化 / 跨进程校验 / 篡改检测 / memory 回归。

覆盖：
- db 模式 log/append 落 audit_log 表，seq 连续、prev_hash 链接；
- 新 AuditLogger（db）实例可跨进程校验链（模拟重启）；
- db 模式篡改检测（改库内 hash 后被 verify_chain 检出）；
- query/entries/clear/size 在 db 模式下的行为；
- 非法 storage 报错；
- memory 模式不落库（回归保护）。
"""
from __future__ import annotations

import hashlib

import pytest

from src.security import AuditLogger


def _sha(payload: str) -> str:
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


@pytest.fixture(autouse=True)
def _clean_audit_table():
    """每个用例前清空 audit_log 表，保证用例独立。"""
    from src.core.db import get_conn
    conn = get_conn()
    conn.execute('DELETE FROM audit_log')
    conn.commit()
    yield
    conn = get_conn()
    conn.execute('DELETE FROM audit_log')
    conn.commit()


def test_db_log_persists_rows():
    logger = AuditLogger(storage='db')
    e1 = logger.log('R4', 'gen', input='a', output='1')
    e2 = logger.log('R5', 'review', input='b', output='2')
    assert e1.seq == 1 and e2.seq == 2
    assert e2.prev_hash == e1.hash
    from src.core.db import get_conn
    rows = get_conn().execute('SELECT * FROM audit_log ORDER BY seq').fetchall()
    assert len(rows) == 2
    assert rows[0]['seq'] == 1 and rows[1]['prev_hash'] == rows[0]['hash']


def test_db_cross_instance_verify():
    """新 AuditLogger（db）从库中恢复并校验全链（模拟进程重启）。"""
    logger = AuditLogger(storage='db')
    for i in range(3):
        logger.log('R4', f'act{i}', input=i, output=i)
    fresh = AuditLogger(storage='db')
    assert fresh.size == 3
    assert fresh.verify_chain() is True
    assert [e.seq for e in fresh.entries()] == [1, 2, 3]


def test_db_tamper_detected_in_db():
    logger = AuditLogger(storage='db')
    logger.log('R4', 'gen', input='a', output='1')
    logger.log('R5', 'review', input='b', output='2')
    # 直接篡改库内 hash（模拟外部篡改）
    from src.core.db import get_conn
    conn = get_conn()
    conn.execute("UPDATE audit_log SET hash='DEADBEEF' WHERE seq=1")
    conn.commit()
    fresh = AuditLogger(storage='db')
    assert fresh.verify_chain() is False


def test_db_tamper_prev_link_detected():
    logger = AuditLogger(storage='db')
    logger.log('R4', 'gen', input='a', output='1')
    logger.log('R5', 'review', input='b', output='2')
    from src.core.db import get_conn
    conn = get_conn()
    conn.execute("UPDATE audit_log SET prev_hash='FORGED' WHERE seq=2")
    conn.commit()
    assert AuditLogger(storage='db').verify_chain() is False


def test_db_query_and_entries():
    logger = AuditLogger(storage='db')
    logger.log('R4', 'gen', input='a', output='1')
    logger.log('R5', 'review', input='b', output='2')
    logger.log('R4', 'gen', input='c', output='3')
    assert len(logger.query({'who': 'R4'})) == 2
    assert len(logger.query({'action': 'review'})) == 1
    assert len(logger.query({'seq': 2})) == 1
    assert len(logger.entries()) == 3


def test_db_clear_and_size():
    logger = AuditLogger(storage='db')
    logger.log('R4', 'gen', input='a', output='1')
    logger.log('R5', 'review', input='b', output='2')
    assert logger.size == 2
    logger.clear()
    assert logger.size == 0
    from src.core.db import get_conn
    n = get_conn().execute('SELECT COUNT(*) AS n FROM audit_log').fetchone()['n']
    assert n == 0


def test_invalid_storage_raises():
    with pytest.raises(ValueError):
        AuditLogger(storage='redis')


def test_memory_mode_not_persisted():
    """memory 模式不落库（回归保护）。"""
    logger = AuditLogger()  # 默认 memory
    logger.log('R4', 'gen', input='a', output='1')
    from src.core.db import get_conn
    n = get_conn().execute('SELECT COUNT(*) AS n FROM audit_log').fetchone()['n']
    assert n == 0
