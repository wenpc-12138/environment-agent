# -*- coding: utf-8 -*-
"""M02 网关层包：FastAPI API + Typer CLI + 消息适配器。

- `api`：`app`（FastAPI，统一 /api/v1 前缀 + /ws/events）
- `cli`：serve / route / complete / tools 子命令
- `adapters`：ChannelAdapter 基类 + AdapterRegistry
"""
from .adapters import AdapterRegistry, ChannelAdapter, get_adapter, register_adapter

__all__ = ['AdapterRegistry', 'ChannelAdapter', 'get_adapter', 'register_adapter']
