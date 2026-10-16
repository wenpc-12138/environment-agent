# -*- coding: utf-8 -*-
"""M02 HTTP 平台适配器（第 7 波：平台适配器落地）。

`HttpChannelAdapter`：通过 HTTP POST（webhook / REST API）主动推送消息，
对接第三方系统（企业微信机器人、飞书群机器人、自定义 Webhook 等）。
零第三方依赖（仅标准库 urllib）。
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any

from . import ChannelAdapter
from src.core.net import open_url


class HttpChannelAdapter(ChannelAdapter):
    """HTTP 主动推送通道：`send` 向 `target`（完整 URL）POST JSON。"""

    name = 'http'

    def __init__(self, timeout: float = 8.0) -> None:
        self.timeout = timeout

    def send(self, target: str, content: str, **kw: Any) -> dict:
        """向 target（HTTP URL）POST JSON 消息，返回平台回执。

        兼容主流 webhook 载荷约定：优先 `{msgtype, text}`（企微/飞书风格），
        或注入 `payload` / `headers` 自定义载荷。
        """
        if not (target or '').startswith(('http://', 'https://')):
            return {'ok': False, 'error': f'非法 target（须为 http(s) URL）: {target}'}
        headers = dict(kw.get('headers') or {})
        headers.setdefault('Content-Type', 'application/json')
        payload = kw.get('payload')
        if payload is None:
            payload = {'msgtype': 'text', 'text': {'content': str(content)}}
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(target, data=body, headers=headers, method='POST')
        try:
            # 本机地址（127.0.0.1 / localhost / ::1）直连：系统代理会把本机请求也转发出去，
            # 造成超时或时好时坏（webhook 自测、内网回调场景尤其明显）。
            with open_url(req, timeout=self.timeout) as resp:  # noqa: S310 用户配置的 webhook
                code = resp.status
                raw = resp.read(512).decode('utf-8', errors='replace')
            return {'ok': 200 <= code < 300, 'status': code, 'response': raw[:300]}
        except Exception as exc:  # noqa: BLE001 网络/超时等统一回执
            return {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}

    def receive(self, **kw: Any) -> list[dict]:
        """HTTP 为主动推送通道：接收由网关 Webhook 端点负责，此处返回空。"""
        return []


__all__ = ['HttpChannelAdapter']
