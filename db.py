# -*- coding: utf-8 -*-
"""生态Agent - SQLite 数据层 (含 FTS5 全文检索)

S1-W5 拆分（2026-08-20）：实现已按域迁入 `src/core/db_v12/` 子包
（schema/base/providers/tasks/kb/memory/usage），本文件仅作兼容别名——
通过 sys.modules 替换使 `import db` 与 `src.core.db_v12` 完全等价
（同一模块对象，monkeypatch/单例状态共享），`import db` /
`from db import *` / `db.xxx` 用法不变。原实现备份：`db.py.bak_s1w5`。
"""
import sys as _sys

from src.core import db_v12 as _db_v12

for _name in dir(_db_v12):
    if not _name.startswith('__'):
        globals()[_name] = getattr(_db_v12, _name)

# 使 `import db` 返回 db_v12 同一模块对象（与 S2-M5 v2_bridge 做法一致）
_sys.modules[__name__] = _db_v12
