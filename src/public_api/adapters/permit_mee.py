# -*- coding: utf-8 -*-
"""M5 排污许可适配器：全国排污许可证管理信息平台公开端。

WebShield 反爬处理（三段式）：
1. 首选：Playwright + 系统 Edge 无头模式执行 JS 挑战，获取会话后进入
   "许可信息公开"页提交查询表单，解析真实许可数据表格（live）。
2. 兜底：旧 urllib 会话流程（无 JS 执行，大概率被挑战拦截；失败即降级）。
3. 离线降级：内置演示样例 + 明确 blocked 提示，绝不伪造真实数据。

真实查询已验证可行（2026-08-09）：过挑战 3-5s + 查询 5-7s；
平台有频率限制，适配器 cache_ttl=3600 保证查询结果缓存 1 小时。
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..base import BaseAdapter

_HOME = "https://permit.mee.gov.cn/"
# 许可信息公开查询页（真实查询接口，Playwright 验证可用）
_QUERY_URL = ("https://permit.mee.gov.cn/perxxgkinfo/syssb/xkgg/"
              "xkgg!licenseInformation.action")
# 旧 urllib 候选（公开查询 action，基本被挑战拦截，仅兜底）
_ACTIONS = (
    "https://permit.mee.gov.cn/permitExt/outside/Publicity/searchList",
    "https://permit.mee.gov.cn/permitExt/defaults/default-index!getInformation.action",
)
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Playwright 查询互斥锁（平台有频率限制，避免并发撞车）
_pw_lock = threading.Lock()

# 离线降级演示样例（真实感结构；blocked 提示供人工核实）
_OFFLINE_DEMO = [
    {"company": "某污水处理有限公司", "permit_no": "91310000MA1K000000001V",
     "industry": "污水处理及其再生利用", "region": "上海市",
     "outlets": [{"name": "废水总排口", "pollutants": "COD、氨氮、总磷、悬浮物",
                  "limit": "COD 50 mg/L；氨氮 5 mg/L"}],
     "blocked": True,
     "note": "演示数据：排污许可公开端启用 WebShield 防护，请登录 permit.mee.gov.cn 人工查询"},
    {"company": "某热电有限责任公司", "permit_no": "91110000MA000000002V",
     "industry": "火力发电", "region": "北京市",
     "outlets": [{"name": "烟气排放口", "pollutants": "SO2、NOx、颗粒物",
                  "limit": "SO2 35 mg/m3；NOx 50 mg/m3"}],
     "blocked": True,
     "note": "演示数据：排污许可公开端启用 WebShield 防护，请登录 permit.mee.gov.cn 人工查询"},
]


def _is_webshield(status: int, body: str) -> bool:
    """挑战页/反爬拦截检测。"""
    if status in (403, 429, 503):
        return True
    low = (body or "").lower()
    if len(low) < 80:
        return True
    return any(k in low for k in ("wshield", "webshield", "访问异常", "安全验证",
                                  "javascript", "challenge"))


class PermitMeeAdapter(BaseAdapter):
    source_id = "permit_mee"
    name = "全国排污许可证信息查询（公开端）"
    category = "permit"
    cache_ttl = 3600

    def __init__(self) -> None:
        super().__init__()
        self._jar = urllib.request.HTTPCookieProcessor().cookiejar
        self._pw_available: bool | None = None  # None=未探测 True/False=结果

    # ==================== Playwright 真实查询（首选） ====================
    def _pw_query(self, company: str = "", permit_no: str = "",
                  timeout: float = 45.0) -> tuple[list[dict], str]:
        """过 WebShield 挑战 → 查询页填表单提交 → 解析真实许可表格。

        任何环节失败抛 RuntimeError，由上层降级。
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # noqa: BLE001
            self._pw_available = False
            raise RuntimeError("playwright 未安装，无法过 WebShield 挑战") from e
        self._pw_available = True

        with _pw_lock:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    channel="msedge", headless=True,
                    args=["--disable-blink-features=AutomationControlled"])
                try:
                    ctx = browser.new_context(user_agent=_UA, locale="zh-CN")
                    page = ctx.new_page()

                    # 1) 首页过挑战（重试 3 次）
                    for i in range(3):
                        try:
                            page.goto(_HOME, timeout=30000, wait_until="commit")
                            time.sleep(1)
                            try:
                                page.wait_for_load_state("domcontentloaded", timeout=15000)
                            except Exception:  # noqa: BLE001
                                pass
                            break
                        except Exception as e:  # noqa: BLE001
                            if i == 2:
                                raise RuntimeError(f"首页访问失败: {e}") from e
                            time.sleep(3)

                    # 2) 查询页
                    for i in range(2):
                        try:
                            page.goto(_QUERY_URL, timeout=30000, wait_until="commit")
                            time.sleep(1)
                            try:
                                page.wait_for_load_state("domcontentloaded", timeout=15000)
                            except Exception:  # noqa: BLE001
                                pass
                            break
                        except Exception as e:  # noqa: BLE001
                            if i == 1:
                                raise RuntimeError(f"查询页访问失败: {e}") from e
                            time.sleep(3)

                    # 3) 填表单：企业名 / 许可编号
                    if permit_no:
                        try:
                            page.locator("input[id*=licen], input[name*=licen]").first.fill(permit_no)
                        except Exception:  # noqa: BLE001
                            pass
                    if company:
                        try:
                            page.locator("#registerentername").fill(company)
                        except Exception:  # noqa: BLE001
                            pass

                    # 4) 提交表单并等待结果表格
                    page.evaluate("() => document.getElementById('mainForm').submit()")
                    rows: list[dict] = []
                    for _ in range(40):  # 最多等 20s
                        time.sleep(0.5)
                        try:
                            rows = page.evaluate(_PW_EXTRACT_JS)
                            if rows:
                                break
                        except Exception:  # noqa: BLE001
                            continue
                    if not rows:
                        raise RuntimeError("查询无结果（可能暂无数据或页面未加载）")
                    return rows, "permit.mee.gov.cn(live)"
                finally:
                    try:
                        browser.close()
                    except Exception:  # noqa: BLE001
                        pass

    # ==================== urllib 兜底（旧流程） ====================
    def _session_get(self, url: str, timeout: float = 15.0) -> tuple[int, str]:
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA,
            "Accept": "text/html,application/json,*/*",
            "Referer": _HOME,
        })
        try:
            with opener.open(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore") if e.fp else ""
            return e.code, body
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"http 失败 {url}: {e}") from e

    def _session_post(self, url: str, data: dict, timeout: float = 15.0) -> tuple[int, str]:
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))
        payload = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(url, data=payload, headers={
            "User-Agent": _UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": _HOME,
        })
        try:
            with opener.open(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore") if e.fp else ""
            return e.code, body
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"http 失败 {url}: {e}") from e

    # ==================== 取数 ====================
    def _fetch_remote(self, company: str = "", permit_no: str = "", **params: Any) -> tuple[list[dict], str]:
        # 1) Playwright 真实查询（首选）
        try:
            rows, src = self._pw_query(company=company, permit_no=permit_no)
            if rows:
                return rows, src
        except Exception as e:  # noqa: BLE001
            self._pw_error = str(e)
        # 2) urllib 旧流程兜底（无 JS 执行，大概率被挑战拦截）
        try:
            status, body = self._session_get(_HOME)
            if _is_webshield(status, body):
                status, body = self._session_get(_HOME)
            query = {"p_qxh": permit_no or "", "p_dwmc": company or "", "p_page": "1"}
            for url in _ACTIONS:
                try:
                    st, resp_body = self._session_post(url, query)
                    if _is_webshield(st, resp_body):
                        continue
                    rows = _parse(resp_body)
                    if rows:
                        return rows, url.split("/")[2]
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError("真实查询失败，已降级离线演示")

    def _fetch_offline(self, company: str = "", permit_no: str = "", **params: Any) -> list[dict]:
        """降级：内置演示样例 + WebShield 人工提示。"""
        if not company and not permit_no:
            return _OFFLINE_DEMO
        hit = [r for r in _OFFLINE_DEMO
               if (company and company in r["company"]) or (permit_no and permit_no == r["permit_no"])]
        return hit or [{"company": company or permit_no or "未知企业",
                        "permit_no": permit_no or "-", "industry": "", "region": "",
                        "outlets": [], "blocked": True,
                        "note": "未命中演示库：排污许可公开端启用 WebShield 防护，"
                                "请登录 permit.mee.gov.cn 人工查询"}]

    def search(self, keyword: str, **params: Any) -> list[dict]:
        try:
            rows, _src = self._pw_query(company=keyword)
            return rows
        except Exception:  # noqa: BLE001
            return self._fetch_offline(company=keyword)


# 查询页表格提取 JS：返回 {region, permit_no, company, industry, validity, issue_date, management}
_PW_EXTRACT_JS = """() => {
    const out = [];
    document.querySelectorAll('table tr').forEach((tr) => {
        const tds = tr.querySelectorAll('td');
        if (tds.length < 8) return;
        const txt = (i) => tds[i] ? (tds[i].innerText || '').trim().replace(/\\s+/g, ' ') : '';
        const company = txt(3);
        const permit = txt(2);
        if (!company || company === '暂无数据' || company === '单位名称') return;
        out.push({
            region: (txt(0) + ' ' + txt(1)).trim(),
            permit_no: permit,
            company: company,
            industry: txt(4),
            validity: txt(5),
            issue_date: txt(6),
            management: txt(7),
        });
    });
    return out;
}"""


def _parse(body: str) -> list[dict]:
    """宽容解析查询响应（JSON 或 HTML 表格）。"""
    body = (body or "").strip()
    if not body:
        return []
    # JSON 优先
    try:
        data = json.loads(body)
    except Exception:  # noqa: BLE001
        data = None
    if data is not None:
        rows = _walk_json(data)
        return rows
    # HTML 表格兜底：提取企业名/许可证号行
    import re
    rows = []
    for m in re.finditer(r'<td[^>]*>\s*([^<]{2,40})\s*</td>', body):
        v = m.group(1).strip()
        if re.search(r"[0-9]{2}[A-Z0-9]{8,}", v) or "有限公司" in v or "厂" in v:
            rows.append({"company": v[:40], "permit_no": "", "industry": "",
                         "region": "", "outlets": [], "note": "HTML 表格原始行"})
    return rows[:20]


def _walk_json(node: Any) -> list[dict]:
    out = []
    if isinstance(node, dict):
        if any(k in node for k in ("companyName", "dwmc", "公司名称", "permitNo")):
            rec = {
                "company": str(node.get("companyName") or node.get("dwmc") or node.get("公司名称") or ""),
                "permit_no": str(node.get("permitNo") or node.get("xkbh") or node.get("许可证编号") or ""),
                "industry": str(node.get("industry") or node.get("hy") or node.get("行业") or ""),
                "region": str(node.get("region") or node.get("area") or node.get("地区") or ""),
                "outlets": [],
            }
            if rec["company"] or rec["permit_no"]:
                out.append(rec)
            return out
        for v in node.values():
            out.extend(_walk_json(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(_walk_json(v))
    return out
