# -*- coding: utf-8 -*-
"""M2 空气质量适配器：中国环境监测总站空气质量实时发布。

候选公开接口（任一可用即取数，失败自动降级离线样例并标记 degraded）：
- https://air.cnemc.cn:18007/CityAirQuality/GetAQIData
- https://air.cnemc.cn/CityAirQuality/GetAQIData

数据字段：aqi / level（等级）/ primary（首要污染物）/ pm25 / pm10 / so2 / no2 / o3 / co。
"""
from __future__ import annotations

import re
from typing import Any

from ..base import BaseAdapter

_ENDPOINTS = (
    "https://air.cnemc.cn:18007/CityAirQuality/GetAQIData",
    "https://air.cnemc.cn/CityAirQuality/GetAQIData",
)

# 离线降级演示样例（接口不可用时展示，明确非实时）
_OFFLINE_DEMO = [
    {"city": "北京", "aqi": 55, "level": "良", "primary": "PM2.5",
     "pm25": 38, "pm10": 60, "so2": 6, "no2": 22, "o3": 90, "co": 0.5},
    {"city": "上海", "aqi": 48, "level": "优", "primary": "-",
     "pm25": 30, "pm10": 48, "so2": 7, "no2": 28, "o3": 82, "co": 0.6},
    {"city": "广州", "aqi": 42, "level": "优", "primary": "-",
     "pm25": 26, "pm10": 40, "so2": 8, "no2": 30, "o3": 95, "co": 0.7},
    {"city": "深圳", "aqi": 39, "level": "优", "primary": "-",
     "pm25": 24, "pm10": 36, "so2": 7, "no2": 24, "o3": 88, "co": 0.6},
]

_LEVEL_MAP = {"优": "优", "良": "良", "轻度污染": "轻度污染", "中度污染": "中度污染",
              "重度污染": "重度污染", "严重污染": "严重污染"}


def _pick(data: Any, city: str) -> list[dict]:
    """从接口响应中提取城市 AQI 记录（宽容解析）。"""
    rows: list[dict] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "aqi" in node or "AQI" in node:
                rows.append(node)
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    out: list[dict] = []
    for r in rows:
        rec = _normalize(r)
        if not rec:
            continue
        if city and not (city in rec["city"] or rec["city"] in city):
            continue
        out.append(rec)
    return out or (_normalize_unknown(data) if not city else [])


def _normalize(r: dict) -> dict | None:
    name = str(r.get("city") or r.get("cityName") or r.get("area") or "").strip()
    if not name:
        return None
    aqi = r.get("aqi")
    if aqi is None:
        aqi = r.get("AQI")
    try:
        aqi = int(float(aqi))
    except (TypeError, ValueError):
        return None
    return {
        "city": name, "aqi": aqi,
        "level": str(r.get("level") or r.get("quality") or "").strip() or "未知",
        "primary": str(r.get("primary") or r.get("primaryPollutant") or "-").strip(),
        "pm25": r.get("pm2_5") if r.get("pm2_5") is not None else r.get("pm25"),
        "pm10": r.get("pm10"),
        "so2": r.get("so2"), "no2": r.get("no2"),
        "o3": r.get("o3"), "co": r.get("co"),
    }


def _normalize_unknown(data: Any) -> list[dict]:
    """响应无 aqi 键时兜底：返回原始结构摘要（防止解析失败误判空数据）。"""
    return [{"city": "未知", "aqi": None, "level": "", "primary": "",
             "raw": str(data)[:200]}]


class AirCnemcAdapter(BaseAdapter):
    source_id = "air_cnemc"
    name = "全国空气质量实时发布（中国环境监测总站）"
    category = "air"
    cache_ttl = 300

    def _fetch_remote(self, city: str = "", **params: Any) -> tuple[list[dict], str]:
        errs = []
        for url in _ENDPOINTS:
            try:
                data = self._http_json(url)
                rows = _pick(data, city)
                if rows:
                    return rows, url.split("/")[2]
            except Exception as e:  # noqa: BLE001
                errs.append(str(e)[:50])
        raise RuntimeError("全部端点失败: " + "; ".join(errs)[:120])

    def _fetch_offline(self, city: str = "", **params: Any) -> list[dict]:
        """离线降级：内置演示样例（degraded 由基类标记）。"""
        if not city:
            return _OFFLINE_DEMO
        hit = [r for r in _OFFLINE_DEMO if city in r["city"] or r["city"] in city]
        return hit or _OFFLINE_DEMO[:1]

    def search(self, keyword: str, **params: Any) -> list[dict]:
        """按城市名检索空气质量。"""
        return self._fetch_offline(city=keyword)
