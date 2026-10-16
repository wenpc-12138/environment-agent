# -*- coding: utf-8 -*-
"""P6 M4：standard_intel 标准核验接入公开 API（在线优先 / 回退 SearXNG）。"""
from __future__ import annotations

import standard_intel as si


class TestCurrencyCheckOnline:
    def test_public_api_hit(self, monkeypatch):
        """适配器命中（含离线对照表）→ 采用 public-api 结果。"""
        monkeypatch.setattr(
            "src.public_api.registry.fetch",
            lambda source_id, **kw: {"ok": True, "data": [
                {"code": "GB/T 14848-1993", "validity": "被替代",
                 "note": "已被 GB/T 14848-2017 代替"}]},
        )
        r = si._currency_check_online("GB/T 14848-1993")
        assert r["validity"] == "被替代"
        assert r["method"].startswith("public-api")

    def test_unknown_falls_back(self, monkeypatch):
        """适配器返回"未知" → 回退 SearXNG。"""
        monkeypatch.setattr(
            "src.public_api.registry.fetch",
            lambda source_id, **kw: {"ok": True, "data": [
                {"code": "GB 12345", "validity": "未知"}]},
        )
        fake = {"validity": "现行有效", "note": "SearXNG 判定",
                "evidence": [], "method": "searxng"}
        monkeypatch.setattr(si, "_currency_check", lambda *a, **k: fake)
        r = si._currency_check_online("GB 12345")
        assert r["validity"] == "现行有效"
        assert r["method"] == "searxng"

    def test_adapter_error_falls_back(self, monkeypatch):
        """适配器异常 → 回退 SearXNG。"""
        def boom(*a, **kw):
            raise RuntimeError("registry unavailable")

        monkeypatch.setattr("src.public_api.registry.fetch", boom)
        fake = {"validity": "未知(未联网)", "note": "offline", "method": "searxng"}
        monkeypatch.setattr(si, "_currency_check", lambda *a, **k: fake)
        r = si._currency_check_online("GB 3838-2002")
        assert r["method"] == "searxng"

    def test_offline_table_trusted(self, monkeypatch):
        """离线对照表命中（degraded=True）同样可信采用。"""
        monkeypatch.setattr(
            "src.public_api.registry.fetch",
            lambda source_id, **kw: {"ok": True, "degraded": True, "data": [
                {"code": "GB 3095-1996", "validity": "被替代",
                 "note": "已被 GB 3095-2012 代替"}]},
        )
        r = si._currency_check_online("GB 3095-1996")
        assert r["validity"] == "被替代"
        assert "(offline)" in r["method"]
