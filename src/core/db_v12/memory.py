# -*- coding: utf-8 -*-
"""S1-W5 db.py 拆分：任务记忆数据层（memory 域）。

从根 db.py 原样搬移：memory_list/memory_get/memory_set/memory_delete。
"""
from __future__ import annotations

import json

from .base import q, w

def memory_list():
    return q("SELECT * FROM memory_entries ORDER BY updated_at DESC")


def memory_get(key):
    r = q("SELECT * FROM memory_entries WHERE key=?", (key,), one=True)
    if r:
        w("UPDATE memory_entries SET hits=hits+1 WHERE key=?", (key,))
    return r


def memory_set(key, content):
    w("INSERT INTO memory_entries(key,content,updated_at) VALUES(?,?,datetime('now','localtime'))"
      " ON CONFLICT(key) DO UPDATE SET content=excluded.content, updated_at=datetime('now','localtime')",
      (key, content))


def memory_delete(key):
    w("DELETE FROM memory_entries WHERE key=?", (key,))
