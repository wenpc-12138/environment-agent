# -*- coding: utf-8 -*-
"""M02 平台适配器行为测试（第 7 波）：CLI 通道 + HTTP webhook 通道。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.gateway.adapters import get_adapter
from src.gateway.adapters.cli_channel import CliChannelAdapter
from src.gateway.adapters.http_channel import HttpChannelAdapter


# -- CLI 通道 ------------------------------------------------------------
def test_cli_send_writes_to_injected_out():
    lines = []
    adapter = CliChannelAdapter(out=lines.append)
    result = adapter.send('debug', '你好，环境监测')
    assert result['ok'] is True
    assert lines == ['[debug] 你好，环境监测']


def test_cli_send_without_target():
    lines = []
    adapter = CliChannelAdapter(out=lines.append)
    adapter.send('', '纯消息')
    assert lines == ['纯消息']


def test_cli_receive_from_inbox():
    adapter = CliChannelAdapter(inbox=[{'msg': 'a'}, {'msg': 'b'}])
    assert adapter.receive() == [{'msg': 'a'}, {'msg': 'b'}]
    assert adapter.receive() == []  # 增量消费


def test_cli_registered_default():
    adapter = get_adapter('cli')
    assert isinstance(adapter, CliChannelAdapter)


# -- HTTP 通道 -----------------------------------------------------------
class _WebhookHandler(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8')
        _WebhookHandler.received.append((self.path, json.loads(body)))
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):  # noqa: ARG002 静默日志
        pass


@pytest.fixture()
def webhook_server():
    _WebhookHandler.received = []
    server = ThreadingHTTPServer(('127.0.0.1', 0), _WebhookHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def test_http_send_posts_webhook(webhook_server):
    port = webhook_server.server_address[1]
    adapter = HttpChannelAdapter(timeout=5.0)
    result = adapter.send(f'http://127.0.0.1:{port}/hook', '监测任务完成')
    assert result['ok'] is True
    assert result['status'] == 200
    path, payload = _WebhookHandler.received[0]
    assert path == '/hook'
    assert payload == {'msgtype': 'text', 'text': {'content': '监测任务完成'}}


def test_http_send_custom_payload(webhook_server):
    port = webhook_server.server_address[1]
    adapter = HttpChannelAdapter(timeout=5.0)
    result = adapter.send(
        f'http://127.0.0.1:{port}/custom', 'x',
        payload={'markdown': {'content': '**标题**'}}, headers={'X-Token': 'abc'},
    )
    assert result['ok'] is True
    path, payload = _WebhookHandler.received[0]
    assert payload == {'markdown': {'content': '**标题**'}}
    assert path == '/custom'


def test_http_send_invalid_url():
    adapter = HttpChannelAdapter()
    result = adapter.send('ftp://nope', 'x')
    assert result['ok'] is False
    assert 'target' in result['error']


def test_http_send_connection_error():
    adapter = HttpChannelAdapter(timeout=1.0)
    result = adapter.send('http://127.0.0.1:1/nope', 'x')
    assert result['ok'] is False


def test_http_receive_empty():
    assert HttpChannelAdapter().receive() == []


def test_http_registered_default():
    adapter = get_adapter('http')
    assert isinstance(adapter, HttpChannelAdapter)
