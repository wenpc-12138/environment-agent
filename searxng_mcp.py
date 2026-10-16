# -*- coding: utf-8 -*-
"""SearXNG MCP 客户端 - Agent 侧隔离调用层 (规避 AGPL-3.0)

- 通过标准 MCP 协议(streamable HTTP) 调用独立进程 searxng_mcp_server.py,
  SearXNG 与 Agent 主体完全进程隔离, 不构成 AGPL 派生产品。
- server 常驻子进程, 崩溃/退出自动重启; 全部同步接口, 内部 asyncio 桥接。
- 仅当 SearXNG 已启用时由 websearch.SearxngProvider 调用, 失败抛异常交由上层降级。
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_SCRIPT = os.path.join(BASE_DIR, "searxng_mcp_server.py")
DEFAULT_PORT = 8890
START_TIMEOUT = 10.0  # 等待 server 就绪秒数

_lock = threading.Lock()
_state = {"proc": None, "url": None, "last_err": ""}

MCP_UNAVAILABLE_MSG = "SearXNG MCP server 不可用"


def _server_url():
    """确保 MCP server 子进程运行, 返回 HTTP 入口 URL (线程安全, 幂等)"""
    with _lock:
        proc = _state["proc"]
        if proc is not None and proc.poll() is None:
            return _state["url"]
        port = DEFAULT_PORT
        url = f"http://127.0.0.1:{port}/mcp"
        # 已有端口被占用则直接复用(可能是外部启动的 server)
        if _port_open(port):
            _state["proc"] = None
            _state["url"] = url
            return url
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            proc = subprocess.Popen(
                [sys.executable, SERVER_SCRIPT, "--transport", "http", "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=BASE_DIR,
                creationflags=flags,
            )
            _state["proc"] = proc
            _state["url"] = url
        except Exception as e:  # pragma: no cover
            _state["last_err"] = str(e)
            raise RuntimeError(f"SearXNG MCP server 启动失败: {e}") from e
        deadline = time.time() + START_TIMEOUT
        while time.time() < deadline:
            if _port_open(port):
                return url
            if proc.poll() is not None:
                _state["last_err"] = f"进程退出 code={proc.returncode}"
                break
            time.sleep(0.15)
        raise RuntimeError(_state["last_err"] or "SearXNG MCP server 启动超时")


def _port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _call(tool, args, timeout=45.0):
    """调用 MCP 工具, 返回文本内容"""
    try:
        url = _server_url()
    except RuntimeError:
        raise
    if not url:
        raise RuntimeError(MCP_UNAVAILABLE_MSG)

    async def _run():
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await asyncio.wait_for(session.call_tool(tool, args), timeout=timeout)
                texts = [c.text for c in (res.content or []) if hasattr(c, "text")]
                return "\n".join(texts)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


def search(query, top_n=5, time_range=None, site_filter=None):
    """调用 MCP server.web_search, 返回 [{title,url,snippet,engine}]"""
    raw = _call("web_search", {
        "query": query,
        "top_n": top_n,
        "time_range": time_range or "",
        "site_filter": site_filter or "",
    })
    try:
        data = json.loads(raw)
    except Exception:
        raise RuntimeError(f"SearXNG MCP 返回非 JSON: {raw[:200]}")
    if not data.get("ok"):
        raise RuntimeError(data.get("error") or "SearXNG 搜索失败")
    return data.get("results", [])


def fetch_text(url, max_chars=6000):
    """调用 MCP server.web_fetch, 返回 {title, source, text} 或错误描述"""
    raw = _call("web_fetch", {"url": url, "max_chars": max_chars}, timeout=45.0)
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "text" in data:
            return data
    except Exception:
        pass
    if raw.startswith("ERR "):
        return {"error": raw[4:]}
    return {"text": raw}


def health():
    """MCP server 自身与 SearXNG 可用性检测"""
    try:
        raw = _call("health", {}, timeout=8.0)
        data = json.loads(raw)
        data["mcp_ok"] = True
        return data
    except Exception as e:
        return {"mcp_ok": False, "error": str(e)}


def stop():
    """停止常驻 server 子进程 (仅内部/测试用)"""
    with _lock:
        proc = _state["proc"]
        _state["proc"] = None
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
