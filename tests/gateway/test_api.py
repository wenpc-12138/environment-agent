# -*- coding: utf-8 -*-
"""M02 网关行为测试：FastAPI 路由 + 核心端点（临时库隔离）。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.core import config
from src.gateway.api import app


def _setup_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'gw.db'))
    config.get_settings.cache_clear()
    try:
        from src.core import db as core_db
        core_db.run_migrations()
    finally:
        pass


def test_health(tmp_path, monkeypatch) -> None:
    _setup_db(tmp_path, monkeypatch)
    with TestClient(app) as client:
        resp = client.get('/api/v1/health')
        assert resp.status_code == 200
        body = resp.json()
        assert body['status'] == 'ok'


def test_kb_search_endpoint(tmp_path, monkeypatch) -> None:
    _setup_db(tmp_path, monkeypatch)
    try:
        # 先入库一条标准，再经网关检索
        from src.kb.standards import StandardKB

        f = tmp_path / 'hj535.md'
        f.write_text('HJ 535-2009 水质 氨氮的测定 纳氏试剂分光光度法\n正文内容……', encoding='utf-8')
        StandardKB().ingest(str(f), kind='HJ')
        with TestClient(app) as client:
            resp = client.get('/api/v1/kb/search', params={'q': '氨氮', 'top_n': 5})
            assert resp.status_code == 200
            body = resp.json()
            assert body['count'] >= 1
            assert body['hits'][0]['doc_id']
            assert body['hits'][0]['score'] > 0
    finally:
        config.get_settings.cache_clear()


def test_reports_endpoints(tmp_path, monkeypatch) -> None:
    _setup_db(tmp_path, monkeypatch)
    with TestClient(app) as client:
        for step in ('generate', 'review', 'compliance'):
            resp = client.post(f'/api/v1/reports/R-001/{step}', json={'task': '样例任务'})
            assert resp.status_code == 200
            body = resp.json()
            assert body['report_id'] == 'R-001'
            assert body['step'] == step


def test_project_detail_placeholder(tmp_path, monkeypatch) -> None:
    _setup_db(tmp_path, monkeypatch)
    with TestClient(app) as client:
        resp = client.get('/api/v1/projects/P-9')
        assert resp.status_code == 200
        assert resp.json()['found'] is False


def test_routes_exposed() -> None:
    routes = {getattr(r, 'path', '') for r in app.routes}
    assert '/api/v1/kb/search' in routes
    assert '/api/v1/health' in routes
    assert any(p.startswith('/api/v1/reports/') for p in routes)
    assert '/ws/events' in routes
