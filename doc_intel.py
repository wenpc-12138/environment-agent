# -*- coding: utf-8 -*-
"""doc_intel.py - 通用文档智能总结模块
参考《文档快读与智能总结-通用技术方案.md》6 层流水线落地(适用于任意知识库条目,
不限标准/政策; 标准/政策条目另有 standard_intel 做结构化解读+联网查新):

  L1 文档类型探测: 按字符量/图像占比判断 text / short / image-heavy
  L3 排版重建:     章节骨架抽取(复用 standard_intel.extract_skeleton)
  L4 信息抽取:     关键参数正则(浓度/限值/波长/时间/温度/百分比等) + 引用标准号
  L5 分层总结:     Map-Reduce -> 章节级要点(Map, 规则) + 全文级多版本输出(Reduce, LLM)
                   输出: 一句话 / TL;DR / 结构化长摘要 / 核心要点 / 章节要点 / 关键参数
  L6 质量验证:     数字回校(总结中数字须出现于原文) + 引用回溯 + 幻觉拦截(标准号回校)

结果写回 kb_entries.metadata_json.{summary} 并落盘 data/kb/summaries/<title>_总结.md。
"""

import json
import os
import re
import threading
from datetime import datetime

import standard_intel as _si  # 复用 extract_skeleton / extract_refs / _llm_json

# ---------------- L4 关键参数抽取(正则, 离线零成本) ----------------
_PARAM_RE = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*"
    r"(mg/L|mg/l|μg/L|ug/L|µg/L|ng/L|g/L|kg/L|mol/L|mmol/L|μmol/L|umol/L|"
    r"mg/kg|μg/m3|ug/m3|mg/m3|μm|um|nm|mm|cm|km|℃|°C|K|kPa|MPa|Pa|pH|%|min|h|"
    r"mL|mL/min|L/min|r/min|rpm|d|a|V|kV|mA|Hz|kHz)(?![0-9])", re.I)
_STD_INLINE_RE = _si._REF_RE  # 引用标准号(幻觉回校用)


def detect_doc_type(md):
    """L1 文档类型探测: empty / short / image-heavy / text"""
    if not md or not (md or "").strip():
        return "empty"
    total = len(md)
    imgs = len(re.findall(r"!\[[^\]]*\]\([^)]+\)|<img[^>]*>", md))
    lines = max(len(md.splitlines()), 1)
    if total < 200:
        return "short"
    if imgs and imgs / lines > 0.15:
        return "image-heavy"
    return "text"


def extract_key_params(md, max_items=40):
    """L4 关键参数抽取: 返回 [{"v":"值 单位","ctx":"前文片段"}, ...]"""
    if not md:
        return []
    out, seen = [], set()
    for m in _PARAM_RE.finditer(md):
        val = m.group(1) + " " + m.group(2).upper()
        if val in seen:
            continue
        seen.add(val)
        start = max(0, m.start() - 16)
        ctx = (md[start:m.end()] or "").replace("\n", " ").strip()[:42]
        out.append({"v": val, "ctx": ctx})
        if len(out) >= max_items:
            break
    return out


# ---------------- L5 分层总结 ----------------
_SUMMARY_PROMPT = (
    "你是文档理解与总结专家。根据给定标题与全文生成结构化总结 JSON, 字段:"
    '{"one_liner":"一句话总结, 不超过50字","tldr":"TL;DR 精炼摘要, 不超过200字,'
    ' 覆盖核心要点不含细节","long_summary":"结构化长摘要, 分要点列出, 保留关键数据/'
    '参数/结论, 长度不超过原文10%","key_points":["核心要点1","核心要点2","核心要点3"]}\n'
    "要求: 只依据给定全文提炼, 不得编造数字或结论; 不确定的不写; 仅输出 JSON, 不要其它解释; 不要使用 emoji。\n"
    "标题: __TITLE__\n\n全文:\n__BODY__"
)


def _llm_summary(title, body):
    """Reduce 阶段 LLM 多版本输出; 无真实 Provider/失败返回 None"""
    obj = _si._llm_json(_SUMMARY_PROMPT.replace("__TITLE__", title).replace("__BODY__", body))
    if not obj:
        return None
    return {"one_liner": (obj.get("one_liner") or "").strip(),
            "tldr": (obj.get("tldr") or "").strip(),
            "long_summary": (obj.get("long_summary") or "").strip(),
            "key_points": [str(p).strip() for p in (obj.get("key_points") or []) if str(p).strip()]}


def _skeleton(md, max_items=60):
    """章节骨架抽取: 优先 standard_intel 规则, 空则剥离 Markdown 标题前缀(#)后重试,
    兼容 '## 1 适用范围' 与 '1 适用范围' 两种排版"""
    sk = _si.extract_skeleton(md, max_items=max_items)
    if sk:
        return sk
    stripped = re.sub(r"^\s*#{1,6}\s*", "", (md or ""), flags=re.M)
    sk2 = _si.extract_skeleton(stripped, max_items=max_items)
    return sk2


def _chapter_points(md, skeleton):
    """Map 阶段(规则层): 每个章节对应段落的首段截断作为章节级要点"""
    points = []
    if not md:
        return points
    for item in skeleton[:20]:
        no = item["no"]
        pat = re.compile(rf"^\s*#{{0,6}}\s*{re.escape(no)}[、.．\s]+[^\n]{{0,10}}\n(.{{0,260}})", re.M)
        m = pat.search(md)
        if m:
            t = m.group(1).strip().replace("\n", " ")
            if t:
                points.append({"no": no, "title": item["title"], "point": t[:140]})
    return points


def _rule_summary(title, md):
    """Reduce 阶段规则降级: 一句话=首段截断, TL;DR=前2段, 长摘要=每章首段拼接(零成本兜底)"""
    paras = [p.strip() for p in (md or "").split("\n") if p.strip()]
    one = (paras[0] if paras else title or "")[:50]
    tldr = (" ".join(paras[:2]) if len(paras) >= 2 else (paras[0] if paras else ""))[:200]
    long = "\n".join(f"- {p[:120]}" for p in paras[:8])
    return {"one_liner": one, "tldr": tldr, "long_summary": long,
            "key_points": [p[:60] for p in paras[:5]]}


# ---------------- L6 质量验证 ----------------
def _verify(one_liner, tldr, long_summary, source, refs):
    """数字回校 + 引用回溯(标准号) + 幻觉拦截标记"""
    comb = " ".join([one_liner or "", tldr or "", long_summary or ""])
    nums = set(re.findall(r"\d+(?:\.\d+)?", comb))
    missing = sorted(n for n in nums if len(n) >= 2 and (source or "").count(n) == 0)
    halluc = []
    for m in _STD_INLINE_RE.finditer(comb):
        code = m.group(0).replace(" ", "").upper()
        if code and code not in (refs or []):
            halluc.append(code)
    return {"numbers_checked": len(nums), "numbers_missing": missing[:10],
            "refs_checked": len(set(halluc)), "hallucinated": sorted(set(halluc))[:10],
            "passed": not missing and not halluc,
            "note": "数字/标准号已回校原文" if (not missing and not halluc)
            else "存在未回校内容, 建议人工复核"}


# ---------------- 总结落盘 ----------------
def _write_summary_md(eid, title, summ):
    """按方案多版本输出格式落盘 总结.md, 返回路径"""
    try:
        import db
        d = os.path.join(db.DATA_DIR, "kb", "summaries")
        os.makedirs(d, exist_ok=True)
        safe = re.sub(r'[\\/:*?"<>|]', "_", (title or f"entry_{eid}"))[:60]
        path = os.path.join(d, f"{safe}_总结.md")
        vf = summ.get("verify") or {}
        lines = [f"# {title or f'条目{eid}'} 智能总结", "",
                 "## 1. 一句话总结", summ.get("one_liner") or "", "",
                 "## 2. TL;DR", summ.get("tldr") or "", "",
                 "## 3. 结构化长摘要", summ.get("long_summary") or "(未生成)", "",
                 "## 4. 核心要点"]
        for p in (summ.get("key_points") or []):
            lines.append(f"- {p}")
        lines += ["", "## 5. 章节要点"]
        cps = summ.get("chapter_points") or []
        if cps:
            for cp in cps:
                lines.append(f"- [{cp['no']}] {cp['title']}: {cp['point']}")
        else:
            lines.append("(未生成)")
        lines += ["", "## 6. 关键参数"]
        params = summ.get("key_params") or []
        if params:
            for p in params:
                lines.append(f"- {p['v']}  (上下文: {p['ctx']})")
        else:
            lines.append("(未抽取)")
        lines += ["", "## 7. 引用标准"]
        refs = summ.get("refs") or []
        if refs:
            for r in refs:
                lines.append(f"- {r}")
        else:
            lines.append("(无)")
        lines += ["", "## 8. 质量验证", f"- 状态: **{'通过' if vf.get('passed') else '待复核'}**",
                  f"- 数字回校: 检查 {vf.get('numbers_checked', 0)} 个, 未回校 {len(vf.get('numbers_missing') or [])} 个",
                  f"- 幻觉拦截: 标准号回校 {vf.get('refs_checked', 0)} 个",
                  f"- 说明: {vf.get('note') or ''}",
                  f"- 文档类型: {summ.get('doc_type') or ''} | 引擎: {summ.get('engine') or ''} | "
                  f"生成时间: {summ.get('generated_at') or ''}"]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return path
    except Exception:
        return ""


# ---------------- 主流程: 单条通用智能总结 ----------------
def summarize_entry(eid, sync=False):
    """对任意知识库条目生成通用智能总结(L1/L3/L4/L5/L6), 写回 metadata_json.summary 并落盘。
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
        doc_type = detect_doc_type(md)
        skeleton = _skeleton(md)
        refs = _si.extract_refs(md, exclude=std_no)
        key_params = extract_key_params(md)
        body = md if len(md) <= 8000 else md[:8000]
        llm = _llm_summary(title, body)
        if llm:
            summ = llm
            engine = "llm"
        else:
            summ = _rule_summary(title, md)
            engine = "rule"
        summ["chapter_points"] = _chapter_points(md, skeleton)
        summ["key_params"] = key_params
        summ["refs"] = refs
        summ["doc_type"] = doc_type
        summ["engine"] = engine
        summ["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        summ["verify"] = _verify(summ.get("one_liner"), summ.get("tldr"),
                                 summ.get("long_summary"), md, refs)
        path = _write_summary_md(eid, title, summ)
        summ["md_path"] = path
        old_meta["summary"] = summ
        db.w("UPDATE kb_entries SET metadata_json=? WHERE id=?",
             (json.dumps(old_meta, ensure_ascii=False), eid))
        return {"ok": True, "eid": eid, "engine": engine, "doc_type": doc_type,
                "one_liner": summ.get("one_liner"), "verify": summ.get("verify")}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


# ---------------- 后台串行队列 ----------------
_queue = []
_queue_set = set()
_queue_lock = threading.Lock()
_worker = None


def _enqueue(eid):
    global _worker
    with _queue_lock:
        if eid in _queue_set:
            return False
        _queue.append(eid)
        _queue_set.add(eid)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_drain, daemon=True, name="doc-intel")
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
            summarize_entry(eid, sync=True)
        except Exception:
            pass
        with _queue_lock:
            _queue_set.discard(eid)


def queued_count():
    with _queue_lock:
        return len(_queue)


# ---------------- 批量补总结 ----------------
def batch_summarize(limit=200, only_missing=True):
    """存量批量补总结: 遍历未生成过 summary 的条目入后台队列"""
    import db
    if only_missing:
        rows = db.q("SELECT id FROM kb_entries WHERE id NOT IN "
                    "(SELECT id FROM kb_entries WHERE metadata_json LIKE '%summary%') "
                    "ORDER BY id DESC LIMIT ?", (limit,))
    else:
        rows = db.q("SELECT id FROM kb_entries ORDER BY id DESC LIMIT ?", (limit,))
    queued = 0
    for r in rows:
        if _enqueue(r["id"]):
            queued += 1
    return {"ok": True, "matched": len(rows), "queued": queued}


def get_summary(eid):
    """读取条目已生成的通用智能总结"""
    import db
    row = db.q("SELECT metadata_json FROM kb_entries WHERE id=?", (eid,), one=True)
    if not row:
        return None
    try:
        meta = json.loads(row["metadata_json"] or "{}")
    except Exception:
        meta = {}
    return meta.get("summary")
