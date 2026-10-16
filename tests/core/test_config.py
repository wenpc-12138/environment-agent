# -*- coding: utf-8 -*-
"""config 模块测试：环境变量优先级与路径解析。"""
from __future__ import annotations

from src.core import config


def test_env_override(monkeypatch) -> None:
    """环境变量 ECOAGENT_DB 优先级高于 db_path（绝对路径直接返回）。"""
    import os
    from pathlib import Path

    # 跨平台：POSIX 用 /tmp/...，Windows 用 C:/...（旧写法在 macOS/Linux 视为相对路径而失败）
    custom = Path('C:/tmp/custom.db') if os.name == 'nt' else Path('/tmp/custom.db')
    monkeypatch.setenv('ECOAGENT_DB', str(custom))
    config.get_settings.cache_clear()
    try:
        s = config.get_settings()
        assert s.db_file == custom
    finally:
        config.get_settings.cache_clear()


def test_defaults() -> None:
    """默认值合理性。"""
    s = config.get_settings()
    assert 0 < s.router_confidence < 1
    assert s.context_soft_budget < s.context_hard_budget
    assert s.kb_top_k > 0
