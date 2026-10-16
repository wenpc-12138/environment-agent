# -*- coding: utf-8 -*-
"""M3 水质适配器：国家水质自动综合监管平台（中国环境监测总站）。

公开入口（候选端点，任一可用即取数，失败自动降级离线样例并标记 degraded）：
- http://szzdjc.cnemc.cn:8070/GJZ/Business/Publish/GetSectionList  断面列表
- http://szzdjc.cnemc.cn:8070/GJZ/Business/Publish/GetSectionData  断面监测数据

数据字段：section（断面）/ river（河流）/ water_class（水质类别 Ⅰ-劣Ⅴ）/
ph / do（溶解氧）/ codmn（高锰酸盐指数）/ nh3n（氨氮）。
"""
from __future__ import annotations

from typing import Any

from ..base import BaseAdapter

_ENDPOINTS = (
    "http://szzdjc.cnemc.cn:8070/GJZ/Business/Publish/GetSectionList",
    "http://szzdjc.cnemc.cn:8070/GJZ/Business/Publish/GetSectionData",
)

# 离线降级演示样例（接口不可用时展示，明确非实时）
_OFFLINE_DEMO = [
    {"section": "武汉段", "river": "长江", "water_class": "Ⅲ类",
     "ph": 7.6, "do": 8.1, "codmn": 3.2, "nh3n": 0.42},
    {"section": "兰州段", "river": "黄河", "water_class": "Ⅱ类",
     "ph": 8.0, "do": 7.8, "codmn": 2.1, "nh3n": 0.28},
    {"section": "贡湖", "river": "太湖", "water_class": "Ⅳ类",
     "ph": 7.9, "do": 6.5, "codmn": 4.6, "nh3n": 0.88},
    {"section": "广州段", "river": "珠江", "water_class": "Ⅱ类",
     "ph": 7.3, "do": 7.2, "codmn": 2.4, "nh3n": 0.19},
]


def _pick(data: Any, section: str) -> list[dict]:
    """从接口响应提取断面水质记录（宽容递归解析）。"""
    rows: list[dict] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if any(k in node for k in ("sectionName", "section", "断面", "waterClass")):
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
        if section and not (section in rec["section"] or rec["section"] in section):
            continue
        out.append(rec)
    return out


def _normalize(r: dict) -> dict | None:
    name = str(r.get("sectionName") or r.get("section") or r.get("断面") or "").strip()
    if not name:
        return None
    river = str(r.get("riverName") or r.get("river") or r.get("河流") or "").strip()
    cls = str(r.get("waterClass") or r.get("water_class") or r.get("水质类别") or "").strip()
    return {
        "section": name, "river": river,
        "water_class": cls or "未知",
        "ph": r.get("ph") or r.get("PH"),
        "do": r.get("do") or r.get("DO") or r.get("溶解氧"),
        "codmn": r.get("codmn") or r.get("CODMn") or r.get("高锰酸盐指数"),
        "nh3n": r.get("nh3n") or r.get("NH3N") or r.get("氨氮"),
    }


class WaterCnemcAdapter(BaseAdapter):
    source_id = "water_cnemc"
    name = "全国水质自动监测（国家水质自动综合监管平台）"
    category = "water"
    cache_ttl = 600

    def _fetch_remote(self, section: str = "", **params: Any) -> tuple[list[dict], str]:
        errs = []
        for url in _ENDPOINTS:
            try:
                data = self._http_json(url)
                rows = _pick(data, section)
                if rows:
                    return rows, url.split("/")[2]
            except Exception as e:  # noqa: BLE001
                errs.append(str(e)[:50])
        raise RuntimeError("全部端点失败: " + "; ".join(errs)[:120])

    def _fetch_offline(self, section: str = "", **params: Any) -> list[dict]:
        if not section:
            return _OFFLINE_DEMO
        hit = [r for r in _OFFLINE_DEMO if section in r["section"] or r["section"] in section
               or section in r["river"]]
        return hit or _OFFLINE_DEMO[:1]

    def search(self, keyword: str, **params: Any) -> list[dict]:
        """按断面或河流名检索水质。"""
        return self._fetch_offline(section=keyword)
