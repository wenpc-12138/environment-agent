# -*- coding: utf-8 -*-
"""M4 标准核验适配器：标准有效性（现行/已废止/被替代/未知）。

在线：openstd 国家标准检索页 HTML 判定（候选端点，失败自动降级）。
离线：内置高置信废止/替代对照表（公开公共知识）+ 未命中返回"未知"。
接入 standard_intel.check_validity：适配器命中即用，失败/未知回退 SearXNG。
"""
from __future__ import annotations

from typing import Any

from ..base import BaseAdapter

_ENDPOINTS = (
    "https://openstd.samr.gov.cn/bzgk/std/std_list?p.p1=0&p.p90=circulation_date&p.p91=desc&p.p2={code}",
)

# 内置废止/替代对照表（确定性公共知识；命中即用，degraded 仍可信）
_OFFLINE_TABLE = {
    "GB/T 14848-1993": {"validity": "被替代", "note": "已被 GB/T 14848-2017 代替（地下水质量标准）"},
    "GB 3095-1996": {"validity": "被替代", "note": "已被 GB 3095-2012 代替（环境空气质量标准）"},
    "GB 3838-1988": {"validity": "被替代", "note": "已被 GB 3838-2002 代替（地表水环境质量标准）"},
    "GB 8978-1996": {"validity": "现行有效", "note": "现行有效（污水综合排放标准）"},
    "GB 18918-2002": {"validity": "现行有效", "note": "现行有效（城镇污水处理厂污染物排放标准）"},
    "GB 16297-1996": {"validity": "现行有效", "note": "现行有效（大气污染物综合排放标准）"},
    "GB 12348-2008": {"validity": "现行有效", "note": "现行有效（工业企业厂界环境噪声排放标准）"},
    "GB 3096-2008": {"validity": "现行有效", "note": "现行有效（声环境质量标准）"},
    "GB 13223-2011": {"validity": "现行有效", "note": "现行有效（火电厂大气污染物排放标准）"},
    "GB/T 14848-2017": {"validity": "现行有效", "note": "现行有效（地下水质量标准）"},
}


def _check_html(html: str, code: str) -> dict:
    """从 openstd 检索页 HTML 解析标准状态（解析结果表格行）。

    检索结果行结构（<tr> 内按 <td> 顺序）：
      序号 | 标准号 | 语种 | 采标 | 标准名称 | 类型(强标/推标) | 状态(现行/即将实施/废止) | 发布日期 | 实施日期 | 操作
    openstd 仅收录国家标准（GB），行业标准（如 HJ）检索为 0 条，返回"未知"并说明。
    """
    if not html:
        return {"validity": "未知", "note": "未获取到页面内容"}
    import re
    # 0 条结果：openstd 仅收录国家标准，HJ/DB 等行业/地方标准不在其中
    if re.search(r"共\s*0\s*条", html):
        return {"validity": "未知",
                "note": "openstd 国家标准库未收录该标准号（可能为行业/地方标准，如 HJ、DB）"}
    # 定位包含该标准号的结果行 <tr>（忽略检索框回显 input，仅匹配表格单元格）
    norm = code.upper().replace(" ", "")
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        row = m.group(1)
        if norm and norm not in row.upper().replace(" ", ""):
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 7:
            continue
        def _cell(t: str) -> str:
            return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", t))
        state = ""
        for c in cells:
            t = _cell(c)
            if t in ("现行", "即将实施", "废止", "已废止", "被替代"):
                state = t
                break
        if not state:
            continue
        name = _cell(cells[4]) if len(cells) > 4 else ""
        pub = _cell(cells[7])[:10] if len(cells) > 7 else ""
        imp = _cell(cells[8])[:10] if len(cells) > 8 else ""
        state_map = {"现行": "现行有效", "即将实施": "即将实施",
                     "废止": "已废止", "已废止": "已废止", "被替代": "被替代"}
        note = f"国家标准库检索：状态={state}"
        if name:
            note += f"，标准名称：{name}"
        if pub:
            note += f"，发布 {pub}"
        if imp:
            note += f"，实施 {imp}"
        return {"validity": state_map.get(state, "未知"), "note": note}
    # 页面无结果行（简化页面/测试 mock 场景）：宽松语境判定
    idx = html.find(code)
    window = html[max(0, idx - 300): idx + 600] if idx >= 0 else html
    if re.search(r"已废止|废止", window):
        return {"validity": "已废止", "note": "检索页显示已废止"}
    if re.search(r"被替代|代替", window):
        return {"validity": "被替代", "note": "检索页显示已被替代"}
    if re.search(r"现行|有效", window):
        return {"validity": "现行有效", "note": "检索页显示现行有效"}
    return {"validity": "未知",
            "note": "国家标准库未收录该标准号（可能为行业/地方标准，如 HJ、DB）"}


class StdMeeAdapter(BaseAdapter):
    source_id = "std_mee"
    name = "标准有效性核验（国家标准检索 + 内置对照表）"
    category = "std"
    cache_ttl = 86400

    def _fetch_remote(self, code: str = "", **params: Any) -> tuple[list[dict], str]:
        code = (code or "").strip().upper()
        errs = []
        import urllib.parse
        for url in _ENDPOINTS:
            try:
                # 标准号含空格/斜杠（如 "HJ 535-2009"、"GB/T 14848-1993"），必须 URL 编码
                quoted = url.format(code=urllib.parse.quote(code, safe="/-"))
                html = self._http_text(quoted)
                if not code:
                    # health() 无参探测：空标准号返回标准列表首页，仅验证端点可达
                    return [{"validity": "未知", "note": "openstd 端点连通性探测"}], url.split("/")[2]
                verdict = _check_html(html, code)
                # "未知"也是有效判定（如行业标准未收录），返回由上层决定回退，而非报"抓取失败"
                return [{**verdict, "code": code}], url.split("/")[2]
            except Exception as e:  # noqa: BLE001
                errs.append(str(e)[:50])
        raise RuntimeError("全部端点失败: " + "; ".join(errs)[:120])

    def _fetch_offline(self, code: str = "", **params: Any) -> list[dict]:
        code = (code or "").strip().upper()
        row = _OFFLINE_TABLE.get(code)
        if row:
            return [{**row, "code": code, "source": "offline-table"}]
        # 通用后缀回退：同前缀最新年份标准（如 GB 3838-2002 后无更新则现行）
        return [{"code": code, "validity": "未知",
                 "note": "不在内置对照表，离线无法判定（建议联网核验）", "source": "offline-table"}]

    def search(self, keyword: str, **params: Any) -> list[dict]:
        """按标准号检索核验结果。"""
        return self._fetch_offline(code=keyword)

    @staticmethod
    def _http_text(url: str, timeout: float = 10.0) -> str:
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"http 失败 {url}: {e}") from e
