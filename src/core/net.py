# -*- coding: utf-8 -*-
"""本机（loopback）网络访问治理。

**问题**：当操作系统或环境变量配置了 HTTP 代理时，Python 的 urllib / requests
会把发往 `127.0.0.1` 的请求也交给代理转发，导致本机服务调用（SearXNG、OCR worker、
webhook 推送、启动就绪探针）出现超时或随机失败——表现为「同一个用例时好时坏」。

**方案**：
- `ensure_local_no_proxy()`：把 loopback 主机并入 `no_proxy`/`NO_PROXY`，
  对 requests 生效（其 `should_bypass_proxies` 每次请求读环境变量）；
- `no_proxy_opener()`：返回显式禁用代理的 urllib opener。macOS 上 urllib 的
  `proxy_bypass` 走的是系统配置、不认 `no_proxy`，因此本机请求必须显式禁用代理；
- `open_url()`：按目标地址自动决定是否禁用代理，供零散调用点使用。
"""
from __future__ import annotations

import ipaddress
import os
import urllib.parse
import urllib.request

# 视为“本机”的主机名（0.0.0.0 用于监听/自连场景）
LOCAL_HOSTS = ('127.0.0.1', 'localhost', '::1', '0.0.0.0')


def is_loopback_url(url: str) -> bool:
    """URL 是否指向本机（localhost / 127.0.0.0/8 / ::1 / 0.0.0.0）。"""
    try:
        host = (urllib.parse.urlsplit(url or '').hostname or '').strip().lower()
    except ValueError:
        return False
    if not host:
        return False
    if host in LOCAL_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def ensure_local_no_proxy() -> str:
    """把 loopback 主机并入 no_proxy / NO_PROXY（幂等，保留用户已有配置）。

    返回合并后的值。仅影响列表内的本机地址，外部请求的代理设置不受影响。
    """
    raw = os.environ.get('no_proxy') or os.environ.get('NO_PROXY') or ''
    hosts = [h.strip() for h in raw.split(',') if h.strip()]
    for h in LOCAL_HOSTS:
        if h not in hosts:
            hosts.append(h)
    value = ','.join(hosts)
    os.environ['no_proxy'] = value
    os.environ['NO_PROXY'] = value
    return value


def no_proxy_opener(*handlers):
    """构造禁用代理的 urllib opener（用于本机服务调用）。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), *handlers)


def open_url(req, timeout: float = 30, *handlers):
    """按目标地址自动选择是否走代理的 urlopen（本机地址一律直连）。"""
    url = getattr(req, 'full_url', None) or str(req)
    if is_loopback_url(url):
        opener = no_proxy_opener(*handlers)
    else:
        opener = urllib.request.build_opener(*handlers)
    return opener.open(req, timeout=timeout)


__all__ = ['LOCAL_HOSTS', 'is_loopback_url', 'ensure_local_no_proxy',
           'no_proxy_opener', 'open_url']
