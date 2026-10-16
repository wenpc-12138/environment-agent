# -*- coding: utf-8 -*-
"""M6 气象适配器：中国天气网公开接口（免登录）。

实况接口：https://d1.weather.com.cn/sk_2d/{城市代码}.html（返回 JS 变量 citySK={...}）。
城市代码 aid：北京 101010100、上海 101020100、广州 101280101、深圳 101280601 等。
编码：老接口 GBK，回退 UTF-8。
失败自动降级内置 4 城演示样例并标记 degraded。
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

from ..base import BaseAdapter

_LIVE = "https://d1.weather.com.cn/sk_2d/{code}.html"

_OFFLINE_DEMO = [
    {"city": "北京", "temp": 28, "weather": "晴", "wind": "东南风", "wind_level": "2级",
     "humidity": 45, "pressure": 1004},
    {"city": "上海", "temp": 30, "weather": "多云", "wind": "东风", "wind_level": "3级",
     "humidity": 60, "pressure": 1005},
    {"city": "广州", "temp": 33, "weather": "阵雨", "wind": "南风", "wind_level": "2级",
     "humidity": 78, "pressure": 1002},
    {"city": "深圳", "temp": 32, "weather": "多云", "wind": "南风", "wind_level": "2级",
     "humidity": 72, "pressure": 1003},
]


class WeatherAdapter(BaseAdapter):
    source_id = "weather"
    name = "中国天气网（实况气象）"
    category = "weather"
    cache_ttl = 600
    _CITIES = {
        "北京": "101010100", "上海": "101020100", "天津": "101030100", "重庆": "101040100",
        "广州": "101280101", "深圳": "101280601", "杭州": "101210101", "南京": "101190101",
        "武汉": "101200101", "成都": "101270101", "西安": "101110101", "沈阳": "101070101",
    }

    def _fetch_remote(self, city: str = "", **params: Any) -> tuple[list[dict], str]:
        city = (city or "").strip() or "北京"  # health() 无参探测时用默认城市验证端点
        code = self._CITIES.get(city, city)
        if not code:
            raise RuntimeError("缺少城市名")
        body = self._http_text(_LIVE.format(code=code))
        m = re.search(r"var\s+\w+\s*=\s*(\{.*\});?\s*$", body, re.S)
        if not m:
            raise RuntimeError("响应无数据")
        obj = json.loads(m.group(1))
        rec = {
            "city": str(obj.get("cityname") or city).strip(),
            "temp": obj.get("temp"), "weather": obj.get("weather"),
            "wind": obj.get("WD"), "wind_level": obj.get("WS"),
            "humidity": obj.get("SD"), "pressure": obj.get("qy"),
        }
        return [rec], "weather.com.cn"

    def _fetch_offline(self, city: str = "", **params: Any) -> list[dict]:
        if not city:
            return _OFFLINE_DEMO
        hit = [r for r in _OFFLINE_DEMO if city in r["city"]]
        return hit or _OFFLINE_DEMO[:1]

    def search(self, keyword: str, **params: Any) -> list[dict]:
        return self._fetch_offline(city=keyword)

    @staticmethod
    def _http_text(url: str, timeout: float = 10.0) -> str:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Referer": "https://www.weather.com.cn/",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        for enc in ("gbk", "utf-8"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="ignore")
