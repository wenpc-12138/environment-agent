# -*- coding: utf-8 -*-
"""本机（loopback）网络访问治理测试。

背景：机器上配置了系统 HTTP 代理时，urllib / requests 会把发往 127.0.0.1 的
请求也交给代理，导致本机 webhook 自测、SearXNG 搜索、OCR 调用随机超时
（表现为用例时好时坏）。本组用例锁定以下行为：
- loopback 判定覆盖 localhost / 127.0.0.0/8 / ::1 / 0.0.0.0；
- `ensure_local_no_proxy()` 幂等合并、保留用户已有 no_proxy 配置；
- 配置了不可用代理时，本机 webhook 推送仍然成功（回归防护）。
"""
from __future__ import annotations

import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.core import net
from src.gateway.adapters.http_channel import HttpChannelAdapter


# ---------- 判定与 no_proxy 合并 ----------

@pytest.mark.parametrize('url', [
    'http://127.0.0.1:8888/search',
    'http://127.5.5.5/x',
    'https://localhost/hook',
    'http://[::1]:8000/x',
    'http://0.0.0.0:5000/',
])
def test_is_loopback_url_true(url):
    assert net.is_loopback_url(url) is True


@pytest.mark.parametrize('url', [
    'https://api.deepseek.com/v1',
    'http://10.0.0.5/internal',
    'http://example.com/',
    '',
    'not-a-url',
])
def test_is_loopback_url_false(url):
    assert net.is_loopback_url(url) is False


def test_is_loopback_url_ignores_scheme():
    """判定只看主机：非 http(s) 方案但主机为本机时同样命中。"""
    assert net.is_loopback_url('ftp://127.0.0.1/x') is True


def test_ensure_local_no_proxy_merges_and_is_idempotent(monkeypatch):
    monkeypatch.setenv('no_proxy', 'example.com')
    monkeypatch.delenv('NO_PROXY', raising=False)
    first = net.ensure_local_no_proxy()
    assert 'example.com' in first, '用户已有配置必须保留'
    for h in ('127.0.0.1', 'localhost', '::1'):
        assert h in first
    second = net.ensure_local_no_proxy()
    assert second == first, '重复调用应幂等'
    assert second.count('127.0.0.1') == 1


def test_no_proxy_opener_ignores_env_proxy(hook_server, monkeypatch):
    """行为验证：设置了代理环境变量时，用本机 opener 访问 127.0.0.1 依然直连成功。

    说明：`build_opener(ProxyHandler({}))` 会顶掉默认的系统代理处理器
    （空 proxies 不注册任何 `<scheme>_open`，故不出现在 opener.handlers 中）。
    """
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:9')
    monkeypatch.delenv('no_proxy', raising=False)
    monkeypatch.delenv('NO_PROXY', raising=False)
    port = hook_server.server_address[1]
    req = urllib.request.Request(f'http://127.0.0.1:{port}/ping', data=b'{}', method='POST')
    with net.no_proxy_opener().open(req, timeout=5) as resp:
        assert resp.status == 200


# ---------- 回归：系统代理不可用时，本机 webhook 仍应成功 ----------

class _Hook(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n)
        type(self).received.append((self.path, json.loads(body.decode('utf-8'))))
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):  # noqa: ARG002 静默日志
        pass


@pytest.fixture()
def hook_server():
    _Hook.received = []
    server = ThreadingHTTPServer(('127.0.0.1', 0), _Hook)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


def test_local_webhook_bypasses_broken_proxy(hook_server, monkeypatch):
    """把代理指向一个必然连不上的地址：本机推送仍须成功（否则线上会随机超时）。"""
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:9')
    monkeypatch.setenv('https_proxy', 'http://127.0.0.1:9')
    port = hook_server.server_address[1]
    result = HttpChannelAdapter(timeout=5.0).send(f'http://127.0.0.1:{port}/hook', '监测任务完成')
    assert result.get('ok') is True, f'本机 webhook 不应走代理: {result}'
    assert result.get('status') == 200
    assert _Hook.received, '本机服务应收到请求'


def test_external_target_still_uses_proxy_handler(monkeypatch):
    """非本机地址不做直连改写（仍走默认 opener，尊重用户代理设置）。"""
    assert net.is_loopback_url('https://api.deepseek.com/v1') is False
