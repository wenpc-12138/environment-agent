# -*- coding: utf-8 -*-
"""生态Agent - 工具注册表:KB 优先查库 / 联网检索 / 落库 / 记忆"""
import json
import os
import re
import time
from urllib.parse import urljoin

from src.core import db_v12 as db
from . import websearch

CATEGORIES = {
    "network": "网络资料",
    "gov": "政府发布",
    "standard": "标准规范",
    "policy": "政策法规",
    "draft": "征求意见稿",
    "other": "其他",
}
CATEGORY_LABELS = dict(CATEGORIES)


def _fmt_entry(e):
    validity = e.get("validity") or "未知"
    src_type = e.get("source_type") or "原文"
    flag = " [待复核]" if e.get("status") == "flagged" else ""
    return (
        f"[{CATEGORIES.get(e.get('category'), '其他')}] {e.get('title','')}{flag}\n"
        f"来源: {e.get('url') or e.get('source') or '本地'} | 类型: {src_type} | 有效性: {validity}\n"
        f"内容: {(e.get('content') or '')[:500]}"
    )


def kb_lookup(query, top_n=5):
    """查本地知识库(FTS5 全文检索)"""
    results = db.kb_search(query, top_n)
    if not results:
        return "知识库无匹配结果。可尝试: 1) 联网搜索后落库; 2) 换关键词重试。"
    lines = [f"命中 {len(results)} 条,按相关度排序:"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. " + _fmt_entry(r))
    return "\n\n".join(lines)


def kb_stats_tool():
    """知识库统计: 总量/分类/有效性/置信度/纠错/关系"""
    s = db.kb_stats()
    by_cat = "、".join(f"{k}={v}" for k, v in sorted(s["by_category"].items(), key=lambda x: -x[1]))
    by_valid = "、".join(f"{k}={v}" for k, v in sorted(s["by_validity"].items(), key=lambda x: -x[1]))
    lines = [
        f"知识库统计: 共 {s['total']} 条",
        f"分类: {by_cat or '无'}",
        f"有效性: {by_valid or '无'}",
        f"平均置信度: {s['avg_confidence']} | 待复核: {s['flagged']} 条",
        f"纠错单: 共 {s['corrections']['total']} (待处理 {s['corrections']['pending']}) | 关系: {s['relations']} 条",
    ]
    return "\n".join(lines)


def kb_correct(entry_id, issue, suggestion="", corrected_content=""):
    """纠错知识条目: 记录纠错单, 可选提供修正内容(自动降置信度待复核)"""
    e = db.kb_get(int(entry_id)) if str(entry_id).isdigit() else None
    if not e:
        return f"未找到条目 id={entry_id}，可用 kb_lookup/locate 先定位"
    cid = db.kb_correct(int(entry_id), issue=issue, suggestion=suggestion or "",
                        corrected_content=corrected_content or "", reporter="agent")
    if corrected_content:
        return (f"纠错单 #{cid} 已登记并应用修正: {e['title']}\n"
                f"条目已标记[待复核]并降置信度，待人工确认(kb_correct_resolve)。")
    return f"纠错单 #{cid} 已登记(待处理): {e['title']}\n问题: {issue}"


def kb_relation(from_id, to_id, rel_type="related", note=""):
    """在两条知识条目间建立关系(related/supersedes/derived_from)"""
    a = db.kb_get(int(from_id)) if str(from_id).isdigit() else None
    b = db.kb_get(int(to_id)) if str(to_id).isdigit() else None
    if not a or not b:
        return "关系建立失败: 条目不存在，请先用 kb_lookup/locate 定位两条条目的 id"
    db.kb_relation_add(int(from_id), int(to_id), rel_type=rel_type, note=note or "")
    return f"已建立关系: [{a['title']}] --{rel_type}--> [{b['title']}]"


def locate(query, limit=5):
    """精确定位知识库条目:按标准编号/标题/来源URL 查找, 返回 id/分类/来源/落库时间"""
    rows = db.kb_locate(query, limit)
    if not rows:
        return f"知识库中未定位到与「{query}」匹配的条目。可先 web_search 联网补充, 再 kb_save 落库。"
    lines = [f"知识库定位命中 {len(rows)} 条(精确度优先):"]
    for i, r in enumerate(rows, 1):
        cat = CATEGORIES.get(r.get("category"), "其他")
        lines.append(
            f"{i}. [{cat}] id={r['id']} {r['title']}\n"
            f"   来源: {r.get('url') or '本地'}\n"
            f"   落库时间: {r.get('created_at')}\n"
            f"   内容: {(r.get('content') or '')[:300]}"
        )
    return "\n\n".join(lines)


def web_search(query, top_n=5, site_filter=None, time_range=None):
    """联网搜索(多引擎自动降级, 支持站点限定与时间过滤)"""
    try:
        results = websearch.search(query, top_n, site_filter=site_filter, time_range=time_range)
    except Exception as e:
        return f"联网搜索失败: {e}"
    if not results:
        return "联网搜索无结果。"
    lines = [f"联网搜索命中 {len(results)} 条:"]
    for i, r in enumerate(results, 1):
        src = f"[{r.get('source', '')}] " if r.get("source") else ""
        lines.append(f"{i}. {src}{r['title']}\n   URL: {r['url']}\n   摘要: {r['snippet'][:200]}")
    return "\n\n".join(lines)


def _persist_downloads(task_id, save_dir, snap, md, auto_kb=True):
    """把本次下载到任务 downloads/ 的文档整理落盘: 原始文件已保留, 这里保存 Markdown 副本,
    并可自动进入知识库(本地导入管道: 解析->质检->分类->落库->分块向量化)。
    返回给 LLM 的落盘说明文本。"""
    new = []
    try:
        for f in sorted(os.listdir(save_dir)):
            if f in snap or f.endswith(".md"):
                continue
            if os.path.isfile(os.path.join(save_dir, f)):
                new.append(f)
    except Exception:
        return ""
    if not new:
        return ""
    lines = [f"已下载 {len(new)} 个文档到任务输出文件夹 downloads/: " + ", ".join(new)]
    for f in new:
        base = os.path.splitext(f)[0]
        # 错误页/失效页拦截：站点用 200 包装的 404（如 mee.gov.cn 失效 PDF），不入库
        try:
            from . import websearch as _ws
            if _ws._is_error_page(md):
                lines.append(f"- {f}: 内容为错误页/失效页(疑似 404)，未入库")
                continue
        except Exception:
            pass
        try:
            # 1) Markdown 副本落盘到任务输出文件夹 downloads/<名>.md
            db.task_output_save(task_id, f"downloads/{base}.md", md)
        except Exception:
            pass
        # 2) 进入知识库
        if auto_kb:
            try:
                md_path = os.path.join(save_dir, f"{base}.md")
                report = db.kb_import_files([md_path], batch_name=f"web-{task_id}-{int(time.time())}")
                if report.get("ok"):
                    lines.append(f"- {f}: 已转换为 Markdown 并进入知识库(条目 id={report.get('entries')})")
                else:
                    lines.append(f"- {f}: 知识库入库失败({report.get('errors') or '未知原因'})")
            except Exception as e:
                lines.append(f"- {f}: 知识库入库失败({e})")
    return "\n".join(lines)


def web_fetch(url, max_chars=30000, task_id=None):
    """抓取网页正文或下载文档(PDF/Word/Excel/PPT 等)解析为 Markdown 全文。
    文档原文件自动下载保存到任务输出文件夹 downloads/, 转换的 Markdown 同步保存并自动进入知识库。"""
    save_dir = None
    snap = set()
    if task_id:
        save_dir = os.path.join(db.task_output_dir(task_id), "downloads")
        try:
            snap = set(os.listdir(save_dir)) if os.path.isdir(save_dir) else set()
        except Exception:
            snap = set()
    try:
        md = websearch.fetch_text(url, max_chars, save_dir=save_dir)
    except Exception as e:
        return f"网页抓取失败: {e}"
    if task_id and save_dir:
        try:
            note = _persist_downloads(task_id, save_dir, snap, md, auto_kb=True)
            if note:
                md = md + "\n\n" + note
        except Exception:
            pass
    return md


def _kb_ingest_sync(title, path, category, source="附件解析"):
    """同步执行本地文档完整入库: Markdown 转换(含表格还原/扫描 OCR) + 元数据提取
    + 规则分类 + 落库 + MD 副本落盘 + 分块向量化。返回 (eid, md); 失败返回 (None, "")。"""
    import kb_pipeline as _kp
    try:
        md = _kp.extract_markdown(path)
    except Exception:
        md = ""
    if not (md or "").strip():
        return None, ""
    try:
        plain = _kp.md_from_text(md) or md
        # 自动命名: 标题为空用文件名; 检测到标准号且文件名未含时追加 (标准号)
        title = (title or "").strip() or os.path.splitext(os.path.basename(path))[0]
        meta = _kp.parse_meta(title, plain)
        std_no = (meta.get("std_no") or "").replace(" ", "")
        if std_no and std_no not in title.replace(" ", ""):
            title = f"{title} ({std_no})"
        domain, itype, stype, conf = _kp.classify_doc(title, plain)
        # 标题/内容含"征求意见稿"时自动归类为征求意见稿
        if "征求意见稿" in (title or "") or "征求意见" in plain[:200]:
            category = "draft"
        # 本地文件入库不携带网络地址, url 置空(避免列表显示本机路径)
        eid = db.kb_add(title, "", category if category in CATEGORIES else "other",
                        md[:200000], source=source, item_type=itype, domain=domain,
                        source_type="文档", validity=meta.get("validity") or "未知",
                        confidence=conf, std_no=meta.get("std_no") or "",
                        org=meta.get("org") or "", publish_date=meta.get("publish_date") or "",
                        metadata={"file": path, "sync": True})
    except Exception:
        return None, ""
    try:
        md_dir = os.path.join(db.DATA_DIR, "kb")
        files_dir = os.path.join(md_dir, "files")
        os.makedirs(files_dir, exist_ok=True)
        md_path = _kp.save_md_copy(md_dir, eid, md)
        fcopy = ""
        try:
            import shutil as _sh
            fcopy = os.path.join(files_dir, f"{eid}_{os.path.basename(path)}")
            _sh.copy2(path, fcopy)
        except Exception:
            fcopy = ""
        db.w("UPDATE kb_entries SET metadata_json=? WHERE id=?",
             (json.dumps({"file": fcopy or path, "file_md": md_path, "sync": True},
                         ensure_ascii=False), eid))
    except Exception:
        pass
    try:
        db.kb_embed_entry(eid)
    except Exception:
        pass
    # 标准/政策/法规类条目: 后台自动触发智能解读 + 联网查新(现行/废止确认)
    try:
        import standard_intel as _si
        if itype in ("standard", "regulation", "policy") \
                or (meta.get("std_no") or "").strip() \
                or domain in ("标准", "政策", "法规"):
            _si.interpret_entry(eid, do_check=True, sync=False)
    except Exception:
        pass
    # 所有条目: 后台自动触发通用文档智能总结(一句话/TL;DR/结构化长摘要 + 质量验证)
    try:
        import doc_intel as _di
        _di.summarize_entry(eid, sync=False)
    except Exception:
        pass
    return eid, md


def _kb_async_ingest(title, path, category):
    """后台线程包装: 同步执行完整入库(供兼容调用/测试)"""
    _kb_ingest_sync(title, path, category, source="附件异步入库")


def _kb_save_local_file(title, path, category, task_id=None):
    """附件/本地文档同步处理: 完整 Markdown 转换(含表格还原/扫描 OCR) + 同步入库,
    完成后立即把完整全文返回给 Agent 直接查看作答。
    入库与查看同步完成: 返回时该文档已全文落库并分块向量化, 可立即被 kb_lookup 检索。"""
    if not os.path.isfile(path):
        return f"落库失败: 文件不存在: {path}"
    eid, md = _kb_ingest_sync(title, path, category, source="附件解析")
    if not eid or not (md or "").strip():
        return f"落库失败: 无法解析文件内容(可能为加密或损坏): {path}"
    return (f"[文件已同步完整解析并全文入库(id={eid}, 分类={CATEGORIES.get(category, '其他')}, "
            f"共 {len(md)} 字符); 入库已完成, 可直接用 kb_lookup/kb_hybrid 检索]\n\n"
            f"===== 文件全文内容 =====\n{md}")


def kb_save(title, url, category, content, task_id=None):
    """将检索到的内容全文落库到本地知识库(五分类)。
    若传入内容过短且带来源 URL, 自动抓取来源全文(网页/PDF/Word/Excel 均解析为 Markdown)后入库;
    文档类来源自动下载保留到任务输出文件夹 downloads/ 并保存 Markdown 副本;
    来源为本地文件路径时直接解析该文件全文(扫描版 PDF 自动 OCR)。"""
    if category not in CATEGORIES:
        category = "other"
    # 标题/内容含"征求意见稿"时自动归类为征求意见稿
    if "征求意见稿" in (title or "") or "征求意见" in (content or "")[:200]:
        category = "draft"
    full = (content or "").strip()
    grabbed = False
    if len(full) < 800:
        if url and (url.startswith("http://") or url.startswith("https://")):
            save_dir = None
            snap = set()
            if task_id:
                save_dir = os.path.join(db.task_output_dir(task_id), "downloads")
                try:
                    snap = set(os.listdir(save_dir)) if os.path.isdir(save_dir) else set()
                except Exception:
                    snap = set()
            try:
                fetched = websearch.fetch_text(url, max_chars=300000, save_dir=save_dir)
                if fetched and len(fetched) > len(full) + 100:
                    full = fetched
                    grabbed = True
                    if task_id and save_dir:
                        try:
                            note = _persist_downloads(task_id, save_dir, snap, full, auto_kb=False)
                            if note:
                                full = full + "\n\n" + note
                        except Exception:
                            pass
            except Exception:
                pass
        elif url and url.lower().endswith((".pdf", ".docx", ".doc", ".html", ".htm", ".txt", ".md", ".xlsx")):
            try:
                import os as _os
                if _os.path.isfile(url):
                    # 附件/本地文档: 快速读取文本立即返回供 Agent 作答, 同时后台异步完成
                    # 完整 Markdown 转换 + 分类 + 落库, 避免同步等待完整解析(尤其扫描 OCR)拖慢首答
                    return _kb_save_local_file(title, url, category, task_id)
            except Exception:
                pass
    if not full:
        return f"落库失败: 内容为空, 且无法从来源自动抓取全文: {title}"
    eid = db.kb_add(title, url, category, full)
    way = "已自动抓取来源全文" if grabbed else "已提供完整内容"
    return (f"已全文落库到本地知识库(id={eid}, 分类={CATEGORIES[category]}): {title}\n"
            f"入库方式: {way} | 内容长度: {len(full)} 字符")


# 标准检索入库: 官方优先来源(国家标准公开平台 + 生态环境部 + 地方标准平台 + 政府站)
_STD_GOV_DOMAINS = [
    "mee.gov.cn", "openstd.samr.gov.cn", "std.samr.gov.cn", "hbba.sacinfo.org.cn",
    "dbba.sacinfo.org.cn", "gov.cn",
]
# 国家标准/地方标准的官方权威来源: 按标准号前缀匹配来源域名
_STD_SOURCE_DOMAINS = {
    # 国家标准: 生态环境部(环境类排放/质量标准有公告+PDF全文) +
    # 全国标准信息公共服务平台 + 国家标准全文公开系统 + 标准信息服务平台
    "GB": ["mee.gov.cn", "std.samr.gov.cn", "openstd.samr.gov.cn", "hbba.sacinfo.org.cn", "gov.cn"],
    "GB/T": ["mee.gov.cn", "openstd.samr.gov.cn", "std.samr.gov.cn", "hbba.sacinfo.org.cn", "gov.cn"],
    "GB/Z": ["mee.gov.cn", "std.samr.gov.cn", "openstd.samr.gov.cn", "gov.cn"],
    "GBJ": ["mee.gov.cn", "std.samr.gov.cn", "openstd.samr.gov.cn", "gov.cn"],
    "GBZ": ["mee.gov.cn", "std.samr.gov.cn", "openstd.samr.gov.cn", "gov.cn"],
    # 地方标准: 地方标准信息服务平台 + 地方人民政府/市场监管局网站
    "DB": ["dbba.sacinfo.org.cn", "gov.cn", "std.samr.gov.cn"],
    "DBJ": ["dbba.sacinfo.org.cn", "gov.cn"],
    "DB/T": ["dbba.sacinfo.org.cn", "gov.cn"],
    # 环保行业: 生态环境部
    "HJ": ["mee.gov.cn", "gov.cn"],
    "HJ/T": ["mee.gov.cn", "gov.cn"],
    # 其他行业标准: 政府站兜底
    "ISO": ["gov.cn", "std.samr.gov.cn"],
    "IEC": ["gov.cn", "std.samr.gov.cn"],
    "DL": ["gov.cn", "std.samr.gov.cn"],
    "DL/T": ["gov.cn", "std.samr.gov.cn"],
    "CJ": ["gov.cn", "std.samr.gov.cn"],
    "CJJ": ["gov.cn", "std.samr.gov.cn"],
    "CJ/T": ["gov.cn", "std.samr.gov.cn"],
    "JG": ["gov.cn", "std.samr.gov.cn"],
    "JGJ": ["gov.cn", "std.samr.gov.cn"],
    "JG/T": ["gov.cn", "std.samr.gov.cn"],
    "TSG": ["gov.cn", "std.samr.gov.cn"],
    "WS": ["gov.cn", "std.samr.gov.cn"],
    "TB": ["gov.cn", "std.samr.gov.cn"],
    "SL": ["gov.cn", "std.samr.gov.cn"],
    "LY": ["gov.cn", "std.samr.gov.cn"],
    "SC": ["gov.cn", "std.samr.gov.cn"],
    "NY": ["gov.cn", "std.samr.gov.cn"],
    "YY": ["gov.cn", "std.samr.gov.cn"],
    "CY": ["gov.cn", "std.samr.gov.cn"],
    "GA": ["gov.cn", "std.samr.gov.cn"],
    "JT": ["gov.cn", "std.samr.gov.cn"],
    "JTG": ["gov.cn", "std.samr.gov.cn"],
    "QJ": ["gov.cn", "std.samr.gov.cn"],
    "MH": ["gov.cn", "std.samr.gov.cn"],
    "YD": ["gov.cn", "std.samr.gov.cn"],
    "YD/T": ["gov.cn", "std.samr.gov.cn"],
}
# 已知标准前缀白名单(防止把 PDF 文件名前缀如 W020220 误判为标准号)
_STD_PREFIX_RE = re.compile(
    r"^(GB|GBJ|GBZ|GB/T|GB/Z|HJ|HJ/T|HJ/Z|DB|DBJ|DB/T|ISO|IEC|DL|DL/T|CJ|CJJ|CJ/T|"
    r"JG|JGJ|JG/T|TSG|WS|TB|SL|LY|SC|NY|YY|CY|GA|JT|JTG|QJ|MH|YD|YD/T)\s*[/-]?\s*\d",
    re.I)


def _std_source_domains(query):
    """按查询中的标准号前缀返回官方权威来源域名列表:
    GB* → 国家标准公开平台/std.samr.gov.cn; DB* → 地方标准平台+地方政府站; HJ → 生态环境部;
    无标准号(政府文件等) → 通用官方域。"""
    qn = _norm_std_text(query or "").upper()
    if not qn:
        return _STD_GOV_DOMAINS
    for prefix in sorted(_STD_SOURCE_DOMAINS, key=len, reverse=True):
        pn = _norm_std_text(prefix).upper()
        if qn.startswith(pn):
            return _STD_SOURCE_DOMAINS[prefix]
    # 无标准号: 政府文件等, 用通用官方域
    return _STD_GOV_DOMAINS


def _norm_std_text(s):
    """标准号/标题归一化: 去空白, 破折号统一为连字符(用于相关性匹配)"""
    return re.sub(r"\s+", "", (s or "").replace("—", "-").replace("–", "-").replace("－", "-"))


def _clean_std_title(title):
    """清理搜索标题的站点后缀: 'xxx_中华人民共和国生态环境部' → 'xxx'
    后缀限定为中文机构名(防止把标准号年份如 '-2022)' 误删)"""
    t = (title or "").strip()
    t = re.sub(
        r"[_\-—\s]+(中华人民共和国)?[\u4e00-\u9fa5]{2,12}"
        r"(生态环境部|政府门户网站|官网|市生态环境局|省生态环境厅|"
        r"市场监督管理局|标准化技术委员会|人民政府)?\s*$",
        "", t).strip()
    return t


# 地方标准完整号: DB32/4440-2022, DB31/802-2014 (省份码/序号-年份)
_DB_STD_RE = re.compile(
    r"(DB\s*\d{2}\s*[/／]\s*\d{2,6}(?:[.-]\d+)*\s*(?:[-—–]\s*\d{4})?)", re.I)


def _extract_std_no(query, plain):
    """提取标准号: 候选 = 查询串 + 正文, 均做前缀白名单校验;
    优先前缀与查询一致(如查询 DB32 只取 DB32*), 且取最完整(含年份)候选。"""
    import kb_pipeline as _kp
    blob = (query or "") + "\n" + (plain or "")[:3000]
    cands = _kp._STD_RE.findall(blob)
    # 地方标准完整号(DB32/4440-2022)单独匹配, 优先于拆分号(DB32)
    db_full = _DB_STD_RE.findall(blob)
    cands = [re.sub(r"\s+", "", c) for c in db_full] + cands
    # 查询串中的标准号前缀(如 DB32 / GB3838 / HJ91), 用于限定候选系列
    q_std = _kp._STD_RE.findall(query or "")
    q_prefix = _norm_std_text(q_std[0]).upper() if q_std else ""
    best = ""
    for c in cands:
        cc = _norm_std_text(c)
        if not (_STD_PREFIX_RE.match(cc) and re.search(r"\d", cc)):
            continue
        # 前缀一致: 查询标准号(如 DB32)要求候选同系列(DB32*), 避免取到其它省份(DB11)
        if q_prefix:
            p2 = re.match(r"[A-Z]+", q_prefix)
            digits = re.search(r"\d[\d\.]*", q_prefix)
            head = (p2.group(0) if p2 else "") + (digits.group(0) if digits else "")
            if not cc.upper().startswith(head):
                continue
        # 更完整: 含年份 > 不含; 长度更长 > 更短
        if (bool(re.search(r"\d{4}$", cc)) > bool(re.search(r"\d{4}$", best))) \
                or (bool(re.search(r"\d{4}$", cc)) == bool(re.search(r"\d{4}$", best))
                    and len(cc) > len(best)):
            best = cc
    return best


# 政府文件文号(如 国发〔2023〕1号 / 环办监测〔2020〕39号 / 生态环境部令 第28号 / 公告 2023年 第1号)
_DOC_NO_RES = [
    re.compile(r"[^，。、\s]{2,16}〔\d{4}〕\s*\d{1,3}\s*号"),
    re.compile(r"令\s*[（(]?\s*第\s*[〇零一二三四五六七八九十百\d]+\s*号"),
    re.compile(r"(公告|通告)\s*[（(]?\s*第\s*[〇零一二三四五六七八九十百\d]+\s*号"),
    re.compile(r"[^，。、\s]{2,14}\[\d{4}\]\s*\d{1,3}\s*号"),
    re.compile(r"公告\s*(\d{4})\s*年\s*第\s*[〇零一二三四五六七八九十百\d]+\s*号"),
]


def _extract_doc_no(plain, title=""):
    """提取政府文件文号(如 国发〔2023〕1号 / 生态环境部令 第28号), 返回 (文号, 文号类型)"""
    blob = (title or "") + "\n" + (plain or "")[:3000]
    for rx in _DOC_NO_RES:
        m = rx.search(blob)
        if m:
            no = re.sub(r"\s+", "", m.group(0))
            # 清理残留的左右括号
            no = no.replace("（", "(").replace("）", ")").replace("(", "").replace(")", "")
            if "令" in no:
                return no, "令号"
            if "公告" in no or "通告" in no:
                return no, "公告号"
            return no, "文号"
    return "", ""


def _auto_cat(itype, url, has_std_no):
    """按文档类型与来源自动映射入库分类:
    standard→标准规范, draft→征求意见稿, regulation/policy→政策法规,
    gov.cn 来源→政府发布, 其余→网络资料"""
    if itype == "standard" or has_std_no:
        return "standard"
    if itype == "draft":
        return "draft"
    if itype in ("regulation", "policy"):
        return "policy"
    if "gov.cn" in (url or ""):
        return "gov"
    return "other"


def _content_related(q, title, md):
    """校验抓取内容与查询相关。
    判定: 标题或正文头部含查询整串 → 强相关;
    或含查询中 ≥2 个 4字以上中文词, 或仅 1 个中文词时该词命中;
    或查询含标准号(如 GB 3838-2002)时正文/标题含标准号即相关。"""
    qn = _norm_std_text(q).lower()
    if not qn:
        return True
    tn = _norm_std_text(title).lower()
    head = _norm_std_text((md or "")[:1500]).lower()
    if qn in tn or qn in head:
        return True
    zh = re.findall(r"[\u4e00-\u9fa5]{4,}", qn)
    if zh:
        hits = sum(1 for w in zh if w in tn or w in head)
        if hits >= 2 or (len(zh) == 1 and hits == 1):
            return True
    # 标准号匹配: 查询含标准号时, 正文/标题含标准号数字段即相关
    m = re.search(r"([a-z]{1,4}[^a-z\d]*\d[\d\.]*)", qn)
    if m and (m.group(1) in tn or m.group(1) in head):
        return True
    return False


def _page_pdf_urls(url):
    """从标准公告页 HTML 中提取 PDF 附件直链(绝对地址, 去重, URL 规范化)。
    trafilatura 转 Markdown 会丢失附件链接, 这里直接从原始 HTML 兜底提取。
    地方政府旧站链接常含全角斜杠/空格/中文(如 'DB32／ 4440-2022 xxx.pdf'),
    需统一转为可下载的百分号编码 URL。"""
    try:
        html = websearch._fetch_html(url)
    except Exception:
        return []
    from urllib.parse import quote
    out, seen = [], set()
    for href in re.findall(r'[\"\']([^\"\']*?\.pdf[^\"\']*?)[\"\']', html or "", re.I):
        href = href.replace("／", "/").replace("（", "(").replace("）", ")").replace("　", " ")
        # 对非 ASCII/空格做百分号编码, 保留已有 %xx 与合法 URL 结构
        href = quote(href, safe="%/:=?&~#+@!$'()*;,[]-_.~")
        abs_url = urljoin(url, href)
        if abs_url not in seen:
            seen.add(abs_url)
            out.append(abs_url)
    return out


def _extract_std_title(md, q, std_no=""):
    """从标准 PDF/正文中提取具体标准名(如 '地表水环境质量监测技术规范')。
    优先: 1) 查询串中的中文标准名; 2) 含查询词的行; 3) 紧随标准号之后的中文标题行; 4) 文档头部候选。
    排除章节编号行/完整句/封面机构行/发布信息行/抓取器包装行。"""
    qn = _norm_std_text(q).lower()
    sn = _norm_std_text(std_no or "").lower()
    lines = (md or "").splitlines()

    def _ok(c):
        c = c.strip()
        if not (6 <= len(c) <= 40):
            return False
        if not re.search(r"[\u4e00-\u9fa5]", c):
            return False
        if c.startswith(("格式:", "来源:", "标题:", "正文", "该页面为", "已自动")):
            return False  # 抓取器包装行
        if re.match(r"^[\d一二三四五六七八九十]+[\.、\s]", c):
            return False  # 章节编号行
        if re.search(r"发布|实施|代替|批准|目\s*录|前言|范围|术语和定义|"
                     r"致谢|编制说明|电子版|审校|technical|specification", c, re.I):
            return False
        if re.match(r"^中华人民共和国", c) or re.search(r"国家生态环境标准|国家环境保护标准", c):
            return False  # 封面机构行
        if c.endswith(("。", "；", "，", ":")):
            return False  # 完整句子
        if re.search(r"^[\w]{1,3}\s+[〇零一二三四五六七八九十\d]", c):
            return False  # 乱码行(单字符+编号)
        return True

    # 0) 查询串中最长的中文名称片段(标准名/文件名主体, ≥5字)
    zh = re.findall(r"[\u4e00-\u9fa5]{5,}", qn)
    if zh:
        return max(zh, key=len)
    cands = [re.sub(r"^#{1,6}\s*|\*\*", "", line).strip() for line in lines]
    cands = [c for c in cands if _ok(c)]
    # 1) 含查询词整串
    for c in cands:
        if qn and qn in _norm_std_text(c).lower():
            return c
    # 2) 紧随标准号之后的行(标准号行后 1~6 行内首个合法中文标题)
    if sn:
        for i, line in enumerate(lines):
            if sn in _norm_std_text(line).lower():
                for j in range(i + 1, min(i + 7, len(lines))):
                    c = re.sub(r"^#{1,6}\s*|\*\*", "", lines[j]).strip()
                    if _ok(c):
                        return c
                break
    # 3) 文档头部候选(前 40 行内第一个合法标题)
    for c in cands[:40]:
        return c
    return ""


def std_import(query, category="", task_id=None):
    """标准/政府文件检索入库(免链接): 仅凭标准名称/标准号(如 HJ 91.2-2022、地表水环境质量
    监测技术规范)或政府文件名称(如 排污许可管理条例、生态环境部关于开展XX的通知), 自动联网
    搜索官方来源(优先生态环境部 mee.gov.cn/国家标准公开平台/政府站), 抓取公告页并自动下载
    PDF 附件解析全文, 提取标准号/文号/机构/日期等元数据, 自动分类(标准/政策法规/政府发布/
    征求意见稿)后全文入库, 并后台触发智能解读+联网查新+总结。
    所有标准与政府文件的入库都应通过本工具, 无需提供链接。"""
    q = (query or "").strip()
    if not q:
        return "检索入库失败: 查询为空, 请提供标准名称/标准号或政府文件名称(如 HJ 91.2-2022、排污许可管理条例)"
    lines = [f"标准/政府文件检索入库: 查询「{q}」"]
    # 1) 多查询策略: 原始查询 + "标准号(去年份)+标准名" 双通道, 避免旧版年份锁定搜索
    src_domains = _std_source_domains(q)
    qs = [q]
    m = re.search(r"((?:[A-Z]{1,4}|DB\s*\d{2})[^\u4e00-\u9fa5]{0,6}?-\d{4})", q, re.I)
    if m:
        base = m.group(1)
        base2 = re.sub(r"-\d{4}", "", base).replace(" ", "")
        q2 = (q.replace(base, base2) if base2 else q)
        if q2 != q:
            qs.append(q2)  # 如 "GB 3095-2012 环境空气质量标准" → "GB 3095 环境空气质量标准"
    results = []
    for qi in qs:
        try:
            rr = websearch.search(qi, top_n=8, site_filter=src_domains)
        except Exception:
            rr = []
        if rr:
            results.extend(rr)
    if not results:
        try:
            results = websearch.search(q, top_n=8)
        except Exception:
            results = []
    if not results:
        return f"标准检索入库失败: 未搜到与「{q}」相关的结果"
    # 去重(按 URL)
    seen, dedup = set(), []
    for r in results:
        u = (r.get("url") or "").strip()
        if u and u in seen:
            continue
        seen.add(u)
        dedup.append(r)
    results = dedup
    lines.append(f"搜索命中 {len(results)} 条(来源域: {','.join(src_domains[:3])}...)" if len(src_domains) > 3
                 else f"搜索命中 {len(results)} 条(来源域: {','.join(src_domains)}):")
    for i, r in enumerate(results, 1):
        lines.append(f"  {i}. {r.get('title', '')}\n     {r.get('url', '')}")
    # 2) 候选排序: 标准类型对应官方域最高 > 其它官方域 > 第三方;
    #    官方 PDF 直链 > 官方公告页 html; 标题/URL 与查询强相关加分;
    #    新版优先: URL 含最新日期段(2026/2025)加分, 标题含"废止"减分
    import datetime as _dt
    _cur_year = _dt.date.today().year
    def _score(r):
        url = (r.get("url") or "").lower()
        title = (r.get("title") or "")
        official = any(d in url for d in _STD_GOV_DOMAINS)
        matched = any(d in url for d in src_domains)
        s = 5 if matched else (3 if official else 0)
        is_pdf = bool(re.search(r"\.pdf(\?|$)", url))
        if official and is_pdf:
            s += 2  # 官方 PDF 直链: 全文完整, 最优先
        elif official:
            s += 1  # 官方公告页: 可自动提取 PDF 附件
        else:
            s += 1 if is_pdf else 0
        # 新版优先: URL 日期段(如 /202602/) 越接近当前年/月 加分; 标题含"废止/替代"减分
        for _y in range(_cur_year, _cur_year - 4, -1):
            if f"/{_y}" in url:
                s += (4 - (_cur_year - _y))
                break
        if re.search(r"废止|已废止|被替代|代替.*?号", title):
            s -= 4
        qn = _norm_std_text(q)
        if qn and (qn in _norm_std_text(title + " " + url)):
            s += 3
        return -s
    results.sort(key=_score)
    # 3) 逐个候选抓取全文(自动 PDF 附件解析) + 相关性校验, 取首个合格
    #    内容阈值 3000 字符: 标准全文(几十页 PDF)远大于此, 简介页/摘要页(<3000)自动跳过
    save_dir = None
    snap = set()
    if task_id:
        save_dir = os.path.join(db.task_output_dir(task_id), "downloads")
        try:
            snap = set(os.listdir(save_dir)) if os.path.isdir(save_dir) else set()
        except Exception:
            snap = set()
    # 预解析所有候选(正文过短的公告页尝试提取 PDF 附件全文)
    _parsed = []  # [(url, rtitle, md, 版本年份int或0)]
    # 性能护栏：最多抓取 _MAX_CANDIDATE_FETCH 条候选且首个合格即停。
    # 背景：搜索可命中 10+ 条，逐个串行抓全文(每条 PDF 最长 60s)会累积到 50s+，
    # 前端 SSE 表现为"卡死"，且用户等待期间可能断开连接导致任务完成确认丢失。
    _MAX_CANDIDATE_FETCH = 4
    for r in results:
        if len(_parsed) >= _MAX_CANDIDATE_FETCH:
            lines.append(f"  - 已达候选抓取上限({_MAX_CANDIDATE_FETCH})，停止后续抓取")
            break
        url = (r.get("url") or "").strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        # 备案公告列表页(如 dbba.sacinfo.org.cn/rnDetail/xxx 含多标准表格, 非单标准来源)
        # 直接排除, 避免标准号从无关行错乱提取
        if "/rnDetail/" in url:
            lines.append(f"  - 备案公告列表页(多标准), 跳过: {url}")
            continue
        rtitle = r.get("title") or ""
        try:
            md = websearch.fetch_text(url, max_chars=1_000_000, save_dir=save_dir)
        except Exception as e:
            lines.append(f"  - 抓取失败: {url} ({e})")
            continue
        if not (md and len(md.strip()) > 3000):
            # 官方公告页: 简介页内容过短且含 PDF 附件时, 直接从 HTML 提取附件直链重抓全文
            pdfs = _page_pdf_urls(url) if (url.lower().endswith((".shtml", ".html", ".htm", "/"))
                                           or re.search(r"\.(shtml|html?)(\?|$)", url.lower())) else []
            got_attach = False
            for p in pdfs[:3]:
                try:
                    pmd = websearch.fetch_text(p, max_chars=1_000_000, save_dir=save_dir)
                except Exception:
                    continue
                if pmd and len(pmd.strip()) > 3000:
                    md, url = pmd, p
                    got_attach = True
                    lines.append(f"  - 已从公告页提取 PDF 附件全文: {p}")
                    break
            if not got_attach and not (md and len(md.strip()) >= 200):
                lines.append(f"  - 内容过短(疑似简介页), 跳过: {r.get('url')}")
                continue
        if not _content_related(q, rtitle or "", md):
            lines.append(f"  - 内容与查询不相关, 跳过: {url}")
            continue
        # 版本年份: 优先取标题中标准号年份(如 GB 3095-2026, 最可靠);
        # 否则仅当 URL 是"标准正式发布栏目"页(含 /fgbz/ 且不含 other/知识库/镜像子栏目)
        # 时才取 URL 日期段年份(/202602/ → 2026)。
        # 知识库/资料/其他标准页(如 cjjg.mee.gov.cn/zsyd/、/fgbz/bz/bzwb/other/xxbz/)
        # 的页面日期只是收录时间, 不代表标准版本, 不得作为版本证据。
        ver_year = 0
        m_ver = re.search(r"(?:GB|HJ|DB\s*\d{2})\s*\d*[\s\-—–]?\s*(\d{4})\b", rtitle, re.I)
        if m_ver:
            ver_year = int(m_ver.group(1))
        else:
            _ul = (url or "").lower()
            if "/fgbz/" in _ul and not any(k in _ul for k in
                                          ("/other/", "/zsyd/", "/resources/", "/gate/big5/", "/kjbz/")):
                m_ver2 = re.search(r"/(20\d{2})\d{2}/", url)
                if m_ver2:
                    ver_year = int(m_ver2.group(1))
        _parsed.append((url, rtitle, md, ver_year))
        # 性能护栏：合格候选达到 2 个即停止抓取（保留版本比对能力，同时避免 10+ 候选串行抓取累积超时）
        if len(_parsed) >= 2:
            lines.append(f"  - 已取到 {len(_parsed)} 个合格候选，停止后续抓取")
            break
    # 版本检测: 查询含旧年份(如 GB 3095-2012)但**官方来源**候选含更新年份(如 2026)时, 标记新版存在。
    # 仅信任官方权威来源(mee.gov.cn / std.samr.gov.cn / openstd / 政府站)的版本年份,
    # 第三方页面(如 doc88/百度文库 标题含 'GB3838-2025')不得作为新版证据, 防止误判。
    _q_year = re.search(r"-\s*(\d{4})\b", q)
    _new_ver = 0
    _new_ver_title = ""
    if _q_year:
        _qv = int(_q_year.group(1))
        _official_parsed = [(u, t, m, v) for u, t, m, v in _parsed
                            if any(d in (u or "").lower() for d in src_domains)]
        for _u, _t, _m, _v in _official_parsed:
            if _v > _qv:
                _new_ver = max(_new_ver, _v)
        if _new_ver:
            # 新版标题: 仅从官方候选取标题含标准号年份(如 'GB 3095-2026')的, 便于提取新版标准号
            for _u, _t, _m, _v in _official_parsed:
                if _v == _new_ver and re.search(r"\d{4}", _t or ""):
                    _new_ver_title = _t
                    break
            if not _new_ver_title:
                for _u, _t, _m, _v in _official_parsed:
                    if _v == _new_ver and _t:
                        _new_ver_title = _t
                        break
    # 0) 查询旧版但官方源已发现新版时, 优先采用官方新版候选(避免入库旧版内容却标新版号)
    picked = None
    if _new_ver:
        _new_srcs = [(u, t, m, v) for u, t, m, v in _parsed
                     if v == _new_ver
                     and any(d in (u or "").lower() for d in src_domains)
                     and len((m or "").strip()) >= 200]
        if _new_srcs:
            _new_srcs.sort(key=lambda x: -len((x[2] or "").strip()))
            picked = _new_srcs[0][:3]
            lines.append(f"  - 优先官方新版候选: {picked[0]}")
    # 第一轮: 取全文充足的完整源(标准全文/政府文件全文)。
    # 排序: 官方源优先(第三方标题可能伪造年份, 不得压过官方源), 同域内新版优先
    if not picked:
        full_srcs = [(u, t, m, v) for u, t, m, v in _parsed if len((m or "").strip()) >= 3000]
        if full_srcs:
            full_srcs.sort(key=lambda x: (0 if any(d in (x[0] or "").lower() for d in src_domains) else 1,
                                          -x[3]))
            picked = full_srcs[0][:3]
    # 第二轮(兜底): 官方来源域详情页(如 std.samr.gov.cn 详情页含标准元数据, 全文需登录):
    # 无全文源时接受短正文, 保证权威来源 + 元数据入库
    if not picked:
        _fallback = [(u, t, m, v) for u, t, m, v in _parsed
                     if any(d in (u or "").lower() for d in src_domains)
                     and len((m or "").strip()) >= 200]
        if _fallback:
            _fallback.sort(key=lambda x: -x[3])
            picked = _fallback[0][:3]
            lines.append(f"  - 无全文源, 采用官方来源域详情页(元数据入库): {picked[0]}")
    if not picked:
        return "\n".join(lines + ["标准检索入库失败: 候选页面均未能解析出有效全文"])
    url, rtitle, md = picked
    if _new_ver:
        lines.append(f"  - 提示: 已检测到该标准 {_new_ver} 年新版本(现行), 查询年份 {_q_year.group(1)} 已修订")
    # 4) 标题清理 + 元数据提取 + 自动分类
    import kb_pipeline as _kp
    plain = _kp.md_from_text(md) or md
    title = _clean_std_title(rtitle) or q
    meta = _kp.parse_meta(title, plain)
    # 标准号提取: 若已发现新版, 优先用新版候选标题中的完整标准号(如 GB3095-2026)
    _std_blob = q
    if _new_ver and _new_ver_title:
        _std_blob = f"{_new_ver_title}\n{q}"
    std_no = _extract_std_no(_std_blob, plain)
    if not std_no:
        # meta 兜底的标准号也做前缀白名单校验, 防止 PDF 文件名前缀(如 W020240)误判
        _m_no = (meta.get("std_no") or "").replace(" ", "")
        if _m_no and _STD_PREFIX_RE.match(_m_no):
            std_no = _m_no
    # 政府文件文号提取(如 国发〔2023〕1号 / 生态环境部令 第28号);
    # 标准文档(有白名单标准号)不提取文号, 避免误带引用文号
    doc_no, doc_no_type = "", ""
    if not std_no:
        doc_no, doc_no_type = _extract_doc_no(plain, title)
        if not doc_no:
            for _r in results:
                _dn, _dnt = _extract_doc_no("", _r.get("title") or "")
                if _dn:
                    doc_no, doc_no_type = _dn, _dnt
                    break
    std_title = _extract_std_title(md, q, std_no)
    if std_title and std_title not in title:
        title = std_title
    if std_no and std_no not in _norm_std_text(title):
        title = f"{title} ({std_no})"
    elif doc_no and doc_no not in _norm_std_text(title):
        title = f"{title} ({doc_no})"
    # 分类: 标准号非空(白名单) 或 查询含标准号 → 按标准分类; 否则按政府文件规则分类
    # (避免 classify_doc 把 PDF 文件名前缀如 W020240 误判为标准号)
    _classify_blob = plain
    if not std_no:
        _classify_blob = re.sub(r"[A-Za-z]{1,5}\d{5,}", "", _classify_blob)
    if std_no:
        domain, itype, stype, conf = _kp.classify_doc(title, _classify_blob)
    else:
        domain, itype, stype, conf = _kp.classify_doc(title, _classify_blob)
        if itype == "standard":
            itype = "policy" if "意见" in title or "通知" in title else "regulation"
    # 分类自动映射: 显式指定优先, 否则按文档类型/来源判断
    cat = category if category in CATEGORIES else _auto_cat(itype, url, bool(std_no))
    if "征求意见稿" in title or "征求意见" in plain[:200]:
        cat = "draft"
    # 5) 落库(带完整元数据, 政府文件文号写入 metadata)
    _md_meta = {"auto_import": True, "query": q}
    if doc_no:
        _md_meta["doc_no"] = doc_no
        _md_meta["doc_no_type"] = doc_no_type
    eid = db.kb_add(title, url, cat, md[:1_000_000], source="标准/政府文件检索自动入库",
                    item_type=itype, domain=domain, source_type="网页",
                    validity=meta.get("validity") or "未知", confidence=conf,
                    std_no=std_no, org=meta.get("org") or "",
                    publish_date=meta.get("publish_date") or "",
                    implement_date=meta.get("implement_date") or "",
                    metadata=_md_meta)
    # 6) MD 副本落盘 + 分块向量化
    try:
        md_dir = os.path.join(db.DATA_DIR, "kb")
        os.makedirs(os.path.join(md_dir, "files"), exist_ok=True)
        md_path = _kp.save_md_copy(md_dir, eid, md)
        db.w("UPDATE kb_entries SET metadata_json=? WHERE id=?",
             (json.dumps({"file_md": md_path, "auto_import": True, "query": q},
                         ensure_ascii=False), eid))
    except Exception:
        pass
    try:
        db.kb_embed_entry(eid)
    except Exception:
        pass
    # 7) 标准/政策/法规类: 后台智能解读 + 联网查新; 全部: 后台通用总结
    try:
        import standard_intel as _si
        if itype in ("standard", "regulation", "policy") or std_no \
                or domain in ("标准", "政策", "法规"):
            _si.interpret_entry(eid, do_check=True, sync=False)
    except Exception:
        pass
    try:
        import doc_intel as _di
        _di.summarize_entry(eid, sync=False)
    except Exception:
        pass
    if task_id and save_dir:
        try:
            note = _persist_downloads(task_id, save_dir, snap, md, auto_kb=False)
            if note:
                lines.append(note)
        except Exception:
            pass
    _id_label = "标准号" if std_no else ("文号" if doc_no else "编号")
    _id_val = std_no or doc_no or "未识别"
    lines.append(
        f"已入库: id={eid} | 分类={CATEGORIES[cat]} | 标题: {title}\n"
        f"{_id_label}: {_id_val} | 机构: {meta.get('org') or '未知'}\n"
        f"发布: {meta.get('publish_date') or '未知'} | 实施: {meta.get('implement_date') or '未知'}\n"
        f"来源: {url} | 内容 {len(md)} 字符(已全文入库并向量化, 后台触发解读/查新/总结)"
    )
    return "\n".join(lines)


def kb_hybrid(query, top_n=5):
    """多路召回检索(FTS5全文+向量+关系扩散, RRF融合), 命中带召回来源标记"""
    results = db.kb_hybrid_search(query, top_n)
    if not results:
        return "多路召回无命中。可尝试: 1) 联网搜索后落库; 2) 换关键词重试。"
    lines = [f"混合检索命中 {len(results)} 条(来源标记: fts=全文 vec=向量 rel=关系):"]
    for i, r in enumerate(results, 1):
        tag = "+".join(r.get("recall") or [])
        lines.append(f"{i}. [{tag}] {_fmt_entry(r)}")
    return "\n\n".join(lines)


def kb_vector(query, top_n=5):
    """语义向量检索(本地哈希词袋向量, 无需嵌入模型)"""
    try:
        results = db.kb_vector_search(query, top_n)
    except Exception as e:
        return f"向量检索失败: {e}"
    if not results:
        return "向量检索无命中(可能尚无已分块向量化条目)。"
    lines = [f"向量检索命中 {len(results)} 条:"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. " + _fmt_entry(r))
    return "\n\n".join(lines)


def _resolve_kb_paths(paths):
    """归一化 Agent 传入的路径参数(可能缺 data/ 前缀、是裸文件名或相对 cwd 的路径):
    - 绝对路径直接用; 相对路径优先按项目根(base)解析, 再按进程 cwd 解析
    - 均失败时尝试 data/uploads/ 与 uploads/ 下同名文件
    - 目录项递归展开为其中可读文件
    返回 (file_list, missing_list)"""
    import re as _re
    import vlm_convert
    base = os.path.dirname(db.DATA_DIR)
    uploads = [os.path.join(db.DATA_DIR, "uploads"), os.path.join(base, "uploads")]
    items = []
    if isinstance(paths, str):
        items = [p for p in _re.split(r"[,，;]", paths) if p.strip()]
    elif isinstance(paths, (list, tuple)):
        items = [str(p) for p in paths]
    files, missing = [], []
    for raw in items:
        raw = (raw or "").strip().strip("\"'")
        if not raw:
            continue
        cand = [raw]
        if not os.path.isabs(raw):
            cand.insert(0, os.path.join(base, raw))
            cand.insert(1, os.path.join(db.DATA_DIR, raw))  # data/<raw>
        for up in uploads:
            cand.append(os.path.join(up, os.path.basename(raw)))
        hit = None
        for c in cand:
            if os.path.isdir(c) or os.path.isfile(c):
                hit = c
                break
        if hit is None:
            missing.append(raw)
            continue
        files.extend(vlm_convert.expand_paths(hit))
    seen, uniq = set(), []
    for f in files:
        rp = os.path.normcase(os.path.abspath(f))
        if rp not in seen:
            seen.add(rp)
            uniq.append(f)
    return uniq, missing


def _path_hint(missing=None):
    """生成路径修复提示: 列出 data/uploads 下当前可用的文档, 供 Agent 重新传参"""
    lines = ["未找到可读取的文件(路径可能缺 data/ 前缀、文件名有误或相对路径解析失败)。"]
    if missing:
        lines.append("未识别: " + ", ".join(str(m) for m in missing[:5]))
    up = os.path.join(db.DATA_DIR, "uploads")
    if os.path.isdir(up):
        docs = sorted(os.listdir(up))
        docs = [d for d in docs
                if os.path.splitext(d)[1].lower() in
                (".pdf", ".docx", ".doc", ".md", ".txt", ".html", ".htm", ".xlsx")]
        if docs:
            lines.append("data/uploads 下现有文件: " + ", ".join(docs[:15]))
            lines.append("请用绝对路径或形如 data/uploads/<文件名> 的路径重试。")
    return "\n".join(lines)


def kb_import(paths, batch_name=""):
    """批量导入本地文档(PDF/DOCX/HTML/TXT/MD/XLSX), 自动解析+分类+落库+分块向量化"""
    try:
        files, missing = _resolve_kb_paths(paths)
        if not files:
            return "批量导入失败(无有效文件):\n" + _path_hint(missing)
        report = db.kb_import_files(files, batch_name)
    except Exception as e:
        return f"批量导入失败: {e}"
    lines = [f"批量导入完成(batch={report['batch']}): 成功 {report['ok']} / 失败 {report['fail']}"]
    if report.get("entries"):
        lines.append("新增条目 id: " + ", ".join(str(x) for x in report["entries"][:20]))
    if report.get("errors"):
        lines.append("失败明细:")
        lines.extend(f"- {e}" for e in report["errors"][:10])
    # 批量导入后: 标准/政策/法规条目自动触发智能解读 + 联网查新
    try:
        import standard_intel as _si
        for eid in (report.get("entries") or []):
            _si.interpret_entry(eid, do_check=True, sync=False)
    except Exception:
        pass
    # 批量导入后: 所有条目自动触发通用文档智能总结(一句话/TL;DR/结构化长摘要 + 质量验证)
    try:
        import doc_intel as _di
        for eid in (report.get("entries") or []):
            _di.summarize_entry(eid, sync=False)
    except Exception:
        pass
    return "\n".join(lines)


def kb_convert(paths, out_dir="", dpi=144, page_batch=4):
    """本地文档(PDF/图片优先) -> Markdown 存档。

    按《路径A_RapidAI全家桶》优先走纯本地管线(ocr_worker /convert_rapid):
      RapidLayout 版面分析 -> RapidOCR 文字 -> RapidTable 表格结构 -> RapidLaTeXOCR 公式 -> MD 拼装。
    未安装 RapidAI 全家桶或失败回退 VLM 六步管线(vlm_convert, 需多模态 Provider):
      Step 0 探测页型 -> Step 1 渲染PNG -> Step 2 VLM 视觉理解 -> Step 3 骨架抽取
      -> Step 4 结构化重排 -> Step 5 质量回校; 无视觉 Provider 再回退传统 RapidOCR(功能不降级)。
    返回各文件存档路径与转换报告。"""
    import vlm_convert
    base = out_dir.strip() or os.path.join(db.DATA_DIR, "convert_md")
    files, missing = _resolve_kb_paths(paths)
    if not files:
        return "未找到可转换的文件:\n" + _path_hint(missing)
    results = vlm_convert.convert_files_to_md(files, base, dpi=dpi, page_batch=page_batch)
    lines = []
    for src, out_md, report in results:
        if out_md:
            warn = report.get("warnings") or []
            tail = ""
            if warn:
                tail = " 警告: " + " | ".join(warn[:3])
                if len(warn) > 3:
                    tail += " ..."
            if report.get("fallback"):
                tail += " [RapidOCR 回退]"
            lines.append("[OK] %s -> %s%s" % (os.path.basename(src), out_md, tail))
        else:
            lines.append("[FAIL] %s: %s" % (os.path.basename(src), report.get("error", "转换失败")))
    return "\n".join(lines) or "无转换结果"


# ============ 报告分类学习(动态类型注册表) ============
_REPORT_TYPES_PATH = os.path.join("data", "report_types.json")


def _load_report_types():
    """加载报告类型注册表(持久化 data/report_types.json, 支持动态新增类型)"""
    try:
        with open(_REPORT_TYPES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data:
            return data
    except Exception:
        pass
    return {}


def _save_report_types(types):
    try:
        with open(_REPORT_TYPES_PATH, "w", encoding="utf-8") as f:
            json.dump(types, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


_REPORT_TYPES = _load_report_types()
_DEFAULT_REPORT_TYPE = "acceptance"
if _DEFAULT_REPORT_TYPE not in _REPORT_TYPES:
    _REPORT_TYPES = {
        "acceptance": {
            "label": "验收报告", "template": "report_table_template.md",
            "sections": ["验收监测依据", "工程建设内容", "污染源", "监测结果", "验收监测结论"],
            "hint": ["验收", "竣工环境保护"],
        },
    }
    _save_report_types(_REPORT_TYPES)


def _detect_report_type(text, fname=""):
    """根据文件名+文本识别报告类型, 无法识别返回 None"""
    blob = (fname or "") + "\n" + (text or "")[:3000]
    best, best_n = None, 0
    for rtype, cfg in _REPORT_TYPES.items():
        n = sum(1 for h in cfg.get("hint", []) if h in blob)
        if n > best_n:
            best, best_n = rtype, n
    return best if best_n > 0 else None


def _extract_report_sections(text, rtype=_DEFAULT_REPORT_TYPE):
    """从报告文本提炼章节结构: 返回该报告类型出现过的章节特征"""
    keys = _REPORT_TYPES.get(rtype, {}).get("sections", [])
    return [k for k in keys if k in (text or "")]


def _register_report_type(rtype, label, template, sections, hints):
    """动态注册新报告类型并持久化"""
    _REPORT_TYPES[rtype] = {
        "label": label, "template": template,
        "sections": list(dict.fromkeys(sections)),
        "hint": list(dict.fromkeys(hints)),
    }
    _save_report_types(_REPORT_TYPES)
    return _REPORT_TYPES[rtype]


# 报告种类词(用于从未知报告自动聚类新类型): 关键词 -> 报告类型名
_AUTO_TYPE_WORDS = {
    "验收": "验收报告", "竣工环境保护": "验收报告",
    "监测": "监测报告", "检测": "检测报告", "采样": "监测报告",
    "方法验证": "方法验证报告", "方法确认": "方法验证报告",
    "不确定度": "不确定度报告", "测量不确定度": "不确定度报告",
    "环境影响评价": "环评报告", "环评": "环评报告",
    "质控": "质控报告", "质量控制": "质控报告",
    "排污许可": "排污许可报告", "排污许可证": "排污许可报告",
    "应急预案": "应急预案报告", "风险评估": "风险评估报告",
    "审计": "审计报告", "核查": "核查报告", "评估": "评估报告",
    "调研": "调研报告", "可行性研究": "可行性研究报告",
    "评价": "评价报告", "年度报告": "年度报告", "月报": "监测月报",
}


def _auto_cluster_type(text, fname=""):
    """从未知报告自动聚类报告类型: 返回 {key, label} 或 None。
    key 为英文 slug(用于注册表/模板文件名), label 为中文类型名。
    英文 slug 映射表 + 通用兜底(拼音转写略, 用 label 去重简化)。"""
    blob = (fname or "") + "\n" + (text or "")[:1500]
    for word, label in _AUTO_TYPE_WORDS.items():
        if word in blob:
            key = _AUTO_TYPE_SLUG.get(label, label)
            return {"key": key, "label": label}
    return None


# 自动聚类类型的中文 label -> 英文 slug(模板文件名/注册表key)
_AUTO_TYPE_SLUG = {
    "验收报告": "acceptance", "监测报告": "monitoring", "检测报告": "testing",
    "方法验证报告": "method-validation", "不确定度报告": "uncertainty",
    "环评报告": "eia", "质控报告": "qaqc",
    "排污许可报告": "emission-permit", "应急预案报告": "emergency-plan",
    "风险评估报告": "risk-assessment", "审计报告": "audit",
    "核查报告": "verification", "评估报告": "assessment",
    "调研报告": "research", "可行性研究报告": "feasibility",
    "评价报告": "evaluation", "年度报告": "annual", "监测月报": "monthly-monitoring",
}


def _extract_heading_sections(text):
    """从报告文本提取章节标题(Markdown 标题行/数字或中文序号章节行), 去重返回"""
    out, seen = [], set()
    _CN_NO = r"[一二三四五六七八九十百]+"
    for line in (text or "").splitlines():
        c = line.strip()
        # Markdown 标题
        m = re.match(r"^#{1,6}\s*(.+)", c)
        if m:
            c = m.group(1).strip()
        elif re.match(r"^\d+(\.\d+)*[、.．]\s*\S", c) and len(c) <= 30:
            c = re.sub(r"^\d+(\.\d+)*[、.．]\s*", "", c).strip()
        elif re.match(rf"^({_CN_NO})[、.]\s*\S", c) and len(c) <= 30:
            c = re.sub(rf"^({_CN_NO})[、.]\s*", "", c).strip()
        else:
            continue
        if not c or len(c) < 2 or len(c) > 30:
            continue
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
        if len(out) >= 25:
            break
    return out


def _aggregate_auto_sections(texts):
    """从多份自动聚类样本聚合高频章节标题(≥50%样本出现)"""
    if not texts:
        return []
    freq = {}
    per_doc = []
    for base, t in texts:
        secs = _extract_heading_sections(t)
        per_doc.append(secs)
        for s in set(secs):
            freq[s] = freq.get(s, 0) + 1
    n = len(texts)
    th = max(2, n // 2 + 1) if n > 2 else 1
    high = sorted([(k, v) for k, v in freq.items() if v >= th], key=lambda x: -x[1])
    # 限20个章节, 且排除疑似正文短句(含标点/数字过多)
    out = []
    for k, v in high[:20]:
        if re.search(r"[。；，、：]", k):
            continue
        out.append(k)
    return out


def _generate_template(tmpl_dir, template, rtype, label, sections):
    """根据学习到的章节自动生成模板骨架"""
    path = os.path.join(tmpl_dir, template)
    if os.path.exists(path):
        return path, False
    body = ["# {label} — 标准结构（自动生成）".format(label=label),
            "",
            "> 该模板由 skill_learn 对真实样本学习后自动生成（报告类型: {rtype}）。".format(rtype=rtype),
            "> 章节依据样本高频结构，编制时可参考对应标准/导则完善。",
            "",
            "## 一、封面与基本信息",
            "- 项目/任务名称、委托单位、编制单位、报告编号、日期",
            "",
            "## 二、正文结构",
            ""]
    for i, s in enumerate(sections, 1):
        body.append("{i}. **{s}**：".format(i=i, s=s))
        body.append("   - （待补充：该章节主要内容/表格要素）")
        body.append("")
    body.append("## 三、附件")
    body.append("附件1 委托书/任务单　附件2 原始记录/数据　附件3 相关证明材料")
    body.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(body))
    return path, True


def skill_learn(paths, skill="report-learning", dry_run=False, report_type="auto", task_id=None):
    """多类型报告批量学习(自动分门别类完善模板):
    对目录/文件中的样本文档(验收/监测/方法验证/不确定度/环评/质控等报告 PDF/Word)逐份 OCR 解析
    入库知识库, 自动识别报告类型(auto)或指定类型, 按类型提炼章节结构, 与对应模板比对,
    生成"模板学习报告"(各类别高频章节/新发现章节/缺失章节), 供完善模板。
    report_type: auto=自动识别; 或具体类型名(acceptance/monitoring/method-validation/
    uncertainty/eia/qaqc)。dry_run=True 时只分析不落库。"""
    files, missing = _resolve_kb_paths(paths)
    if not files:
        return "学习失败(无有效文件):\n" + _path_hint(missing)
    # 技能目录与模板定位(通用报告学习技能)
    skill_dir = os.path.join("data", "agents", "skills", skill)
    tmpl_dir = os.path.join(skill_dir, "references", "templates")
    os.makedirs(tmpl_dir, exist_ok=True)
    lines = [f"报告样本学习: skill={skill}, 样本 {len(files)} 份, 类型模式={report_type}"]
    # 每类报告的章节基线(模板中已有章节)
    base_keys = {}
    for rtype, cfg in _REPORT_TYPES.items():
        tp = os.path.join(tmpl_dir, cfg["template"])
        try:
            t = open(tp, encoding="utf-8").read()
            base_keys[rtype] = set(k for k in cfg["sections"] if k in t)
        except Exception:
            base_keys[rtype] = set()
    # 逐份学习: 解析 + 类型识别 + 入库(可跳过) + 章节提炼
    learned = []          # (文件名, eid, 类型, 章节列表)
    freq = {}             # 类型 -> {章节: 次数}
    type_count = {}       # 类型 -> 样本数
    new_found = {}        # 类型 -> 新章节集合
    auto_types = {}       # 自动识别的新类型: rtype -> {label, count, texts}
    import kb_pipeline as _kp
    for i, f in enumerate(files, 1):
        base = os.path.basename(f)
        # 1) 解析(OCR 自动兜底)
        try:
            md = _kp.extract_markdown(f)
        except Exception:
            md = ""
        if not (md or "").strip():
            lines.append(f"  [{i}/{len(files)}] {base}: 解析失败(空内容)")
            continue
        plain = _kp.md_from_text(md) or md
        # 2) 类型识别: 指定类型 > 注册表匹配 > 自动聚类新类型
        rtype = report_type if report_type in _REPORT_TYPES else _detect_report_type(plain, base)
        if not rtype:
            # 未命中注册表: 从文件名/标题提取报告种类词聚类(如"监测月报""排污许可年报"等)
            _guess = _auto_cluster_type(plain, base)
            if _guess:
                rtype = _guess["key"]
                at = auto_types.setdefault(rtype, {"label": _guess["label"], "count": 0, "texts": []})
                at["count"] += 1
                at["texts"].append((base, plain[:2000]))
        rtype = rtype or _DEFAULT_REPORT_TYPE
        # 3) 入库(默认; dry_run 跳过)
        eid = None
        if not dry_run:
            try:
                eid, _ = _kb_ingest_sync("", f, "other", source="技能样本学习")
            except Exception:
                eid = None
        # 4) 章节提炼: 先按注册表章节, 未注册新类型则提取标题行章节
        secs = _extract_report_sections(plain, rtype)
        if not secs and rtype in auto_types:
            secs = _extract_heading_sections(plain)
        learned.append((base, eid, rtype, secs))
        type_count[rtype] = type_count.get(rtype, 0) + 1
        fq = freq.setdefault(rtype, {})
        for k in secs:
            fq[k] = fq.get(k, 0) + 1
        nf = new_found.setdefault(rtype, set())
        bks = base_keys.get(rtype, set())
        if not bks or (set(secs) - bks):
            nf.update(set(secs) - bks)
        lines.append(f"  [{i}/{len(files)}] {base}: [{_REPORT_TYPES.get(rtype, {}).get('label', rtype)}] "
                     f"{'入库 id='+str(eid) if eid else '未入库'}, 章节 {len(secs)} 个")
    if not learned:
        return "\n".join(lines + ["学习失败: 无有效内容"])
    # 自动聚类的新类型: 注册 + 生成模板(样本>=2 或用户指定)
    newly_registered = []
    for rtype, at in sorted(auto_types.items(), key=lambda x: -x[1]["count"]):
        if at["count"] < 2:
            continue
        label = at["label"]
        # 从样本提炼章节(取高频标题行)
        secs = _aggregate_auto_sections(at["texts"])
        if not secs:
            continue
        template = f"{rtype}_template.md"
        _register_report_type(rtype, label, template, secs, [label, at["label"]])
        tp, created = _generate_template(tmpl_dir, template, rtype, label, secs)
        newly_registered.append((rtype, label, at["count"], template, created))
        lines.append(f"  [自动] 新报告类型 {label}({rtype}): 样本 {at['count']} 份, "
                     f"章节 {len(secs)} 个, {'生成模板 ' + template if created else '模板已存在'}")
    # 学习报告(按类型分组)
    lines.append(f"\n=== 模板学习报告 ===")
    for rtype, cnt in sorted(type_count.items(), key=lambda x: -x[1]):
        cfg = _REPORT_TYPES.get(rtype, {})
        fq = freq.get(rtype, {})
        n = cnt
        lines.append(f"\n--- {cfg.get('label', rtype)} ({n} 份) ---")
        lines.append(f"提炼章节特征 {len(fq)} 个")
        high = sorted([(k, v) for k, v in fq.items() if v >= max(2, n / 2)],
                      key=lambda x: -x[1])
        if high:
            lines.append(f"高频章节(≥{int(max(2, n/2))} 份):")
            for k, v in high:
                flag = "" if k in base_keys.get(rtype, set()) else " [新!]"
                lines.append(f"  - {k} ({v}/{n}){flag}")
        nf = new_found.get(rtype, set())
        if nf:
            lines.append("新发现章节(模板未覆盖):")
            for k in sorted(nf, key=lambda x: -fq.get(x, 0)):
                lines.append(f"  - {k} ({fq.get(k, 0)}/{n})")
        bks = base_keys.get(rtype, set())
        if bks:
            never = [k for k in bks if k not in fq]
            if never:
                lines.append(f"模板有但样本未出现的章节({len(never)}): {', '.join(never)}")
        # 模板文件确认/提示
        tp = os.path.join(tmpl_dir, cfg.get("template", ""))
        exists = os.path.exists(tp) if tp else False
        if tp:
            lines.append(f"模板: {'已存在 ' + cfg['template'] if exists else '缺失(建议按高频章节生成 ' + cfg['template'] + ')'}")
    # 学习记录写盘(按类型)
    try:
        learn_dir = os.path.join("data", "learn")
        os.makedirs(learn_dir, exist_ok=True)
        import time as _t
        rp = os.path.join(learn_dir, f"{skill}_{_t.strftime('%Y%m%d_%H%M%S')}.json")
        with open(rp, "w", encoding="utf-8") as fh:
            json.dump({"skill": skill, "samples": len(learned), "type_count": type_count,
                       "freq": freq, "new_found": {k: sorted(v) for k, v in new_found.items()},
                       "learned": [
                           {"file": b, "eid": e, "type": t, "sections": s}
                           for b, e, t, s in learned
                       ]}, fh, ensure_ascii=False, indent=1)
        lines.append(f"\n学习记录: {rp}")
    except Exception:
        pass
    if dry_run:
        lines.append("\n[dry_run] 未落库, 仅分析")
    return "\n".join(lines)


def report_build(report_type, title="", out_dir="", task_id=None):
    """报告编制(自动调用): 按报告类型匹配已学习模板, 生成报告骨架 Markdown。
    report_type: 类型名(acceptance/monitoring/method-validation/uncertainty/eia/qaqc 或
    自动学习新增的类型key); 支持中文类型名自动匹配(label)。
    生成骨架后, 报告内容由 Agent 结合知识库/素材填充。"""
    global _REPORT_TYPES
    if not _REPORT_TYPES:
        _REPORT_TYPES = _load_report_types()
    # 匹配类型: 英文key 或 中文label
    cfg = None
    if report_type in _REPORT_TYPES:
        cfg = _REPORT_TYPES[report_type]
    else:
        for k, c in _REPORT_TYPES.items():
            if c.get("label") == report_type or report_type in c.get("label", ""):
                cfg = c
                report_type = k
                break
    if not cfg:
        known = "、".join(f"{k}({c.get('label','')})" for k, c in _REPORT_TYPES.items())
        return (f"报告编制失败: 未知报告类型「{report_type}」。\n"
                f"已知类型: {known}\n"
                f"可用 skill_learn 学习该类型报告后自动注册新模板。")
    # 模板定位
    skill_dir = os.path.join("data", "agents", "skills", "report-learning")
    tmpl_dir = os.path.join(skill_dir, "references", "templates")
    tp = os.path.join(tmpl_dir, cfg.get("template", ""))
    if not os.path.exists(tp):
        return f"报告编制失败: 模板缺失 {tp}。可先用 skill_learn 学习该类报告生成模板。"
    tmpl = open(tp, encoding="utf-8").read()
    # 骨架生成: 提取模板章节
    sections = []
    for line in tmpl.splitlines():
        m = re.match(r"^#{1,4}\s+(.+)$", line.strip())
        if m:
            sections.append(m.group(1).strip())
        elif re.match(r"^\d+[、.．]\s*\S", line.strip()):
            sections.append(re.sub(r"^\d+[、.．]\s*", "", line.strip()))
    if not sections:
        sections = cfg.get("sections", [])
    t = title or f"{cfg['label']}骨架"
    out = [f"# {t}", "", f"> 报告类型: {cfg['label']} | 模板: {cfg.get('template')} | 由 report_build 生成骨架",
           "", f"## 一、基本信息", f"- 项目/任务名称: 【待补充】", f"- 委托单位: 【待补充】",
           f"- 编制单位: 【待补充】", f"- 报告编号/日期: 【待补充】", "", "## 二、正文", ""]
    for i, s in enumerate(sections, 1):
        out.append(f"{i}. **{s}**")
        out.append(f"   - 【待补充: {s} 内容/表格要素】")
        out.append("")
    out.append("## 三、附件")
    out.append("附件1 【待补充】")
    md = "\n".join(out)
    # 落盘(可选)
    saved = ""
    if out_dir:
        try:
            os.makedirs(out_dir, exist_ok=True)
            rp = os.path.join(out_dir, f"{t}.md")
            with open(rp, "w", encoding="utf-8") as f:
                f.write(md)
            saved = rp
        except Exception:
            saved = ""
    # 写回当前任务附件目录(便于用户直接查看)
    if task_id and not saved:
        try:
            tdir = db.task_output_dir(task_id)
            rp = os.path.join(tdir, f"{t}.md")
            os.makedirs(tdir, exist_ok=True)
            with open(rp, "w", encoding="utf-8") as f:
                f.write(md)
            saved = rp
        except Exception:
            pass
    return (f"报告骨架已生成: {cfg['label']}({report_type})\n"
            f"章节 {len(sections)} 个, 已按模板 {cfg.get('template')} 展开为骨架(带【待补充】占位)\n"
            f"{('已保存: ' + saved) if saved else '未保存(可要求保存到指定目录)'}\n"
            f"后续请结合知识库/素材填充各章节后生成正式报告。")


def kb_interpret(entry_id, check=True):
    """标准/政策文件智能解读与查新: 生成结构化解读(元信息/一句话总结/章节骨架/
    核心内容浓缩/修订要点/引用网络)并联网确认现行有效/废止, 结果写回条目并落盘 解读.md。
    entry_id 为知识库条目 id; check=True 时同时执行联网查新(现行/废止/被替代判定)。"""
    try:
        import standard_intel as _si
        r = _si.interpret_entry(int(entry_id), do_check=check, sync=True)
        if not r.get("ok"):
            return f"解读失败: {r.get('reason')}"
        return (f"智能解读完成(id={r['eid']}, 标准号: {r['std_no'] or '无'}, 引擎: {r['engine']})\n"
                f"查新结论: {r['validity']}\n章节骨架 {r['skeleton']} 条, 引用标准 {r['refs']} 个\n"
                f"已落盘解读文件与元数据, 详情见知识库条目与 data/kb/interpretations/")
    except Exception as e:
        return f"解读失败: {e}"


def kb_recheck_batch(limit=200, only_unchecked=True):
    """存量批量查新重检: 对 std_no 非空条目后台逐个联网查新(现行/废止), 不改内容只更新 validity"""
    try:
        import standard_intel as _si
        r = _si.batch_recheck(limit=limit, only_unchecked=only_unchecked)
        return f"批量查新重检已入队: 匹配 {r['matched']} 条, 实际入队 {r['queued']} 条(后台串行执行)"
    except Exception as e:
        return f"批量查新重检失败: {e}"


def kb_summarize(entry_id):
    """通用文档智能总结: 对任意知识库条目生成多版本总结(一句话/TL;DR/结构化长摘要/
    核心要点/章节要点/关键参数)并做质量验证(数字回校/幻觉拦截), 结果写回条目并落盘 总结.md。"""
    try:
        import doc_intel as _di
        r = _di.summarize_entry(int(entry_id), sync=True)
        if not r.get("ok"):
            return f"智能总结失败: {r.get('reason')}"
        vf = r.get("verify") or {}
        return (f"智能总结完成(id={r['eid']}, 引擎: {r['engine']}, 文档类型: {r.get('doc_type')})\n"
                f"一句话: {r.get('one_liner') or ''}\n"
                f"质量验证: 数字回校 {vf.get('numbers_checked', 0)} 个, 未回校 "
                f"{len(vf.get('numbers_missing') or [])} 个, 状态 "
                f"{'通过' if vf.get('passed') else '待复核'}\n"
                f"已落盘总结文件与元数据, 详情见知识库条目与 data/kb/summaries/")
    except Exception as e:
        return f"智能总结失败: {e}"


def kb_summarize_batch(limit=200, only_missing=True):
    """存量批量智能总结: 对未生成过总结的条目后台逐个生成多版本总结(后台串行执行)"""
    try:
        import doc_intel as _di
        r = _di.batch_summarize(limit=limit, only_missing=only_missing)
        return f"批量智能总结已入队: 匹配 {r['matched']} 条, 实际入队 {r['queued']} 条(后台串行执行)"
    except Exception as e:
        return f"批量智能总结失败: {e}"


def kb_audit():
    """知识库健康审计: 完整性/置信度/纠错积压/冲突/重复检测, 输出健康分与问题清单"""
    r = db.kb_audit()
    lines = [
        f"知识库健康审计: 健康分 {r['health']}/100",
        f"条目 {r['total']} 条 | 已分块 {r['chunked']} 条 | QA {r['qa_entries']} | 记忆 {r['memories']} | 缓存 {r['cache_entries']}",
        f"缺来源 {r['no_source']} | 缺机构 {r['no_org']} | 待复核 {r['flagged']} | 低置信 {r['low_confidence']}",
        f"纠错待处理 {r['pending_corrections']} | 冲突 {r['conflicts']} | 重复标准号 {r['duplicate_std']}",
    ]
    issues = []
    if r["no_source"]:
        issues.append(f"有 {r['no_source']} 条无来源信息, 建议补充 url/source")
    if r["no_org"]:
        issues.append(f"有 {r['no_org']} 条缺发布机构")
    if r["flagged"]:
        issues.append(f"有 {r['flagged']} 条待复核(纠错修正后)")
    if r["conflicts"]:
        issues.append(f"检测到 {r['conflicts']} 处冲突(标准号有效性/重复), 建议 kb_relation 建替代关系")
    if r["duplicate_std"]:
        issues.append(f"标准号重复 {r['duplicate_std']} 处")
    if issues:
        lines.append("问题清单:")
        lines.extend(f"- {x}" for x in issues)
    return "\n".join(lines)


def kb_harvest(title, qa_pairs, prefs=None, facts=None):
    """对话收割: 将问答对沉淀为知识条目、偏好与事实写入记忆表"""
    try:
        r = db.kb_harvest_conversation(title, qa_pairs or [], prefs, facts)
    except Exception as e:
        return f"对话收割失败: {e}"
    return (f"对话收割完成: 沉淀知识条目 {r['entries']} 条, 写入记忆 {r['memories']} 条"
            f"(来源对话: {title})")


def kb_export(domain=None, fmt="json"):
    """导出知识库为 zip(json 全字段或 markdown 可读版)"""
    try:
        r = db.kb_export(domain=domain, fmt=fmt)
    except Exception as e:
        return f"导出失败: {e}"
    return (f"知识库导出完成: {r['filename']} ({r['count']} 条, {r['size']} 字节)\n"
            f"格式: {fmt} | 领域: {domain or '全部'}")


def kb_backup(kind="manual", note=""):
    """知识库自动备份: VACUUM INTO 数据库快照 + kb/ 目录 zip 打包"""
    try:
        r = db.kb_backup(kind=kind or "manual", note=note or "Agent触发")
    except Exception as e:
        return f"备份失败: {e}"
    return (f"知识库备份完成({r['kind']}): 数据库快照 {r['db_size']} 字节, "
            f"kb 目录 {r['files_count']} 个文件\n路径: {r['db_path'] or r['zip_path']}")


def memory_set(key, content):
    db.memory_set(key, content)
    return f"已写入任务记忆 [{key}]"


def memory_get(key):
    r = db.memory_get(key)
    return f"[{key}] = {r['content']}" if r else f"记忆中无 [{key}]"


def vision_analyze(args):
    """G6 图片视觉理解：VLM 直读优先，RapidOCR 兜底。"""
    from src.vision.analyze import analyze_image
    r = analyze_image(args.get("path", ""), args.get("question", ""))
    if not r.get("ok"):
        return f"[图片识别失败] {r.get('error')}"
    method = r.get("method", "vlm")
    return (f"[图片识别 ({method})]\n{r.get('text')}")


def spawn_subagent(args):
    """G2 动态子代理：按角色派生后台子代理执行子任务，可回收结果。"""
    from src.agents.subagent import SubAgentRunner, SubAgentSpec
    action = (args.get("action") or "spawn").strip().lower()
    runner = SubAgentRunner()
    if action == "list":
        jobs = runner.list()
        return "运行中子代理: " + ("、".join(f"{j['id']}({j['status']})" for j in jobs)
                                   if jobs else "无")
    if action == "collect":
        sub_id = (args.get("sub_id") or "").strip()
        if not sub_id:
            return "缺少 sub_id"
        r = runner.collect(sub_id, float(args.get("timeout") or 60))
        if not r:
            return f"子代理 {sub_id} 不存在"
        res = r.get("result") or {}
        return (f"[子代理 {r['id']} status={r['status']}] ok={res.get('ok')} "
                f"role={res.get('role')} tool_calls={res.get('tool_calls')}\n"
                f"结果: {str(res.get('result') or '')[:500]}")
    # spawn
    task = (args.get("task") or "").strip()
    if not task:
        return "缺少 task（子任务描述）"
    spec = SubAgentSpec(name=(args.get("name") or "subagent"),
                        role_id=(args.get("role_id") or "R4").upper())
    sub_id = runner.spawn(spec, task)
    return (f"已派生子代理 {sub_id}（{spec.name}，角色 {spec.role_id}）后台执行中。"
            f"用 spawn_subagent action=collect sub_id={sub_id} 回收结果。")


def schedule_task(args):
    """H2 定时任务：自然语言 -> 应用内调度器（到期自动建任务执行）。"""
    from src.scheduler import ScheduleManager, parse_nl
    mgr = ScheduleManager()
    action = (args.get("action") or "add").strip().lower()
    if action == "list":
        rows = mgr.list()
        if not rows:
            return "暂无定时任务"
        lines = ["[定时任务列表]"]
        for r in rows:
            on = "ON" if r["enabled"] else "OFF"
            nxt = r.get("next_run") or "-"
            lines.append(f"#{r['id']} [{on}] {r['title']} (cron={r['cron_desc']}, 下次={nxt})")
        return "\n".join(lines)
    if action in ("pause", "resume", "remove"):
        sid = int(args.get("sid") or 0)
        if not sid:
            return "缺少 sid（定时任务id）"
        r = getattr(mgr, action)(sid)
        return ("已暂停" if action == "pause" else "已恢复" if action == "resume" else "已删除") \
            + f"定时任务 #{sid}" if r.get("ok") else f"操作失败: {r.get('error')}"
    # H3 Cron 记忆：notepad（草稿本读写）/ continuity（上次摘要注入开关）
    if action == "notepad":
        sid = int(args.get("sid") or 0)
        if not sid:
            return "缺少 sid（定时任务id）"
        text = (args.get("text") or "").strip()
        if text:
            r = mgr.set_notepad(sid, text)
            return f"已更新任务 #{sid} 草稿本" if r.get("ok") else f"操作失败: {r.get('error')}"
        r = mgr.get_notepad(sid)
        if not r.get("ok"):
            return f"操作失败: {r.get('error')}"
        return (f"[任务 #{sid} 草稿本]\n{r.get('notepad') or '(空)'}"
                + "\n更新请用 schedule_task action=notepad sid=N text=...")
    if action == "continuity":
        sid = int(args.get("sid") or 0)
        if not sid:
            return "缺少 sid（定时任务id）"
        on = str(args.get("on", "1")).lower() in ("1", "true", "yes", "on")
        r = mgr.set_continuity(sid, on)
        return (f"任务 #{sid} continuity 已{'开启' if on else '关闭'}"
                if r.get("ok") else f"操作失败: {r.get('error')}")
    # add
    title = (args.get("title") or "").strip()
    if not title:
        return "缺少 title（如'每天9点生成空气质量日报'）"
    r = mgr.add(title, args.get("cron_desc") or "", args.get("prompt") or "",
                args.get("mode") or "craft")
    if not r.get("ok"):
        return f"添加失败: {r.get('error')}"
    return (f"已创建定时任务 #{r['id']}: {title}\n"
            f"cron: {r['cron_desc']} | 下次执行: {r['next_run']}\n"
            f"到期将自动创建任务并执行。可用 schedule_task action=list 查看，"
            f"action=pause/resume/remove 管理。")


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "kb_lookup",
            "description": "检索本地生态环境知识库(含标准规范/政策法规/政府发布/网络资料),按相关度返回。回答前应优先调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词,可多词以空格分隔"},
                    "top_n": {"type": "integer", "description": "返回条数,默认5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "locate",
            "description": "精确定位本地知识库条目:按标准编号/标题/来源URL 查找, 返回条目 id、分类、来源与落库时间。落库前或回答出处问题时调用, 避免重复落库。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "要定位的标准编号/标题/URL 关键词"},
                    "limit": {"type": "integer", "description": "返回条数,默认5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_stats",
            "description": "知识库统计: 条目总量、分类/有效性分布、平均置信度、待复核数、纠错单与关系数",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_correct",
            "description": "知识库纠错: 登记纠错单并标记待处理; 提供 corrected_content 时应用修正、条目降置信度待复核",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "integer", "description": "条目id(kb_lookup/locate 可查)"},
                    "issue": {"type": "string", "description": "发现的问题描述"},
                    "suggestion": {"type": "string", "description": "建议的修正方向"},
                    "corrected_content": {"type": "string", "description": "可选: 修正后的完整内容"},
                },
                "required": ["entry_id", "issue"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_relation",
            "description": "知识库关系: 在两条条目间建立 related/supersedes/derived_from 关系",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_id": {"type": "integer", "description": "来源条目id"},
                    "to_id": {"type": "integer", "description": "目标条目id"},
                    "rel_type": {"type": "string", "description": "关系类型: related/supersedes/derived_from, 默认related"},
                    "note": {"type": "string", "description": "关系说明"},
                },
                "required": ["from_id", "to_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_hybrid",
            "description": "多路召回检索知识库(全文FTS+语义向量+关系扩散, RRF融合排序), 适合语义相近但关键词不同的查询, 命中带召回来源标记",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词或自然语言描述"},
                    "top_n": {"type": "integer", "description": "返回条数,默认5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_vector",
            "description": "语义向量检索知识库(本地哈希词袋向量, 无需嵌入模型), 对同义词/语义改写场景优于全文检索",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索语义描述"},
                    "top_n": {"type": "integer", "description": "返回条数,默认5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_import",
            "description": "批量导入本地文档到知识库(PDF/DOCX/HTML/TXT/MD/XLSX): 自动解析文本、规则提取标准号/机构/日期、自动分类、落库并分块向量化",
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {"type": "string",
                              "description": "文件路径或目录路径, 多个用逗号分隔(目录则递归扫描支持格式)。路径规则: 推荐绝对路径, 或相对项目根的路径如 data/uploads/<文件名>; 支持直接传裸文件名(自动到 data/uploads/ 下查找)。若找不到会自动列出 uploads 目录可用文件供重试"},
                    "batch_name": {"type": "string", "description": "批次名称(默认batch)"},
                },
                "required": ["paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_convert",
            "description": "本地文档转 Markdown 存档(PDF/图片/DOCX/HTML/XLSX/TXT, 支持目录批量): 扫描版 PDF 优先纯本地 RapidAI 全家桶(RapidLayout版面分析+RapidOCR文字+RapidTable表格+RapidLaTeXOCR公式)转结构化 Markdown, 化学式/LaTeX公式/Markdown表格/条款编号完整保留; 未安装或失败回退 VLM 六步管线(需多模态 Provider), 再回退传统 RapidOCR, 功能不降级。",
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {"type": "string",
                              "description": "文件或目录路径, 多个用逗号分隔(目录递归扫描 pdf/png/jpg/docx/xlsx 等)。路径规则: 推荐绝对路径, 或相对项目根路径如 data/uploads/<文件名>; 支持裸文件名(自动到 data/uploads/ 查找)。找不到时自动列出 uploads 可用文件供重试"},
                    "out_dir": {"type": "string", "description": "可选: 存档目录(默认 data/convert_md/)"},
                    "dpi": {"type": "integer", "description": "可选: 扫描页渲染分辨率, 默认144"},
                    "page_batch": {"type": "integer", "description": "可选: VLM 逐批转录每批页数, 默认4"},
                },
                "required": ["paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill_learn",
            "description": "多类型报告批量学习(自动分门别类完善模板): 对目录/文件中的样本文档(验收报告/监测报告/方法验证报告/不确定度报告/环评报告/质控报告等 PDF/Word)逐份 OCR 解析入库知识库, 自动识别报告类型(auto)并按类型提炼章节结构, 与对应模板比对, 输出模板学习报告(各类别高频章节/新发现章节/缺失章节), 供完善模板。用户提供一批同类或多类报告/文档让 Agent 学习并完善模板时调用; 单份报告亦可(dry_run=true 先分析不落库)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {"type": "string",
                              "description": "文件或目录路径, 多个用逗号分隔(目录递归扫描)。推荐绝对路径"},
                    "skill": {"type": "string", "description": "技能名(默认 report-learning 通用报告学习技能)"},
                    "report_type": {"type": "string", "enum": ["auto", "acceptance", "monitoring", "method-validation", "uncertainty", "eia", "qaqc"],
                                    "description": "报告类型: auto=自动识别(默认); 或指定类型(含学习后动态注册的新类型)"},
                    "dry_run": {"type": "boolean", "description": "true=只分析不落库"},
                },
                "required": ["paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_build",
            "description": "报告编制(自动调用模板): 按报告类型匹配已学习的模板(acceptance验收/monitoring监测/method-validation方法验证/uncertainty不确定度/eia环评/qaqc质控 及 skill_learn 自动学习注册的新类型, 支持中文类型名), 生成报告骨架 Markdown(带【待补充】占位)。用户要求编制/生成XX报告且该类型已有模板时调用; 若类型无模板先用 skill_learn 学习。",
            "parameters": {
                "type": "object",
                "properties": {
                    "report_type": {"type": "string", "description": "报告类型key或中文名, 如 acceptance / 验收报告 / monitoring"},
                    "title": {"type": "string", "description": "报告标题(可选)"},
                    "out_dir": {"type": "string", "description": "骨架保存目录(可选, 默认写任务附件目录)"},
                },
                "required": ["report_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_audit",
            "description": "知识库健康审计: 输出健康分、完整性/置信度/纠错积压/冲突/重复检测报告与问题清单",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_harvest",
            "description": "对话收割: 将本次对话的问答对沉淀为知识条目、用户偏好/事实写入记忆表, 供后续任务复用",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "对话主题, 作为来源标记"},
                    "qa_pairs": {"type": "array", "items": {"type": "array", "items": {"type": "string"}},
                                 "description": "问答对列表, 每项为 [问题, 答案]"},
                    "prefs": {"type": "array", "items": {"type": "string"},
                              "description": "可选: 用户偏好列表"},
                    "facts": {"type": "array", "items": {"type": "string"},
                              "description": "可选: 事实列表"},
                },
                "required": ["title", "qa_pairs"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_export",
            "description": "导出知识库为 zip 压缩包(json 全字段或 markdown 可读版), 支持按领域过滤",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "可选: 领域过滤(如 环保行业/环评/法律)"},
                    "fmt": {"type": "string", "enum": ["json", "markdown"],
                            "description": "导出格式, 默认json"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_backup",
            "description": "知识库自动备份: 生成数据库快照(VACUUM INTO)与 kb/ 目录 zip 压缩包, 可每日定时或手动触发。",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["manual", "daily", "startup"],
                             "description": "备份类型, 默认manual"},
                    "note": {"type": "string", "description": "可选: 备份备注"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索最新资料(政策、标准、监测方法、限值等)。支持站点限定与时间过滤, 用于补充本地知识库的不足。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "top_n": {"type": "integer", "description": "返回条数,默认5"},
                    "site_filter": {"type": "string",
                                     "description": "可选: 站点限定域名(如 mee.gov.cn), 自动加 site: 定向政府/官方来源"},
                    "time_range": {"type": "string", "enum": ["d", "w", "m", "y"],
                                   "description": "可选: 时间范围 d=24小时 w=一周 m=一月 y=一年"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "抓取网页正文(转 Markdown, 保留标题/段落/列表/表格)或下载 PDF 解析全文(Markdown)。标准/法规/规范等文档链接为 PDF 时直接传 PDF 链接, 将自动下载并全文解析。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "完整 URL(支持网页与 PDF 链接)"},
                    "max_chars": {"type": "integer", "description": "最大字符数,默认30000; 全文入库可传更大值"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "std_import",
            "description": "标准/政府文件检索入库(免链接): 仅凭标准名称/标准号(如 HJ 91.2-2022、地表水环境质量监测技术规范)或政府文件名称(如 排污许可管理条例、生态环境部关于开展XX的通知)自动联网搜索官方来源(优先生态环境部 mee.gov.cn/国家标准公开平台/政府站), 抓取公告页并自动下载 PDF 附件解析全文, 提取标准号/文号/机构/发布与实施日期等元数据, 自动分类(标准规范/政策法规/政府发布/征求意见稿)后全文入库, 并后台触发智能解读+联网查新+总结。所有标准与政府文件入库一律调用本工具, 无需提供链接。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "标准名称/标准号或政府文件名称, 如 'HJ 91.2-2022'、'地表水环境质量监测技术规范'、'排污许可管理条例'、'生态保护红线管理办法'"},
                    "category": {"type": "string", "enum": ["standard", "network", "gov", "policy", "draft", "other"],
                                 "description": "可选: 强制指定分类; 缺省按文档类型自动判断(标准→标准规范, 法规政策→政策法规, 政府站→政府发布, 征求意见→征求意见稿)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_save",
            "description": "把资料全文落库到本地知识库(五分类), 供后续任务复用。要求全文入库: 应先把网页/PDF 用 web_fetch 抓取全文(Markdown)后整体作为 content 传入; 若 content 过短且提供 url, 将自动抓取来源全文(含 PDF 解析)后入库。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "资料标题"},
                    "url": {"type": "string", "description": "来源链接(可为空)"},
                    "category": {"type": "string", "enum": ["network", "gov", "standard", "policy", "other"],
                                 "description": "分类: 网络资料/政府发布/标准规范/政策法规/其他"},
                    "content": {"type": "string", "description": "资料全文内容(Markdown 格式, 不截断)"},
                },
                "required": ["title", "category", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_interpret",
            "description": "标准/政策文件智能解读与查新: 生成结构化解读(元信息/一句话总结/章节骨架/核心内容浓缩/修订要点/引用网络)并联网确认该标准或政策现行有效/已废止/被替代, 结果写回条目并落盘解读文件。用户询问某标准/政策是否现行有效时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "integer", "description": "知识库条目 id"},
                    "check": {"type": "boolean", "description": "是否同步联网查新, 默认 true"},
                },
                "required": ["entry_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_recheck_batch",
            "description": "存量知识库批量查新重检: 对标准号非空且未查新过的条目, 后台逐个联网确认现行有效/废止, 更新 validity 标记。首次上线查新功能后用于存量数据批量补检。",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "最多重检条数, 默认200"},
                    "only_unchecked": {"type": "boolean", "description": "仅重检未查新过的条目, 默认 true"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_summarize",
            "description": "通用文档智能总结: 对任意知识库条目(不限标准/政策)生成多版本总结(一句话/TL;DR/结构化长摘要/核心要点/章节要点/关键参数)并做质量验证(数字回校/幻觉拦截), 结果写回条目并落盘总结文件。用户需要快速理解某文档内容/要点时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "integer", "description": "知识库条目 id"},
                },
                "required": ["entry_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_summarize_batch",
            "description": "存量知识库批量智能总结: 对未生成过总结的条目, 后台逐个生成多版本总结(一句话/TL;DR/结构化长摘要)。首次上线智能总结功能后用于存量数据批量补总结。",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "最多处理条数, 默认200"},
                    "only_missing": {"type": "boolean", "description": "仅处理未生成过总结的条目, 默认 true"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_set",
            "description": "把用户明确告知的项目事实/偏好写入任务记忆(长期保留,跨会话注入)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "记忆键名(英文或简短描述)"},
                    "content": {"type": "string", "description": "记忆内容"},
                },
                "required": ["key", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_get",
            "description": "读取任务记忆中保存的某条内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "记忆键名"},
                },
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calc_formula",
            "description": "标准驱动公式计算（FormulaEngine）：按标准号或计算类型自动匹配公式并计算，含单位自动换算，返回结果与计算过程。",
            "parameters": {
                "type": "object",
                "properties": {
                    "standard": {"type": "string", "description": "标准号，如 GB 3838-2002（留空则按 calc_type 匹配）"},
                    "calc_type": {"type": "string", "description": "计算类型：污染指数/超标倍数/均值/综合污染指数/达标判定/排放速率"},
                    "data": {"type": "object", "description": "参数：键为参数名或别名（Ci/Si/C/V），值可为数值或 {value, unit}（单位自动换算）"},
                    "formula_id": {"type": "string", "description": "可选：显式公式 id（如 std-index-single）"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vision_analyze",
            "description": "图片视觉理解（G6）：识别现场照片/报表截图/扫描件内容。多模态 Provider 可用时 VLM 直读（可带问题），否则 RapidOCR 提取文字。path 可为上传附件路径。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "图片路径（如上传附件返回的 path）"},
                    "question": {"type": "string", "description": "可选：针对图片的具体问题，如'识别表格中的监测数据'"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_subagent",
            "description": "动态子代理（G2）：按角色(R1-R8)派生一个子代理在后台执行子任务（独立上下文，不占用当前对话窗口），可立即用 action=collect 回收结果。例：把'检索该项目所有水质标准限值'派给 R2 检索员。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["spawn", "collect", "list"],
                               "description": "spawn=启动子代理 / collect=回收结果(需sub_id) / list=查看运行中"},
                    "task": {"type": "string", "description": "子代理要执行的子任务描述"},
                    "role_id": {"type": "string", "enum": ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"],
                                "description": "角色（默认 R4 编制员）"},
                    "name": {"type": "string", "description": "子代理名，默认 subagent"},
                    "sub_id": {"type": "string", "description": "collect 时必填：spawn 返回的子代理 id"},
                    "timeout": {"type": "number", "description": "collect 等待秒数，默认 60"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_task",
            "description": "定时任务调度：把自然语言描述转为定时任务（如'每天9点生成空气质量日报'），到期自动创建任务并执行。支持：每天X点 / 每周X HH:MM / 每小时 / 每N分钟；action=list 查看全部；action=pause/resume/remove 管理指定 id。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "list", "pause", "resume", "remove"],
                               "description": "操作类型，默认add"},
                    "title": {"type": "string", "description": "定时任务标题，含自然语言时间描述，如'每天9点生成空气质量日报'"},
                    "prompt": {"type": "string", "description": "到期后自动执行的任务指令（缺省用标题）"},
                    "mode": {"type": "string", "description": "任务模式，默认craft"},
                    "sid": {"type": "integer", "description": "定时任务id（pause/resume/remove 必填）"},
                },
                "required": [],
            },
        },
    },
]


def _run_calc_formula(args):
    """执行 FormulaEngine 计算，返回可读结果。"""
    try:
        from src.compute.engine import FormulaEngine
        r = FormulaEngine().calc(
            args.get("standard", ""), args.get("calc_type", ""),
            args.get("data") or {}, args.get("formula_id", ""))
        if not r.get("ok"):
            return f"计算失败: {r.get('error')}"
        return (f"[{r['name']}] = {r['value']} {r['unit']}\n"
                f"公式: {r['expr']}（{r.get('standard', '')} {r.get('clause', '')}）\n"
                f"过程: {'; '.join(r['trace'])}")
    except Exception as e:
        return f"计算失败: {e}"


def execute_tool(name, args, task_id=None):
    """执行工具,返回 (ok: bool, output: str)"""
    try:
        if name == "calc_formula":
            return True, _run_calc_formula(args)
        if name == "kb_lookup":
            return True, kb_lookup(args.get("query", ""), int(args.get("top_n", 5)))
        if name == "locate":
            return True, locate(args.get("query", ""), int(args.get("limit", 5)))
        if name == "kb_stats":
            return True, kb_stats_tool()
        if name == "kb_correct":
            return True, kb_correct(int(args.get("entry_id", 0)), args.get("issue", ""),
                                    args.get("suggestion", ""), args.get("corrected_content", ""))
        if name == "kb_relation":
            return True, kb_relation(int(args.get("from_id", 0)), int(args.get("to_id", 0)),
                                     args.get("rel_type", "related"), args.get("note", ""))
        if name == "web_search":
            return True, web_search(
                args.get("query", ""),
                int(args.get("top_n", 5)),
                site_filter=args.get("site_filter"),
                time_range=args.get("time_range"),
            )
        if name == "web_fetch":
            return True, web_fetch(args.get("url", ""), int(args.get("max_chars", 30000)), task_id=task_id)
        if name == "kb_save":
            return True, kb_save(args.get("title", ""), args.get("url", ""), args.get("category", "other"),
                                 args.get("content", ""), task_id=task_id)
        if name == "std_import":
            return True, std_import(args.get("query", ""), args.get("category", "") or "", task_id=task_id)
        if name == "memory_set":
            return True, memory_set(args.get("key", ""), args.get("content", ""))
        if name == "memory_get":
            return True, memory_get(args.get("key", ""))
        if name == "schedule_task":
            return True, schedule_task(args)
        if name == "spawn_subagent":
            return True, spawn_subagent(args)
        if name == "vision_analyze":
            return True, vision_analyze(args)
        if name == "kb_hybrid":
            return True, kb_hybrid(args.get("query", ""), int(args.get("top_n", 5)))
        if name == "kb_vector":
            return True, kb_vector(args.get("query", ""), int(args.get("top_n", 5)))
        if name == "kb_import":
            return True, kb_import(args.get("paths", ""), args.get("batch_name", ""))
        if name == "kb_convert":
            return True, kb_convert(args.get("paths", ""), args.get("out_dir", ""),
                                    int(args.get("dpi") or 144), int(args.get("page_batch") or 4))
        if name == "skill_learn":
            return True, skill_learn(args.get("paths", ""), args.get("skill", "report-learning"),
                                     bool(args.get("dry_run")), args.get("report_type", "auto"),
                                     task_id=task_id)
        if name == "report_build":
            return True, report_build(args.get("report_type", ""), args.get("title", ""),
                                      args.get("out_dir", ""), task_id=task_id)
        if name == "kb_audit":
            return True, kb_audit()
        if name == "kb_harvest":
            return True, kb_harvest(args.get("title", ""), args.get("qa_pairs") or [],
                                    args.get("prefs"), args.get("facts"))
        if name == "kb_export":
            return True, kb_export(args.get("domain"), args.get("fmt", "json"))
        if name == "kb_backup":
            return True, kb_backup(args.get("kind", "manual"), args.get("note", ""))
        if name == "kb_interpret":
            return True, kb_interpret(int(args.get("entry_id", 0)),
                                      bool(args.get("check", True)))
        if name == "kb_recheck_batch":
            return True, kb_recheck_batch(int(args.get("limit", 200)),
                                          bool(args.get("only_unchecked", True)))
        if name == "kb_summarize":
            return True, kb_summarize(int(args.get("entry_id", 0)))
        if name == "kb_summarize_batch":
            return True, kb_summarize_batch(int(args.get("limit", 200)),
                                            bool(args.get("only_missing", True)))
        return False, f"未知工具: {name}"
    except Exception as e:
        return False, f"工具执行异常: {e}"
