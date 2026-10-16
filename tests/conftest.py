# -*- coding: utf-8 -*-
"""pytest 全局配置：项目根加入 sys.path，保证 import src.* 可用。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _cleanup_db_conn():
    """每个用例结束后关闭线程本地 db 连接，防止残留连接串库（M01）。"""
    yield
    from src.core import db

    db.close_db()
