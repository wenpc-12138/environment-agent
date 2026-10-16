# -*- coding: utf-8 -*-
"""SearXNG MCP Server - 独立进程, 规避 AGPL-3.0 传染风险

核心思路: SearXNG(AGPL-3.0) 以独立服务形式运行, 本 Server 通过标准
MCP 协议(JSON-RPC over stdio / HTTP) 暴露搜索能力给 Agent 主进程。
- Agent 主体与 SearXNG 之间仅存进程/网络边界的数据交换,
  不构成 AGPL 派生产品, 主程序无需开放源代码。
- 本 Server 不包含任何 SearXNG 代码, 仅调用其 JSON API (format=json),
  因此自身同样不受 AGPL 传染。

工具:
- web_search(query, top_n, time_range, site_filter) -> JSON 字符串
- web_fetch(url, max_chars) -> 正文纯文本
- health() -> JSON 状态

传输: --transport stdio(默认) | http ; http 模式参数 --host/--port
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

import requests

try:
    from websearch import fetch_text  # 复用 Agent 正文抓取(非 AGPL 代码)
except Exception:  # pragma: no cover
    fetch_text = None

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_SX_TIME = {"d": "day", "w": "week", "m": "month", "y": "year"}
_CONF = {"base_url": "http://localhost:8888", "timeout": 30, "language": "zh-CN", "max_results": 10}


def _load_conf():
    """加载 SearXNG 配置: 环境变量 SEARXNG_MCP_BASE_URL > data/searxng.json > 默认值"""
    url = os.environ.get("SEARXNG_MCP_BASE_URL")
    if url:
        _CONF["base_url"] = url.strip().rstrip("/")
        return
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "searxng.json")
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
        if cfg.get("base_url"):
            _CONF["base_url"] = cfg["base_url"].strip().rstrip("/")
        for k in ("timeout", "language", "max_results"):
            if k in cfg and cfg[k] not in (None, ""):
                _CONF[k] = cfg[k]
    except Exception:
        pass


def _sx_search(query, top_n, time_range):
    """调用 SearXNG JSON API, 返回统一格式结果(不含 stamp 字段)"""
    _load_conf()  # 每次调用刷新, 支持 launcher 自动更换端口后仍指向最新实例
    params = {
        "q": query,
        "format": "json",
        "language": _CONF["language"],
        "safesearch": 0,
        "pageno": 1,
    }
    if time_range in _SX_TIME:
        params["time_range"] = _SX_TIME[time_range]
    resp = requests.get(
        f"{_CONF['base_url']}/search",
        params=params,
        headers={"User-Agent": UA, "Accept": "application/json"},
        timeout=_CONF["timeout"],
    )
    if resp.status_code != 200:
        raise RuntimeError(f"SearXNG HTTP {resp.status_code}")
    data = resp.json()
    results = []
    for item in data.get("results", [])[:top_n]:
        url = item.get("url") or ""
        if not url:
            continue
        results.append({
            "title": item.get("title") or "",
            "url": url,
            "snippet": item.get("content") or "",
            "engine": item.get("engine") or "",
        })
    return results


def _sx_health():
    _load_conf()  # 每次调用刷新, 感知端口变化
    try:
        r = requests.get(f"{_CONF['base_url']}/healthz", headers={"User-Agent": UA}, timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_stdio():
    """stdio 传输模式: 供 Agent 子进程启动, 每行一个 JSON-RPC 消息"""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("searxng")

    @mcp.tool()
    def web_search(query: str, top_n: int = 5, time_range: str = "", site_filter: str = "") -> str:
        """调用 SearXNG 元搜索(AGPL 服务以独立进程隔离)。返回 JSON: {results:[{title,url,snippet,engine}]}"""
        q = query
        if site_filter:
            s = site_filter.strip()
            if s and f"site:{s}" not in q:
                q = f"{q} site:{s}"
        try:
            results = _sx_search(q, int(top_n), time_range or None)
            return json.dumps({"ok": True, "results": results}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    def web_fetch(url: str, max_chars: int = 6000) -> str:
        """抓取网页正文纯文本(标题/来源/正文)。失败返回错误描述"""
        if not fetch_text:
            return "ERR websearch.fetch_text 不可用"
        try:
            out = fetch_text(url, max_chars=max_chars)
            if isinstance(out, dict):
                return json.dumps(out, ensure_ascii=False)
            return str(out)
        except Exception as e:
            return f"ERR {e}"

    @mcp.tool()
    def health() -> str:
        """SearXNG 可用性检测。返回 JSON: {ok, base_url, time}"""
        return json.dumps({
            "ok": _sx_health(),
            "base_url": _CONF["base_url"],
            "time": _now(),
        }, ensure_ascii=False)

    mcp.run(transport="stdio")


def run_http(host, port):
    """HTTP 传输模式: 常驻服务, Agent 通过 streamable HTTP 连接"""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("searxng", host=host, port=port)

    @mcp.tool()
    def web_search(query: str, top_n: int = 5, time_range: str = "", site_filter: str = "") -> str:
        q = query
        if site_filter:
            s = site_filter.strip()
            if s and f"site:{s}" not in q:
                q = f"{q} site:{s}"
        try:
            results = _sx_search(q, int(top_n), time_range or None)
            return json.dumps({"ok": True, "results": results}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    def web_fetch(url: str, max_chars: int = 6000) -> str:
        if not fetch_text:
            return "ERR websearch.fetch_text 不可用"
        try:
            out = fetch_text(url, max_chars=max_chars)
            if isinstance(out, dict):
                return json.dumps(out, ensure_ascii=False)
            return str(out)
        except Exception as e:
            return f"ERR {e}"

    @mcp.tool()
    def health() -> str:
        return json.dumps({
            "ok": _sx_health(),
            "base_url": _CONF["base_url"],
            "time": _now(),
        }, ensure_ascii=False)

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    _load_conf()
    ap = argparse.ArgumentParser(description="SearXNG MCP Server (AGPL 隔离)")
    ap.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8890)
    args = ap.parse_args()
    if args.transport == "http":
        run_http(args.host, args.port)
    else:
        run_stdio()
