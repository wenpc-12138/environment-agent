# -*- coding: utf-8 -*-
"""v2.0 统一异常体系（coding_standards §5）。

所有业务异常继承 `EABaseError`；HTTP 层统一映射（M02 网关落地）：
NotFoundError -> 404，ContractViolationError -> 422，ComplianceError -> 403。
"""
from __future__ import annotations

from typing import Type


class EABaseError(Exception):
    """Environment Agent 基类异常。"""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class NotFoundError(EABaseError):
    """资源不存在（HTTP 404）。"""


class ContractViolationError(EABaseError):
    """契约不一致（HTTP 422）。"""


class ComplianceError(EABaseError):
    """合规不通过（HTTP 403）。"""


class SandboxError(EABaseError):
    """沙箱执行失败（HTTP 500）。"""


HTTP_STATUS_MAP: dict[Type[EABaseError], int] = {
    NotFoundError: 404,
    ContractViolationError: 422,
    ComplianceError: 403,
    SandboxError: 500,
}


def http_status_for(exc: Exception) -> int:
    """返回异常对应的 HTTP 状态码，未知异常统一 500。"""
    return HTTP_STATUS_MAP.get(type(exc), 500)
