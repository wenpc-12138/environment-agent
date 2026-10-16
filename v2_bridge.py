# -*- coding: utf-8 -*-
"""v1.2 Flask 界面 -> v2.0 模块桥接层（M16 增量集成方案）

DEPRECATED（S2-M5, 2026-08-20）：实现已迁入 `src/gateway/bridge_compat.py`，
本文件仅作兼容重导出（含下划线私有函数，供既有测试/工具脚本使用），
`import v2_bridge` / `from v2_bridge import *` / `v2_bridge._procedural()`
用法不变；前端 /api/v2 全部迁移到 src/gateway/api 后本文件删除。
"""
import sys as _sys

from src.gateway import bridge_compat as _bridge

# 显式转发全部属性（含下划线私有函数），使 `v2_bridge.xxx` 等价于 bridge_compat.xxx
for _name in dir(_bridge):
    if not _name.startswith('__'):
        globals()[_name] = getattr(_bridge, _name)

# 确保 sys.modules 中的 v2_bridge 与 bridge_compat 共享单例状态（模块级 _WF_ENGINE 等）
_sys.modules[__name__] = _bridge
