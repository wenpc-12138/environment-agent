# -*- coding: utf-8 -*-
"""P6 公开 API 适配器注册表（M1 骨架）。

对齐 M02 ChannelAdapter 模式：注册/发现/健康检查，支持幂等注册与懒注册。
"""
from __future__ import annotations

import threading
from typing import Any

_registry: dict[str, Any] = {}
_lock = threading.Lock()
_health_cache: dict[str, tuple[float, dict]] = {}
_HEALTH_TTL = 60.0  # 健康探测结果缓存秒数，避免列表接口被网络超时拖垮


def register(adapter: Any) -> None:
    """注册适配器（幂等：同 source_id 覆盖）。"""
    with _lock:
        _registry[adapter.source_id] = adapter


def register_default() -> None:
    """注册内置适配器（导入即触发，懒加载防循环依赖）。"""
    try:
        from src.public_api.adapters.air_cnemc import AirCnemcAdapter
        register(AirCnemcAdapter())
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.public_api.adapters.water_cnemc import WaterCnemcAdapter
        register(WaterCnemcAdapter())
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.public_api.adapters.std_mee import StdMeeAdapter
        register(StdMeeAdapter())
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.public_api.adapters.permit_mee import PermitMeeAdapter
        register(PermitMeeAdapter())
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.public_api.adapters.weather import WeatherAdapter
        register(WeatherAdapter())
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.public_api.adapters.law_npc import LawNpcAdapter
        register(LawNpcAdapter())
    except Exception:  # noqa: BLE001
        pass


def get(source_id: str) -> Any | None:
    return _registry.get(source_id)


def _health_cached(a: Any) -> dict:
    """探测 + 缓存（TTL 内复用；异常返回 ok=False）。"""
    with _lock:
        hit = _health_cache.get(a.source_id)
        if hit and _now() - hit[0] < _HEALTH_TTL:
            return hit[1]
    try:
        h = a.health()
    except Exception:  # noqa: BLE001
        h = {"ok": False}
    with _lock:
        _health_cache[a.source_id] = (_now(), h)
    return h


def _health_peek(a: Any) -> dict:
    """快速视图：命中缓存直接返回；未命中返回 ok=None 并后台异步探测。"""
    with _lock:
        hit = _health_cache.get(a.source_id)
        if hit and _now() - hit[0] < _HEALTH_TTL:
            return hit[1]
    threading.Thread(target=_health_cached, args=(a,), daemon=True).start()
    return {"ok": None}


def _now() -> float:
    import time
    return time.time()


def list_sources(probe: bool = False) -> list[dict]:
    """全部源：{source_id, name, category, cache_ttl, ok}。
    probe=False（默认）：快速返回，未缓存源 ok=None 并后台异步探测，绝不阻塞。
    probe=True：同步真实探测（仅用于手动刷新场景）。"""
    out = []
    for a in _registry.values():
        h = _health_cached(a) if probe else _health_peek(a)
        out.append({"source_id": a.source_id, "name": a.name,
                    "category": a.category, "cache_ttl": a.cache_ttl, "ok": h.get("ok")})
    return out


def health_all() -> dict:
    """各源健康汇总（快速：缓存优先，未缓存后台探测）。"""
    total = len(_registry)
    ok = 0
    sources = {}
    for a in _registry.values():
        h = _health_peek(a)
        if h.get("ok"):
            ok += 1
        sources[a.source_id] = {"name": a.name, "category": a.category, **h}
    return {"ok": ok, "total": total, "sources": sources}


def fetch(source_id: str, **params: Any) -> dict:
    """按 source_id 取数；未知源或异常返回降级结果。"""
    a = _registry.get(source_id)
    if not a:
        return {"ok": False, "error": f"未知数据源: {source_id}", "degraded": True,
                "data": [], "source": "unknown", "cached": False, "ts": ""}
    try:
        return a.fetch(**params)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "degraded": True, "data": [],
                "source": source_id, "cached": False, "ts": ""}


def search(keyword: str, category: str = "", **params: Any) -> list[dict]:
    """跨源检索：按 category 过滤（空则全部）。"""
    out = []
    for a in _registry.values():
        if category and a.category != category:
            continue
        try:
            res = a.search(keyword, **params)
            if res:
                out.append({"source_id": a.source_id, "name": a.name, "items": res})
        except Exception:  # noqa: BLE001
            continue
    return out
