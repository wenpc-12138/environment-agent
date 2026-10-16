# -*- coding: utf-8 -*-
"""M02 CLI 平台适配器（第 7 波：平台适配器落地）。

`CliChannelAdapter`：命令行交互通道——`send` 输出到 stdout（可注入 `out` 回调），
`receive` 从可注入的 inbox 队列拉取。用于本地调试 / 无头环境。
"""
from __future__ import annotations

import sys
from typing import Any, Callable

from . import ChannelAdapter


class CliChannelAdapter(ChannelAdapter):
    """命令行通道：send 打印（默认 stdout），receive 从 inbox 队列取。"""

    name = 'cli'

    def __init__(self, out: Callable[[str], None] | None = None,
                 inbox: list[dict] | None = None) -> None:
        self._out = out or (lambda s: print(s, flush=True))
        self._inbox = inbox if inbox is not None else []

    def send(self, target: str, content: str, **kw: Any) -> dict:
        """打印消息到输出（可注入 out 回调便于测试/日志重定向）。"""
        prefix = f'[{target}] ' if target else ''
        line = f'{prefix}{content}'
        self._out(line)
        return {'ok': True, 'output': line}

    def receive(self, **kw: Any) -> list[dict]:
        """拉取待处理消息（增量：取走即清空 inbox）。"""
        items = list(self._inbox)
        self._inbox.clear()
        return items


__all__ = ['CliChannelAdapter']
