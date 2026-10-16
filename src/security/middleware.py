# -*- coding: utf-8 -*-
"""M14 网关审计中间件（UPGRADE_PLAN §M14：在网关层注入中间件记录全请求）。

`AuditMiddleware` 为 Starlette BaseHTTPMiddleware：每个 HTTP 请求记录
method+path+query（输入）与状态码（输出），写入 AuditLogger 哈希链，
并通过响应头 X-Audit-Seq 暴露该条审计序号。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .audit import AuditLogger


class AuditMiddleware(BaseHTTPMiddleware):
    """记录全部 HTTP 请求到审计哈希链。"""

    def __init__(self, app, logger: AuditLogger | None = None):
        self._logger = logger or AuditLogger()
        super().__init__(app)

    @property
    def logger(self) -> AuditLogger:
        return self._logger

    async def dispatch(self, request: Request, call_next) -> Response:
        method = request.method
        path = request.url.path
        query = str(request.url.query)
        status = 200
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            status = 500
            raise
        finally:
            entry = self._logger.log(
                who='gateway',
                action=f'{method} {path}',
                input=query,
                output=f'{status}',
            )
        response.headers['X-Audit-Seq'] = str(entry.seq)
        return response


__all__ = ['AuditMiddleware']
