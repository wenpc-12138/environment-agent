# -*- coding: utf-8 -*-
"""M14 安全审计契约测试（contracts.md §3.M14）。

src/security/ 未实现时自动 skip；实现后自动激活。
"""
from __future__ import annotations

import inspect

import pytest


def test_audit_log_entry_fields() -> None:
    """AuditLogEntry 字段与契约一致（哈希链）。"""
    auditor = pytest.importorskip('src.security.audit', reason='M14 AuditLogger 未实现')
    assert {'who', 'action', 'input_hash', 'output_hash', 'prev_hash', 'ts'} <= set(
        auditor.AuditLogEntry.model_fields
    )


def test_audit_logger_signatures() -> None:
    """AuditLogger.log / verify_chain。"""
    auditor = pytest.importorskip('src.security.audit', reason='M14 AuditLogger 未实现')
    log = inspect.signature(auditor.AuditLogger.log)
    assert list(log.parameters)[:3] == ['self', 'who', 'action']
    assert {'input', 'output'} <= set(log.parameters)
    verify = inspect.signature(auditor.AuditLogger.verify_chain)
    assert list(verify.parameters)[:2] == ['self', 'since_seq']
