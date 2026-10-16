# -*- coding: utf-8 -*-
"""errors 模块边界与失败用例测试。"""
from __future__ import annotations

import pytest

from src.core.errors import (
    ComplianceError,
    ContractViolationError,
    EABaseError,
    NotFoundError,
    SandboxError,
    http_status_for,
)


def test_message_and_code() -> None:
    """异常携带 message 与可选 code。"""
    err = EABaseError('出错了', code='E100')
    assert err.message == '出错了'
    assert err.code == 'E100'


def test_unknown_exception_maps_500() -> None:
    """未注册异常映射 500。"""
    assert http_status_for(ValueError('x')) == 500


@pytest.mark.parametrize(
    'exc_cls, status',
    [
        (NotFoundError, 404),
        (ContractViolationError, 422),
        (ComplianceError, 403),
        (SandboxError, 500),
    ],
)
def test_mapping_table(exc_cls, status) -> None:
    assert http_status_for(exc_cls('x')) == status
