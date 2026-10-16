# -*- coding: utf-8 -*-
"""P6 M1 骨架：注册表 / 统一入口 / 缓存 / 降级。"""
from __future__ import annotations

import json

import pytest

from src.public_api import base, registry
from src.public_api.adapters.air_cnemc import AirCnemcAdapter
from src.public_api.adapters.water_cnemc import WaterCnemcAdapter
from src.public_api.adapters.std_mee import StdMeeAdapter, _check_html
from src.public_api.adapters.permit_mee import PermitMeeAdapter, _parse, _is_webshield
from src.public_api.adapters.weather import WeatherAdapter
from src.public_api.adapters.law_npc import LawNpcAdapter, _parse as law_parse

MOCK_RESP = {
    "timePoint": "2026-08-07 10:00",
    "cityData": [
        {"city": "北京", "aqi": 55, "level": "良", "primary": "PM2.5",
         "pm2_5": 38, "pm10": 60, "so2": 6, "no2": 22, "o3": 90, "co": 0.5},
        {"city": "上海", "aqi": 48, "level": "优", "primary": "-",
         "pm2_5": 30, "pm10": 48, "so2": 7, "no2": 28, "o3": 82, "co": 0.6},
    ],
}


@pytest.fixture()
def clean_registry():
    registry._registry.clear()
    yield
    registry._registry.clear()


class TestRegistry:
    def test_register_get(self, clean_registry):
        a = AirCnemcAdapter()
        registry.register(a)
        assert registry.get("air_cnemc") is a
        assert registry.list_sources()[0]["source_id"] == "air_cnemc"

    def test_register_idempotent(self, clean_registry):
        registry.register(AirCnemcAdapter())
        registry.register(AirCnemcAdapter())
        assert len(registry._registry) == 1

    def test_fetch_unknown_source(self, clean_registry):
        r = registry.fetch("nope")
        assert r["ok"] is False and r["degraded"] is True


class TestAirAdapter:
    def test_remote_ok(self, monkeypatch, clean_registry):
        monkeypatch.setattr(base.BaseAdapter, "_http_json",
                            staticmethod(lambda *a, **k: MOCK_RESP))
        a = AirCnemcAdapter()
        registry.register(a)
        r = registry.fetch("air_cnemc", city="北京")
        assert r["ok"] is True and r["degraded"] is False
        assert r["source"] != "offline"
        assert r["data"][0]["city"] == "北京"
        assert r["data"][0]["aqi"] == 55

    def test_cache_hit(self, monkeypatch, clean_registry):
        calls = {"n": 0}
        real = base.BaseAdapter._http_json

        def fake(*a, **k):
            calls["n"] += 1
            return MOCK_RESP

        monkeypatch.setattr(base.BaseAdapter, "_http_json", staticmethod(fake))
        a = AirCnemcAdapter()
        registry.register(a)
        registry.fetch("air_cnemc", city="北京")
        r2 = registry.fetch("air_cnemc", city="北京")
        assert r2["cached"] is True
        assert calls["n"] == 1  # 第二次命中缓存不再联网

    def test_offline_degrade(self, monkeypatch, clean_registry):
        def boom(*a, **k):
            raise base.AdapterError("connection refused")

        monkeypatch.setattr(base.BaseAdapter, "_http_json", staticmethod(boom))
        a = AirCnemcAdapter()
        registry.register(a)
        r = registry.fetch("air_cnemc", city="北京")
        assert r["ok"] is True and r["degraded"] is True
        assert r["source"].startswith("offline")
        assert r["data"] and r["data"][0]["city"] == "北京"

    def test_health_fail(self, monkeypatch, clean_registry):
        def boom(*a, **k):
            raise base.AdapterError("timeout")

        monkeypatch.setattr(base.BaseAdapter, "_http_json", staticmethod(boom))
        a = AirCnemcAdapter()
        h = a.health()
        assert h["ok"] is False

    def test_search_offline(self, clean_registry):
        a = AirCnemcAdapter()
        items = a.search("上海")
        assert items and items[0]["city"] == "上海"


class TestBridge:
    def test_v2_bridge_fetch(self, monkeypatch):
        import v2_bridge
        monkeypatch.setattr(base.BaseAdapter, "_http_json",
                            staticmethod(lambda *a, **k: MOCK_RESP))
        r = v2_bridge.publicapi_fetch("air_cnemc", city="上海")
        assert r["ok"] is True and r["data"][0]["city"] == "上海"
        srcs = v2_bridge.publicapi_sources()
        assert any(s["source_id"] == "air_cnemc" for s in srcs)


WATER_RESP = {
    "data": [
        {"sectionName": "武汉段", "riverName": "长江", "waterClass": "Ⅲ类",
         "ph": 7.6, "do": 8.1, "codmn": 3.2, "nh3n": 0.42},
        {"sectionName": "兰州段", "riverName": "黄河", "waterClass": "Ⅱ类",
         "ph": 8.0, "do": 7.8, "codmn": 2.1, "nh3n": 0.28},
    ]
}


class TestWaterAdapter:
    def test_remote_ok(self, monkeypatch, clean_registry):
        monkeypatch.setattr(base.BaseAdapter, "_http_json",
                            staticmethod(lambda *a, **k: WATER_RESP))
        a = WaterCnemcAdapter()
        registry.register(a)
        r = registry.fetch("water_cnemc", section="武汉")
        assert r["ok"] is True and r["degraded"] is False
        assert r["data"][0]["section"] == "武汉段"
        assert r["data"][0]["water_class"] == "Ⅲ类"

    def test_section_filter(self, monkeypatch, clean_registry):
        monkeypatch.setattr(base.BaseAdapter, "_http_json",
                            staticmethod(lambda *a, **k: WATER_RESP))
        a = WaterCnemcAdapter()
        registry.register(a)
        r = registry.fetch("water_cnemc", section="兰州")
        assert len(r["data"]) == 1 and r["data"][0]["section"] == "兰州段"

    def test_offline_degrade(self, monkeypatch, clean_registry):
        def boom(*a, **k):
            raise base.AdapterError("timeout")

        monkeypatch.setattr(base.BaseAdapter, "_http_json", staticmethod(boom))
        a = WaterCnemcAdapter()
        registry.register(a)
        r = registry.fetch("water_cnemc", section="太湖")
        assert r["ok"] is True and r["degraded"] is True
        assert r["data"][0]["river"] == "太湖"

    def test_search_by_river(self, clean_registry):
        items = WaterCnemcAdapter().search("长江")
        assert items and items[0]["river"] == "长江"

    def test_default_registered(self, clean_registry):
        import src.public_api as papi
        papi.registry._registry.clear()
        papi.registry.register_default()
        ids = {a.source_id for a in papi.registry._registry.values()}
        assert {"air_cnemc", "water_cnemc", "std_mee"} <= ids


class TestStdMee:
    def test_offline_table_hit(self, monkeypatch, clean_registry):
        def boom(*a, **k):
            raise base.AdapterError("timeout")

        # std_mee 使用 _http_text（openstd 为 HTML 页面），须 patch 正确方法
        monkeypatch.setattr(StdMeeAdapter, "_http_text", staticmethod(boom))
        a = StdMeeAdapter()
        registry.register(a)
        r = registry.fetch("std_mee", code="GB/T 14848-1993")
        assert r["degraded"] is True
        assert r["data"][0]["validity"] == "被替代"
        assert "14848-2017" in r["data"][0]["note"]

    def test_offline_table_miss(self, monkeypatch, clean_registry):
        def boom(*a, **k):
            raise base.AdapterError("timeout")

        monkeypatch.setattr(StdMeeAdapter, "_http_text",
                            staticmethod(boom))
        registry.register(StdMeeAdapter())
        r = registry.fetch("std_mee", code="GB 99999-2099")
        assert r["data"][0]["validity"] == "未知"

    def test_remote_html_repeal(self, monkeypatch, clean_registry):
        html = ("<html>... GB/T 14848-1993 该标准已废止，由 GB/T 14848-2017 代替 ...</html>")
        monkeypatch.setattr(StdMeeAdapter, "_http_text",
                            staticmethod(lambda *a, **k: html))
        a = StdMeeAdapter()
        registry.register(a)
        r = registry.fetch("std_mee", code="GB/T 14848-1993")
        assert r["degraded"] is False
        assert r["data"][0]["validity"] == "已废止"

    def test_check_html_direct(self):
        assert _check_html("GB 3838-2002 现行有效", "GB 3838-2002")["validity"] == "现行有效"
        assert _check_html("已废止", "GB 3095-1996")["validity"] == "已废止"
        assert _check_html("无相关内容", "GB 12345")["validity"] == "未知"

    def test_search(self, clean_registry):
        items = StdMeeAdapter().search("GB 18918-2002")
        assert items[0]["validity"] == "现行有效"


PERMIT_JSON = json.dumps({"list": [
    {"companyName": "某某环境科技有限公司", "permitNo": "91310000MA1K000000001V",
     "industry": "环境治理", "region": "上海市"},
]}, ensure_ascii=False)

ENTRY_PAGE = ("<html><body>全国排污许可证管理信息平台-公开端 排污单位许可信息公开查询入口页面，"
              "支持按企业名称、许可证编号检索排污许可信息。normal page content</body></html>")


class TestPermitMee:
    def test_remote_json_ok(self, monkeypatch, clean_registry):
        a = PermitMeeAdapter()
        registry.register(a)
        monkeypatch.setattr(PermitMeeAdapter, "_session_get",
                            lambda self, url, timeout=15: (200, ENTRY_PAGE))
        monkeypatch.setattr(PermitMeeAdapter, "_session_post",
                            lambda self, url, data, timeout=15: (200, PERMIT_JSON))
        r = registry.fetch("permit_mee", company="某某")
        assert r["ok"] is True and r["degraded"] is False
        assert r["data"][0]["company"] == "某某环境科技有限公司"

    def test_webshield_degrades(self, monkeypatch, clean_registry):
        a = PermitMeeAdapter()
        registry.register(a)
        monkeypatch.setattr(PermitMeeAdapter, "_session_get",
                            lambda self, url, timeout=15: (403, "<script>wshield 挑战</script>"))
        monkeypatch.setattr(PermitMeeAdapter, "_session_post",
                            lambda self, url, data, timeout=15: (403, "blocked"))
        r = registry.fetch("permit_mee", company="某某")
        assert r["ok"] is True and r["degraded"] is True
        assert r["data"][0]["blocked"] is True
        assert "WebShield" in r["data"][0]["note"]

    def test_offline_http_error(self, monkeypatch, clean_registry):
        a = PermitMeeAdapter()
        registry.register(a)

        def boom(self, url, timeout=15):
            raise RuntimeError("dns fail")

        monkeypatch.setattr(PermitMeeAdapter, "_session_get", boom)
        r = registry.fetch("permit_mee")
        assert r["degraded"] is True
        assert len(r["data"]) >= 2

    def test_offline_by_company(self, monkeypatch, clean_registry):
        a = PermitMeeAdapter()
        registry.register(a)

        def boom(self, url, timeout=15):
            raise RuntimeError("dns fail")

        monkeypatch.setattr(PermitMeeAdapter, "_session_get", boom)
        r = registry.fetch("permit_mee", company="热电")
        assert r["data"][0]["company"].find("热电") >= 0

    def test_parse_json(self):
        rows = _parse(PERMIT_JSON)
        assert rows[0]["permit_no"].startswith("9131")

    def test_parse_html_rows(self):
        html = "<table><tr><td>某某环保有限公司</td><td>91320000MA0000001V</td></tr></table>"
        rows = _parse(html)
        assert rows and rows[0]["company"] == "某某环保有限公司"

    def test_is_webshield(self):
        assert _is_webshield(403, "blocked") is True
        assert _is_webshield(200, "wshield verify") is True
        assert _is_webshield(200, "x") is True
        assert _is_webshield(200, ENTRY_PAGE) is False


WEATHER_JS = ('var citySK = {"cityname":"北京","temp":"28","weather":"晴",'
              '"WD":"东南风","WS":"2级","SD":"45%","qy":"1004"};')


class TestWeather:
    def test_remote_ok(self, monkeypatch, clean_registry):
        monkeypatch.setattr(WeatherAdapter, "_http_text",
                            staticmethod(lambda *a, **k: WEATHER_JS))
        a = WeatherAdapter()
        registry.register(a)
        r = registry.fetch("weather", city="北京")
        assert r["ok"] is True and r["degraded"] is False
        assert r["data"][0]["temp"] == "28"
        assert r["data"][0]["weather"] == "晴"

    def test_offline(self, monkeypatch, clean_registry):
        def boom(*a, **k):
            raise RuntimeError("dns fail")

        monkeypatch.setattr(WeatherAdapter, "_http_text", staticmethod(boom))
        a = WeatherAdapter()
        registry.register(a)
        r = registry.fetch("weather", city="上海")
        assert r["degraded"] is True
        assert r["data"][0]["city"] == "上海"

    def test_city_codes(self):
        assert WeatherAdapter._CITIES["北京"] == "101010100"
        assert WeatherAdapter._CITIES["广州"] == "101280101"

    def test_search(self, clean_registry):
        items = WeatherAdapter().search("广州")
        assert items[0]["city"] == "广州"


LAW_JSON = {"result": {"data": [
    {"title": "中华人民共和国环境保护法", "bbrq": "2014-04-24",
     "sxrq": "2015-01-01", "path": "/flfg/lffg/201404/t20140424_216515.html"},
]}}


class TestLaw:
    def test_remote_ok(self, monkeypatch, clean_registry):
        monkeypatch.setattr(base.BaseAdapter, "_http_json",
                            staticmethod(lambda *a, **k: LAW_JSON))
        a = LawNpcAdapter()
        registry.register(a)
        r = registry.fetch("law_npc", keyword="环境保护法")
        assert r["ok"] is True and r["degraded"] is False
        assert "环境保护法" in r["data"][0]["title"]
        assert r["data"][0]["bbrq"] == "2014-04-24"

    def test_offline(self, monkeypatch, clean_registry):
        def boom(*a, **k):
            raise base.AdapterError("timeout")

        monkeypatch.setattr(base.BaseAdapter, "_http_json", staticmethod(boom))
        a = LawNpcAdapter()
        registry.register(a)
        r = registry.fetch("law_npc", keyword="排污许可")
        assert r["degraded"] is True
        assert any("排污许可" in x["title"] for x in r["data"])

    def test_parse(self):
        rows = law_parse(LAW_JSON)
        assert rows and rows[0]["title"].startswith("中华人民共和国")

    def test_default_registered_all(self, clean_registry):
        import src.public_api as papi
        papi.registry._registry.clear()
        papi.registry.register_default()
        ids = {a.source_id for a in papi.registry._registry.values()}
        assert ids >= {"air_cnemc", "water_cnemc", "std_mee",
                       "permit_mee", "weather", "law_npc"}
