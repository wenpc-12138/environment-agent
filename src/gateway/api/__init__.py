# -*- coding: utf-8 -*-
"""M02 Web API 网关（FastAPI，contracts.md §3.M16 后端 REST 约定）。

> 状态（ADR-019, 2026-08-20）：**契约门面，不承载业务**。真实业务网关为 v1.2 Flask
> （`app.py` → `/api/v2` → v2_bridge，S2 迁入 src/gateway/api 为 Flask Blueprint）；
> 本 FastAPI `/api/v1` 仅保留 health / kb/search 演示端点，不再新增业务端点。

统一前缀 /api/v1；核心端点：
- GET  /api/v1/health                健康检查
- GET  /api/v1/kb/search?q=...       知识库检索（M06 StandardKB）
- GET  /api/v1/projects/{pid}        项目详情（v1.2 语义占位）
- POST /api/v1/reports/{id}/generate  报告生成（任务创建占位）
- POST /api/v1/reports/{id}/review    报告审核（M11 占位）
- POST /api/v1/reports/{id}/compliance 合规检查（M12 占位）
- POST /api/v1/module-pipeline       模块流水线（M09 占位）
- WS   /ws/events                    事件推送

fastapi 未安装时本模块 import 失败（契约测试自动 skip），属预期降级；
安装后（requirements.txt 已登记）自动激活。
"""
from __future__ import annotations

import asyncio

from fastapi import FastAPI, WebSocket
from pydantic import BaseModel, Field

from ...kb.standards import StandardKB
from ...security import AuditLogger, AuditMiddleware

app = FastAPI(title='Ecosystem Agent API', version='2.0.0')
app.add_middleware(AuditMiddleware, logger=AuditLogger())  # M14：全请求哈希链审计

_kb = StandardKB()


class SearchQuery(BaseModel):
    q: str = Field(..., min_length=1, description='检索关键词')
    category: str | None = None
    validity: str | None = None
    top_n: int = Field(default=5, ge=1, le=50)


class ReportAction(BaseModel):
    task: str = Field(default='', description='任务描述（generate/review/compliance 共用）')


@app.get('/api/v1/health')
def health() -> dict:
    return {'status': 'ok', 'version': '2.0.0'}


@app.get('/api/v1/kb/search')
def kb_search(q: str, category: str | None = None, validity: str | None = None,
              top_n: int = 5) -> dict:
    filters = {'category': category, 'validity': validity} if (category or validity) else None
    hits = _kb.search(q, filters=filters, top_k=max(1, min(top_n, 50)))
    return {'query': q, 'count': len(hits), 'hits': [h.model_dump() for h in hits]}


@app.get('/api/v1/projects/{pid}')
def project_detail(pid: str) -> dict:
    # v1.2 项目表未在 v2 契约内；返回统一占位结构（M09 落地后对接）
    return {'id': pid, 'found': False, 'detail': None}


@app.post('/api/v1/reports/{rid}/generate')
def report_generate(rid: str, body: ReportAction | None = None) -> dict:
    return {'report_id': rid, 'status': 'accepted', 'step': 'generate',
            'task': (body.task if body else '')}


@app.post('/api/v1/reports/{rid}/review')
def report_review(rid: str, body: ReportAction | None = None) -> dict:
    return {'report_id': rid, 'status': 'accepted', 'step': 'review',
            'task': (body.task if body else '')}


@app.post('/api/v1/reports/{rid}/compliance')
def report_compliance(rid: str, body: ReportAction | None = None) -> dict:
    return {'report_id': rid, 'status': 'accepted', 'step': 'compliance',
            'task': (body.task if body else '')}


@app.post('/api/v1/module-pipeline')
def module_pipeline() -> dict:
    return {'status': 'accepted', 'pipeline': 'module_pipeline'}


@app.websocket('/ws/events')
async def ws_events(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            msg = await ws.receive_text()
            await asyncio.sleep(0)
            await ws.send_text(f'echo:{msg}')
    except Exception:
        await ws.close()


__all__ = ['app']
