# -*- coding: utf-8 -*-
"""M04 联网检索工具注册契约测试（第 7 波：联网检索落地）。"""
import inspect
import sys
import types

import pytest

from src.tools import McpClient, ToolRegistry, register_web_tools


def test_mcp_client_contract_signatures():
    sigs = {
        'search': ['self', 'query', 'top_n', 'time_range', 'site_filter'],
        'fetch_text': ['self', 'url', 'max_chars'],
        'health': ['self'],
        'search_summary': ['self', 'query', 'top_n', 'time_range', 'site_filter'],
        'stats': ['self'],
    }
    for method, names in sigs.items():
        params = list(inspect.signature(getattr(McpClient, method)).parameters)
        assert params == names, f'{method} 参数应为 {names}，实际 {params}'


def test_register_web_tools_returns_ids():
    reg = ToolRegistry(load_v12=False)
    ids = register_web_tools(reg)
    assert ids == ['web.search', 'web.fetch', 'web.health']


def test_web_tools_capability_web():
    reg = ToolRegistry(load_v12=False)
    register_web_tools(reg)
    for spec in reg.list(capability='web'):
        assert spec.id in ('web.search', 'web.fetch', 'web.health')
    assert len(reg.list(capability='web')) == 3


def test_web_search_execute_with_injected_client():
    engine = types.SimpleNamespace()
    engine.results = [{'title': 'T', 'url': 'https://a.example', 'snippet': 'S'}]
    engine.calls = 0

    def fake_search(query, top_n=5, time_range=None, site_filter=None):
        engine.calls += 1
        return engine.results

    engine.search = fake_search
    engine.fetch_text = lambda url, max_chars=6000: ''
    engine.health = lambda: True

    mod = types.ModuleType('_fake_web_searxng')
    for k, v in (('search', fake_search), ('fetch_text', engine.fetch_text), ('health', engine.health)):
        setattr(mod, k, v)
    sys.modules['_fake_web_searxng'] = mod
    try:
        client = McpClient(module_name='_fake_web_searxng', cache_ttl=60.0)
        reg = ToolRegistry(load_v12=False)
        register_web_tools(reg, client=client)
        out = reg.execute('web.search', {'query': '生态标准', 'top_n': 3})
        assert out.ok is True
        assert out.data['count'] == 1
        assert out.data['results'][0]['url'] == 'https://a.example'
        assert '在线检索' in out.data['summary']
        assert engine.calls == 1
    finally:
        sys.modules.pop('_fake_web_searxng', None)


def test_web_search_requires_query():
    reg = ToolRegistry(load_v12=False)
    register_web_tools(reg)
    out = reg.execute('web.search', {})
    assert out.ok is False
    assert 'query' in (out.data or {}).get('error', '')


def test_web_fetch_validates_url():
    reg = ToolRegistry(load_v12=False)
    register_web_tools(reg)
    out = reg.execute('web.fetch', {'url': 'not-a-url'})
    assert out.ok is False


def test_web_health_reports_engine():
    reg = ToolRegistry(load_v12=False)
    register_web_tools(reg)
    out = reg.execute('web.health', {})
    assert out.ok is True
    assert out.data['engine'] == 'searxng_mcp'
