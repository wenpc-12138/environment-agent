# -*- coding: utf-8 -*-
"""S3-H3 斜杠命令测试：/api/v2/commands 解析端点。

覆盖：
- 命令列表（无 text 参数时返回全部命令）；
- 已知命令解析（/report /calc /learn /schedule /approve /help）；
- 带参数解析（args 透传）；
- 未知命令报错；
- 大小写不敏感。
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def client():
    from src.gateway.flask_app import app
    app.config['TESTING'] = True
    return app.test_client()


def test_commands_list(client):
    r = client.get('/api/v2/commands')
    assert r.status_code == 200
    j = r.get_json()
    assert 'commands' in j
    names = {c['command'] for c in j['commands']}
    assert {'/report', '/calc', '/learn', '/schedule', '/approve'} <= names


def test_parse_report(client):
    r = client.get('/api/v2/commands?text=/report%20验收报告')
    j = r.get_json()
    assert j['ok'] is True
    assert j['command'] == '/report'
    assert j['args'] == '验收报告'
    assert 'endpoint' in j


def test_parse_without_args(client):
    r = client.get('/api/v2/commands?text=/calc')
    j = r.get_json()
    assert j['ok'] is True and j['command'] == '/calc' and j['args'] == ''


def test_parse_case_insensitive(client):
    r = client.get('/api/v2/commands?text=/LEARN%20报告类型')
    j = r.get_json()
    assert j['ok'] is True and j['command'] == '/learn'
    assert j['args'] == '报告类型'


def test_unknown_command(client):
    r = client.get('/api/v2/commands?text=/nope%20x')
    j = r.get_json()
    assert j['ok'] is False
    assert '未知命令' in j['error']


def test_help_known(client):
    r = client.get('/api/v2/commands?text=/help')
    j = r.get_json()
    assert j['ok'] is True and j['command'] == '/help'
