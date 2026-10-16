# -*- coding: utf-8 -*-
"""生态Agent - 联网搜索 (Search Provider 架构)

S2-M2 迁移（2026-08-20）：自根目录 `websearch.py` 原样迁入；
根文件已转兼容重导出（`from src.tools.websearch import *`）。

统一 SearchResult 格式: {title, url, snippet, source, retrieved_at}
- SearXNG(自托管元搜索, 唯一联网搜索引擎, 零费用/私有化/可审计); 已移除搜狗/360/Bing 爬虫兜底
- SearXNG 默认经 MCP Server 独立进程调用(规避 AGPL-3.0 传染风险), mcp=False 时直连 JSON API
- SearXNG 配置: data/searxng.json (环境变量可覆盖 SEARXNG_URL/SEARXNG_ENABLED/SEARXNG_MCP/...)
- 自动健康检测 /healthz(60s 缓存), 检测通过才走 SearXNG, 失败直接返回空结果
- 支持 site: 站点限定 与 time_range 时间过滤
- 结果缓存 (search_cache 表, 默认 24h)
- fetch_text 抓取正文: 多级兜底链 requests 直抓 -> curl_cffi 指纹模拟(403 反爬)
  -> 百度百科开放 API(baike.baidu.com 专治) -> trafilatura 本地正文提取 -> Jina Reader
  (r.jina.ai 国内网络常不可达, 仅作最后兜底; 见 github.com/jina-ai/reader#1238)
"""
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse, parse_qs, quote as urlquote

import searxng_mcp  # Agent 侧 MCP 客户端(独立进程隔离调用 SearXNG)
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

try:
    from src.core import db_v12 as db
except Exception:  # 无数据库环境降级为无缓存
    db = None

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_search_lock = threading.Lock()


def _related(query, results):
    """粗略相关性过滤: 标题/链接中至少命中 1 个查询关键词, 过滤无关结果"""
    qwords = set(re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", query))
    if not qwords:
        return True
    hits = 0
    for r in results:
        text = r["title"] + " " + r["url"]
        if any(w in text for w in qwords):
            hits += 1
    return hits >= 1


def _stamp(engine):
    return {"source": engine, "retrieved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


# ---------------- SearXNG Provider ----------------
DEFAULT_SEARXNG_CONFIG = {
    "enabled": True,          # 是否启用 SearXNG 作为首选搜索
    "base_url": "http://localhost:8888",  # SearXNG 实例地址
    "timeout": 30,            # 单次搜索请求超时(秒, 覆盖冷启动首次搜索 ~15s)
    "max_results": 10,        # 返回给 Agent 的结果数
    "language": "zh-CN",      # JSON API 语言参数
    "site_filter": "",        # 默认站点过滤, 如 mee.gov.cn (空=不限定)
    "mcp": True,              # 经 MCP Server 独立进程调用(规避 AGPL-3.0), False 则直连 JSON API
}
# S2-M2 迁移适配：本文件位于 src/tools/，项目根 = parents[2]，配置仍在项目根 data/
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(_PROJECT_ROOT, "data", "searxng.json")
_SX_TIME = {"d": "day", "w": "week", "m": "month", "y": "year"}
_searxng_health = {"ok": None, "at": 0.0}  # 健康检测缓存 (60s)
_config_lock = threading.Lock()


def get_config():
    """读取 SearXNG 配置: 默认值 <- data/searxng.json <- 环境变量覆盖"""
    # 本机 SearXNG 直连：系统代理会把 127.0.0.1 请求也转发出去，导致搜索随机超时
    from src.core.net import ensure_local_no_proxy

    ensure_local_no_proxy()
    cfg = dict(DEFAULT_SEARXNG_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    if os.environ.get("SEARXNG_URL"):
        cfg["base_url"] = os.environ["SEARXNG_URL"].strip()
    if os.environ.get("SEARXNG_ENABLED") is not None:
        cfg["enabled"] = os.environ["SEARXNG_ENABLED"].lower() in ("1", "true", "yes", "on")
    if os.environ.get("SEARXNG_TIMEOUT"):
        try:
            cfg["timeout"] = int(os.environ["SEARXNG_TIMEOUT"])
        except ValueError:
            pass
    if os.environ.get("SEARXNG_MAX_RESULTS"):
        try:
            cfg["max_results"] = int(os.environ["SEARXNG_MAX_RESULTS"])
        except ValueError:
            pass
    if os.environ.get("SEARXNG_LANGUAGE"):
        cfg["language"] = os.environ["SEARXNG_LANGUAGE"].strip()
    if os.environ.get("SEARXNG_MCP") is not None:
        cfg["mcp"] = os.environ["SEARXNG_MCP"].lower() in ("1", "true", "yes", "on")
    return cfg


def save_config(data):
    """持久化 SearXNG 配置到 data/searxng.json (仅写配置键, 不写环境变量覆盖值)"""
    cfg = get_config()
    for k in DEFAULT_SEARXNG_CONFIG:
        if k in data:
            cfg[k] = data[k]
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({k: cfg[k] for k in DEFAULT_SEARXNG_CONFIG}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise RuntimeError(f"配置写入失败: {e}") from e
    return cfg


class SearxngProvider:
    """SearXNG 元搜索 Provider
    - 默认经 MCP Server 独立进程调用 (规避 AGPL-3.0 传染风险)
    - mcp=False 时直连 JSON API 作为备用通道
    """

    def __init__(self, cfg=None):
        cfg = cfg or get_config()
        self.base_url = (cfg.get("base_url") or "http://localhost:8888").rstrip("/")
        self.timeout = float(cfg.get("timeout", 15))
        self.max_results = int(cfg.get("max_results", 10))
        self.language = cfg.get("language") or "zh-CN"
        self.use_mcp = bool(cfg.get("mcp", True))

    def _get(self, path, params, timeout=None):
        return requests.get(
            f"{self.base_url}{path}",
            params=params,
            headers={"User-Agent": UA, "Accept": "application/json"},
            timeout=timeout or self.timeout,
        )

    def health(self):
        """SearXNG 可用性检测 (60s 缓存), MCP 模式同时校验 MCP server 与 SearXNG 本体"""
        now = time.time()
        if now - _searxng_health["at"] < 60 and _searxng_health["ok"] is not None:
            return _searxng_health["ok"]
        ok = False
        try:
            if self.use_mcp:
                st = searxng_mcp.health()
                ok = bool(st.get("mcp_ok") and st.get("ok"))
            else:
                ok = self._get("/healthz", {}, timeout=3).status_code == 200
        except Exception:
            ok = False
        _searxng_health["ok"] = ok
        _searxng_health["at"] = now
        return ok

    def search(self, query, top_n=5, time_range=None):
        """返回统一格式结果列表; time_range: 'd'|'w'|'m'|'y'
        - MCP 模式: 经 searxng_mcp_client 调用独立进程, 与 SearXNG 保持进程隔离
        - 直连模式: 直接调用 SearXNG JSON API (备用)
        """
        if self.use_mcp:
            results = searxng_mcp.search(query, top_n=top_n, time_range=time_range)
            return [dict(r, **_stamp("searxng")) for r in results]
        params = {
            "q": query,
            "format": "json",
            "language": self.language,
            "safesearch": 0,
            "pageno": 1,
        }
        if time_range in _SX_TIME:
            params["time_range"] = _SX_TIME[time_range]
        resp = self._get("/search", params)
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
                "engine": item.get("engine") or "",  # 审计: 实际底层引擎(bing/baidu/ddg..)
                **_stamp("searxng"),
            })
        return results


def _provider_chain(cfg):
    """组装搜索 Provider 链: 仅 SearXNG (已移除搜狗/360/Bing 爬虫兜底)"""
    if cfg.get("enabled") and cfg.get("base_url"):
        return [("searxng", SearxngProvider(cfg).search)]
    return []


def search(query, top_n=5, site_filter=None, time_range=None, use_cache=True):
    """返回 [{title, url, snippet, source, retrieved_at}]
    - 唯一引擎 SearXNG(若启用且健康), 失败直接返回空结果(无兜底)
    - site_filter: 站点限定, 字符串或列表 (如 'mee.gov.cn'), 自动拼 site:
    - time_range: 'd'|'w'|'m'|'y' (24小时/周/月/年)
    - use_cache: 结果缓存 24h, 命中直接返回
    SearXNG 不可用或结果无关时返回空列表
    """
    cfg = get_config()
    # 未显式传 site_filter 时, 应用配置级默认站点过滤
    if not site_filter and cfg.get("site_filter"):
        site_filter = cfg["site_filter"]
    if site_filter:
        sites = [site_filter] if isinstance(site_filter, str) else list(site_filter)
        for s in sites:
            s = (s or "").strip()
            if s and f"site:{s}" not in query:
                query = f"{query} site:{s}"
    key = hashlib.md5(f"{query}|{top_n}|{time_range or ''}".encode("utf-8")).hexdigest()
    if use_cache and db is not None:
        try:
            with _search_lock:
                hit = db.search_cache_get(key)
            if hit:
                return hit
        except Exception:
            pass
    for name, provider in _provider_chain(cfg):
        try:
            results = provider(query, top_n, time_range)
            if results and _related(query, results):
                if use_cache and db is not None:
                    try:
                        with _search_lock:
                            db.search_cache_set(key, query, results, name)
                    except Exception:
                        pass
                return results
        except Exception:
            continue
    return []


def status():
    """SearXNG 配置与可用性状态 (供设置面板/API 展示)"""
    cfg = get_config()
    state = {"config": cfg}
    if cfg.get("enabled") and cfg.get("base_url"):
        try:
            state["available"] = SearxngProvider(cfg).health()
        except Exception:
            state["available"] = False
    else:
        state["available"] = False
    # MCP 隔离通道状态
    try:
        state["mcp"] = searxng_mcp.health() if cfg.get("enabled") and cfg.get("mcp") else {"mcp_ok": False, "reason": "disabled"}
    except Exception as e:
        state["mcp"] = {"mcp_ok": False, "error": str(e)}
    state["config_path"] = CONFIG_PATH
    state["engine_chain"] = (
        ("searxng(mcp)" if cfg.get("mcp") else "searxng(json)") if cfg.get("enabled") else "searxng(disabled)"
    )
    # 自动拉起守护器状态 (软件启动自动带起 SearXNG / 端口自动查找 / 退出自动清理)
    try:
        import searxng_launcher
        state["launcher"] = searxng_launcher.status()
    except Exception as e:
        state["launcher"] = {"error": str(e)}
    return state


def _decode_text(resp):
    """requests 对无 charset 声明的响应默认按 ISO-8859-1 解码导致中文乱码。
    此处按实际字节重新探测: utf-8 -> gb18030 -> chardet 推断。
    政府老站(如 mee.gov.cn)常不声明 charset 且为 GB2312/GBK 编码。"""
    raw = resp.content
    if not raw:
        return resp.text
    declared = (resp.encoding or "").lower()
    if declared and declared not in ("iso-8859-1", "latin-1", "ascii"):
        return resp.text  # 已声明有效编码, 直接用
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    try:
        return raw.decode(resp.apparent_encoding or "gb18030", errors="replace")
    except Exception:
        return resp.text


_FETCH_HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.baidu.com/",
}
_BAIKE_API = "https://baike.baidu.com/api/openapi/BaikeLemmaCardApi?scope=103&format=json&appid=379020&bk_key={key}"


def _fetch_baike_html(url, timeout=10):
    """百度百科开放 API 通道(免登录 JSON): 解决 baike.baidu.com 403 反爬。
    返回统一 HTML 结构文本, 供正文提取管线处理; 失败返回 None。"""
    try:
        path = urlparse(url).path  # /item/词条名/277567 或 /item/词条名
        segs = [s for s in path.split("/") if s]
        if not segs:
            return None
        # item 后第一个路径段为词条名(可能 URL 编码)
        key = segs[1] if len(segs) >= 2 and segs[0] == "item" else segs[0]
        from urllib.parse import unquote
        key = unquote(key)
        if not key:
            return None
        data = requests.get(
            _BAIKE_API.format(key=urlquote(key)),
            headers={"User-Agent": UA},
            timeout=timeout,
        )
        if data.status_code != 200:
            return None
        d = data.json()
        title = d.get("title") or key
        parts = []
        if d.get("abstract"):
            parts.append(f"<p>{d['abstract']}</p>")
        if d.get("desc"):
            parts.append(f"<p>{d['desc']}</p>")
        card = d.get("card") or {}
        for k, v in (card.items() if isinstance(card, dict) else []):
            if isinstance(v, (str, int, float)) and str(v).strip():
                parts.append(f"<p>{k}: {v}</p>")
        if not parts:
            return None
        return (f"<html><head><title>{title}</title></head><body>"
                f"<h1>{title}</h1>{''.join(parts)}</body></html>")
    except Exception:
        return None


def _fetch_html(url, timeout=15):
    """多级抓取网页 HTML:
    1. requests 直抓 (多数政府/新闻/论坛站可用)
    2. curl_cffi 模拟 Chrome TLS/HTTP2 指纹 (绕过 Cloudflare 等 403)
    3. 百度百科开放 API (baike.baidu.com 强反爬专治)
    4. Jina Reader r.jina.ai 兜底 (github.com/jina-ai/reader#1238: 国内常不可达, 仅最后尝试)
    全部失败返回 None。"""
    # 1) requests 直抓
    try:
        resp = requests.get(url, headers=_FETCH_HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200 and resp.content:
            return _decode_text(resp)
    except requests.exceptions.RequestException:
        pass
    # 2) curl_cffi 浏览器指纹模拟 (TLS/HTTP2/JA3 模仿 Chrome, 见 github.com/lexiforest/curl_cffi)
    try:
        from curl_cffi import requests as _creq
        cresp = _creq.get(
            url,
            impersonate="chrome124",
            headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"},
            timeout=timeout,
            allow_redirects=True,
        )
        if cresp.status_code == 200 and getattr(cresp, "content", b""):
            try:
                return cresp.text
            except Exception:
                return _decode_text(cresp)
    except Exception:
        pass
    # 3) 百度百科开放 API (403 反爬绕过)
    if (urlparse(url).hostname or "").endswith("baike.baidu.com"):
        html = _fetch_baike_html(url)
        if html:
            return html
    # 4) Jina Reader 兜底 (网络不可达时静默失败)
    try:
        jresp = requests.get("https://r.jina.ai/" + url, headers={"User-Agent": UA}, timeout=12)
        if jresp.status_code == 200 and jresp.text.strip():
            return _decode_text(jresp)
    except requests.exceptions.RequestException:
        pass
    return None


_DOC_URL_EXTS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md", ".csv"}
_CT_EXT_MAP = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "text/html": ".html",
}


def _safe_name(name):
    """文件名安全化: 去掉路径分隔与非法字符, 控制长度"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip().strip(".")
    if len(name) > 120:
        ext = os.path.splitext(name)[1]
        name = name[:120 - len(ext)] + ext
    return name or "download"


def _is_doc_url(url):
    """是否为文档类链接(PDF/Word/Excel/PPT/文本等文件型 URL)"""
    p = urlparse(url.split("?")[0].lower())
    return os.path.splitext(p.path)[1] in _DOC_URL_EXTS


def download_file(url, save_dir=None, timeout=60, max_size=64 * 1024 * 1024):
    """下载网络文件到 save_dir(不删除, 供任务输出文件夹保留原始文件);
    save_dir 为 None 时下载到临时文件(用完即删)。
    文件名优先取 URL basename, 无扩展名时按 Content-Type 推断。返回本地路径, 失败返回 None。"""
    import tempfile
    from urllib.parse import unquote as _unquote
    try:
        with requests.get(url, headers={"User-Agent": UA}, timeout=timeout, stream=True) as resp:
            if resp.status_code != 200:
                return None
            ct = (resp.headers.get("Content-Type") or "").lower().split(";")[0].strip()
            raw = _unquote(os.path.basename(urlparse(url).path) or "download")
            ext = os.path.splitext(raw)[1].lower()
            if ext not in _DOC_URL_EXTS:
                ext = _CT_EXT_MAP.get(ct, "")
            if ext and not raw.lower().endswith(ext):
                raw += ext
            name = _safe_name(raw)
            if save_dir:
                os.makedirs(save_dir, exist_ok=True)
                path = os.path.join(save_dir, name)
            else:
                fd, path = tempfile.mkstemp(suffix=ext or ".bin")
                os.close(fd)
            size = 0
            with open(path, "wb") as f:
                for chunk in resp.iter_content(65536):
                    f.write(chunk)
                    size += len(chunk)
                    if size > max_size:
                        try:
                            os.unlink(path)
                        except Exception:
                            pass
                        return None
            return path
    except Exception:
        return None


def _is_pdf_url(url):
    return url.split("?")[0].lower().endswith(".pdf")


def _fetch_pdf(url, save_dir=None, timeout=30):
    """下载 PDF 到 save_dir(提供则保留原文件)/临时文件, 返回本地路径; 失败返回 None"""
    return download_file(url, save_dir=save_dir, timeout=timeout)


# 错误页特征（站点用 200 状态码包装的 404/失效页，正文为错误提示而非目标内容）
_ERROR_PAGE_PATTERNS = (
    "页面不存在", "地址有错", "访问的地址有错", "您访问的页面", "抱歉，您访问",
    "访问的页面不存在", "404", "not found", "页面已删除", "无法找到该页",
    "您访问的地址", "地址栏输入网址", "确认其拼写正确",
)


def _is_error_page(text: str) -> bool:
    """检测抓取结果是否为错误页/失效页（返回 True 表示应丢弃）。"""
    t = (text or "").strip()
    if not t or len(t) < 30:
        return False
    low = t.lower()
    hits = sum(1 for p in _ERROR_PAGE_PATTERNS if p.lower() in low)
    # 命中 >=2 个特征词（如"页面不存在"+“地址有错”）才判定，避免误伤正常含"404"的标准文本
    return hits >= 2


def _fetch_pdf_text(url, max_chars=300000, save_dir=None):
    """下载 PDF 并解析为 Markdown 全文(标准/法规等文档), 返回 '来源: ... 内容: ...'。
    save_dir 提供时 PDF 原文件保留到该目录(任务输出文件夹), 否则临时文件用完即删。"""
    import os as _os
    path = _fetch_pdf(url, save_dir=save_dir)
    if not path:
        raise RuntimeError(f"PDF 下载失败: {url}")
    try:
        md = ""
        try:
            import kb_pipeline as kp
            md = (kp.extract_markdown(path) or "").strip()
        except Exception:
            md = ""
        if not md:
            try:
                import kb_pipeline as kp
                md = (kp.extract_text(path) or "").strip()
            except Exception:
                md = ""
        if not md:
            raise RuntimeError(f"PDF 解析无文本内容: {url}")
        # 错误页识别：站点用 200 包装的 404 页（如 mee.gov.cn 失效 PDF），不得作为全文
        if _is_error_page(md):
            raise RuntimeError(f"PDF 内容为错误页/失效页(疑似 404): {url}")
        return f"来源: {url}\n格式: PDF 全文(Markdown)\n内容:\n{md[:max_chars]}"
    finally:
        if not save_dir:  # 临时文件才删除; 落盘到任务输出目录则保留原件
            try:
                _os.unlink(path)
            except Exception:
                pass


def fetch_document(url, save_dir=None, max_chars=300000):
    """下载文档(PDF/Word/Excel/PPT/文本)到 save_dir(提供则保留原文件)并解析为 Markdown 全文。
    返回 {"text": 解析结果, "file": 本地路径(save_dir 提供时), "name": 文件名, "ext": 扩展名}"""
    path = download_file(url, save_dir=save_dir)
    if not path:
        raise RuntimeError(f"文档下载失败: {url}")
    md = ""
    try:
        import kb_pipeline as kp
        md = (kp.extract_markdown(path) or "").strip()
        if not md:
            md = (kp.extract_text(path) or "").strip()
    except Exception:
        md = ""
    if not md:
        if not save_dir:
            try:
                os.unlink(path)
            except Exception:
                pass
        raise RuntimeError(f"文档解析无文本内容: {url}")
    # 错误页识别：站点用 200 包装的 404（如 mee.gov.cn 失效 PDF），不得作为全文
    if _is_error_page(md):
        raise RuntimeError(f"文档内容为错误页/失效页(疑似 404): {url}")
    ext = os.path.splitext(path)[1].lstrip(".").upper() or "文档"
    return {
        "text": f"来源: {url}\n格式: {ext} 全文(Markdown)\n内容:\n{md[:max_chars]}",
        "file": path if save_dir else None,
        "name": os.path.basename(path),
        "ext": os.path.splitext(path)[1].lower(),
    }


def _html_to_md(soup):
    """HTML -> Markdown 简化转换: 保留标题/段落/列表/表格/代码块结构"""
    lines = []

    def walk(node):
        if isinstance(node, str):
            t = node.strip()
            if t:
                lines.append(t)
            return
        name = (node.name or "").lower()
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            txt = node.get_text(" ", strip=True)
            if txt:
                lines.append("")
                lines.append("#" * int(name[1]) + " " + txt)
                lines.append("")
            return
        if name == "p":
            txt = node.get_text(" ", strip=True)
            if txt:
                lines.append(txt)
            return
        if name == "ul":
            for li in node.find_all("li", recursive=False):
                txt = li.get_text(" ", strip=True)
                if txt:
                    lines.append("- " + txt)
            lines.append("")
            return
        if name == "ol":
            for i, li in enumerate(node.find_all("li", recursive=False), 1):
                txt = li.get_text(" ", strip=True)
                if txt:
                    lines.append(f"{i}. {txt}")
            lines.append("")
            return
        if name == "table":
            rows = node.find_all("tr")
            for ri, tr in enumerate(rows):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                if not cells:
                    continue
                lines.append("| " + " | ".join(cells) + " |")
                if ri == 0:
                    lines.append("| " + " | ".join("---" for _ in cells) + " |")
            lines.append("")
            return
        if name in ("pre", "code"):
            txt = node.get_text("\n", strip=True)
            if txt:
                lines.append("")
                lines.append("```")
                lines.append(txt)
                lines.append("```")
                lines.append("")
            return
        if name == "blockquote":
            txt = node.get_text(" ", strip=True)
            if txt:
                lines.append("> " + txt)
                lines.append("")
            return
        if name == "br":
            return
        if name == "a":
            # 附件链接(PDF/Office 文档)保留为 markdown 链接, 避免被转换时过滤
            href = (node.get("href") or "").strip()
            txt = node.get_text(" ", strip=True) or href
            if href and re.search(r"\.(pdf|docx?|xlsx?|zip|rar)(\?|$)", href.lower()):
                lines.append(f"[{txt}]({href})")
            elif txt:
                lines.append(txt)
            return
        for child in node.children:
            walk(child)

    walk(soup)
    md = "\n".join(lines)
    md = re.sub(r"\n{3,}", "\n\n", md)
    # 附件链接兜底: p/table/ul 等容器分支用 get_text 提取会丢失 href,
    # 这里统一收集页面所有附件链接(PDF/Office)追加到末尾, 保证不被过滤
    extra = []
    seen = set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href or not re.search(r"\.(pdf|docx?|xlsx?|zip|rar)(\?|$)", href.lower()):
            continue
        if href in seen or href in md:
            continue  # a 分支已输出或已收集
        seen.add(href)
        txt = a.get_text(" ", strip=True) or href
        extra.append(f"- [{txt}]({href})")
    if extra:
        md = (md + "\n\n## 页面附件\n" + "\n".join(extra)).strip()
    return md


_PDF_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*\.pdf[^)]*)\)", re.I)
# HTML <a href="...pdf">text</a> 格式（trafilatura 等提取器可能丢链接时直接从 HTML 补提）
_HTML_PDF_LINK_RE = re.compile(r"<a[^>]*href=[\"']([^\"']*\.pdf[^\"']*)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_STD_PATH_MARK = ("/fgbz/bz/bzwb", "/fgbz/flfg", "/fgbz/hjbz")


def _extract_pdf_links(md, page_url):
    """从 markdown 或 HTML 中提取 PDF 附件链接(去重, 拼绝对 URL), 返回 [(链接文本, 绝对URL)]

    支持两种格式：
    - Markdown: `[text](url.pdf)`
    - HTML: `<a href="url.pdf">text</a>`（trafilatura 等提取器丢链接时用）
    """
    links = []
    seen = set()
    for m in _PDF_LINK_RE.finditer(md or ""):
        text, href = (m.group(1) or "").strip(), (m.group(2) or "").strip()
        if not href:
            continue
        abs_url = urljoin(page_url, href)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        links.append((text or abs_url, abs_url))
    for m in _HTML_PDF_LINK_RE.finditer(md or ""):
        href, text = (m.group(1) or "").strip(), (m.group(2) or "").strip()
        if not href:
            continue
        abs_url = urljoin(page_url, href)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        links.append((text or abs_url, abs_url))
    return links


def _is_std_page(url, title):
    """判断是否为标准公告页(生态环境部/政府标准发布栏目或标题含标准号)"""
    u = (url or "").lower()
    t = (title or "")
    if any(m in u for m in _STD_PATH_MARK):
        return True
    if "标准" in t and re.search(r"(hj|gb|ghgb|hj/t|gb/t)\s?[-／]\s?\d", t.lower()):
        return True
    return False


def _maybe_auto_pdf(body, url, title, max_chars, save_dir=None, html=None):
    """页面正文含 PDF 附件链接 且 (正文过短 或 为标准公告页) 时,
    自动下载解析 PDF 附件全文, 返回全文文本; 否则返回 None。
    目的: 标准公告页正文通常只有简介, 全文在 PDF 附件里,
    避免 Agent 拿不到全文而反复联网搜索(触发反爬)。
    save_dir 提供时 PDF 原文件保留到该目录(任务输出文件夹 downloads/)。
    html 提供时优先从原始 HTML 提取 PDF 链接（正文 Markdown 可能丢失链接）。"""
    pdf_links = _extract_pdf_links(body, url)
    # 正文 Markdown 丢了附件链接时，从原始 HTML 补提（trafilatura 等提取器常丢 <a>）
    if not pdf_links and html:
        pdf_links = _extract_pdf_links(html, url)
    if not pdf_links:
        return None
    body_len = len((body or "").strip())
    if body_len >= 2000 and not _is_std_page(url, title):
        return None
    for _text, _pdf_url in pdf_links[:3]:  # 最多尝试 3 个附件
        try:
            _md = _fetch_pdf_text(_pdf_url, max(max_chars, 30000), save_dir=save_dir)
            if _md:
                return _md
        except Exception:
            continue
    return None


def fetch_text(url, max_chars=30000, save_dir=None):
    """抓取网页正文或下载文档(PDF/Word/Excel/PPT/文本)解析为 Markdown 全文。
    - 文档类: 自动下载 -> 解析为 Markdown 全文(PDF/Word/Excel/PPT/文本)
    - 网页: 直抓 -> Jina Reader 兜底, 转 Markdown 保留标题/段落/列表/表格/附件链接
    - 标准公告页: 正文过短或为标准页时, 自动下载页面 PDF 附件解析全文
    save_dir 提供时下载的文档原文件保留到该目录(任务输出文件夹 downloads/), 否则临时文件用完即删
    返回 '标题/来源: ... 内容: ...'
    """
    if _is_doc_url(url):
        return fetch_document(url, save_dir=save_dir, max_chars=max(max_chars, 10000))["text"]
    if _is_pdf_url(url):
        return _fetch_pdf_text(url, max(max_chars, 10000), save_dir=save_dir)
    html = _fetch_html(url)
    if not html:
        raise RuntimeError(f"抓取失败: {url}")
    if not re.search(r"<[a-zA-Z!][^>]*>", html):
        # Jina Reader 返回的 Markdown/纯文本
        body = re.sub(r"\s{2,}", " ", html).strip()
        if _is_error_page(body):
            raise RuntimeError(f"网页内容为错误页/失效页(疑似 404): {url}")
        auto = _maybe_auto_pdf(body, url, url, max_chars, save_dir=save_dir, html=html)
        if auto:
            return f"来源: {url}\n该页面为标准公告页, 已自动下载并解析 PDF 附件全文:\n{auto}"
        return f"来源: {url}\n内容:\n{body[:max_chars]}"
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "form", "aside"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else url
    # 优先 trafilatura 本地正文提取(github.com/adbar/trafilatura, 替代不可达的 Jina Reader),
    # 提取过短/失败时降级到内置 HTML->Markdown 转换(保留附件链接等)
    body = ""
    try:
        import trafilatura
        md_t = trafilatura.extract(html, include_comments=False, include_tables=True, output_format="markdown")
        if md_t and len(md_t.strip()) > 50:
            body = md_t.strip()
    except Exception:
        md_t = None
    if not body:
        body = _html_to_md(soup)
    if not body:
        body = soup.get_text(" ", strip=True)
        body = re.sub(r"\s{2,}", " ", body)
    if _is_error_page(body) or _is_error_page(title):
        raise RuntimeError(f"网页内容为错误页/失效页(疑似 404): {url}")
    auto = _maybe_auto_pdf(body, url, title, max_chars, save_dir=save_dir, html=html)
    if auto:
        return (f"标题: {title}\n来源: {url}\n"
                f"该页面为标准公告页, 已自动下载并解析 PDF 附件全文:\n{auto}")
    return f"标题: {title}\n来源: {url}\n正文(Markdown):\n{body[:max_chars]}"
