# -*- coding: utf-8 -*-
"""M7 法规适配器：国家法律法规数据库（flk.npc.gov.cn）公开 API。

API：GET /api/?type=flfg&searchType=title;accurate&sortTr=f_bbrq_s;desc
      &page=1&size=10[&searchValue=关键词]（返回 JSON，免登录）
字段：title 标题 / bbrq 公布日期 / sxrq 施行日期 / path 原文路径。
失败自动降级内置常用环保法规并标记 degraded。
"""
from __future__ import annotations

import urllib.parse
from typing import Any

from ..base import BaseAdapter

_API = "https://flk.npc.gov.cn/api/"

_OFFLINE_DEMO = [
    {"title": "中华人民共和国环境保护法", "bbrq": "2014-04-24", "sxrq": "2015-01-01", "url": ""},
    {"title": "中华人民共和国水污染防治法", "bbrq": "2017-06-27", "sxrq": "2018-01-01", "url": ""},
    {"title": "中华人民共和国大气污染防治法", "bbrq": "2015-08-29", "sxrq": "2016-01-01", "url": ""},
    {"title": "中华人民共和国固体废物污染环境防治法", "bbrq": "2020-04-29", "sxrq": "2020-09-01", "url": ""},
    {"title": "中华人民共和国环境影响评价法", "bbrq": "2018-12-29", "sxrq": "2018-12-29", "url": ""},
    {"title": "排污许可管理条例", "bbrq": "2021-01-24", "sxrq": "2021-03-01", "url": ""},
]


def _parse(data: Any) -> list[dict]:
    """宽容递归提取 {title, bbrq, sxrq} 法规记录。"""
    out: list[dict] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "title" in node:
                out.append({"title": str(node.get("title") or "").strip(),
                            "bbrq": str(node.get("bbrq") or "").strip(),
                            "sxrq": str(node.get("sxrq") or "").strip(),
                            "url": str(node.get("path") or "").strip()})
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return out


class LawNpcAdapter(BaseAdapter):
    source_id = "law_npc"
    name = "国家法律法规数据库"
    category = "law"
    cache_ttl = 86400

    def _fetch_remote(self, keyword: str = "", **params: Any) -> tuple[list[dict], str]:
        query = {"type": "flfg", "searchType": "title;accurate",
                 "sortTr": "f_bbrq_s;desc", "page": "1", "size": "10"}
        if keyword:
            query["searchValue"] = keyword
        url = _API + "?" + urllib.parse.urlencode(query)
        data = self._http_json(url)
        rows = _parse(data)
        if rows:
            return rows, "flk.npc.gov.cn"
        raise RuntimeError("无结果")

    def _fetch_offline(self, keyword: str = "", **params: Any) -> list[dict]:
        if not keyword:
            return _OFFLINE_DEMO
        hit = [r for r in _OFFLINE_DEMO if keyword in r["title"]]
        return hit or _OFFLINE_DEMO[:2]

    def search(self, keyword: str, **params: Any) -> list[dict]:
        return self._fetch_offline(keyword=keyword)
