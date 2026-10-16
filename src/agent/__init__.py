# -*- coding: utf-8 -*-
"""S2-M1 主循环迁移：Agent 引擎包。

- `prompts.py` 系统提示组装（build_system_prompt / BASE_SYSTEM / MODE_HINTS ...）
- `engine.py`  Agent 主循环（Agent 类 + request_stop/_stopped/infer_domain）

根目录 `agent_core.py` 已转兼容重导出（`from src.agent import *`）。
"""
from .engine import (
    Agent, STOP_EVENTS, infer_domain, request_stop, _stopped,
)
from .prompts import (
    BASE_SYSTEM, MODE_HINTS, build_system_prompt,
)

__all__ = [
    'Agent', 'STOP_EVENTS', 'infer_domain', 'request_stop',
    'BASE_SYSTEM', 'MODE_HINTS', 'build_system_prompt',
]
