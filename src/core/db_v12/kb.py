# -*- coding: utf-8 -*-
"""S1-W5 db.py 拆分：知识库数据层（kb 域，最大）。

从根 db.py 原样搬移：kb 检索/CRUD/版本/纠错/关系/向量/缓存/审计/备份/导入
导出 等 48 个函数 + _KB_META_FIELDS 常量。_VEC_OK/_VEC_METRIC 为跨模块共享
状态（base.init_db 写入），此处经 `from . import base as _base` 动态引用。
"""
from __future__ import annotations

import json
import re as _re
import sqlite3
import os

from . import base as _base
from .base import DATA_DIR, DB_PATH, q, w, get_db, begin_batch, commit_batch

_KB_META_FIELDS = [
    "item_type", "domain", "source_type", "validity", "confidence",
    "status", "std_no", "org", "publish_date", "implement_date",
]

# kb_entries 实际列名缓存（_kb_columns 惰性填充，兼容旧库缺列）
_KB_COLS: set | None = None


def _kb_guess_title(plain, fallback):
    """从正文首段提取真实标题(优先于文件名/部委文件编号), 失败回退文件名
    跳过封面杂行(ICS 分类号/单字母编号/标准抬头/日期行等), 优先标准号行"""
    import kb_pipeline as kp
    _junk = _re.compile(
        r"^(ICS[\d. ]*|[A-Za-z]{1,3}\s*\d{1,4}|[\d.\s]{1,12}|"
        r"中华人民共和国国家标准|中华人民共和国国家环境保护标准|中华人民共和国行业标准|"
        r"代替.*|实施日期.*|发布.*|Environmental quality standards.*)$"
    )
    # 封面抬头行: "中华人民共和国国家环境保护标准HJ 1047-2019" 整行(抬头+标准号),
    # 不作为标题, 仅提取其中标准号作兜底
    _cover = _re.compile(
        r"^中华人民共和国(?:国家环境保护标准|国家标准|行业标准|环境保护行业标准)"
        r"(?:[ 　（(]*[A-Z]{1,4}[\dA-Z．.]*[ 　]?\d{2,6}(?:[-—–]\d{4})?[)）]?)+$"
    )
    if not plain:
        return fallback
    lines = plain.splitlines()
    # 0) 识别封面抬头行并提取标准号(兜底标题)
    cover_no = ""
    for ln in lines:
        t = ln.strip(" #*-\t\u3000").strip()
        if _cover.match(t):
            m = kp._STD_RE.search(t)
            if m and not cover_no:
                cover_no = m.group(1).replace(" ", "")
    # 0.5) 优先官方文件全称: "XX条例(中华人民共和国国务院令第N号)" /
    #      以"条例/办法/实施细则"等结尾的正式名称行
    for ln in lines:
        t = ln.strip(" #*-\t\u3000").strip()
        if not t or _cover.match(t) or _junk.match(t) or kp._is_segment_start(t):
            continue
        if 4 <= len(t) <= 60 and (
                _re.search(r"[（(][^）)]*(?:国务院|省(?:级)?人民政府|部|总局|局)令\s*第\s*\d+\s*号[）)]", t)
                or _re.search(r"(?:条例|办法|实施细则|通则|导则)$", t)):
            return t.replace("\u2002", "\u3000")
    # 1) 优先正文标题行: 标准特征词(水质/大气/测定/质量标准等)且非封面/杂行/
    #    跳过"第X条"段首行(防止"第四条 国家建立健全..."被误判为标题)
    for ln in lines:
        t = ln.strip(" #*-\t\u3000").strip()
        if not t or _cover.match(t) or _junk.match(t) or kp._is_segment_start(t):
            continue
        if 4 <= len(t) <= 60 and _re.search(
                r"水质|大气|土壤|地下水|地表水|噪声|固体废物|固废|测定|监测技术|"
                r"排放标准|质量标准|控制标准|规范|通则|方法", t):
            return t
    # 2) 优先标准号行: GB 3838-2002 / HJ/T 91-2002 等(跳过封面抬头行/段首行)
    for ln in lines:
        t = ln.strip(" #*-\t\u3000").strip()
        if _cover.match(t) or kp._is_segment_start(t):
            continue
        if 4 <= len(t) <= 60 and not t.startswith(("http://", "https://", "www.")):
            if _re.search(r"\b(GB|HJ|GHZB|CJ|SL|DB\d{2}|NY|SC|LY|WS|TB|JB|DL)\s*[／/]?\s*T?\s*[\d.]+", t):
                return t
    # 3) 首个非杂行: 跳过 ICS 分类号/单字母编号/标准抬头/"第X条"段首行等
    for ln in lines:
        t = ln.strip(" #*-\t\u3000").strip()
        if not t or _junk.match(t) or _cover.match(t) or kp._is_segment_start(t):
            continue
        if 4 <= len(t) <= 60 and not t.startswith(("http://", "https://", "www.")):
            return t
    # 4) 封面抬头标准号兜底
    if cover_no:
        return cover_no
    return fallback


def _build_fts_query(query):
    """中文二元分词 + 字母数字保留,OR 组合,适配 unicode61 分词器"""
    terms = []
    for tok in query.split():
        for m in _re.finditer(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", tok):
            seg = m.group()
            if _re.match(r"[\u4e00-\u9fff]+", seg):
                if len(seg) == 1:
                    terms.append(f'"{seg}"')
                else:
                    terms.extend(f'"{seg[i:i + 2]}"' for i in range(len(seg) - 1))
            else:
                terms.append(f'"{seg}"')
    return " OR ".join(terms) if terms else None


def _kb_columns():
    """kb_entries 实际列名集合(兼容旧库缺列, 结果缓存于模块级)"""
    global _KB_COLS
    if _KB_COLS is None:
        try:
            _KB_COLS = {r["name"] for r in q("PRAGMA table_info(kb_entries)")}
        except Exception:
            _KB_COLS = set()
    return _KB_COLS


def kb_search(query, top_n=5, category=None, item_type=None, validity=None, domain=None):
    """知识库检索: 词级连续 LIKE 加权排序(中文/标准号可靠), FTS5 兜底(英文/数字)。
    按空格拆词, 每词须连续出现在 标题/标准号/正文 之一; 命中权重 标准号5/标题3/正文1,
    同分时新条目(id 大)优先, 避免新入库文档被 LIMIT 截断。"""
    filters, fargs = [], []
    for _k, _v in (("category", category), ("item_type", item_type), ("validity", validity), ("domain", domain)):
        if _v:
            filters.append(f"k.{_k}=?")
            fargs.append(_v)
    where = (" AND " + " AND ".join(filters)) if filters else ""
    words = [w for w in _re.split(r"\s+", (query or "").strip()) if w]
    if words:
        has_std = "std_no" in _kb_columns()
        like_parts, like_args, score_exprs, score_args = [], [], [], []
        for w in words:
            if has_std:
                like_parts.append("(k.title LIKE ? OR k.std_no LIKE ? OR k.content LIKE ?)")
                like_args += [f"%{w}%", f"%{w}%", f"%{w}%"]
                score_exprs.append("(CASE WHEN k.title LIKE ? THEN 3 ELSE 0 END"
                                   " + CASE WHEN k.std_no LIKE ? THEN 5 ELSE 0 END"
                                   " + CASE WHEN k.content LIKE ? THEN 1 ELSE 0 END)")
                score_args += [f"%{w}%", f"%{w}%", f"%{w}%"]
            else:
                like_parts.append("(k.title LIKE ? OR k.content LIKE ?)")
                like_args += [f"%{w}%", f"%{w}%"]
                score_exprs.append("(CASE WHEN k.title LIKE ? THEN 3 ELSE 0 END"
                                   " + CASE WHEN k.content LIKE ? THEN 1 ELSE 0 END)")
                score_args += [f"%{w}%", f"%{w}%"]
        rows = q(
            "SELECT k.*, (%s) AS rel_score FROM kb_entries k WHERE %s%s"
            " ORDER BY rel_score DESC, k.id DESC LIMIT ?"
            % (" + ".join(score_exprs), " AND ".join(like_parts), where),
            score_args + like_args + fargs + [top_n])
        if rows:
            for _r in rows:
                _r["score"] = _r.pop("rel_score")
            return rows
    # FTS5 兜底(英文/数字检索)
    safe = _build_fts_query(query)
    if safe:
        try:
            rows = q(
                "SELECT k.*, bm25(kb_fts) AS rel_score FROM kb_entries k JOIN kb_fts ON kb_fts.rowid=k.id"
                f" WHERE kb_fts MATCH ?{where} ORDER BY rel_score LIMIT ?",
                [safe] + fargs + [top_n])
            if rows:
                for _r in rows:
                    _r["score"] = _r.pop("rel_score")
                return rows
        except Exception:
            pass
        # S1-W3: kb_fts(unicode61) 无命中时,走 kb_fts_tg(trigram) 子串召回
        # (标准号/数字/英文子串, 如查 "3095" 命中 "GB 3095-2012"; 2 字中文由 LIKE 主路径覆盖)
        try:
            rows = q(
                "SELECT k.*, bm25(kb_fts_tg) AS rel_score FROM kb_entries k"
                " JOIN kb_fts_tg ON kb_fts_tg.rowid=k.id"
                f" WHERE kb_fts_tg MATCH ?{where} ORDER BY rel_score LIMIT ?",
                [safe] + fargs + [top_n])
            if rows:
                for _r in rows:
                    _r["score"] = _r.pop("rel_score")
                return rows
        except Exception:
            pass
    return []


def kb_locate(query, limit=5):
    """精确定位知识库条目:标题或来源URL 精确/包含匹配, 优先精确命中"""
    qry = (query or "").strip()
    if not qry:
        return []
    exact = q(
        "SELECT * FROM kb_entries WHERE title=? OR url=? "
        "ORDER BY CASE WHEN title=? THEN 0 WHEN url=? THEN 1 ELSE 2 END, id DESC LIMIT ?",
        (qry, qry, qry, qry, limit),
    )
    if exact:
        return exact
    like = f"%{qry}%"
    return q(
        "SELECT * FROM kb_entries WHERE title LIKE ? OR url LIKE ? ORDER BY id DESC LIMIT ?",
        (like, like, limit),
    )


def kb_list(category=None, limit=100):
    if category:
        return q("SELECT * FROM kb_entries WHERE category=? ORDER BY id DESC LIMIT ?", (category, limit))
    return q("SELECT * FROM kb_entries ORDER BY id DESC LIMIT ?", (limit,))


def kb_add(title, url, category, content, source="", **meta):
    """落库知识条目(兼容旧五参调用), 自动写版本链 v1 与来源记录"""
    eid = w(
        "INSERT INTO kb_entries(title,url,category,content,source,item_type,domain,source_type,"
        " validity,confidence,status,std_no,org,publish_date,implement_date,metadata_json,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))",
        (
            title, url or "", category or "network", content, source or "",
            meta.get("item_type") or "knowledge", meta.get("domain") or "",
            meta.get("source_type") or "原文", meta.get("validity") or "未知",
            float(meta.get("confidence") or 0.8), meta.get("status") or "active",
            meta.get("std_no") or "", meta.get("org") or "",
            meta.get("publish_date") or "", meta.get("implement_date") or "",
            json.dumps(meta.get("metadata") or {}, ensure_ascii=False),
        ),
    )
    kb_version_add(eid, note="创建", version=1)
    src_url = (url or "").strip()
    _is_web = src_url.lower().startswith(("http://", "https://"))
    if src_url or source:
        # 网络资料: kind=web + url; 本地上传: kind=file, 不携带本机路径
        _kb_source_add(eid, kind="web" if _is_web else "file",
                       name=source or title, url=src_url if _is_web else "")
    return eid


def kb_get(eid):
    return q("SELECT * FROM kb_entries WHERE id=?", (eid,), one=True)


def kb_get_detail(eid):
    """条目详情: 自身 + 版本链 + 纠错记录 + 引用关系 + 来源"""
    entry = kb_get(eid)
    if not entry:
        return None
    entry["versions"] = q(
        "SELECT * FROM kb_versions WHERE entry_id=? ORDER BY version DESC", (eid,))
    entry["corrections"] = q(
        "SELECT * FROM kb_corrections WHERE entry_id=? ORDER BY id DESC", (eid,))
    entry["relations"] = q(
        "SELECT r.*, t.title to_title FROM kb_relations r LEFT JOIN kb_entries t ON t.id=r.to_id"
        " WHERE r.from_id=? ORDER BY r.id DESC", (eid,))
    entry["sources"] = q(
        "SELECT * FROM kb_sources WHERE entry_id=? ORDER BY id DESC", (eid,))
    try:
        entry["metadata"] = json.loads(entry.get("metadata_json") or "{}")
    except Exception:
        entry["metadata"] = {}
    return entry


def kb_delete(eid):
    w("DELETE FROM kb_entries WHERE id=?", (eid,))
    w("DELETE FROM kb_versions WHERE entry_id=?", (eid,))
    w("DELETE FROM kb_corrections WHERE entry_id=?", (eid,))
    w("DELETE FROM kb_relations WHERE from_id=? OR to_id=?", (eid, eid))
    w("DELETE FROM kb_sources WHERE entry_id=?", (eid,))
    w("DELETE FROM kb_chunks WHERE entry_id=?", (eid,))
    if _base._VEC_OK:
        try:
            w("DELETE FROM kb_vec WHERE entry_id=?", (eid,))
        except Exception:
            pass


def kb_update(eid, **fields):
    """更新条目字段(白名单), 内容/有效性/状态变化时写版本链"""
    cur = kb_get(eid)
    if not cur:
        return None
    allowed = set(_KB_META_FIELDS) | {"title", "category", "source", "content"}
    sets, args = [], []
    changed = {}
    for k, v in fields.items():
        if v is None:
            continue
        if k not in allowed:
            continue
        if str(cur.get(k) or "") != str(v or ""):
            sets.append(f"{k}=?")
            args.append(v)
            changed[k] = {"old": cur.get(k), "new": v}
    if not sets:
        return cur["id"]
    args.append(eid)
    w(f"UPDATE kb_entries SET {', '.join(sets)}, updated_at=datetime('now','localtime') WHERE id=?", args)
    if changed:
        kb_version_add(eid, note="内容更新", diff=json.dumps(changed, ensure_ascii=False))
    return eid


def kb_version_add(eid, note="", version=None, prev_id=None, diff=""):
    if version is None:
        last = q("SELECT version FROM kb_versions WHERE entry_id=? ORDER BY version DESC LIMIT 1",
                 (eid,), one=True)
        version = (last["version"] + 1) if last else 1
    if prev_id is None:
        last = q("SELECT id FROM kb_versions WHERE entry_id=? ORDER BY version DESC LIMIT 1",
                 (eid,), one=True)
        prev_id = last["id"] if last else 0
    return w(
        "INSERT INTO kb_versions(entry_id,prev_id,version,diff,note) VALUES(?,?,?,?,?)",
        (eid, prev_id, version, diff, note),
    )


def kb_correct(eid, issue, suggestion="", corrected_content="", reporter="user"):
    """纠错闭环: 记录纠错单; 若提供修正内容则更新条目内容并标记复核中"""
    cid = w(
        "INSERT INTO kb_corrections(entry_id,reporter,issue,suggestion,corrected_content,status)"
        " VALUES(?,?,?,?,?,?)",
        (eid, reporter or "user", issue, suggestion or "", corrected_content or "", "pending"),
    )
    if corrected_content:
        kb_update(eid, content=corrected_content, status="flagged",
                  confidence=0.4)  # 修正后降置信度待复核
        w("UPDATE kb_corrections SET status='applied' WHERE id=?", (cid,))
        kb_version_add(eid, note="纠错修正", diff=json.dumps({"correction_id": cid}, ensure_ascii=False))
    return cid


def kb_correct_resolve(cid, accepted=True):
    """复核纠错单: 接受则恢复条目状态并升置信度"""
    row = q("SELECT * FROM kb_corrections WHERE id=?", (cid,), one=True)
    if not row:
        return False
    st = "resolved" if accepted else "rejected"
    w("UPDATE kb_corrections SET status=? WHERE id=?", (st, cid))
    if accepted and row["entry_id"]:
        kb_update(row["entry_id"], status="active", confidence=0.9)
    return True


def kb_relation_add(from_id, to_id, rel_type="related", note=""):
    return w(
        "INSERT INTO kb_relations(from_id,to_id,rel_type,note) VALUES(?,?,?,?)",
        (from_id, to_id, rel_type or "related", note or ""),
    )


def _kb_source_add(entry_id, kind="web", name="", url=""):
    w("INSERT INTO kb_sources(entry_id,kind,name,url) VALUES(?,?,?,?)",
      (entry_id, kind, name or "", url or ""))


def kb_stats():
    """知识库统计: 总量/分类/领域/有效性/置信度/纠错/关系/来源"""
    total = q("SELECT COUNT(*) c FROM kb_entries", one=True)["c"]
    by_cat = q("SELECT category, COUNT(*) c FROM kb_entries GROUP BY category")
    by_valid = q("SELECT validity, COUNT(*) c FROM kb_entries GROUP BY validity")
    by_type = q("SELECT item_type, COUNT(*) c FROM kb_entries GROUP BY item_type")
    by_domain = q("SELECT domain, COUNT(*) c FROM kb_entries GROUP BY domain")
    conf = q("SELECT AVG(confidence) a FROM kb_entries", one=True)
    flagged = q("SELECT COUNT(*) c FROM kb_entries WHERE status='flagged'", one=True)["c"]
    corr_pending = q("SELECT COUNT(*) c FROM kb_corrections WHERE status='pending'", one=True)["c"]
    corr_total = q("SELECT COUNT(*) c FROM kb_corrections", one=True)["c"]
    rel_total = q("SELECT COUNT(*) c FROM kb_relations", one=True)["c"]
    return {
        "total": total,
        "by_category": dict((r["category"], r["c"]) for r in by_cat),
        "by_validity": dict((r["validity"], r["c"]) for r in by_valid),
        "by_item_type": dict((r["item_type"], r["c"]) for r in by_type),
        "by_domain": dict((r["domain"], r["c"]) for r in by_domain),
        "avg_confidence": round(conf["a"] or 0, 2),
        "flagged": flagged,
        "corrections": {"total": corr_total, "pending": corr_pending},
        "relations": rel_total,
    }


def kb_chunk_add(entry_id, chunk_index, content, chunk_type="para", embedding=None):
    """存储条目分块(embedding 为 BLOB 字节或 numpy 数组)"""
    blob = None
    if embedding is not None:
        try:
            import numpy as _np
            if isinstance(embedding, _np.ndarray):
                blob = embedding.astype("float32").tobytes()
            else:
                blob = bytes(embedding)
        except Exception:
            blob = None
    tok = len(str(content or "").replace(" ", ""))
    return w(
        "INSERT INTO kb_chunks(entry_id,chunk_index,chunk_type,content,token_count,embedding)"
        " VALUES(?,?,?,?,?,?)",
        (entry_id, chunk_index or 0, chunk_type or "para", content or "", tok, blob),
    )


def kb_chunk_clear(entry_id):
    w("DELETE FROM kb_chunks WHERE entry_id=?", (entry_id,))


def kb_get_chunks(entry_id):
    return q("SELECT * FROM kb_chunks WHERE entry_id=? ORDER BY chunk_index", (entry_id,))


def kb_embed_entry(entry_id, force=False):
    """为条目生成分块+向量(仅当无分块或 force 时); 同时写入 vec0 条目级向量"""
    import kb_pipeline as kp
    if not force and q("SELECT COUNT(*) c FROM kb_chunks WHERE entry_id=?", (entry_id,), one=True)["c"]:
        return kb_get_chunks(entry_id)
    cur = kb_get(entry_id)
    if not cur:
        return []
    kb_chunk_clear(entry_id)
    chunks = kp.chunk_text(cur["content"] or "")
    if not chunks:
        return []
    vecs = []
    for i, (txt, ctype) in enumerate(chunks):
        v = kp.embed_text(txt)
        kb_chunk_add(entry_id, i, txt, ctype, v)
        vecs.append(v)
    # 条目级向量 = 分块向量均值归一化, 写入 vec0(KNN 检索用;失败静默)
    if _base._VEC_OK and vecs:
        try:
            import numpy as _np
            avg = _np.mean(_np.stack([_np.asarray(v, dtype="float32") for v in vecs]), axis=0)
            nrm = float(_np.linalg.norm(avg)) or 1.0
            blob = (avg / nrm).astype("float32").tobytes()
            w("INSERT OR REPLACE INTO kb_vec(entry_id, embedding) VALUES(?,?)", (entry_id, blob))
        except Exception:
            pass
    return kb_get_chunks(entry_id)


def _embed_bytes_to_vec(blob):
    import numpy as _np
    if not blob:
        return None
    try:
        return _np.frombuffer(bytes(blob), dtype="float32")
    except Exception:
        return None


def kb_vector_search(query, top_n=5):
    """向量检索: 优先 vec0 KNN(distance 按度量换算相似度), 降级全库 numpy 暴力"""
    import kb_pipeline as kp
    import numpy as _np
    qv = kp.embed_text(query)
    qblob = _np.asarray(qv, dtype="float32").tobytes()
    # 路A: vec0 KNN(余弦/欧氏距离 -> 相似度)
    if _base._VEC_OK:
        try:
            k = max(top_n * 3, 10)
            rows = q(
                "SELECT entry_id, distance FROM kb_vec WHERE embedding MATCH ? AND k = ?",
                (qblob, k),
            )
            out = []
            for r in rows:
                d = float(r["distance"])
                if _base._VEC_METRIC == "cosine":
                    s = max(0.0, min(1.0, 1.0 - d))
                else:
                    s = 1.0 / (1.0 + d)
                cur = kb_get(r["entry_id"])
                if cur:
                    cur["score"] = round(s, 4)
                    out.append(cur)
                    if len(out) >= top_n:
                        break
            if out:
                return out
        except Exception:
            pass
    # 路B: 全库分块向量暴力(兼容 kb_vec 缺失/扩展不可用)
    rows = q("SELECT entry_id, content, embedding FROM kb_chunks WHERE embedding IS NOT NULL")
    if not rows:
        return []
    scores = {}
    for r in rows:
        ev = _embed_bytes_to_vec(r["embedding"])
        if ev is None or len(ev) != len(qv):
            continue
        s = float(_np.dot(qv, ev))
        scores.setdefault(r["entry_id"], []).append(s)
    ranked = sorted(
        ((eid, max(vs)) for eid, vs in scores.items()), key=lambda x: x[1], reverse=True)
    out = []
    for eid, s in ranked[:top_n]:
        cur = kb_get(eid)
        if cur:
            cur["score"] = round(s, 4)
            out.append(cur)
    return out


def _rrf_fuse(ranked_lists, k=60):
    """Reciprocal Rank Fusion: 融合多路召回(每路为 id 有序列表), 返回有序 id 列表"""
    rrf = {}
    for lst in ranked_lists:
        for rank, eid in enumerate(lst):
            rrf[eid] = rrf.get(eid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(rrf.items(), key=lambda x: x[1], reverse=True)


def kb_hybrid_search(query, top_n=5, category=None, domain=None, fuse=True):
    """多路召回(全文+向量+关系扩散) + RRF 融合, 返回带来源标记的条目"""
    # 路1: FTS5 全文
    fts_rows = kb_search(query, top_n=top_n * 2, category=category, domain=domain)
    fts_ids = [r["id"] for r in fts_rows]
    fts_score = {r["id"]: r.get("score") or 0 for r in fts_rows}
    # 路2: 向量检索
    vec_rows = []
    try:
        vec_rows = kb_vector_search(query, top_n=top_n * 2)
    except Exception:
        pass
    vec_ids = [r["id"] for r in vec_rows]
    vec_score = {r["id"]: r.get("score") or 0 for r in vec_rows}
    # 路3: 关系扩散(被检索结果关联到的条目)
    rel_ids = []
    if fts_ids:
        placeholders = ",".join("?" * len(fts_ids))
        rel_rows = q(
            f"SELECT DISTINCT to_id id FROM kb_relations WHERE from_id IN ({placeholders})"
            f" UNION SELECT DISTINCT from_id id FROM kb_relations WHERE to_id IN ({placeholders})",
            fts_ids + fts_ids)
        rel_ids = [r["id"] for r in rel_rows if r["id"] not in fts_ids]
    if not fuse or not (fts_ids or vec_ids):
        return fts_rows + vec_rows
    fused = _rrf_fuse([fts_ids, vec_ids])
    out = []
    for eid, rr in fused[:top_n]:
        cur = kb_get(eid)
        if not cur:
            continue
        src = []
        if eid in fts_ids:
            src.append("fts")
        if eid in vec_ids:
            src.append("vec")
        if eid in rel_ids:
            src.append("rel")
        cur["score"] = round(rr, 4)
        cur["recall"] = src
        out.append(cur)
    # 补齐: 若融合结果不足, 追加纯关系扩散与向量候选
    seen = {r["id"] for r in out}
    for eid in rel_ids:
        if len(out) >= top_n:
            break
        if eid in seen:
            continue
        cur = kb_get(eid)
        if cur:
            cur["score"] = 0.0
            cur["recall"] = ["rel"]
            out.append(cur)
            seen.add(eid)
    return out


def _qhash(query):
    """语义近似缓存键: 标题 + 归一化 + bigram 指纹(md5), 使近似查询命中同一缓存"""
    import hashlib
    import re as _re
    q = (query or "").strip().lower()
    q = _re.sub(r"[\s，。！？、；：""''（）《》【】-,.!?;:'\"()\x5b\x5d{}]+", "", q)
    if not q:
        return "empty"
    toks = []
    for seg in _re.findall(r"[\u4e00-\u9fff]+", q):
        if len(seg) == 1:
            toks.append(seg)
        else:
            toks.extend(seg[i:i + 2] for i in range(len(seg) - 1))
    toks.extend(_re.findall(r"[a-z0-9]{2,}", q))
    toks = sorted(set(toks))
    return hashlib.md5("|".join(toks).encode("utf-8")).hexdigest()


def kb_cache_get(query, ttl_seconds=86400, semantic=True):
    """语义查询缓存命中: 精确 _qhash 优先, 未命中时对已缓存查询做向量相似度兜底"""
    h = _qhash(query)
    row = q("SELECT * FROM kb_query_cache WHERE query_hash=?", (h,), one=True)
    if not row and semantic:
        row = _kb_cache_semantic_hit(query)
    if not row:
        return None
    import time as _time
    from datetime import datetime as _dt
    try:
        created = _dt.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
        if (_time.time() - created.timestamp()) > ttl_seconds:
            return None
    except Exception:
        pass
    w("UPDATE kb_query_cache SET hit_count=hit_count+1, last_hit_at=datetime('now','localtime')"
      " WHERE id=?", (row["id"],))
    try:
        return json.loads(row["results_json"])
    except Exception:
        return None


def _kb_cache_semantic_hit(query, threshold=0.80):
    """在已缓存查询中做向量召回(小库快速法), 最相似且超过阈值则命中"""
    import kb_pipeline as kp
    import numpy as _np
    try:
        qv = kp.embed_text(query)
        rows = q("SELECT * FROM kb_query_cache ORDER BY id DESC LIMIT 300")
        best, best_s = None, threshold
        for r in rows:
            tv = kp.embed_text(r["query_text"])
            s = float(_np.dot(qv, tv))
            if s > best_s:
                best, best_s = r, s
        return best
    except Exception:
        return None


def kb_cache_set(query, results):
    h = _qhash(query)
    w("INSERT INTO kb_query_cache(query_hash,query_text,results_json) VALUES(?,?,?)"
      " ON CONFLICT(query_hash) DO UPDATE SET results_json=excluded.results_json,"
      " hit_count=kb_query_cache.hit_count",
      (h, query, json.dumps(results, ensure_ascii=False)))


def kb_memory_add(memory_type, content, scope="kb", scope_id="", confidence=0.6, source=""):
    return w(
        "INSERT INTO kb_memories(memory_type,scope,scope_id,content,confidence,source_conversation)"
        " VALUES(?,?,?,?,?,?)",
        (memory_type or "fact", content or "", scope or "kb", scope_id or "",
         float(confidence or 0.6), source or ""),
    )


def kb_memory_list(memory_type=None, scope=None, limit=50):
    if memory_type and scope:
        return q("SELECT * FROM kb_memories WHERE memory_type=? AND scope=? ORDER BY id DESC LIMIT ?",
                 (memory_type, scope, limit))
    if memory_type:
        return q("SELECT * FROM kb_memories WHERE memory_type=? ORDER BY id DESC LIMIT ?",
                 (memory_type, limit))
    return q("SELECT * FROM kb_memories ORDER BY id DESC LIMIT ?", (limit,))


def kb_harvest_conversation(title, qa_pairs, prefs=None, facts=None):
    """对话收割: 将 QA 对沉淀为知识条目(knowledge/qa), 偏好与事实写入记忆表"""
    added = 0
    for q_text, a_text in (qa_pairs or []):
        if not q_text or not a_text:
            continue
        eid = kb_add(q_text[:80], "", "chat", a_text, source="对话收割",
                     item_type="qa", domain="对话", source_type="对话记录",
                     validity="未知", confidence=0.6, metadata={"harvest": True, "conversation": title})
        kb_embed_entry(eid)
        added += 1
    mem = 0
    for kind, items in (("pref", prefs), ("fact", facts)):
        for item in items or []:
            if item:
                kb_memory_add(kind, item, scope="user", confidence=0.7, source=title)
                mem += 1
    return {"entries": added, "memories": mem}


def kb_audit():
    """M4 健康审计: 生成一次性健康报告(不入库)与持久化快照"""
    total = q("SELECT COUNT(*) c FROM kb_entries", one=True)["c"]
    no_src = q("SELECT COUNT(*) c FROM kb_entries WHERE url='' AND source=''", one=True)["c"]
    no_org = q("SELECT COUNT(*) c FROM kb_entries WHERE org=''", one=True)["c"]
    flagged = q("SELECT COUNT(*) c FROM kb_entries WHERE status='flagged'", one=True)["c"]
    low_conf = q("SELECT COUNT(*) c FROM kb_entries WHERE confidence<0.5", one=True)["c"]
    pend_corr = q("SELECT COUNT(*) c FROM kb_corrections WHERE status='pending'", one=True)["c"]
    chunked = q("SELECT COUNT(DISTINCT entry_id) c FROM kb_chunks", one=True)["c"]
    qa_count = q("SELECT COUNT(*) c FROM kb_entries WHERE item_type='qa'", one=True)["c"]
    mem_count = q("SELECT COUNT(*) c FROM kb_memories", one=True)["c"]
    cache_count = q("SELECT COUNT(*) c FROM kb_query_cache", one=True)["c"]
    conflicts = len(kb_conflicts())
    dup_std = q(
        "SELECT std_no, COUNT(*) c FROM kb_entries WHERE std_no!=''"
        " GROUP BY std_no HAVING c>1", ())
    dup_std_count = sum(r["c"] - 1 for r in dup_std)
    health = 100.0
    if total:
        health -= min(20, (no_src / total) * 40)
        health -= min(15, (no_org / total) * 30)
        health -= min(15, low_conf / total * 100 * 0.3)
        health -= min(10, (flagged / total) * 50)
        health -= min(10, pend_corr * 2)
        health -= min(10, conflicts * 3)
        health -= min(10, dup_std_count * 2)
    health = round(max(0, min(100, health)), 1)
    report = {
        "health": health,
        "total": total,
        "chunked": chunked,
        "qa_entries": qa_count,
        "memories": mem_count,
        "cache_entries": cache_count,
        "no_source": no_src,
        "no_org": no_org,
        "flagged": flagged,
        "low_confidence": low_conf,
        "pending_corrections": pend_corr,
        "conflicts": conflicts,
        "duplicate_std": dup_std_count,
        "generated_at": "",
    }
    w("INSERT INTO kb_audits(report_json) VALUES(?)", (json.dumps(report, ensure_ascii=False),))
    row = q("SELECT created_at FROM kb_audits WHERE id=last_insert_rowid()", one=True)
    if row:
        report["generated_at"] = row["created_at"]
    return report


def kb_audit_latest():
    row = q("SELECT * FROM kb_audits ORDER BY id DESC LIMIT 1", (), one=True)
    if not row:
        return None
    try:
        r = json.loads(row["report_json"])
        r["generated_at"] = row["created_at"]
        return r
    except Exception:
        return None


def kb_conflicts():
    """M4 冲突检测: 同一标准号多条状态冲突 / 重复近似条目"""
    out = []
    # 1. 同标准号但有效性不同
    rows = q(
        "SELECT std_no, COUNT(*) c, COUNT(DISTINCT validity) v FROM kb_entries"
        " WHERE std_no!='' GROUP BY std_no HAVING c>1")
    for r in rows:
        if r["v"] > 1:
            out.append({"type": "validity_conflict", "std_no": r["std_no"],
                        "entries": r["c"], "detail": "同一标准号存在多种有效性标记"})
    # 2. 同标准号且有效性冲突
    rows2 = q(
        "SELECT std_no, COUNT(*) c FROM kb_entries WHERE std_no!='' GROUP BY std_no HAVING c>3")
    for r in rows2:
        out.append({"type": "duplicate_std", "std_no": r["std_no"], "entries": r["c"],
                    "detail": "同一标准号条目过多, 疑似重复"})
    # 3. 相似标题重复(前 12 字符相同)
    rows3 = q(
        "SELECT substr(title,1,12) t, COUNT(*) c FROM kb_entries GROUP BY t HAVING c>1")
    for r in rows3:
        if r["c"] > 1:
            out.append({"type": "similar_title", "title_prefix": r["t"], "entries": r["c"],
                        "detail": "标题前缀相同, 疑似重复条目"})
    return out


def kb_vec_load(conn=None):
    """尝试加载 sqlite-vec 扩展并返回是否可用(独立连接/外部调用用)"""
    try:
        import sqlite_vec
        conn = conn or get_db()
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        _base._VEC_OK = True
        return True
    except Exception:
        _base._VEC_OK = False
        return False


def kb_qc_check(text, title=""):
    """入库质检: 返回 (verdict, reason)
    verdict: pass / empty / low_quality / duplicate"""
    text = (text or "").strip()
    title = (title or "").strip()
    if not text:
        return "empty", "内容为空"
    if len(text) < 50:
        return "low_quality", f"内容过短({len(text)}字符)"
    if title:
        # 精确标题重复: 强信号, 直接拦截
        dup = q("SELECT id FROM kb_entries WHERE title=? LIMIT 1", (title,), one=True)
        if dup:
            return "duplicate", f"标题与条目#{dup['id']}重复"
        # 前缀撞车(如部委文件编号 W02026xxx 前 12 位相同): 需内容指纹双重确认才判重复, 避免误杀
        if len(title) >= 8:
            import hashlib as _hl0
            sig0 = _hl0.md5(text[:500].encode("utf-8", "ignore")).hexdigest()
            for r in q("SELECT id FROM kb_entries WHERE substr(title,1,12)=? ORDER BY id DESC LIMIT 20",
                       (title[:12],)):
                row = q("SELECT substr(content,1,500) s FROM kb_entries WHERE id=?",
                        (r["id"],), one=True)
                if row and _hl0.md5((row["s"] or "").encode("utf-8", "ignore")).hexdigest() == sig0:
                    return "duplicate", f"标题近似且内容指纹与条目#{r['id']}重复"
    # 内容指纹重复(前500字符 md5 近似)
    import hashlib as _hl
    sig = _hl.md5(text[:500].encode("utf-8", "ignore")).hexdigest()
    dup2 = q("SELECT id FROM kb_entries WHERE substr(content,1,500) IS NOT NULL LIMIT 1")
    if dup2:
        rows = q("SELECT id, substr(content,1,500) s FROM kb_entries WHERE length(content)>100"
                 " ORDER BY id DESC LIMIT 300")
        for r in rows:
            if _hl.md5((r["s"] or "").encode("utf-8", "ignore")).hexdigest() == sig:
                return "duplicate", f"内容指纹与条目#{r['id']}重复"
    return "pass", ""


def kb_qc_list(limit=100):
    """质检记录列表"""
    return q("SELECT * FROM kb_import_qc ORDER BY id DESC LIMIT ?", (limit,))


def kb_qc_stats():
    rows = q("SELECT verdict, COUNT(*) c FROM kb_import_qc GROUP BY verdict")
    return {r["verdict"]: r["c"] for r in rows}


def kb_classify_doc(title, text="", fallback=None):
    """LLM 兜底分类包装: 规则置信度不足时调 LLM, 失败回退规则结果"""
    import kb_pipeline as kp
    if fallback is None:
        fallback = kp.classify_doc(title, text)
    return kp.classify_llm(title, text, fallback)


def kb_embed_all(batch_size=20):
    """为缺失向量的条目批量补向量(分批避免大事务)"""
    import numpy as _np
    missing = q("SELECT id FROM kb_entries WHERE id NOT IN"
                " (SELECT DISTINCT entry_id FROM kb_chunks) ORDER BY id")
    total, done = len(missing), 0
    for i in range(0, len(missing), batch_size):
        for r in missing[i:i + batch_size]:
            try:
                kb_embed_entry(r["id"], force=True)
                done += 1
            except Exception:
                pass
    return {"total": total, "done": done}


def kb_backup(kind="manual", note=""):
    """自动备份: VACUUM INTO 数据库快照 + data/kb/ 目录 zip 打包; 返回备份信息"""
    import time as _t
    import zipfile
    stamp = _t.strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(DATA_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    db_dst = os.path.join(backup_dir, f"ecoagent_kb_backup_{stamp}.db")
    zip_dst = os.path.join(backup_dir, f"kb_{stamp}.zip")
    info = {"kind": kind, "stamp": stamp, "db_path": "", "zip_path": "", "db_size": 0,
            "files_count": 0, "status": "done", "note": note}
    # 1) 数据库快照(VACUUM INTO 不接受参数, 需转义单引号拼接)
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA busy_timeout=5000")
        esc = db_dst.replace("'", "''")
        conn.execute(f"VACUUM INTO '{esc}'")
        conn.close()
        info["db_path"] = db_dst
        info["db_size"] = os.path.getsize(db_dst)
    except Exception as e:
        info["status"] = "partial"
        info["note"] = (info["note"] + " | " if info["note"] else "") + f"db快照失败:{e}"
    # 2) kb/ 目录 zip
    try:
        kb_dir = os.path.join(DATA_DIR, "kb")
        if os.path.isdir(kb_dir):
            count = 0
            with zipfile.ZipFile(zip_dst, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, names in os.walk(kb_dir):
                    for n in names:
                        p = os.path.join(root, n)
                        zf.write(p, os.path.relpath(p, DATA_DIR))
                        count += 1
            info["zip_path"] = zip_dst
            info["files_count"] = count
    except Exception as e:
        info["status"] = "partial"
        info["note"] = (info["note"] + " | " if info["note"] else "") + f"zip打包失败:{e}"
    w("INSERT INTO kb_backups(kind,path,db_size,files_count,status,note) VALUES(?,?,?,?,?,?)",
      (kind, db_dst or zip_dst, info["db_size"], info["files_count"], info["status"], info["note"]))
    return info


def kb_backup_if_due(interval_hours=24):
    """每日自动备份: 距上次备份超过 interval_hours 才触发"""
    import time as _t
    last = q("SELECT created_at FROM kb_backups ORDER BY id DESC LIMIT 1", one=True)
    if last:
        from datetime import datetime as _dt
        try:
            t0 = _dt.strptime(last["created_at"], "%Y-%m-%d %H:%M:%S").timestamp()
            if _t.time() - t0 < interval_hours * 3600:
                return {"skipped": True, "last": last["created_at"]}
        except Exception:
            pass
    info = kb_backup(kind="daily", note="每日自动")
    return info


def kb_backups_list(limit=10):
    return q("SELECT * FROM kb_backups ORDER BY id DESC LIMIT ?", (limit,))


def kb_restore(path):
    """从备份数据库恢复: 仅覆盖 kb 相关普通表(不含 FTS/虚拟表, 返回受影响表数)"""
    if not path or not os.path.isfile(path):
        return {"ok": False, "error": "备份文件不存在"}
    dst = get_db()
    try:
        dst.execute("ATTACH DATABASE ? AS kbsrc", (path,))
        tables = [r[0] for r in dst.execute(
            "SELECT name FROM kbsrc.sqlite_master WHERE type='table'"
            " AND name LIKE 'kb%' AND name NOT LIKE 'kb_fts%'"
            " AND name NOT LIKE 'kb_fts_%' AND name != 'kb_vec'").fetchall()]
    except Exception as e:
        return {"ok": False, "error": f"无法读取备份:{e}"}
    restored = []
    try:
        for t in tables:
            try:
                dst.execute(f"DROP TABLE IF EXISTS {t}")
                dst.execute(f"CREATE TABLE {t} AS SELECT * FROM kbsrc.{t}")
                restored.append(t)
            except Exception:
                pass
        dst.commit()
    finally:
        try:
            dst.execute("DETACH DATABASE kbsrc")
        except Exception:
            pass
    # 恢复后重建向量索引
    try:
        kb_embed_all(batch_size=20)
    except Exception:
        pass
    return {"ok": True, "restored": restored}


def kb_import_files(paths, batch_name=""):
    """批量导入文档/网页URL: 解析 -> 质检 -> 分类(LLM兜底) -> 落库 -> 分块向量化; 返回导入报告
    - 本地路径: 文件或目录, 支持 PDF/DOCX/HTML/TXT/MD/XLSX
    - http(s):// 开头的行: 视为网页 URL, 校验正规来源(仅 gov.cn 等官方域名)后抓取转 Markdown 入库
    全程单事务提交(提速), 单条失败不阻断后续; 标题优先用正文首段真实标题。"""
    import kb_pipeline as kp
    batch_name = batch_name or "batch"
    if isinstance(paths, str):
        paths = [paths]
    import os as _os
    files, urls = [], []
    for p in paths:
        p = str(p or "").strip()
        if not p:
            continue
        if p.lower().startswith(("http://", "https://")):
            urls.append(p)
            continue
        if _os.path.isdir(p):
            for root, _, names in _os.walk(p):
                for n in names:
                    if _os.path.splitext(n)[1].lower() in kp._EXT_READERS:
                        files.append(_os.path.join(root, n))
        elif _os.path.isfile(p):
            files.append(p)
    if not files and not urls:
        return {"batch": batch_name, "ok": 0, "fail": 0, "entries": [],
                "errors": ["无有效文件或网址"]}
    batch_id = w("INSERT INTO kb_imports(batch_name,status,total_files) VALUES(?,?,?)",
                 (batch_name, "running", len(files) + len(urls)))
    ok, fail, entry_ids, errors = 0, 0, [], []
    md_dir = _os.path.join(DATA_DIR, "kb")
    files_dir = _os.path.join(DATA_DIR, "kb", "files")
    _os.makedirs(files_dir, exist_ok=True)
    begin_batch()
    try:
        # 预解析: 本地文件提取 Markdown; 网页 URL 校验正规来源后抓取(单条失败记空记录不阻断)
        items = []
        for f in files:
            text = kp.extract_markdown(f)
            if not text.strip():
                fail += 1
                errors.append(f"{_os.path.basename(f)}: 解析失败或空内容")
                w("INSERT INTO kb_import_qc(batch_id,file,title,verdict,reason) VALUES(?,?,?,?,?)",
                  (batch_id, _os.path.basename(f), _os.path.splitext(_os.path.basename(f))[0],
                   "empty", "解析失败或空内容"))
                continue
            items.append({"text": text, "display": _os.path.basename(f),
                          "title_hint": _os.path.splitext(_os.path.basename(f))[0],
                          "url": "", "source": "本地导入", "source_type": "文档", "file": f})
        for u in urls:
            try:
                text, hint = kp.url_to_markdown(u)
            except Exception as e:
                fail += 1
                err = f"{u}: 网页抓取失败({e})"
                errors.append(err)
                w("INSERT INTO kb_import_qc(batch_id,file,title,verdict,reason) VALUES(?,?,?,?,?)",
                  (batch_id, u, u, "empty", str(e)))
                continue
            if not text.strip():
                fail += 1
                errors.append(f"{u}: 网页正文为空")
                w("INSERT INTO kb_import_qc(batch_id,file,title,verdict,reason) VALUES(?,?,?,?,?)",
                  (batch_id, u, u, "empty", "网页正文为空"))
                continue
            items.append({"text": text, "display": u, "title_hint": hint or u,
                          "url": u, "source": "网页导入", "source_type": "网页", "file": ""})
        for it in items:
            text, display = it["text"], it["display"]
            # 统一转换为 Markdown 结构化文本入库(Markdown 为资料库统一保存格式)
            plain = kp.md_from_text(text) or text
            # 自动命名: 优先正文首段真实标题(避免部委文件编号 W02026xxx 当标题), 失败回退文件名/网页h1
            title = _kb_guess_title(plain, it["title_hint"])
            # 入库质检: 空/重复 阻断; 低质量 仅标记记录, 不阻断入库(避免误杀短文档)
            verdict, reason = kb_qc_check(plain, title)
            if verdict in ("empty", "duplicate"):
                fail += 1
                errors.append(f"{display}: 质检未通过({reason})")
                w("INSERT INTO kb_import_qc(batch_id,file,title,verdict,reason) VALUES(?,?,?,?,?)",
                  (batch_id, display, title, verdict, reason))
                continue
            meta = kp.parse_meta(title, plain)
            domain, itype, stype, conf = kp.classify_doc(title, plain)
            # LLM 兜底分类: 规则置信度不足时调用 LLM, 失败回退规则结果
            if conf < 0.7:
                domain, itype, stype, conf = kp.classify_llm(title, plain[:1500],
                                                             (domain, itype, stype, conf))
            # 检测到标准号且标题未含时追加 " (标准号)"
            std_no = (meta.get("std_no") or "").replace(" ", "")
            if std_no and std_no not in title.replace(" ", ""):
                title = f"{title} ({std_no})"
            # 分类: 征求意见稿 > 标准(有标准号/standard 类型) > item_type 语义 > 来源兜底
            if "征求意见稿" in title or "征求意见" in plain[:200]:
                category = "draft"
            elif std_no or itype == "standard":
                category = "standard"
            else:
                category = {"regulation": "policy", "policy": "policy", "manual": "other",
                            "knowledge": "other"}.get(itype, stype if stype != "原文" else "file")
            eid = kb_add(title, it["url"], category, text[:200000],
                         source=it["source"], item_type=itype, domain=domain,
                         source_type=it["source_type"], validity=meta.get("validity") or "未知",
                         confidence=conf, std_no=meta.get("std_no") or "",
                         org=meta.get("org") or "", publish_date=meta.get("publish_date") or "",
                         metadata={"file": it["file"] or it["url"], "import_batch": batch_id})
            # 原始文件副本 -> data/kb/files/<eid>_<原名>(仅本地文件), metadata.file 指向副本
            fcopy = ""
            if it["file"]:
                try:
                    import shutil as _sh
                    fcopy = _os.path.join(files_dir, f"{eid}_{display}")
                    _sh.copy2(it["file"], fcopy)
                except Exception:
                    fcopy = ""
            # Markdown 全文落盘到数据目录 kb/ 供资料库直接读取
            md_path = kp.save_md_copy(md_dir, eid, text)
            if md_path or fcopy:
                meta_json = {"file": fcopy or it["file"] or it["url"], "file_md": md_path,
                             "import_batch": batch_id}
                if it["url"]:
                    meta_json["source_url"] = it["url"]
                w("UPDATE kb_entries SET metadata_json=? WHERE id=?",
                  (json.dumps(meta_json, ensure_ascii=False), eid))
            # 分块向量化: 失败不阻断导入(向量缺失仅影响语义检索, 关键词检索仍可用)
            try:
                kb_embed_entry(eid)
            except Exception:
                pass
            # 低质量不阻断, 但记录质检标记
            final_verdict = "pass" if verdict == "pass" else verdict
            w("INSERT INTO kb_import_qc(batch_id,file,title,verdict,reason,entry_id) VALUES(?,?,?,?,?,?)",
              (batch_id, display, title, final_verdict, reason, eid))
            entry_ids.append(eid)
            ok += 1
    finally:
        commit_batch()
    w("UPDATE kb_imports SET status='done', ok_files=?, fail_files=?, entry_ids=?, report_json=?"
      " WHERE id=?",
      (ok, fail, json.dumps(entry_ids), json.dumps({"errors": errors[:20]}, ensure_ascii=False),
       batch_id))
    return {"batch": batch_name, "batch_id": batch_id, "ok": ok, "fail": fail,
            "entries": entry_ids, "errors": errors[:20]}


def kb_imports_list(limit=20):
    return q("SELECT * FROM kb_imports ORDER BY id DESC LIMIT ?", (limit,))


def kb_export(domain=None, fmt="json"):
    """导出知识库: json(全字段)/markdown(可读文本)"""
    import io
    import zipfile
    import time
    if domain:
        rows = q("SELECT * FROM kb_entries WHERE domain=?", (domain,))
    else:
        rows = q("SELECT * FROM kb_entries")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = []
        for r in rows:
            if fmt == "markdown":
                content = (f"# {r['title']}\n\n"
                           f"- 标准号: {r.get('std_no') or ''}\n"
                           f"- 机构: {r.get('org') or ''}\n"
                           f"- 领域: {r.get('domain') or ''}\n"
                           f"- 有效性: {r.get('validity') or ''}\n"
                           f"- 来源: {r.get('url') or r.get('source') or ''}\n\n"
                           f"{r['content']}\n")
                name = f"kb/{r['id']:04d}.md"
                zf.writestr(name, content.encode("utf-8"))
            else:
                name = f"kb/{r['id']:04d}.json"
                zf.writestr(name, json.dumps(dict(r), ensure_ascii=False).encode("utf-8"))
            manifest.append({"id": r["id"], "title": r["title"], "domain": r.get("domain") or ""})
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
        zf.writestr("README.txt",
                    f"EnvironmentAgent 知识库导出 {stamp}\n条目数: {len(rows)}\n".encode("utf-8"))
    data = buf.getvalue()
    import base64
    return {"filename": f"kb_export_{stamp}.zip", "count": len(rows),
            "size": len(data), "b64": base64.b64encode(data).decode("ascii")}
