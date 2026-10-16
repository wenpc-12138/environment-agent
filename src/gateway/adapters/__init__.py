# -*- coding: utf-8 -*-
"""M02 消息平台适配器（contracts.md §3.M17 平台接入）。

- `ChannelAdapter`：平台无关抽象基类（name / send / receive）。
- `AdapterRegistry`：适配器注册表。
- 具体适配器（微信/QQ/企微）实现留待平台接入波次；本波提供基类与注册表，
  保证 M02 网关与消息平台的解耦边界。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ChannelAdapter(ABC):
    """消息通道适配器基类。"""

    name: str = 'base'

    @abstractmethod
    def send(self, target: str, content: str, **kw: Any) -> dict:
        """向 target 发送消息，返回平台回执。"""

    @abstractmethod
    def receive(self, **kw: Any) -> list[dict]:
        """拉取待处理消息（增量轮询），返回 [{sender, content, ts}]。"""


class AdapterRegistry:
    """适配器注册表。"""

    def __init__(self) -> None:
        self._adapters: dict[str, ChannelAdapter] = {}

    def register(self, adapter: ChannelAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> ChannelAdapter | None:
        return self._adapters.get(name)

    def names(self) -> list[str]:
        return sorted(self._adapters)

    def all(self) -> list[ChannelAdapter]:
        return list(self._adapters.values())


_adapters = AdapterRegistry()


def register_adapter(adapter: ChannelAdapter) -> None:
    _adapters.register(adapter)


def get_adapter(name: str) -> ChannelAdapter | None:
    return _adapters.get(name)


# -- 内置适配器注册（第 7 波：平台适配器落地） ---------------------------
_registering_defaults = False


def register_default_adapters() -> None:
    """注册内置平台适配器（http / cli），幂等。"""
    global _registering_defaults
    if _registering_defaults:
        return
    _registering_defaults = True
    try:
        from .cli_channel import CliChannelAdapter
        from .http_channel import HttpChannelAdapter

        _adapters.register(HttpChannelAdapter())
        _adapters.register(CliChannelAdapter())
    finally:
        _registering_defaults = False


register_default_adapters()  # 包导入即注册，`get_adapter('http'/'cli')` 立即可用


__all__ = [
    'ChannelAdapter', 'AdapterRegistry', 'register_adapter', 'get_adapter',
    'register_default_adapters',
]
