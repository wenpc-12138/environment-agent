# -*- coding: utf-8 -*-
"""M05 WorkingMemory：短期工作记忆（进程内存 + TTL 过期）。

契约（contracts.md §3.M05）：
- `set(key, value, ttl=3600)`：写入，ttl 秒后过期
- `get(key)`：读取，已过期返回 None
- Redis 降级：M04 工具层落地后按配置切换后端，本实现先提供线程安全的内存版。
"""
from __future__ import annotations

import threading
import time
from typing import Any


class WorkingMemory:
    """线程安全的进程内 KV 记忆，支持 TTL 过期。"""

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """写入记忆项，ttl 秒后过期。"""
        if not isinstance(key, str) or not key:
            raise ValueError('key 必须为非空字符串')
        if ttl <= 0:
            raise ValueError('ttl 必须为正整数')
        expire_at = time.monotonic() + ttl
        with self._lock:
            self._data[key] = (value, expire_at)

    def get(self, key: str) -> Any | None:
        """读取记忆项；不存在或已过期返回 None。"""
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            value, expire_at = item
            if time.monotonic() > expire_at:
                del self._data[key]
                return None
            return value

    def delete(self, key: str) -> bool:
        """删除记忆项，返回是否存在。"""
        with self._lock:
            return self._data.pop(key, None) is not None

    def clear(self) -> None:
        """清空全部工作记忆。"""
        with self._lock:
            self._data.clear()

    def keys(self) -> list[str]:
        """返回未过期键列表。"""
        now = time.monotonic()
        with self._lock:
            alive = [k for k, (_, exp) in self._data.items() if exp > now]
            for k in list(self._data):
                if self._data[k][1] <= now:
                    del self._data[k]
            return alive
