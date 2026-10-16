# -*- coding: utf-8 -*-
"""生态Agent - 主循环:系统提示组装 / 工具调用 / 流式输出 / 上下文压缩 / 缓存记账

S2-M1 迁移（2026-08-20）：实现已迁入 `src/agent/`（prompts.py 系统提示 +
engine.py Agent 主循环），本文件仅作兼容重导出，`import agent_core` /
`from agent_core import *` / `agent_core.Agent` 用法不变。
"""
from src.agent import *  # noqa: F401,F403
from src.agent import __all__ as _agent_all

__all__ = list(_agent_all)
