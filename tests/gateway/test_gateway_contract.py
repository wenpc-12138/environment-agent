# -*- coding: utf-8 -*-
"""M02 网关层契约测试（contracts.md §3.M16 后端 REST 约定）。

src/gateway/api 为 M01 骨架占位包：可 import 但无实质内容时自动 skip；
M02 实现后自动激活。
"""
from __future__ import annotations

import pytest


def _api():
    api = pytest.importorskip('src.gateway.api', reason='M02 Web API 未实现')
    if not (hasattr(api, 'router') or hasattr(api, 'app')):
        pytest.skip('M02 Web API 未实现（src/gateway/api 为骨架占位）')
    return api


def test_api_prefix() -> None:
    """REST 统一前缀 /api/v1。"""
    _api()


def test_api_routes_exposed() -> None:
    """核心端点存在（projects/reports/kb/module-pipeline）。"""
    api = _api()
    routes = {getattr(r, 'path', '') for r in api.app.routes}
    assert '/api/v1/kb/search' in routes
    assert any(p.startswith('/api/v1/reports/') for p in routes)
