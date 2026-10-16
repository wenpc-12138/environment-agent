# -*- coding: utf-8 -*-
"""M14 安全审计行为测试（与契约测试 tests/security/test_security_contract.py 互补）。"""
from __future__ import annotations

import hashlib

from src.security import AuditLogger


def _sha(payload: str) -> str:
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def test_log_builds_entry_with_hashed_inputs():
    logger = AuditLogger()
    entry = logger.log('R4', 'generate_report', input={'pid': 'prj-1'}, output='ok')
    assert entry.seq == 1
    assert entry.who == 'R4'
    assert entry.action == 'generate_report'
    assert entry.input_hash == _sha(str({'pid': 'prj-1'}))
    assert entry.output_hash == _sha('ok')
    assert entry.prev_hash == 'GENESIS'
    assert entry.ts


def test_hash_chain_links_sequentially():
    logger = AuditLogger()
    e1 = logger.log('R4', 'gen', input='a', output='1')
    e2 = logger.log('R5', 'review', input='b', output='2')
    e3 = logger.log('R5', 'approve', input='c', output='3')
    assert [e.seq for e in logger.entries()] == [1, 2, 3]
    assert e2.prev_hash == e1.hash
    assert e3.prev_hash == e2.hash
    assert e1.prev_hash == 'GENESIS'


def test_verify_chain_clean_returns_true():
    logger = AuditLogger()
    for i in range(3):
        logger.log('R4', f'act{i}', input=i, output=i)
    assert logger.verify_chain() is True
    assert logger.chain_verify() is True


def test_verify_chain_detects_tampering():
    logger = AuditLogger()
    logger.log('R4', 'gen', input='a', output='1')
    logger.log('R5', 'review', input='b', output='2')
    tampered = logger.entries()[1]
    tampered.input_hash = _sha('EVIL')
    assert logger.verify_chain() is False
    assert logger.verify_chain(since_seq=2) is False


def test_verify_chain_detects_broken_prev_link():
    logger = AuditLogger()
    e1 = logger.log('R4', 'gen', input='a', output='1')
    e2 = logger.log('R5', 'review', input='b', output='2')
    e2.prev_hash = 'FORGED'
    assert logger.verify_chain() is False


def test_verify_chain_partial_from_seq():
    logger = AuditLogger()
    logger.log('R4', 'gen', input='a', output='1')
    logger.log('R5', 'review', input='b', output='2')
    # 篡改第 2 条，但 only 校验 seq>=2 起点前链不受影响
    assert logger.verify_chain(since_seq=3) is True
    assert logger.verify_chain(since_seq=2) is True


def test_append_returns_entry_hash():
    logger = AuditLogger()
    h = logger.append('R8', 'approve_role', input_hash='in', output_hash='out')
    assert h == logger.entries()[-1].hash
    assert logger.entries()[0].prev_hash == 'GENESIS'


def test_query_filters():
    logger = AuditLogger()
    logger.log('R4', 'gen', input='a', output='1')
    logger.log('R5', 'review', input='b', output='2')
    logger.log('R4', 'gen', input='c', output='3')
    assert len(logger.query({'who': 'R4'})) == 2
    assert len(logger.query({'action': 'review'})) == 1
    assert len(logger.query({'seq': 2})) == 1
    assert logger.query({'who': 'nobody'}) == []


def test_gateway_middleware_mounted():
    from src.gateway.api import app
    from src.security import AuditMiddleware
    mw_classes = [m.cls for m in app.user_middleware]
    assert AuditMiddleware in mw_classes, '网关应挂载 M14 审计中间件'
