# -*- coding: utf-8 -*-
"""WorkingMemory 行为测试：TTL 过期 / 删除 / 清空。"""
from __future__ import annotations

import time

from src.memory.working import WorkingMemory


def test_set_get_roundtrip() -> None:
    wm = WorkingMemory()
    wm.set('k1', {'a': 1})
    assert wm.get('k1') == {'a': 1}


def test_missing_returns_none() -> None:
    wm = WorkingMemory()
    assert wm.get('nope') is None


def test_ttl_expiry() -> None:
    wm = WorkingMemory()
    wm.set('temp', 'v', ttl=1)
    assert wm.get('temp') == 'v'
    time.sleep(1.2)
    assert wm.get('temp') is None


def test_custom_ttl_default_3600() -> None:
    wm = WorkingMemory()
    wm.set('k', 'v', ttl=3600)
    assert wm.get('k') == 'v'


def test_delete_and_clear() -> None:
    wm = WorkingMemory()
    wm.set('a', 1)
    assert wm.delete('a') is True
    assert wm.delete('a') is False
    wm.set('b', 2)
    wm.set('c', 3)
    wm.clear()
    assert wm.keys() == []
