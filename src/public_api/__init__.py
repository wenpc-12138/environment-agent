# -*- coding: utf-8 -*-
"""P6 国家公开 API 适配器（M1 骨架 + M2 空气质量）。

入口：from src.public_api import registry
调用：registry.register_default() 注册内置适配器，registry.fetch('air_cnemc', city='北京')。
"""
from __future__ import annotations

from .base import BaseAdapter, AdapterError
from . import registry

__all__ = ["BaseAdapter", "AdapterError", "registry"]


def init() -> None:
    """初始化内置适配器（幂等，应用启动或首次调用时执行）。"""
    registry.register_default()
