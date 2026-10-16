# -*- coding: utf-8 -*-
"""MemoryManager 行为测试：三实例组合 + 便捷方法。"""
from __future__ import annotations

from src.core import config
from src.memory.manager import MemoryManager


def test_manager_layers(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'mm.db'))
    config.get_settings.cache_clear()
    try:
        from src.core import db as core_db
        core_db.run_migrations()
        mgr = MemoryManager()
        assert hasattr(mgr, 'working')
        assert hasattr(mgr, 'episodic')
        assert hasattr(mgr, 'procedural')
        # 便捷 remember/recall
        mgr.remember('p1', '完成现场采样')
        hits = mgr.recall('现场采样')
        assert hits and hits[0].entity == 'p1'
    finally:
        config.get_settings.cache_clear()
