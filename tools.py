# -*- coding: utf-8 -*-
"""生态Agent - 工具注册表(kb_lookup/web_search/web_fetch/kb_save/memory)

S2-M3 迁移（2026-08-20）：实现已迁入 `src/tools/v12.py`（单文件原样搬移），
本文件仅作兼容重导出，`import tools` / `from tools import *` /
`tools.TOOL_SCHEMAS` / `tools.execute_tool` 用法不变。原实现备份：
`tools.py.bak_s2m3`。
"""
from src.tools.v12 import *  # noqa: F401,F403
from src.tools.v12 import TOOL_SCHEMAS, execute_tool  # noqa: F401
