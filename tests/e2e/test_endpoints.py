# -*- coding: utf-8 -*-
"""全链路端点冒烟（固化自检测脚本）：app 启动 + 核心页面/静态资源 + v2 关键端点。

说明：所有检测均为只读/无副作用调用（create_app 会 init_db + 启动调度线程，
属既有应用行为）；POST 端点均为无写入操作（parse/ping/plan 不执行/抽取实体）。
"""
from __future__ import annotations

import pytest

import app as a


@pytest.fixture(scope='module')
def client():
    app_ = a.create_app()
    return app_.test_client()


class TestCorePages:
    def test_index(self, client):
        r = client.get('/')
        assert r.status_code == 200

    def test_static_css(self, client):
        r = client.get('/static/style.css')
        assert r.status_code == 200

    def test_static_js(self, client):
        assert client.get('/static/app.js').status_code == 200
        assert client.get('/static/app_v2.js').status_code == 200


class TestHealthAndSkills:
    def test_publicapi_health(self, client):
        r = client.get('/api/v2/publicapi/health')
        assert r.status_code == 200
        assert r.is_json

    def test_skills2(self, client):
        r = client.get('/api/v2/skills2')
        assert r.status_code == 200 and r.get_json().get('ok')

    def test_skills_updates_pending(self, client):
        assert client.get('/api/v2/skills/updates/pending').status_code == 200


class TestV2ReadEndpoints:
    """V2 只读端点冒烟：roles/market/mcp/trace/vision/schedule/graph。"""

    @pytest.mark.parametrize('path', [
        '/api/v2/memory/task-summary',
        '/api/v2/roles',
        '/api/v2/market',
        '/api/v2/mcp/tools',
        '/api/v2/trace/aggregate',
        '/api/v2/vision/supported',
        '/api/v2/schedule',
        '/api/v2/memory/graph?entity=test',
    ])
    def test_get_ok(self, client, path):
        r = client.get(path)
        assert r.status_code == 200
        assert r.is_json


class TestV2PostEndpoints:
    """V2 写入/调用端点冒烟（无副作用调用）。"""

    def test_schedule_parse(self, client):
        r = client.post('/api/v2/schedule/parse',
                        json={'text': '每天9点生成日报'})
        assert r.status_code == 200
        d = r.get_json()
        assert d.get('ok') and d.get('cron_desc') == 'daily 09:00'

    def test_mcp_ping(self, client):
        r = client.post('/api/v2/mcp',
                        json={'jsonrpc': '2.0', 'id': 1, 'method': 'ping', 'params': {}})
        assert r.status_code == 200 and r.get_json()['result'] == {}

    def test_mcp_initialize(self, client):
        r = client.post('/api/v2/mcp',
                        json={'jsonrpc': '2.0', 'id': 2, 'method': 'initialize',
                              'params': {'clientInfo': {'name': 't'}}})
        assert r.get_json()['result']['serverInfo']['name'] == 'environment-agent'

    def test_plan_run(self, client):
        r = client.post('/api/v2/plan/run',
                        json={'text': '生成噪声监测报告', 'mode_hint': 'interactive',
                              'execute': False})
        d = r.get_json()
        assert r.status_code == 200 and d.get('steps')

    def test_graph_extract(self, client):
        r = client.post('/api/v2/memory/graph/extract',
                        json={'text': '武汉市GB 3838-2002 COD'})
        d = r.get_json()
        assert d.get('entities')

    def test_upload_no_file_rejected(self, client):
        # 无文件上传 -> 400（不崩溃）
        assert client.post('/api/upload').status_code in (400, 405)
