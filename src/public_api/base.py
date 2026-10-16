# -*- coding: utf-8 -*-
"""P6 公开 API 适配器基类（M1 骨架）。

统一接口约定：
- fetch(**params) -> AdapterResult：命中缓存(TTL)优先，接口失败自动降级离线数据(degraded=True)
- search(keyword, **params) -> list[dict]：检索式接口（子类实现）
- health() -> {ok, latency_ms, error?}：健康检查（联网探测，异常记不可用）
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from datetime import UTC, datetime
from typing import Any

HTTP_TIMEOUT = 10.0  # 秒


class AdapterError(Exception):
    pass


class BaseAdapter:
    source_id: str = ""
    name: str = ""
    category: str = ""     # air / water / std / permit / weather / law
    cache_ttl: int = 300   # 秒

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    # ---- 统一入口 ----
    def fetch(self, **params: Any) -> dict[str, Any]:
        """取数：缓存优先 -> 远程 -> 离线降级。"""
        key = repr(sorted(params.items()))
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < self.cache_ttl:
                data, source, ts = hit[1]
                return self._result(True, data, source, cached=True, ts=ts)
        try:
            data, source = self._fetch_remote(**params)
            ts = datetime.now(UTC).isoformat()
            with self._lock:
                self._cache[key] = (now, (data, source, ts))
            return self._result(True, data, source, cached=False, ts=ts)
        except Exception as e:  # noqa: BLE001
            data = self._fetch_offline(**params)
            return self._result(True, data, f"offline({self.source_id})",
                                cached=False, degraded=True,
                                ts=datetime.now(UTC).isoformat(), error=str(e))

    # ---- 子类实现 ----
    def _fetch_remote(self, **params: Any) -> tuple[Any, str]:
        raise NotImplementedError

    def _fetch_offline(self, **params: Any) -> Any:
        return []

    def search(self, keyword: str, **params: Any) -> list[dict]:
        return []

    # ---- 健康检查 ----
    def health(self) -> dict[str, Any]:
        t0 = time.monotonic()
        try:
            self._fetch_remote()
            return {"ok": True, "latency_ms": int((time.monotonic() - t0) * 1000)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "latency_ms": int((time.monotonic() - t0) * 1000),
                    "error": str(e)[:80]}

    # ---- 工具 ----
    def _result(self, ok: bool, data: Any, source: str, cached: bool,
                ts: str, degraded: bool = False, error: str = "") -> dict[str, Any]:
        return {"ok": ok, "data": data, "source": source, "cached": cached,
                "ts": ts, "degraded": degraded, "error": error,
                "source_id": self.source_id}

    @staticmethod
    def _http_json(url: str, timeout: float = HTTP_TIMEOUT) -> Any:
        """GET 取 JSON（urllib 零依赖）；异常统一抛 AdapterError。"""
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:  # noqa: BLE001
            raise AdapterError(f"http 失败 {url}: {e}") from e
        try:
            return json.loads(raw)
        except Exception as e:  # noqa: BLE001
            raise AdapterError(f"非 JSON 响应 {url}: {e}") from e
