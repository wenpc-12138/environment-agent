# -*- coding: utf-8 -*-
"""M04 联网检索客户端行为测试（第 7 波：缓存/重试/标准化/降级）。"""
import sys
import types

import pytest

from src.tools.mcp_client import McpClient


class _FakeEngine(types.SimpleNamespace):
    """可编程的假 searxng_mcp 模块（注入代替动态导入）。"""

    def __init__(self):
        self.search_calls = 0
        self.fetch_calls = 0
        self.health_calls = 0
        self.search_result = []
        self.search_error: Exception | None = None
        self.fetch_result = ''
        self.fetch_error: Exception | None = None
        self.health_result = False

    def search(self, query, top_n=5, time_range=None, site_filter=None):
        self.search_calls += 1
        if self.search_error:
            raise self.search_error
        return self.search_result

    def fetch_text(self, url, max_chars=6000):
        self.fetch_calls += 1
        if self.fetch_error:
            raise self.fetch_error
        return self.fetch_result

    def health(self):
        self.health_calls += 1
        return self.health_result


@pytest.fixture()
def fake_engine():
    engine = _FakeEngine()
    sys.modules['_fake_searxng'] = engine
    yield engine
    sys.modules.pop('_fake_searxng', None)


def _client(fake_engine, **kw):
    kw.setdefault('module_name', '_fake_searxng')
    kw.setdefault('cache_ttl', 60.0)
    kw.setdefault('max_retries', 2)
    return McpClient(**kw)


def test_search_normalizes_v12_dict_results(fake_engine):
    fake_engine.search_result = [
        {'title': 'A', 'url': 'https://a.example', 'snippet': 'snip-a'},
        {'title': 'B', 'url': 'https://b.example'},  # 缺 snippet
    ]
    client = _client(fake_engine)
    out = client.search('标准 查询')
    assert out[0] == {'title': 'A', 'url': 'https://a.example', 'snippet': 'snip-a'}
    assert out[1]['snippet'] == ''
    assert fake_engine.search_calls == 1


def test_search_normalizes_str_results(fake_engine):
    fake_engine.search_result = ['https://x.example', '   ', 'https://y.example']
    out = _client(fake_engine).search('q')
    assert len(out) == 2
    assert out[0]['url'] == 'https://x.example'
    assert out[0]['title'].startswith('https://')


def test_search_drops_invalid_items(fake_engine):
    fake_engine.search_result = [{'url': ''}, {'title': 'T', 'url': 'https://ok.example'}]
    out = _client(fake_engine).search('q')
    assert len(out) == 1
    assert out[0]['url'] == 'https://ok.example'


def test_search_cache_avoids_second_call(fake_engine):
    fake_engine.search_result = [{'url': 'https://a.example'}]
    client = _client(fake_engine)
    client.search('q')
    client.search('q')
    assert fake_engine.search_calls == 1
    assert client.stats()['hits'] >= 1


def test_search_cache_ttl_expiry(fake_engine):
    import time

    fake_engine.search_result = [{'url': 'https://a.example'}]
    client = _client(fake_engine, cache_ttl=0.05)
    client.search('q')
    time.sleep(0.08)  # 等待 TTL 过期
    client.search('q')
    assert fake_engine.search_calls == 2  # TTL 过期 -> 重新请求


def test_search_retry_then_success(fake_engine):
    fake_engine.search_error = RuntimeError('flaky')
    fake_engine.search_result = [{'url': 'https://a.example'}]

    def flaky_once():
        if fake_engine.search_calls == 1:
            raise fake_engine.search_error
        return fake_engine.search_result

    fake_engine.search = lambda query, top_n=5, time_range=None, site_filter=None: flaky_once()  # noqa: E731
    out = _client(fake_engine, max_retries=1).search('q')
    assert out[0]['url'] == 'https://a.example'


def test_search_all_retries_fail_returns_empty(fake_engine):
    fake_engine.search_error = RuntimeError('down')
    client = _client(fake_engine, max_retries=1, cache_ttl=0)
    assert client.search('q') == []
    assert fake_engine.search_calls == 2  # 1 次 + 1 次重试


def test_search_degrades_when_module_missing():
    client = McpClient(module_name='_no_such_searxng_module_xyz')
    assert client.search('q') == []


def test_fetch_text_caches_and_degrades(fake_engine):
    fake_engine.fetch_result = 'body'
    client = _client(fake_engine)
    assert client.fetch_text('https://a.example') == 'body'
    client.fetch_text('https://a.example')
    assert fake_engine.fetch_calls == 1
    assert McpClient(module_name='_no_such_module_xyz').fetch_text('https://a.example') == ''


def test_health_cached_and_degrades(fake_engine):
    fake_engine.health_result = True
    client = _client(fake_engine)
    assert client.health() is True
    client.health()
    assert fake_engine.health_calls == 1
    assert McpClient(module_name='_no_such_module_xyz').health() is False


def test_search_summary_format(fake_engine):
    fake_engine.search_result = [
        {'title': '标题A', 'url': 'https://a.example', 'snippet': '摘要A'},
    ]
    text = _client(fake_engine).search_summary('生态标准')
    assert '在线检索「生态标准」结果（1 条）' in text
    assert 'https://a.example' in text


def test_search_summary_empty_when_no_results(fake_engine):
    assert _client(fake_engine).search_summary('q') == ''


def test_stats_reports_cache():
    fake_engine.search_result = [{'url': 'https://a.example'}]
    client = _client(fake_engine)
    client.search('q')
    client.search('q')
    stats = client.stats()
    assert stats['cache_size'] >= 1
    assert stats['hits'] >= 1
    assert stats['misses'] >= 1
