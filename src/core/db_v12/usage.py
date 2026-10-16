# -*- coding: utf-8 -*-
"""S1-W5 db.py 拆分：用量统计/成本/缓存/技能开关数据层（usage 域）。

从根 db.py 原样搬移：log_usage/stats_cache/calc_cost/usage_stats/task_usage/
search_cache_get/set/skill_state/skill_set + USAGE_PRICING 常量。
"""
from __future__ import annotations

import json

from .base import q, w

USAGE_PRICING = {
    "claude-opus-4.5":  {"input": 0.005, "output": 0.025, "cache_read": 0.0005,   "cache_creation": 0.005},
    "claude-sonnet-4.5":{"input": 0.003, "output": 0.015, "cache_read": 0.0003,   "cache_creation": 0.003},
    "claude-opus":      {"input": 0.015, "output": 0.075, "cache_read": 0.0015,   "cache_creation": 0.015},
    "claude-sonnet":    {"input": 0.003, "output": 0.015, "cache_read": 0.0003,   "cache_creation": 0.003},
    "claude":           {"input": 0.003, "output": 0.015, "cache_read": 0.0003,   "cache_creation": 0.003},
    "gpt-5":            {"input": 0.00125, "output": 0.01, "cache_read": 0.000625, "cache_creation": 0.00125},
    "gpt-4o":           {"input": 0.0025, "output": 0.01, "cache_read": 0.00125,   "cache_creation": 0.0025},
    "deepseek-v4-pro":  {"input": 0.000435, "output": 0.00087, "cache_read": 0.000003625, "cache_creation": 0.000435},
    "deepseek-v4-flash":{"input": 0.00014, "output": 0.00028, "cache_read": 0.0000028,   "cache_creation": 0.00014},
    "deepseek-v4":      {"input": 0.00014, "output": 0.00028, "cache_read": 0.0000028,   "cache_creation": 0.00014},
    "deepseek-chat":    {"input": 0.00014, "output": 0.00028, "cache_read": 0.0000028,   "cache_creation": 0.00014},
    "deepseek-reasoner":{"input": 0.00056, "output": 0.0042, "cache_read": 0.0000028,   "cache_creation": 0.00056},
    "deepseek":         {"input": 0.00014, "output": 0.00028, "cache_read": 0.0000028,   "cache_creation": 0.00014},
    "qwen3-max":        {"input": 0.0006, "output": 0.0024, "cache_read": 0.00012,  "cache_creation": 0.0006},
    "qwen":             {"input": 0.0006, "output": 0.0024, "cache_read": 0.00012,  "cache_creation": 0.0006},
    "glm-5":            {"input": 0.001, "output": 0.0032, "cache_read": 0.0001,   "cache_creation": 0.001},
    "glm":              {"input": 0.001, "output": 0.0032, "cache_read": 0.0001,   "cache_creation": 0.001},
    "moonshot":         {"input": 0.001, "output": 0.004,  "cache_read": 0.0001,   "cache_creation": 0.001},
    "kimi":             {"input": 0.001, "output": 0.004,  "cache_read": 0.0001,   "cache_creation": 0.001},
}

_USAGE_FREE_MODELS = ("ollama", "llama", "qwen2.5", "qwen3:1", "local", "phi", "mistral")


def log_usage(task_id, provider_id, model, prompt_tokens, completion_tokens, cache_hit, cache_miss,
              cache_creation=0, thinking_tokens=0, latency_ms=0, mode="", domain=""):
    w(
        "INSERT INTO cache_log(task_id,provider_id,model,prompt_tokens,completion_tokens,cache_hit,cache_miss,"
        "cache_creation,thinking_tokens,latency_ms,mode,domain)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (task_id, provider_id, model, prompt_tokens, completion_tokens, cache_hit, cache_miss,
         cache_creation, thinking_tokens, latency_ms, mode, domain),
    )


def stats_cache():
    rows = q("SELECT * FROM cache_log ORDER BY id DESC LIMIT 50")
    today_rows = q("SELECT * FROM cache_log WHERE date(created_at)=date('now','localtime')")
    total_prompt = sum(r["prompt_tokens"] for r in today_rows)
    total_hit = sum(r["cache_hit"] for r in today_rows)
    total_comp = sum(r["completion_tokens"] for r in today_rows)
    return {
        "recent": rows,
        "today": {
            "requests": len(today_rows),
            "prompt_tokens": total_prompt,
            "completion_tokens": total_comp,
            "cache_hit": total_hit,
            "cache_miss": total_prompt - total_hit,
            "hit_rate": (total_hit / total_prompt) if total_prompt else 0,
        },
    }


def _usage_price(model):
    """按模型名(含模糊匹配)取价表, 未收录返回 None"""
    m = (model or "").strip().lower()
    if not m:
        return None
    if any(k in m for k in _USAGE_FREE_MODELS):
        return {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_creation": 0.0}
    # 精确匹配优先, 其次按最长的包含匹配
    if m in USAGE_PRICING:
        return USAGE_PRICING[m]
    best = None
    for key, p in USAGE_PRICING.items():
        if key in m and (best is None or len(key) > len(best)):
            best = key
    return USAGE_PRICING.get(best)


def calc_cost(model, prompt_tokens, completion_tokens, cache_hit, cache_miss, cache_creation=0):
    """按价表计算单次调用成本(USD); 未收录模型返回 0
    公式(对齐《方案设计》v1.3):
      (miss * input + hit * cache_read + creation * cache_creation + completion * output) / 1000
    """
    p = _usage_price(model)
    if not p:
        return 0.0
    miss = max(int(cache_miss), 0)
    hit = max(int(cache_hit), 0)
    creation = max(int(cache_creation), 0)
    return (
        miss * p["input"]
        + hit * p["cache_read"]
        + creation * p.get("cache_creation", p["input"])
        + max(int(completion_tokens), 0) * p["output"]
    ) / 1000.0


def usage_stats(range_key="today"):
    """Token 与成本统计聚合。range_key: today / 7d / 30d / all"""
    import datetime as _dt
    today = _dt.date.today()
    if range_key == "today":
        since = today.isoformat()
        days = 1
    elif range_key == "7d":
        since = (today - _dt.timedelta(days=6)).isoformat()
        days = 7
    elif range_key == "30d":
        since = (today - _dt.timedelta(days=29)).isoformat()
        days = 30
    else:
        since = None
        days = 30

    if since:
        rows = q(
            "SELECT * FROM cache_log WHERE date(created_at) >= ? ORDER BY id DESC",
            (since,),
        )
    else:
        rows = q("SELECT * FROM cache_log ORDER BY id DESC")

    def _row_cost(r):
        return calc_cost(r["model"], r["prompt_tokens"], r["completion_tokens"],
                         r["cache_hit"], r["cache_miss"], r["cache_creation"] or 0)

    # 汇总
    n = len(rows)
    prompt = sum(r["prompt_tokens"] for r in rows)
    comp = sum(r["completion_tokens"] for r in rows)
    hit = sum(r["cache_hit"] for r in rows)
    miss = sum(r["cache_miss"] for r in rows)
    creation = sum(r["cache_creation"] or 0 for r in rows)
    thinking = sum(r["thinking_tokens"] or 0 for r in rows)
    lat_list = [r["latency_ms"] or 0 for r in rows if (r["latency_ms"] or 0) > 0]
    cost = sum(_row_cost(r) for r in rows)
    hit_rate = (hit / (hit + miss)) if (hit + miss) else 0.0
    task_ids = {r["task_id"] for r in rows if r["task_id"]}

    # 按模型分布(成本降序)
    by_model = {}
    for r in rows:
        md = by_model.setdefault(r["model"] or "unknown", {"requests": 0, "prompt": 0, "comp": 0, "hit": 0, "miss": 0, "cost": 0.0})
        md["requests"] += 1
        md["prompt"] += r["prompt_tokens"]
        md["comp"] += r["completion_tokens"]
        md["hit"] += r["cache_hit"]
        md["miss"] += r["cache_miss"]
        md["cost"] += _row_cost(r)
    by_model = sorted(by_model.items(), key=lambda kv: kv[1]["cost"], reverse=True)

    # 按模式分布(craft/ask/plan)
    by_mode = {}
    for r in rows:
        m = r["mode"] or "craft"
        bm = by_mode.setdefault(m, {"requests": 0, "tokens": 0, "cost": 0.0})
        bm["requests"] += 1
        bm["tokens"] += r["prompt_tokens"] + r["completion_tokens"]
        bm["cost"] += _row_cost(r)
    by_mode = sorted(by_mode.items(), key=lambda kv: kv[1]["cost"], reverse=True)

    # 按领域分布(知识域)
    by_domain = {}
    for r in rows:
        d = r["domain"] or "未分类"
        bd = by_domain.setdefault(d, {"requests": 0, "tokens": 0, "cost": 0.0})
        bd["requests"] += 1
        bd["tokens"] += r["prompt_tokens"] + r["completion_tokens"]
        bd["cost"] += _row_cost(r)
    by_domain = sorted(by_domain.items(), key=lambda kv: kv[1]["cost"], reverse=True)

    # 按日聚合(补零, 成本+命中率)
    daily = []
    for i in range(days - 1, -1, -1):
        d = (today - _dt.timedelta(days=i)).isoformat()
        daily.append({"date": d, "requests": 0, "prompt": 0, "comp": 0, "hit": 0, "miss": 0, "creation": 0, "thinking": 0, "cost": 0.0, "hit_rate": 0.0})
    daily_idx = {d["date"]: d for d in daily}
    for r in rows:
        d = (r["created_at"] or "")[:10]
        if d in daily_idx:
            dd = daily_idx[d]
            dd["requests"] += 1
            dd["prompt"] += r["prompt_tokens"]
            dd["comp"] += r["completion_tokens"]
            dd["hit"] += r["cache_hit"]
            dd["miss"] += r["cache_miss"]
            dd["creation"] += r["cache_creation"] or 0
            dd["thinking"] += r["thinking_tokens"] or 0
            dd["cost"] += _row_cost(r)
    for dd in daily:
        tot = dd["hit"] + dd["miss"]
        dd["hit_rate"] = round((dd["hit"] / tot) if tot else 0.0, 4)

    # 最近明细(含单次成本)
    recent = []
    for r in rows[:50]:
        recent.append({
            "id": r["id"],
            "task_id": r["task_id"],
            "model": r["model"],
            "prompt": r["prompt_tokens"],
            "comp": r["completion_tokens"],
            "hit": r["cache_hit"],
            "miss": r["cache_miss"],
            "creation": r["cache_creation"] or 0,
            "thinking": r["thinking_tokens"] or 0,
            "latency_ms": r["latency_ms"] or 0,
            "mode": r["mode"] or "",
            "domain": r["domain"] or "",
            "cost": _row_cost(r),
            "created_at": r["created_at"],
        })

    # Top 高成本任务(按 task 聚合成本)
    top_tasks = {}
    for r in rows:
        if not r["task_id"]:
            continue
        tt = top_tasks.setdefault(r["task_id"], {"task_id": r["task_id"], "title": "", "requests": 0, "tokens": 0, "cost": 0.0, "latency_ms": 0})
        tt["requests"] += 1
        tt["tokens"] += r["prompt_tokens"] + r["completion_tokens"]
        tt["cost"] += _row_cost(r)
        tt["latency_ms"] += r["latency_ms"] or 0
    if top_tasks:
        ids = list(top_tasks.keys())
        marks = ",".join("?" * len(ids))
        trows = q(f"SELECT id, title FROM tasks WHERE id IN ({marks})", tuple(ids))
        tmap = {t["id"]: t["title"] for t in trows}
        for tid, tt in top_tasks.items():
            tt["title"] = tmap.get(tid) or f"任务 #{tid}"
    top_tasks = sorted(top_tasks.values(), key=lambda t: t["cost"], reverse=True)[:10]
    for tt in top_tasks:
        tt["cost"] = round(tt["cost"], 6)

    # 耗时分布(p50/p95/平均)
    latency = {"count": len(lat_list), "avg_ms": 0, "p50_ms": 0, "p95_ms": 0}
    if lat_list:
        lat_list.sort()
        latency["avg_ms"] = int(sum(lat_list) / len(lat_list))
        latency["p50_ms"] = lat_list[int(len(lat_list) * 0.5)]
        latency["p95_ms"] = lat_list[min(len(lat_list) - 1, int(len(lat_list) * 0.95))]

    return {
        "range": range_key,
        "summary": {
            "requests": n,
            "tasks": len(task_ids),
            "prompt": prompt,
            "comp": comp,
            "hit": hit,
            "miss": miss,
            "creation": creation,
            "thinking": thinking,
            "tokens": prompt + comp,
            "cost": round(cost, 6),
            "hit_rate": round(hit_rate, 4),
        },
        "by_model": [{"model": k, **v} for k, v in by_model],
        "by_mode": [{"mode": k, **v} for k, v in by_mode],
        "by_domain": [{"domain": k, **v} for k, v in by_domain],
        "daily": daily,
        "latency": latency,
        "top_tasks": top_tasks,
        "recent": recent,
    }


def task_usage(task_id):
    """当前任务的 Token 消耗明细(仿 Codex 实时面板),只统计该任务。"""
    tid = str(task_id)
    rows = q("SELECT * FROM cache_log WHERE task_id=? ORDER BY id DESC", (tid,))

    def _row_cost(r):
        return calc_cost(
            r["model"], r["prompt_tokens"], r["completion_tokens"],
            r["cache_hit"], r["cache_miss"], r["cache_creation"] or 0,
        )

    n = len(rows)
    prompt = sum(r["prompt_tokens"] for r in rows)
    comp = sum(r["completion_tokens"] for r in rows)
    hit = sum(r["cache_hit"] for r in rows)
    miss = sum(r["cache_miss"] for r in rows)
    creation = sum(r["cache_creation"] or 0 for r in rows)
    thinking = sum(r["thinking_tokens"] or 0 for r in rows)
    cost = sum(_row_cost(r) for r in rows)
    hit_rate = (hit / (hit + miss)) if (hit + miss) else 0.0
    lat_list = [r["latency_ms"] for r in rows if (r["latency_ms"] or 0) > 0]
    lat_list.sort()
    latency = {"count": len(lat_list), "avg_ms": 0, "p50_ms": 0, "p95_ms": 0}
    if lat_list:
        latency["avg_ms"] = int(sum(lat_list) / len(lat_list))
        latency["p50_ms"] = lat_list[int(len(lat_list) * 0.5)]
        latency["p95_ms"] = lat_list[min(len(lat_list) - 1, int(len(lat_list) * 0.95))]

    task = {}
    t = q("SELECT id, title, mode, status, created_at FROM tasks WHERE id=?", (tid,), one=True)
    if t:
        task = {"id": t["id"], "title": t["title"], "mode": t["mode"],
                "status": t["status"], "created_at": t["created_at"]}

    return {
        "task_id": int(tid),
        "task": task,
        "summary": {
            "requests": n,
            "prompt": prompt,
            "completion": comp,
            "comp": comp,
            "hit": hit,
            "miss": miss,
            "creation": creation,
            "thinking": thinking,
            "tokens": prompt + comp,
            "cost": round(cost, 6),
            "hit_rate": round(hit_rate, 4),
        },
        "latency": latency,
    }


def search_cache_get(query_hash):
    r = q(
        "SELECT * FROM search_cache WHERE query_hash=? AND"
        " datetime(created_at, '+' || ttl_hours || ' hours') > datetime('now','localtime')",
        (query_hash,),
        one=True,
    )
    if not r:
        return None
    try:
        return json.loads(r["results_json"])
    except Exception:
        return None


def search_cache_set(query_hash, query_text, results, provider="", ttl_hours=24):
    try:
        w(
            "INSERT INTO search_cache(query_hash,query_text,results_json,provider,ttl_hours)"
            " VALUES(?,?,?,?,?) ON CONFLICT(query_hash) DO UPDATE SET"
            " results_json=excluded.results_json, provider=excluded.provider,"
            " ttl_hours=excluded.ttl_hours, created_at=datetime('now','localtime')",
            (query_hash, query_text, json.dumps(results, ensure_ascii=False), provider, ttl_hours),
        )
    except Exception:
        pass


def skill_state(key):
    r = q("SELECT enabled FROM skills_state WHERE key=?", (key,), one=True)
    return bool(r and r["enabled"])


def skill_set(key, enabled):
    w("INSERT INTO skills_state(key,enabled) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET enabled=excluded.enabled",
      (key, 1 if enabled else 0))
