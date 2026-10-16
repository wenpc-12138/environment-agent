# -*- coding: utf-8 -*-
"""standard_intel.py - 标准/政策文件智能解读与联网查新
参考 HJ 535-2009 结构化解读样例设计(元信息/一句话总结/章节骨架/核心内容浓缩/修订要点/引用网络),
并在此基础上实现联网查新(现行有效/已废止/被替代/未知)。

三层能力:
  1. 规则层(离线零成本, 永不失败): 章节骨架抽取、引用网络抽取、元信息补全
  2. LLM 层(活跃 Provider 且非 mock): 一句话总结 + 核心内容浓缩 + 修订要点(JSON)
  3. 查新层(SearXNG): 按 std_no/标题联网检索官方渠道, 判定 现行/废止/被替代/未知

结果写入 kb_entries.metadata_json.{interpret,currency} 并落盘
data/kb/interpretations/<std_no>_解读.md(参考样例 7 区块格式)。
"""

import json
import os
import re
import threading
from datetime import datetime

# ---------------- 章节骨架抽取 ----------------
_SKEL_RE = re.compile(r"^(\d+(?:\.\d+)*)[、.．\s]+(.{1,50})$")
_SKEL_SKIP = {"目次", "前言", "目录", "引言", "附", "附录", "索引", "参考文献", "封底"}
_REF_RE = re.compile(
    r"(?<![A-Z0-9])[A-Z]{1,4}(?:[/-][A-Z]{1,4})?/?(?:T|Z)?[-—–]?\s*\d{2,6}(?:\.\d+)*(?:[-—–]\d{4})?(?![0-9])")


def extract_skeleton(md, max_items=60):
    """从 Markdown 正文抽取章节骨架: [{"no":"1","title":"适用范围"}, ...]"""
    if not md:
        return []
    out, seen = [], set()
    for line in md.splitlines():
        line = line.strip()
        if not line or len(line) > 60:
            continue
        m = _SKEL_RE.match(line)
        if not m:
            continue
        no, title = m.group(1), m.group(2).strip()
        if len(title) < 2 or re.search(r"[。．:：；;]", title):
            continue  # 以句号/冒号结尾的行视为正文句子, 非标题
        if title in _SKEL_SKIP:
            continue
        key = (no, title)
        if key in seen:
            continue
        seen.add(key)
        out.append({"no": no, "title": title})
        if len(out) >= max_items:
            break
    return out


def extract_refs(md, exclude=""):
    """从正文抽取引用标准号(引用网络), 排除条目自身 std_no"""
    if not md:
        return []
    exclude = (exclude or "").replace(" ", "").upper()
    found, seen = [], set()
    for m in _REF_RE.finditer(md or ""):
        code = m.group(0).replace(" ", "").upper()
        if not code or code in seen or code == exclude:
            continue
        seen.add(code)
        found.append(code)
    return found[:30]


# ---------------- 元信息规则补全 ----------------
_CN_NAME_RE = re.compile(
    r"^[\s（(]*[A-Z]{1,4}(?:[/-][A-Z]{1,4})?/?(?:T|Z)?[-—–]?\s*\d{2,6}(?:\.\d+)*(?:[-—–]\d{4})?[\s)）]*([^\n\r]+)")
_ORG_RE = re.compile(r"(生态环境部|环境保护部|国家环保局|市场监管总局|国家质量监督检验检疫总局|住房和城乡建设部|水利部|农业农村部)")


def _extract_meta(title, text):
    """规则补全: cn_name / org / std_no(复用 kb_pipeline.parse_meta 主提取, 这里做兜底)"""
    meta = {"cn_name": "", "org": "", "std_no": ""}
    m = _CN_NAME_RE.match((title or "").strip())
    if m:
        meta["cn_name"] = m.group(1).strip()
    m = _ORG_RE.search((title or "") + "\n" + (text or "")[:1200])
    if m:
        meta["org"] = m.group(1)
    return meta


# ---------------- LLM 层 ----------------
_INTERP_PROMPT = (
    "你是生态环境标准文件解读专家。根据下面给定标题与全文, 生成结构化解读 JSON, 字段:"
    '{"std_no":"标准号如 HJ 535-2009","cn_name":"中文名称","en_name":"英文名称",'
    '"category":"所属类别如 水质/大气/固废","replace":"替代关系, 如 代替 HJ 535-2009 前身, 无则空",'
    '"publish_date":"发布日期, 无则空","implement_date":"实施日期, 无则空",'
    '"publisher":"发布单位, 无则空","drafter":"起草单位, 无则空","committee":"归口单位, 无则空",'
    '"summary":"一句话总结, 不超过80字",'
    '"core":{"适用范围":"","方法原理":"","干扰及消除":"","试剂":"","仪器":"",'
    '"样品采集与保存":"","分析步骤":"","计算公式":"","精密度与准确度":"","质量控制":""},'
    '"revision_points":["修订要点1","修订要点2"],"notes":"备注(适用限制/注意事项), 无则空"}\n'
    "要求: 只依据给定全文提炼, 不得编造; 不确定的字段留空字符串; 仅输出 JSON, 不要其它解释; 不要使用 emoji。\n"
    "标题: __TITLE__\n\n全文:\n__BODY__"
)


def _llm_json(prompt, temperature=0.1, max_chars=9000):
    """调用活跃 Provider(OpenAI 兼容)收集 JSON 输出; 无真实 Provider/失败返回 None"""
    try:
        import db
        import providers
        prov = db.get_active_provider()
        if not prov or prov.get("kind") == "mock":
            return None
        p = providers.build_provider(prov)
        msgs = [{"role": "user", "content": prompt}]
        acc = []
        for chunk in p.stream(msgs, tools=None, temperature=temperature):
            d = chunk.get("delta") or {}
            if d.get("content"):
                acc.append(d["content"])
                if sum(len(x) for x in acc) > max_chars * 2:
                    break
        out = "".join(acc).strip()
        m = re.search(r"\{.*\}", out, re.S)
        if not m:
            return None
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _core_fallback(skeleton, text):
    """规则降级: 核心内容浓缩 = 每个章节编号对应段落的首段截断"""
    core = {}
    if not text:
        return core
    for item in skeleton[:20]:
        no = item["no"]
        pat = re.compile(rf"^\s*{re.escape(no)}\s+[^\n]{{0,10}}\n(.{{0,400}})", re.M)
        m = pat.search(text)
        if m:
            core[item["title"]] = m.group(1).strip().replace("\n", " ")[:200]
    return core


# ---------------- 联网查新 ----------------
_ACTIVE_RE = re.compile(r"现行|现行有效|继续有效|仍然有效|现行版本|现行标准")
_REPEAL_RE = re.compile(r"废止|已废止|作废|宣布失效|不再执行|停止实施|失效")
# "由 X 代替/替代" / "被 X 代替/替代": X 是替代者(新标准)
_SUP_REPLACER = re.compile(
    r"(?:由|被)\s*([A-Z]{1,4}(?:[/-][A-Z]{1,4})?/?(?:T|Z)?[-—–]?\s*\d{2,6}(?:\.\d+)*(?:[-—–]\d{4})?)\s*(?:代替|替代)")
# "代替/替代 X": X 是被替代者(旧标准)
_SUP_REPLACED = re.compile(
    r"(?:代替|替代)\s*([A-Z]{1,4}(?:[/-][A-Z]{1,4})?/?(?:T|Z)?[-—–]?\s*\d{2,6}(?:\.\d+)*(?:[-—–]\d{4})?|.{0,20}号)")
_REF_CODE_NORM = re.compile(r"[A-Z]{1,4}(?:[/-][A-Z]{1,4})?/?(?:T|Z)?[-—–]?\s*\d{2,6}(?:\.\d+)*")
_VALIDITY_ORDER = {"被替代": 0, "已废止": 1, "现行有效": 2, "未知": 3}
# "废止/失效"前 8 字符窗口内的否定/疑问语境 → 不构成废止证据("尚未废止"/"是否废止"/"废止了吗"等)
_NEG_BEFORE_RE = re.compile(r"(未|尚未|不会|没有|没|是否|是不是|吗|么|怀疑|疑似|可能|并未|从未|待查|需要确认)")


def _norm_code(code):
    return (code or "").replace(" ", "").replace("—", "-").replace("–", "-").upper()


def _vote_validity(results, query_code=""):
    """多结果投票: 返回 (validity, note, evidences)。
    query_code 为被查询标准号: "由 X 代替/被 X 代替" 中 X==query 表示本标准是替代者(倾向现行),
    X!=query 表示本标准被 X 替代; "代替 X" 中 X==query 表示本标准被替代。"""
    votes = {"现行有效": 0, "已废止": 0, "被替代": 0}
    replace_by = ""
    evidences = []
    qc = _norm_code(query_code)
    for r in results or []:
        text = ((r.get("title") or "") + " " + (r.get("snippet") or "")).replace("\u200b", "")
        if not text.strip():
            continue
        evidences.append({
            "title": (r.get("title") or "")[:120],
            "url": r.get("url") or "",
            "snippet": (r.get("snippet") or "")[:200],
            "source": r.get("source") or "",
        })
        url = (r.get("url") or "") or ""
        nt = _norm_code(text)
        # 0) 权威源(全国标准信息公共服务平台/生态环境部官网)在库 → 现行有效强证据
        if "std.samr.gov.cn" in url or "mee.gov.cn" in url:
            if not qc or qc in nt:
                votes["现行有效"] += 1.5
        # 1) 替代关系: "由/被 X 代替" — X==query 表示本标准替代旧版(现行)
        m = _SUP_REPLACER.search(text)
        if m:
            x = _norm_code(m.group(1))
            if qc and x and x == qc:
                votes["现行有效"] += 1.2  # "由本标准代替旧版"
            elif x:
                votes["被替代"] += 1.5
                replace_by = x
        # 2) "代替 X": X 是被替代者; 若 query 码出现在"代替"语境中, 本标准是替代者(现行)
        m = _SUP_REPLACED.search(text)
        if m:
            x = _norm_code(m.group(1))
            if qc and x and x == qc:
                votes["被替代"] += 1.5
                replace_by = replace_by or ""
            elif qc and qc in nt:
                votes["现行有效"] += 1.0  # "HJ 535 ... 代替 GB 7479": 本标准为现行替代者
        # 3) 废止判定: 排除否定/疑问语境("尚未废止"/"是否废止")
        _repeal = _REPEAL_RE.search(text)
        if _repeal:
            s = text[max(0, _repeal.start() - 8):_repeal.start()]
            if not _NEG_BEFORE_RE.search(s):
                votes["已废止"] += 1.0
        if _ACTIVE_RE.search(text):
            votes["现行有效"] += 0.8
    if not evidences:
        return "未知", "未检索到证据", []
    best = max(votes, key=lambda k: (votes[k], -_VALIDITY_ORDER[k]))
    if votes[best] <= 0:
        best = "未知"
    if best == "被替代":
        note = f"已被替代(由 {replace_by} 代替)" if replace_by else "已被替代(证据见下方链接)"
    elif best == "已废止":
        note = "已废止/失效"
    elif best == "现行有效":
        note = "现行有效"
    else:
        note = "未检索到明确状态(建议人工复核)"
    return best, note, evidences[:5]


def _currency_check_online(std_no, title="", text=""):
    """P6 M4：优先国家公开 API 标准核验（std_mee 适配器，含内置对照表）。

    适配器命中非"未知"结果即采用（离线对照表命中同样可信）；
    失败/未命中回退 SearXNG 多路检索。绝不猜测。
    """
    code = (std_no or "").strip().upper()
    try:
        from src.public_api import registry
        registry.register_default()
        r = registry.fetch("std_mee", code=code)
        if r.get("ok") and r.get("data") and r["data"][0].get("validity"):
            d = r["data"][0]
            validity = d["validity"]
            if validity not in ("未知", ""):
                method = "public-api" + ("(offline)" if r.get("degraded") else "")
                return {"validity": validity, "note": d.get("note", ""),
                        "evidence": d.get("evidence") or [],
                        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "method": method}
    except Exception:
        pass
    return _currency_check(std_no, title, text)


def _currency_check(std_no, title, text=""):
    """联网查新: SearXNG 多路检索, 判定现行/废止/被替代/未知。
    SearXNG 不可用或空结果一律返回"未知", 绝不猜测。"""
    import websearch
    queries = []
    code = (std_no or "").strip().upper()
    if code:
        # 查询词避免"废止/替代"等诱导词(否则 SearXNG 会优先返回含"废止"字样的讨论帖/问答,
        # 被宽松匹配误判为已废止); 优先权威源精确检索
        queries.append(f'"{code}" 标准')
        queries.append(f'"{code}" 现行有效')
        queries.append(f'site:mee.gov.cn {code}')
        queries.append(f'site:std.samr.gov.cn {code}')
        queries.append(f'site:www.mee.gov.cn {code} 现行有效')
    else:
        kw = ((title or "").strip())[:30]
        if kw:
            queries.append(f'"{kw}" 标准')
    results = []
    for q in queries:
        try:
            results.extend(websearch.search(q, top_n=6, use_cache=False) or [])
        except Exception:
            continue
    if not results:
        return {"validity": "未知(未联网)", "note": "SearXNG 不可用或无检索结果, 未作状态判定",
                "evidence": [], "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "method": "searxng"}
    validity, note, evidences = _vote_validity(results, query_code=code)
    return {"validity": validity, "note": note, "evidence": evidences,
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "method": "searxng"}


# ---------------- 解读落盘 ----------------
def _write_interpretation_md(eid, std_no, interp, currency):
    """按参考样例格式落盘 解读.md, 返回路径"""
    try:
        import db
        d = os.path.join(db.DATA_DIR, "kb", "interpretations")
        os.makedirs(d, exist_ok=True)
        fname = (std_no or f"entry_{eid}") + "_解读.md"
        path = os.path.join(d, fname)
        meta = interp.get("meta") or {}
        core = interp.get("core") or {}
        lines = [
            f"# {(interp.get('std_no') or std_no or f'条目{eid}')} 结构化解读",
            "",
            "## 1. 标准元信息",
            "| 字段 | 值 |",
            "| --- | --- |",
            f"| 标准号 | {interp.get('std_no') or ''} |",
            f"| 中文名称 | {interp.get('cn_name') or meta.get('cn_name') or ''} |",
            f"| 英文名称 | {interp.get('en_name') or ''} |",
            f"| 类别 | {interp.get('category') or ''} |",
            f"| 替代关系 | {interp.get('replace') or ''} |",
            f"| 发布日期 | {interp.get('publish_date') or ''} |",
            f"| 实施日期 | {interp.get('implement_date') or ''} |",
            f"| 发布单位 | {interp.get('publisher') or meta.get('org') or ''} |",
            f"| 起草单位 | {interp.get('drafter') or ''} |",
            f"| 归口单位 | {interp.get('committee') or ''} |",
            "",
            "## 2. 一句话总结",
            interp.get("summary") or "",
            "",
            "## 3. 章节骨架",
        ]
        for it in (interp.get("skeleton") or []):
            lines.append(f"- {it['no']}  {it['title']}")
        lines += ["", "## 4. 核心内容浓缩"]
        if core:
            for k, v in core.items():
                if v:
                    lines.append(f"- **{k}**: {v}")
        else:
            lines.append("(未生成)")
        lines += ["", "## 5. 修订要点"]
        for pt in (interp.get("revision_points") or []):
            lines.append(f"- {pt}")
        lines += ["", "## 6. 引用网络"]
        for rf in (interp.get("refs") or []):
            lines.append(f"- {rf}")
        lines += ["", "## 7. 查新结论"]
        lines += [
            f"- 状态: **{currency.get('validity') or '未知'}**",
            f"- 说明: {currency.get('note') or ''}",
            f"- 查新时间: {currency.get('checked_at') or ''}",
        ]
        for ev in (currency.get("evidence") or []):
            if ev.get("url"):
                lines.append(f"- 证据: [{ev.get('title') or ev['url']}]({ev['url']})")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return path
    except Exception:
        return ""


# ---------------- 主流程: 单条解读 + 查新 ----------------
def interpret_entry(eid, do_check=True, sync=False):
    """生成单条目的智能解读(规则+LLM)并联网查新, 结果写回 metadata_json 并落盘。
    sync=True 同步执行(测试/手动 API 用); 默认入后台串行队列。"""
    if not sync:
        return _enqueue(eid)
    try:
        import db
        row = db.q("SELECT * FROM kb_entries WHERE id=?", (eid,), one=True)
        if not row:
            return {"ok": False, "reason": "条目不存在"}
        title = row["title"] or ""
        text = row["content"] or ""
        std_no = (row.get("std_no") or "")
        try:
            old_meta = json.loads(row["metadata_json"] or "{}")
        except Exception:
            old_meta = {}
        md = text if len(text or "") <= 12000 else (text or "")[:12000]
        skeleton = extract_skeleton(md)
        refs = extract_refs(md, exclude=std_no)
        rule_meta = _extract_meta(title, md)
        # LLM 层
        llm = None
        body = md if len(md) <= 8000 else md[:8000]
        llm = _llm_json(_INTERP_PROMPT.replace("__TITLE__", title).replace("__BODY__", body))
        if llm:
            std_no = llm.get("std_no") or std_no
        core = {}
        if llm and isinstance(llm.get("core"), dict):
            core = {k: (v or "") for k, v in llm["core"].items() if v}
        if not core:
            core = _core_fallback(skeleton, md)
        interp = {
            "std_no": std_no or "",
            "cn_name": (llm or {}).get("cn_name") or rule_meta["cn_name"] or title[:60],
            "en_name": (llm or {}).get("en_name") or "",
            "category": (llm or {}).get("category") or "",
            "replace": (llm or {}).get("replace") or "",
            "publish_date": (llm or {}).get("publish_date") or "",
            "implement_date": (llm or {}).get("implement_date") or "",
            "publisher": (llm or {}).get("publisher") or rule_meta["org"] or "",
            "drafter": (llm or {}).get("drafter") or "",
            "committee": (llm or {}).get("committee") or "",
            "summary": (llm or {}).get("summary") or ((md or "").strip()[:80]),
            "skeleton": skeleton,
            "refs": refs,
            "core": core,
            "revision_points": (llm or {}).get("revision_points") or [],
            "notes": (llm or {}).get("notes") or "",
            "meta": rule_meta,
            "engine": "llm" if llm else "rule",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        # 查新层
        currency = {}
        if do_check:
            currency = _currency_check_online(std_no, title, md)
        else:
            currency = {"validity": row.get("validity") or "未知", "note": "未执行联网查新",
                        "evidence": [], "checked_at": "", "method": "offline"}
        path = _write_interpretation_md(eid, std_no, interp, currency)
        interp["md_path"] = path
        old_meta["interpret"] = interp
        old_meta["currency"] = currency
        validity = currency.get("validity") or row.get("validity") or "未知"
        db.w("UPDATE kb_entries SET std_no=?, validity=?, metadata_json=? WHERE id=?",
             (std_no, validity, json.dumps(old_meta, ensure_ascii=False), eid))
        return {"ok": True, "eid": eid, "std_no": std_no, "validity": validity,
                "engine": interp["engine"], "skeleton": len(skeleton), "refs": len(refs)}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"ok": False, "reason": str(e)}


# ---------------- 后台串行队列 ----------------
_queue = []
_queue_set = set()
_queue_lock = threading.Lock()
_worker = None


def _enqueue(eid):
    """入后台串行队列(同条目去重), 返回是否新入队"""
    global _worker
    with _queue_lock:
        if eid in _queue_set:
            return False
        _queue.append(eid)
        _queue_set.add(eid)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_drain, daemon=True, name="std-intel")
            _worker.start()
    return True


def _drain():
    while True:
        with _queue_lock:
            if not _queue:
                _queue_set.clear()
                break
            eid = _queue.pop(0)
        try:
            interpret_entry(eid, do_check=True, sync=True)
        except Exception:
            pass
        with _queue_lock:
            _queue_set.discard(eid)


def queued_count():
    with _queue_lock:
        return len(_queue)


# ---------------- 批量重检 ----------------
def batch_recheck(limit=200, only_unchecked=False):
    """存量批量重检: 遍历 std_no 非空条目(或未查新过的)入后台队列"""
    import db
    if only_unchecked:
        rows = db.q("SELECT id FROM kb_entries WHERE std_no<>'' AND (metadata_json IS NULL OR metadata_json='' "
                    "OR metadata_json NOT LIKE '%currency%') ORDER BY id DESC LIMIT ?", (limit,))
    else:
        rows = db.q("SELECT id FROM kb_entries WHERE std_no<>'' ORDER BY id DESC LIMIT ?", (limit,))
    queued = 0
    for r in rows:
        if _enqueue(r["id"]):
            queued += 1
    return {"ok": True, "matched": len(rows), "queued": queued}


def get_interpretation(eid):
    """读取条目已生成的解读与查新结果"""
    import db
    row = db.q("SELECT metadata_json, validity FROM kb_entries WHERE id=?", (eid,), one=True)
    if not row:
        return None
    try:
        meta = json.loads(row["metadata_json"] or "{}")
    except Exception:
        meta = {}
    return {"interpret": meta.get("interpret"), "currency": meta.get("currency"),
            "validity": row.get("validity")}
