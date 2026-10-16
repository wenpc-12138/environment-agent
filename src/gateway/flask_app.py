# -*- coding: utf-8 -*-
"""生态Agent - Flask 服务与 API 路由（S2-M4 迁移）

S2-M4 迁移（2026-08-20）：自根目录 `app.py` 原样迁入（207 路由不动）；
根 app.py 已转薄入口（`from src.gateway.flask_app import create_app`）。
"""
import json
import os
import re
import subprocess
import sys
import time
import threading
from flask import Flask, request, jsonify, Response, render_template, g

from src.core import db_v12 as db
import tools
from src.skills import loader as skills
import seed
from src.core import context as context_mgr
from src import agent as agent_core
from src.tools import websearch

from pathlib import Path as _Path
BASE_DIR = str(_Path(__file__).resolve().parents[2])  # S2-M4：项目根
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"),
            static_folder=os.path.join(BASE_DIR, "static"))
app.config["JSON_AS_ASCII"] = False
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.config["TEMPLATES_AUTO_RELOAD"] = True  # debug=False 下也实时重载模板,便于热更新 index.html


@app.after_request
def _no_cache(resp):
    # 开发期禁用缓存,避免 HTML/CSS/JS 更新后仍命中旧页面
    if resp.mimetype in ("text/html", "text/css", "application/javascript") or request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


@app.teardown_appcontext
def _close_db(exc):
    db.close_db()


def sse_pack(event, **data):
    payload = json.dumps({"event": event, **data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


def sse_stream(gen):
    for item in gen:
        if isinstance(item, dict) and "event" in item:
            yield sse_pack(item["event"], **{k: v for k, v in item.items() if k != "event"})
        else:
            yield sse_pack("message", **item)
    yield sse_pack("stream_end")


# ---------------- 附件上传(前端拖入的非文本文件保存到服务端, 供 Agent 直接解析) ----------------
UPLOAD_DIR = os.path.join(BASE_DIR, "data", "uploads")


@app.route("/api/upload", methods=["POST"])
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "未收到文件"}), 400
    name = os.path.basename(f.filename)
    safe = re.sub(r"[\\/:*?\"<>|\s]+", "_", name).strip("._") or "attach"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = os.path.join(UPLOAD_DIR, safe)
    if os.path.exists(path):
        stem, ext = os.path.splitext(safe)
        path = os.path.join(UPLOAD_DIR, f"{stem}_{int(time.time())}{ext}")
    f.save(path)
    return jsonify({"ok": True, "path": path, "name": name, "size": os.path.getsize(path)})


@app.route("/uploads/<path:filename>")
def uploads_static(filename):
    """G6：上传目录静态访问（前端图片缩略图）。"""
    from flask import send_from_directory
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/api/vision/analyze", methods=["POST"])
def api_vision_analyze():
    """G6：图片视觉理解（VLM 直读优先 / RapidOCR 兜底）。"""
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.vision_analyze(d.get("path", ""), d.get("question", "")))


@app.route("/api/v2/vision/supported")
def api_v2_vision_supported():
    """G6：当前 Provider 多模态能力检测。"""
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.vision_supported())


# ---------------- 页面 ----------------
@app.route("/")
def index():
    return render_template("index.html")


# S4-F1 Vue3 渐进迁移入口：第一批报告中心（Vite 构建产物，伺服于 /static/vue/）
@app.route("/vue/reports")
def vue_reports():
    from flask import send_from_directory
    return send_from_directory(os.path.join(BASE_DIR, "static", "vue", "src"),
                               "reports.html")


@app.route("/vue/")
def vue_root():
    return vue_reports()


# S4-F1 第二批：知识库 / 计划调度
@app.route("/vue/kb")
def vue_kb():
    from flask import send_from_directory
    return send_from_directory(os.path.join(BASE_DIR, "static", "vue", "src"), "kb.html")


@app.route("/vue/planner")
def vue_planner():
    from flask import send_from_directory
    return send_from_directory(os.path.join(BASE_DIR, "static", "vue", "src"), "planner.html")


# S4-F1 第三批：对话工作台
@app.route("/vue/chat")
def vue_chat():
    from flask import send_from_directory
    return send_from_directory(os.path.join(BASE_DIR, "static", "vue", "src"), "chat.html")


@app.route("/api/meta")
def meta():
    return jsonify({
        "categories": tools.CATEGORIES,
        "presets": [
            {"name": "DeepSeek", "model": "deepseek-v4-pro", "base_url": "https://api.deepseek.com", "desc": "DeepSeek 官方 API,支持上下文硬盘缓存(命中记账)"},
            {"name": "OpenAI", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1", "desc": "OpenAI 官方 API"},
            {"name": "智谱 GLM", "model": "glm-4-flash", "base_url": "https://open.bigmodel.cn/api/paas/v4", "desc": "智谱清言,glm-4-flash 免费"},
            {"name": "通义 Qwen", "model": "qwen-plus", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "desc": "阿里云百炼,OpenAI 兼容模式"},
            {"name": "本地 Ollama", "model": "qwen2.5:7b", "base_url": "http://localhost:11434/v1", "desc": "本地部署,无数据出网"},
        ],
        "budget": {"soft": context_mgr.SOFT_BUDGET, "hard": context_mgr.HARD_BUDGET},
        "tools": [t["function"]["name"] for t in tools.TOOL_SCHEMAS],
    })


# ---------------- 联网搜索配置 (SearXNG) ----------------
@app.route("/api/search/config", methods=["GET"])
def api_search_config():
    return jsonify(websearch.status())


@app.route("/api/search/config", methods=["POST"])
def api_search_config_save():
    data = request.get_json(force=True) or {}
    cfg = websearch.save_config(data)
    return jsonify({"ok": True, "config": cfg})


@app.route("/api/search/status", methods=["GET"])
def api_search_status():
    # 每次查询先幂等触发一次 SearXNG 探测/复用/自愈, 保证 external 实例 PID 等状态实时
    try:
        import searxng_launcher
        searxng_launcher.ensure_running()
    except Exception:  # noqa: BLE001
        pass
    return jsonify(websearch.status())


@app.route("/api/ocr/status", methods=["GET"])
def api_ocr_status():
    # OCR/PDF 独立 worker(rapidocr+pymupdf 在 runtime/ocr/venv) 探测/复用/自愈
    try:
        import ocr_launcher
        ocr_launcher.ensure_running()
        return jsonify(ocr_launcher.status())
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "mode": "error", "last_err": str(e)})


@app.route("/api/search/restart", methods=["POST"])
def api_search_restart():
    """控制: 强制重启本模块管理的 SearXNG(外部/远程实例不接管)"""
    try:
        import searxng_launcher

        snap = searxng_launcher.restart()
        return jsonify({"ok": True, "status": snap})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "detail": str(e)}), 500


# ---------------- Providers ----------------
@app.route("/api/providers", methods=["GET"])
def api_providers():
    return jsonify(db.list_providers())


@app.route("/api/providers", methods=["POST"])
def api_provider_create():
    data = request.get_json(force=True)
    pid = db.upsert_provider(data)
    return jsonify({"id": pid})


@app.route("/api/providers/<int:pid>", methods=["PUT"])
def api_provider_update(pid):
    data = request.get_json(force=True)
    data["id"] = pid
    db.upsert_provider(data)
    return jsonify({"ok": True})


@app.route("/api/providers/<int:pid>", methods=["DELETE"])
def api_provider_delete(pid):
    db.delete_provider(pid)
    return jsonify({"ok": True})


@app.route("/api/providers/<int:pid>/activate", methods=["POST"])
def api_provider_activate(pid):
    db.set_active_provider(pid)
    return jsonify({"ok": True})


@app.route("/api/providers/test", methods=["POST"])
def api_provider_test():
    data = request.get_json(force=True) or {}
    try:
        import requests as rq
        base = (data.get("base_url") or "").rstrip("/")
        if data.get("kind") != "mock":
            if not base:
                return jsonify({"ok": False, "detail": "base_url 为空"}), 400
            url = base + "/chat/completions"
            resp = rq.post(
                url,
                json={"model": data.get("model", ""), "messages": [{"role": "user", "content": "ping"}],
                      "max_tokens": 1, "stream": False},
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {data.get('api_key','')}"},
                timeout=15,
            )
            return jsonify({"ok": resp.status_code == 200, "status": resp.status_code,
                            "detail": resp.text[:300] if resp.status_code != 200 else "连接成功"})
        return jsonify({"ok": True, "detail": "演示模式无需测试"})
    except Exception as e:
        return jsonify({"ok": False, "detail": str(e)}), 400


# ---------------- Tasks ----------------
@app.route("/api/tasks", methods=["GET"])
def api_tasks():
    return jsonify(db.list_tasks())


@app.route("/api/tasks", methods=["POST"])
def api_task_create():
    data = request.get_json(force=True) or {}
    tid = db.create_task(data.get("title") or "新任务", data.get("mode") or "craft")
    return jsonify({"id": tid})


@app.route("/api/tasks/<int:tid>", methods=["GET"])
def api_task_get(tid):
    task = db.get_task(tid)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    msgs = db.get_messages(tid)
    return jsonify({"task": task, "messages": msgs})


@app.route("/api/tasks/<int:tid>", methods=["PATCH"])
def api_task_patch(tid):
    data = request.get_json(force=True)
    db.update_task(tid, **data)
    return jsonify({"ok": True})


@app.route("/api/tasks/<int:tid>", methods=["DELETE"])
def api_task_delete(tid):
    db.delete_task(tid)
    return jsonify({"ok": True})


# ---------------- 任务输出文件夹 ----------------
@app.route("/api/tasks/<int:tid>/outputs", methods=["GET"])
def api_task_outputs(tid):
    """列出任务输出文件夹内容(自动导出对话到 chat.md)"""
    db.export_task_chat(tid)
    return jsonify(db.list_task_outputs(tid))


@app.route("/api/tasks/<int:tid>/outputs/export", methods=["POST"])
def api_task_outputs_export(tid):
    """手动导出任务对话记录到 chat.md"""
    rel = db.export_task_chat(tid)
    return jsonify({"ok": bool(rel), "path": rel})


@app.route("/api/tasks/<int:tid>/outputs/open", methods=["POST"])
def api_task_outputs_open(tid):
    """在操作系统中打开任务输出文件夹(Windows 资源管理器)"""
    d = db.task_output_dir(tid)
    if not os.path.isdir(d):
        return jsonify({"error": "目录不存在"}), 404
    try:
        if sys.platform == "win32":
            os.startfile(d)  # noqa: 仅 Windows
        elif sys.platform == "darwin":
            subprocess.Popen(["open", d])
        else:
            subprocess.Popen(["xdg-open", d])
    except Exception as e:
        return jsonify({"error": f"打开失败: {e}"}), 500
    return jsonify({"ok": True, "path": d})


@app.route("/api/tasks/<int:tid>/outputs/<path:relpath>", methods=["GET"])
def api_task_outputs_file(tid, relpath):
    """读取任务输出文件夹内文件文本(防目录穿越)"""
    content = db.read_task_output(tid, relpath)
    if content is None:
        return jsonify({"error": "文件不存在"}), 404
    return jsonify({"path": relpath, "content": content})


@app.route("/api/tasks/<int:tid>/budget", methods=["GET"])
def api_task_budget(tid):
    msgs = db.get_messages(tid)
    window = [{"role": m["role"], "content": m["content"]} for m in msgs if m["role"] != "tool"]
    task = db.get_task(tid) or {}
    sys_text = agent_core.build_system_prompt(task, task.get("mode", "craft"))
    # 按当前激活模型的上下文窗口计算预算(Provider 可手动覆盖窗口)
    prov = db.get_active_provider()
    model = (prov or {}).get("model", "")
    ctx_manual = int((prov or {}).get("context_length") or 0)
    return jsonify(context_mgr.budget_info(
        [{"role": "system", "content": sys_text}] + window, model=model, context_length=ctx_manual))


@app.route("/api/tasks/<int:tid>/chat", methods=["POST"])
def api_task_chat(tid):
    data = request.get_json(force=True)
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "消息为空"}), 400
    # G6 多模态输入：解析图片附件，自动视觉理解并注入识别内容
    try:
        from src.vision.analyze import inject_image_attachments
        content, _records = inject_image_attachments(content)
    except Exception:
        pass
    mode = data.get("mode") or "craft"
    db.update_task(tid, mode=mode)
    prov = db.get_active_provider()
    if not prov:
        return jsonify({"error": "请先在左侧选择一个 Provider"}), 400
    # 推理强度：前端 快速/标准/深度(low/mid/high) → 后端 reasoning_effort(low/high/xhigh)
    effort_map = {"low": "low", "mid": "high", "high": "xhigh"}
    eff = (data.get("effort") or "").strip().lower()
    if eff in effort_map:
        prov["reasoning_effort"] = effort_map[eff]
    agent = agent_core.Agent(tid, prov, mode)
    resp = Response(sse_stream(agent.run(content)), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@app.route("/api/tasks/<int:tid>/stop", methods=["POST"])
def api_task_stop(tid):
    """G4：停止任务——停止运行并放弃断点（区别于暂停：暂停保留断点供继续任务）。"""
    agent_core.request_stop(tid)
    try:
        from src.gateway import bridge_compat as v2_bridge
        v2_bridge.checkpoint_clear(tid)
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/api/tasks/<int:tid>/pause", methods=["POST"])
def api_task_pause(tid):
    """G4：暂停任务——停止当前运行 + 落断点（窗口摘要/已完成步骤），供后续继续。"""
    import json as _json
    from src.gateway import bridge_compat as v2_bridge
    agent_core.request_stop(tid)
    msgs = db.get_messages(tid)
    recent = []
    done_steps = []
    for m in msgs[-6:]:
        c = (m.get("content") or "")
        recent.append(f"[{m['role']}] {c[:120]}")
    for m in reversed(msgs):
        if m["role"] == "assistant" and m.get("meta"):
            try:
                meta = m["meta"]
                if isinstance(meta, str):
                    meta = _json.loads(meta)
                if meta.get("tool_trace"):
                    done_steps = meta["tool_trace"]
                    break
            except Exception:
                pass
    r = v2_bridge.checkpoint_save(tid, window_summary="\n".join(recent), done_steps=done_steps)
    return jsonify({"ok": True, **r})


@app.route("/api/tasks/<int:tid>/resume", methods=["POST"])
def api_task_resume(tid):
    """G4：继续任务——断点置 resumed，下一条消息自动注入恢复上下文从断点接着干。"""
    from src.gateway import bridge_compat as v2_bridge
    ck = v2_bridge.checkpoint_resume(tid)
    if not ck:
        return jsonify({"ok": False, "error": "任务无断点（未暂停过）"})
    return jsonify({"ok": True, "round": ck.get("round"),
                    "window_summary": (ck.get("window_summary") or "")[:200]})


# ---------------- KB ----------------
@app.route("/api/kb/search")
def api_kb_search():
    q = request.args.get("q", "")
    cat = request.args.get("category") or None
    itype = request.args.get("item_type") or None
    validity = request.args.get("validity") or None
    domain = request.args.get("domain") or None
    top = int(request.args.get("top", 5))
    return jsonify(db.kb_search(q, top, cat, itype, validity, domain))


@app.route("/api/kb/stats")
def api_kb_stats():
    return jsonify(db.kb_stats())


@app.route("/api/kb")
def api_kb_list():
    cat = request.args.get("category") or None
    return jsonify(db.kb_list(cat))


@app.route("/api/kb", methods=["POST"])
def api_kb_add():
    data = request.get_json(force=True)
    eid = db.kb_add(data.get("title", ""), data.get("url", ""), data.get("category", "network"),
                    data.get("content", ""), data.get("source", ""),
                    item_type=data.get("item_type"), domain=data.get("domain"),
                    source_type=data.get("source_type"), validity=data.get("validity"),
                    confidence=data.get("confidence"), status=data.get("status"),
                    std_no=data.get("std_no"), org=data.get("org"),
                    publish_date=data.get("publish_date"), implement_date=data.get("implement_date"),
                    metadata=data.get("metadata") or {})
    return jsonify({"id": eid})


@app.route("/api/kb/<int:eid>")
def api_kb_detail(eid):
    d = db.kb_get_detail(eid)
    if not d:
        return jsonify({"error": "not found"}), 404
    return jsonify(d)


@app.route("/api/kb/<int:eid>", methods=["PUT"])
def api_kb_update(eid):
    data = request.get_json(force=True)
    r = db.kb_update(eid, **{k: v for k, v in data.items() if v is not None})
    if r is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True, "id": r})


@app.route("/api/kb/<int:eid>", methods=["DELETE"])
def api_kb_delete(eid):
    db.kb_delete(eid)
    return jsonify({"ok": True})


@app.route("/api/kb/<int:eid>/correct", methods=["POST"])
def api_kb_correct(eid):
    data = request.get_json(force=True)
    cid = db.kb_correct(eid, data.get("issue", ""), data.get("suggestion", ""),
                        data.get("corrected_content", ""), data.get("reporter", "user"))
    return jsonify({"ok": True, "correction_id": cid})


@app.route("/api/kb/<int:eid>/relation", methods=["POST"])
def api_kb_relation(eid):
    data = request.get_json(force=True)
    db.kb_relation_add(eid, int(data.get("to_id", 0)), data.get("rel_type", "related"),
                       data.get("note", ""))
    return jsonify({"ok": True})


@app.route("/api/kb/<int:eid>/interpret", methods=["POST"])
def api_kb_interpret(eid):
    """触发单条标准/政策智能解读 + 联网查新(后台执行, 返回 queued)"""
    import standard_intel as si
    data = request.get_json(force=True, silent=True) or {}
    do_check = bool(data.get("check", True))
    queued = si.interpret_entry(eid, do_check=do_check, sync=False)
    return jsonify({"ok": True, "queued": queued,
                    "message": "已加入后台解读队列" if queued else "该条目已在队列中"})


@app.route("/api/kb/<int:eid>/interpret")
def api_kb_interpret_get(eid):
    """获取条目已生成的智能解读与查新结果"""
    import standard_intel as si
    r = si.get_interpretation(eid)
    if not r:
        return jsonify({"ok": False, "reason": "条目不存在"})
    return jsonify(r)


@app.route("/api/kb/<int:eid>/currency-check", methods=["POST"])
def api_kb_currency_check(eid):
    """触发单条联网查新(确认现行有效/废止/被替代, 后台执行)"""
    import standard_intel as si
    queued = si.interpret_entry(eid, do_check=True, sync=False)
    return jsonify({"ok": True, "queued": queued,
                    "message": "已加入查新队列" if queued else "该条目已在队列中"})


@app.route("/api/kb/interpret-batch", methods=["POST"])
def api_kb_interpret_batch():
    """存量批量查新重检: 对 std_no 非空且未查新过的条目后台逐个联网查新"""
    import standard_intel as si
    data = request.get_json(force=True, silent=True) or {}
    limit = int(data.get("limit", 200))
    r = si.batch_recheck(limit=limit, only_unchecked=bool(data.get("only_unchecked", True)))
    return jsonify(r)


@app.route("/api/kb/<int:eid>/summarize", methods=["POST"])
def api_kb_summarize(eid):
    """触发单条通用文档智能总结(一句话/TL;DR/结构化长摘要 + 质量验证, 后台执行)"""
    import doc_intel as di
    queued = di.summarize_entry(eid, sync=False)
    return jsonify({"ok": True, "queued": queued,
                    "message": "已加入智能总结队列" if queued else "该条目已在队列中"})


@app.route("/api/kb/<int:eid>/summarize")
def api_kb_summarize_get(eid):
    """获取条目已生成的通用智能总结"""
    import doc_intel as di
    r = di.get_summary(eid)
    if r is None:
        return jsonify({"ok": False, "reason": "条目不存在或尚未生成总结"})
    return jsonify({"ok": True, "summary": r})


@app.route("/api/kb/summarize-batch", methods=["POST"])
def api_kb_summarize_batch():
    """存量批量智能总结: 对未生成过总结的条目后台逐个生成"""
    import doc_intel as di
    data = request.get_json(force=True, silent=True) or {}
    limit = int(data.get("limit", 200))
    r = di.batch_summarize(limit=limit, only_missing=bool(data.get("only_missing", True)))
    return jsonify(r)


# ---------------- KB M2-M4: 混合检索 / 向量 / 导入 / 审计 / 收割 / 导出 ----------------
@app.route("/api/kb/hybrid")
def api_kb_hybrid():
    q = request.args.get("q", "")
    top = int(request.args.get("top", 5))
    return jsonify(db.kb_hybrid_search(q, top))


@app.route("/api/kb/vector")
def api_kb_vector():
    q = request.args.get("q", "")
    top = int(request.args.get("top", 5))
    return jsonify(db.kb_vector_search(q, top))


@app.route("/api/kb/chunks/<int:eid>")
def api_kb_chunks(eid):
    return jsonify([{"id": c["id"], "index": c["chunk_index"], "type": c["chunk_type"],
                     "content": c["content"], "token_count": c["token_count"]}
                    for c in db.kb_get_chunks(eid)])


@app.route("/api/kb/chunks/<int:eid>", methods=["POST"])
def api_kb_embed(eid):
    db.kb_embed_entry(eid, force=True)
    return jsonify({"ok": True})


@app.route("/api/kb/import", methods=["POST"])
def api_kb_import():
    data = request.get_json(force=True)
    paths = data.get("paths", "")
    if isinstance(paths, list):
        paths = ",".join(str(p) for p in paths)
    r = db.kb_import_files(paths, data.get("batch_name", "web"))
    return jsonify(r)


@app.route("/api/kb/imports")
def api_kb_imports():
    return jsonify(db.kb_imports_list())


@app.route("/api/kb/qc")
def api_kb_qc():
    return jsonify({"list": db.kb_qc_list(int(request.args.get("limit", 100))),
                    "stats": db.kb_qc_stats()})


@app.route("/api/kb/backup", methods=["POST"])
def api_kb_backup():
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(db.kb_backup(kind=data.get("kind", "manual"),
                                note=data.get("note", "手动触发")))


@app.route("/api/kb/backups")
def api_kb_backups():
    return jsonify(db.kb_backups_list(int(request.args.get("limit", 10))))


@app.route("/api/kb/audit", methods=["POST"])
def api_kb_audit():
    return jsonify(db.kb_audit())


@app.route("/api/kb/audit/latest")
def api_kb_audit_latest():
    return jsonify(db.kb_audit_latest() or {})


@app.route("/api/kb/conflicts")
def api_kb_conflicts():
    return jsonify(db.kb_conflicts())


@app.route("/api/kb/harvest", methods=["POST"])
def api_kb_harvest():
    data = request.get_json(force=True)
    r = db.kb_harvest_conversation(data.get("title", ""), data.get("qa_pairs") or [],
                                   data.get("prefs"), data.get("facts"))
    return jsonify(r)


@app.route("/api/kb/memories")
def api_kb_memories():
    mt = request.args.get("memory_type") or None
    return jsonify(db.kb_memory_list(memory_type=mt))


@app.route("/api/kb/export")
def api_kb_export():
    domain = request.args.get("domain") or None
    fmt = request.args.get("fmt", "json")
    r = db.kb_export(domain=domain, fmt=fmt)
    import base64
    return jsonify({"filename": r["filename"], "count": r["count"], "size": r["size"],
                    "b64": r["b64"]})


@app.route("/api/kb/export/download")
def api_kb_export_download():
    import io
    domain = request.args.get("domain") or None
    fmt = request.args.get("fmt", "json")
    r = db.kb_export(domain=domain, fmt=fmt)
    import base64
    raw = base64.b64decode(r["b64"])
    from flask import Response
    return Response(raw, mimetype="application/zip",
                    headers={"Content-Disposition": f"attachment; filename={r['filename']}"})


# ---------------- Memory ----------------
@app.route("/api/memory", methods=["GET"])
def api_memory_list():
    return jsonify(db.memory_list())


@app.route("/api/memory", methods=["POST"])
def api_memory_set():
    data = request.get_json(force=True)
    db.memory_set(data.get("key", ""), data.get("content", ""))
    return jsonify({"ok": True})


@app.route("/api/memory/<key>", methods=["DELETE"])
def api_memory_delete(key):
    db.memory_delete(key)
    return jsonify({"ok": True})


# ---------------- Skills ----------------
@app.route("/api/skills")
def api_skills():
    return jsonify(skills.list_skills())


@app.route("/api/skills", methods=["POST"])
def api_skill_create():
    data = request.get_json(force=True)
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"ok": False, "error": "SKILL.md 内容必填"}), 400
    try:
        key = skills.create_skill(body)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "key": key})


@app.route("/api/skills/<key>", methods=["DELETE"])
def api_skill_delete(key):
    skills.delete_skill(key)
    return jsonify({"ok": True})


@app.route("/api/skills/<key>/toggle", methods=["POST"])
def api_skill_toggle(key):
    data = request.get_json(force=True)
    skills.list_skills()
    db.skill_set(key, bool(data.get("enabled")))
    return jsonify({"ok": True})


# ---------------- Stats ----------------
@app.route("/api/stats")
def api_stats():
    return jsonify(db.stats_cache())


@app.route("/api/usage")
def api_usage():
    rng = request.args.get("range", "today")
    if rng not in ("today", "7d", "30d", "all"):
        rng = "today"
    return jsonify(db.usage_stats(rng))


@app.route("/api/tasks/<int:task_id>/usage")
def api_task_usage(task_id):
    return jsonify(db.task_usage(task_id))


# ---------------- DeepSeek Harness 对标补缺 ----------------
# D1 session-title 自动标题；D2 feedback 逐消息反馈；D3 session-reference 跨会话引用


@app.route("/api/tasks/<int:task_id>/auto-title", methods=["POST"])
def api_auto_title(task_id):
    """D1 自动会话标题：任务标题为默认"新任务"时，用首条 user+首轮回复生成。"""
    from src.gateway import bridge_compat as v2_bridge
    msgs = db.get_messages(task_id) or []
    first_user = next((m.get("content") or "" for m in msgs if m.get("role") == "user"), "")
    reply = next((m.get("content") or "" for m in msgs if m.get("role") == "assistant"), "")
    return jsonify(v2_bridge.auto_title(task_id, first_user=first_user, reply=reply))


@app.route("/api/messages/<int:mid>/feedback", methods=["POST"])
def api_message_feedback(mid):
    """D2 逐消息反馈：{value: good|bad, comment} 写入消息 meta。"""
    from src.gateway import bridge_compat as v2_bridge
    data = request.get_json(force=True) or {}
    return jsonify(v2_bridge.message_feedback(mid, value=data.get("value", ""), comment=data.get("comment", "")))


@app.route("/api/messages/feedback")
def api_feedback_list():
    """D2 反馈列表：?task_id= 可选过滤，供复核/统计。"""
    from src.gateway import bridge_compat as v2_bridge
    task_id = request.args.get("task_id", 0, type=int)
    limit = request.args.get("limit", 50, type=int)
    return jsonify(v2_bridge.feedback_list(task_id, limit))


@app.route("/api/tasks/<int:task_id>/ref")
def api_session_ref(task_id):
    """D3 跨会话引用：读取目标任务上下文，供前端预览/注入。"""
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.session_ref(task_id))


# ---------------- V2.0 功能集成（唯一 UI：v1.2 主界面内视图切换） ----------------
# API：/api/v2/*；通过 v2_bridge 直接调用 v2 src.* 模块（角色/工作流/报告/审核/合规/grounding）
# 前端：templates/index.html 内嵌 view-reports/view-roles/view-workflow/view-audit 视图区块 + static/app_v2.js


def _v2(body):
    return jsonify({"ok": True, **body})


@app.route("/api/v2/roles")
def api_v2_roles():
    from src.gateway import bridge_compat as v2_bridge
    return jsonify({"ok": True, "roles": v2_bridge.roles_list()})


@app.route("/api/v2/roles", methods=["POST"])
def api_v2_roles_define():
    from src.gateway import bridge_compat as v2_bridge
    data = request.get_json(force=True) or {}
    try:
        role = v2_bridge.roles_define(
            name=data.get("name", ""),
            domain=data.get("domain", "D1"),
            responsibilities=data.get("responsibilities"),
            permissions=data.get("permissions"),
        )
        return jsonify({"ok": True, "role": role})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/roles/<role_id>/activate", methods=["POST"])
def api_v2_roles_activate(role_id):
    from src.gateway import bridge_compat as v2_bridge
    try:
        return jsonify(v2_bridge.roles_activate(role_id))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/roles/<role_id>", methods=["DELETE"])
def api_v2_roles_delete(role_id):
    from src.gateway import bridge_compat as v2_bridge
    try:
        return jsonify(v2_bridge.roles_delete(role_id))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/workflow/states")
def api_v2_workflow_states():
    from src.gateway import bridge_compat as v2_bridge
    return jsonify({"ok": True, "sm": v2_bridge.workflow_states()})


@app.route("/api/v2/workflow/start", methods=["POST"])
def api_v2_workflow_start():
    from src.gateway import bridge_compat as v2_bridge
    try:
        return jsonify({"ok": True, **v2_bridge.workflow_start()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/workflow/transition", methods=["POST"])
def api_v2_workflow_transition():
    from src.gateway import bridge_compat as v2_bridge
    data = request.get_json(force=True) or {}
    try:
        return jsonify({"ok": True, **v2_bridge.workflow_transition(data.get("instance_id", ""), data.get("event", ""))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/reports/generate", methods=["POST"])
def api_v2_report_generate():
    from src.gateway import bridge_compat as v2_bridge
    data = request.get_json(force=True) or {}
    try:
        return jsonify({"ok": True, **v2_bridge.report_generate(data.get("type", "monitoring"), data.get("project_id", "P-DEMO"))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/reports/review", methods=["POST"])
def api_v2_report_review():
    from src.gateway import bridge_compat as v2_bridge
    data = request.get_json(force=True) or {}
    try:
        return jsonify({"ok": True, "feedback": v2_bridge.report_review(data.get("content", ""), data.get("report_id", ""))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/reports/compliance", methods=["POST"])
def api_v2_report_compliance():
    from src.gateway import bridge_compat as v2_bridge
    data = request.get_json(force=True) or {}
    try:
        return jsonify({"ok": True, "result": v2_bridge.report_compliance(data.get("content", ""), data.get("report_id", ""))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/reports/sign", methods=["POST"])
def api_v2_report_sign():
    from src.gateway import bridge_compat as v2_bridge
    data = request.get_json(force=True) or {}
    try:
        return jsonify({"ok": True, **v2_bridge.report_sign(data.get("report_id", ""))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/workflow/auto", methods=["POST"])
def api_v2_workflow_auto():
    from src.gateway import bridge_compat as v2_bridge
    try:
        return jsonify({"ok": True, **v2_bridge.workflow_auto()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/workflow/events")
def api_v2_workflow_events():
    """SSE 状态推送：按 key 订阅报告状态机实时状态（后台自动流转的可视化）。"""
    from src.gateway import bridge_compat as v2_bridge
    key = request.args.get("key", "demo")

    def gen():
        last = ""
        while True:
            try:
                st = v2_bridge.workflow_state(key)
                cur = f"{st.get('state')}|{(st.get('last') or {}).get('event', '')}|{(st.get('last') or {}).get('ts', '')}"
                if cur != last:
                    last = cur
                    yield {"event": "wf_state", **st}
            except Exception:
                pass
            time.sleep(1)

    return Response(sse_stream(gen()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/v2/reports/expert-opinion", methods=["POST"])
def api_v2_report_expert_opinion():
    """P3 专家意见回流：意见写入原任务对话，Agent 按意见修改报告。"""
    from src.gateway import bridge_compat as v2_bridge
    d = request.json or {}
    return jsonify(v2_bridge.report_expert_opinion(d.get("report_id", ""), d.get("opinion", "")))


@app.route("/api/v2/reports/ground", methods=["POST"])
def api_v2_report_ground():
    from src.gateway import bridge_compat as v2_bridge
    data = request.get_json(force=True) or {}
    try:
        return jsonify({"ok": True, **v2_bridge.report_ground(data.get("content", ""))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---- M13 OERCR 学习闭环 ----
@app.route("/api/v2/learn/observe", methods=["POST"])
def api_v2_learn_observe():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return _v2({"observation": v2_bridge.oercr_observe(
            d.get("task", ""), d.get("domain", ""), d.get("outcome", "partial"), d.get("feedback", ""))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/learn/reflect", methods=["POST"])
def api_v2_learn_reflect():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return _v2(v2_bridge.oercr_reflect(d.get("domain", ""), d.get("gap", ""),
                                           d.get("severity", "P2"), d.get("pattern_hint", "")))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/learn/crystallize", methods=["POST"])
def api_v2_learn_crystallize():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return _v2(v2_bridge.oercr_crystallize(int(d.get("level", 2) or 2),
                                               d.get("role", "R4"), d.get("domain", ""),
                                               d.get("definition", "")))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/learn/pending")
def api_v2_learn_pending():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.oercr_pending())


@app.route("/api/v2/learn/approve-all", methods=["POST"])
def api_v2_learn_approve_all():
    from src.gateway import bridge_compat as v2_bridge
    try:
        return _v2(v2_bridge.oercr_approve_all())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/learn/reuse", methods=["POST"])
def api_v2_learn_reuse():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return _v2(v2_bridge.oercr_reuse(d.get("task", ""), d.get("domain", "")))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---- v2 技能库（v2_skills 表，R8 审核） ----
@app.route("/api/v2/skills2")
def api_v2_skills2():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.skills2_list(request.args.get("status", "")))


@app.route("/api/v2/skills2/<sid>/approve", methods=["POST"])
def api_v2_skills2_approve(sid):
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.skills2_approve(sid))


@app.route("/api/v2/skills2/<sid>/reject", methods=["POST"])
def api_v2_skills2_reject(sid):
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.skills2_reject(sid))


# ---- P0 领域团队（组织模型重构：领域=团队，角色后台化） ----
@app.route("/api/v2/team")
def api_v2_team_list():
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.teams_list())


@app.route("/api/v2/team/<team_id>")
def api_v2_team_get(team_id):
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.team_get(team_id) or {"error": "团队不存在"})


@app.route("/api/v2/team/domain/<domain>")
def api_v2_team_by_domain(domain):
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.team_by_domain(domain) or {"error": "该领域无团队"})


@app.route("/api/v2/team/context", methods=["POST"])
def api_v2_team_context():
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.team_context(request.json.get("domain", "") if request.json else ""))


@app.route("/api/v2/team", methods=["POST"])
def api_v2_team_create():
    from src.gateway import bridge_compat as v2_bridge
    d = request.json or {}
    return jsonify(v2_bridge.team_create(
        team_id=d.get("team_id", ""), domain=d.get("domain", ""),
        name=d.get("name", ""), description=d.get("description", ""),
        roles=d.get("roles"), skills=d.get("skills"),
        wf_template=d.get("wf_template", ""), report_tmpls=d.get("report_tmpls"),
        tools=d.get("tools"), status=d.get("status", "active"),
    ))


@app.route("/api/v2/team/<team_id>", methods=["PUT"])
def api_v2_team_update(team_id):
    from src.gateway import bridge_compat as v2_bridge
    d = request.json or {}
    return jsonify(v2_bridge.team_update(team_id, **d) or {"error": "团队不存在"})


@app.route("/api/v2/team/<team_id>", methods=["DELETE"])
def api_v2_team_delete(team_id):
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.team_delete(team_id))


@app.route("/api/v2/team/onboarding", methods=["POST"])
def api_v2_team_onboarding():
    from src.gateway import bridge_compat as v2_bridge
    d = request.json or {}
    return jsonify(v2_bridge.team_onboarding(
        domain=d.get("domain", ""), name=d.get("name", ""),
        description=d.get("description", ""), skills=d.get("skills"), roles=d.get("roles"),
    ))


@app.route("/api/v2/team/onboarding/recommend", methods=["POST"])
def api_v2_team_onboarding_recommend():
    """P5 新领域引导：生成《能力建议书》（资料不足返回 questions）。"""
    from src.gateway import bridge_compat as v2_bridge
    d = request.json or {}
    return jsonify(v2_bridge.domain_onboarding_recommend(
        domain=d.get("domain", ""), description=d.get("description", ""),
        materials=d.get("materials"),
    ))


@app.route("/api/v2/team/onboarding/confirm", methods=["POST"])
def api_v2_team_onboarding_confirm():
    """P5 新领域引导：确认建议书 → 自动搭建新 Team。"""
    from src.gateway import bridge_compat as v2_bridge
    d = request.json or {}
    return jsonify(v2_bridge.domain_onboarding_confirm(d.get("suggestion") or {}))


# ---- P1 报告模板库（配置化 + 自学习） ----


# ---- P1 报告模板库（配置化 + 自学习） ----
@app.route("/api/v2/templates")
def api_v2_templates_list():
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.templates_list(request.args.get("status", "")))


@app.route("/api/v2/templates/<template_id>")
def api_v2_template_get(template_id):
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.template_get(template_id) or {"error": "模板不存在"})


@app.route("/api/v2/templates/type/<type_>")
def api_v2_template_by_type(type_):
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.template_by_type(type_) or {"error": "该类型无已发布模板"})


@app.route("/api/v2/templates", methods=["POST"])
def api_v2_template_save():
    from src.gateway import bridge_compat as v2_bridge
    d = request.json or {}
    return jsonify(v2_bridge.template_save(
        template_id=d.get("template_id", ""), type_=d.get("type", ""),
        name=d.get("name", ""), sections=d.get("sections"), placeholders=d.get("placeholders"),
        prompt=d.get("prompt", ""), export_title=d.get("export_title", ""),
        docx_path=d.get("docx_path", ""), source_uploads=d.get("source_uploads"),
        status=d.get("status", "draft"),
    ))


@app.route("/api/v2/templates/<template_id>/publish", methods=["POST"])
def api_v2_template_publish(template_id):
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.template_publish(template_id) or {"error": "模板不存在"})


@app.route("/api/v2/templates/<template_id>", methods=["DELETE"])
def api_v2_template_delete(template_id):
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.template_delete(template_id))


@app.route("/api/v2/templates/learn", methods=["POST"])
def api_v2_template_learn():
    """用户上传报告 → 自动归纳模板建议（draft 待预览确认）。"""
    from src.gateway import bridge_compat as v2_bridge
    d = request.json or {}
    try:
        return jsonify({"ok": True, "template": v2_bridge.template_learn(
            d.get("upload_id", ""), d.get("text", ""),
            d.get("report_type", "custom"), d.get("name", ""),
        )})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---- P1 多状态机模板 ----
@app.route("/api/v2/wf/templates")
def api_v2_wf_templates():
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.wf_templates_list())


@app.route("/api/v2/wf/templates/<key>")
def api_v2_wf_template_get(key):
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.wf_template_get(key) or {"error": "状态机不存在"})


# ---- M15 模块流水线 ----
@app.route("/api/v2/pipeline/run", methods=["POST"])
def api_v2_pipeline_run():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return _v2({"blueprint": v2_bridge.pipeline_run(d.get("conversation", ""))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/pipeline/approve", methods=["POST"])
def api_v2_pipeline_approve():
    from src.gateway import bridge_compat as v2_bridge
    try:
        return jsonify(v2_bridge.pipeline_approve())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---- M14 审计 ----
@app.route("/api/v2/audit", methods=["POST"])
def api_v2_audit_log():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return _v2({"entry": v2_bridge.audit_log(d.get("who", "ui"), d.get("action", "op"), d.get("note", ""))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/audit")
def api_v2_audit_query():
    from src.gateway import bridge_compat as v2_bridge
    try:
        return _v2({"entries": v2_bridge.audit_query(
            request.args.get("who", ""), request.args.get("action", ""),
            int(request.args.get("limit", 20)))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/audit/verify")
def api_v2_audit_verify():
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.audit_verify())


# ---- M05 三层记忆 ----
@app.route("/api/v2/memory/working")
def api_v2_memory_working_get():
    from src.gateway import bridge_compat as v2_bridge
    key = request.args.get("key", "")
    if key:
        return _v2(v2_bridge.wm_get(key))
    return _v2(v2_bridge.wm_keys())


@app.route("/api/v2/memory/working", methods=["POST"])
def api_v2_memory_working_set():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return _v2(v2_bridge.wm_set(d.get("key", ""), str(d.get("value", "")), int(d.get("ttl", 3600))))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/memory/episodic", methods=["POST"])
def api_v2_memory_episodic_add():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return _v2(v2_bridge.epi_add(d.get("entity", ""), d.get("event", ""), d.get("payload")))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/memory/episodic")
def api_v2_memory_episodic_query():
    from src.gateway import bridge_compat as v2_bridge
    q = request.args.get("q", "")
    ent = request.args.get("entity", "")
    try:
        if ent:
            return _v2(v2_bridge.epi_summarize(ent))
        return _v2(v2_bridge.epi_query(q, int(request.args.get("top_k", 5))))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/memory/procedural")
def api_v2_memory_procedural():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.skills2_list(request.args.get("status", "")))


# ---- M07 技能执行器 / M03 意图路由 / M04 工具注册表 ----
@app.route("/api/v2/execute/skill", methods=["POST"])
def api_v2_execute_skill():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return _v2({"result": v2_bridge.skill_execute(d.get("skill_id", ""), d.get("params"), d.get("context"))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/intent", methods=["POST"])
def api_v2_intent():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return _v2({"route": v2_bridge.intent_analyze(d.get("text", ""))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/tools")
def api_v2_tools():
    from src.gateway import bridge_compat as v2_bridge
    try:
        return _v2({"tools": v2_bridge.tools_list(request.args.get("capability", ""))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/tools", methods=["POST"])
def api_v2_tools_execute():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return _v2({"result": v2_bridge.tools_execute(d.get("tool_id", ""), d.get("params"))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---- P1 公式计算引擎 ----
@app.route("/api/v2/calc", methods=["POST"])
def api_v2_calc():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return _v2({"result": v2_bridge.calc(
            d.get("standard", ""), d.get("calc_type", ""),
            d.get("data"), d.get("formula_id", ""))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/calc/formulas")
def api_v2_calc_formulas():
    from src.gateway import bridge_compat as v2_bridge
    return _v2({"formulas": v2_bridge.formulas_list(
        request.args.get("standard", ""), request.args.get("calc_type", ""))})


# ---- S3-H3 斜杠命令解析（对齐 Harness commands） ----
# 快捷指令 → 目标 /api/v2 端点；仅解析映射，不承载业务逻辑
_COMMAND_MAP = {
    "/report":   {"label": "报告",   "endpoint": "报告生成（/api/v2/reports/generate）"},
    "/calc":     {"label": "计算",   "endpoint": "公式计算（/api/v2/calc）"},
    "/learn":    {"label": "学习",   "endpoint": "OERCR 学习（/api/v2/learn/*）"},
    "/schedule": {"label": "定时",   "endpoint": "定时任务（/api/v2/schedule/*）"},
    "/approve":  {"label": "审批",   "endpoint": "R8 审批（/api/v2/review/*）"},
    "/help":     {"label": "帮助",   "endpoint": "命令列表"},
}


@app.route("/api/v2/commands")
def api_v2_commands():
    """斜杠命令解析：/cmd [参数] → {command, label, endpoint, hint}。"""
    text = (request.args.get("text") or "").strip()
    if not text:
        return jsonify({"commands": [
            {"command": k, "label": v["label"], "endpoint": v["endpoint"]}
            for k, v in _COMMAND_MAP.items()]})
    first = text.split(None, 1)[0].lower()
    rest = text[len(first):].strip()
    if first not in _COMMAND_MAP:
        return jsonify({"ok": False, "error": f"未知命令 {first}，可用: {', '.join(_COMMAND_MAP)}"})
    cmd = _COMMAND_MAP[first]
    return jsonify({"ok": True, "command": first, "label": cmd["label"],
                    "endpoint": cmd["endpoint"], "args": rest})


# ---- P2 资料缺口检测（对话索要） ----
@app.route("/api/v2/materials/check", methods=["POST"])
def api_v2_materials_check():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return _v2({"check": v2_bridge.materials_check(
            d.get("report_type", ""), d.get("conversation", ""),
            d.get("task_id"))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/materials/status")
def api_v2_materials_status():
    from src.gateway import bridge_compat as v2_bridge
    tid = request.args.get("task_id")
    return _v2(v2_bridge.materials_status(int(tid) if tid else None))


# ---- P5 文档学习管线 ----
@app.route("/api/v2/learning/learn", methods=["POST"])
def api_v2_learning_learn():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return _v2(v2_bridge.learn_report(
            d.get("report_type", ""), d.get("text", ""), d.get("source", "")))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/learning/status")
def api_v2_learning_status():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.learning_status())


# ---- P6 公开 API 适配器 ----
@app.route("/api/v2/publicapi/sources")
def api_v2_publicapi_sources():
    from src.gateway import bridge_compat as v2_bridge
    return _v2({"sources": v2_bridge.publicapi_sources()})


@app.route("/api/v2/publicapi/fetch", methods=["POST"])
def api_v2_publicapi_fetch():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    params = {k: v for k, v in d.items() if k != "source_id"}
    return _v2(v2_bridge.publicapi_fetch(d.get("source_id", ""), **params))


@app.route("/api/v2/publicapi/health")
def api_v2_publicapi_health():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.publicapi_health())


# ---- 记忆中心（Memory Hub 轻量版：资产治理 / ACL 可见性 / 使用统计 / R8 审核） ----
@app.route("/api/v2/memory/assets")
def api_v2_memory_assets():
    """记忆资产列表：type/visibility/status/q 过滤，use_count 排序。"""
    from src.memory import assets
    return _v2({
        "assets": assets.list_assets(
            asset_type=request.args.get("type") or None,
            visibility=request.args.get("visibility") or None,
            status=request.args.get("status", "active"),
            q=request.args.get("q", ""),
            limit=int(request.args.get("limit", 200)),
            offset=int(request.args.get("offset", 0)),
        ),
        "stats": assets.stats(),
    })


@app.route("/api/v2/memory/assets/<asset_id>", methods=["PATCH"])
def api_v2_memory_assets_update(asset_id):
    """修改资产可见性/团队/状态（ACL 治理）。"""
    from src.memory import assets
    d = request.get_json(force=True) or {}
    ok = False
    if "visibility" in d:
        ok = assets.set_visibility(asset_id, d["visibility"], d.get("team_id", ""))
    if "status" in d:
        ok = assets.set_status(asset_id, d["status"]) or ok
    if not ok:
        return jsonify({"ok": False, "error": "修改失败"}), 400
    return _v2({"ok": True})


@app.route("/api/v2/memory/assets/<asset_id>", methods=["DELETE"])
def api_v2_memory_assets_delete(asset_id):
    """删除资产登记（联动底层记忆）。"""
    from src.memory import assets
    try:
        asset_type, _, source_id = asset_id.partition(":")
        assets.remove(asset_type, source_id)
        return _v2({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/memory/summaries")
def api_v2_memory_summaries():
    """L2 场景记忆：历史任务摘要列表（含全文）。"""
    from src.core.db import get_conn
    try:
        rows = get_conn().execute(
            "SELECT task_id, title, abstract, overview, created_at FROM task_summaries "
            "ORDER BY created_at DESC LIMIT 100").fetchall()
        return _v2({"summaries": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/memory/summaries/<task_id>", methods=["DELETE"])
def api_v2_memory_summaries_delete(task_id):
    """删除任务摘要（隐私治理）。"""
    from src.core.db import get_conn
    from src.memory import assets
    try:
        with get_conn():
            get_conn().execute("DELETE FROM task_summaries WHERE task_id=?", (task_id,))
        assets.remove("summary", task_id)
        return _v2({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---- 短期任务压缩（offload + 符号画布，对齐 TencentDB 上下文卸载） ----
@app.route("/api/v2/memory/offload")
def api_v2_memory_offload():
    """任务 offload 统计与符号画布：?task_id= 或 ?latest=1（取最近画布）。"""
    from src.memory import offload
    from src.core.db import get_conn
    try:
        task_id = request.args.get("task_id", "")
        if not task_id and request.args.get("latest"):
            row = get_conn().execute(
                "SELECT task_id FROM task_canvases ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            task_id = row["task_id"] if row else ""
        if not task_id:
            return jsonify({"ok": False, "error": "暂无任务画布，完成任务后自动生成"}), 404
        row = get_conn().execute(
            "SELECT * FROM task_canvases WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            # 未落库：实时生成
            import db as dbmod
            msgs = dbmod.get_messages(int(task_id)) if str(task_id).isdigit() else []
            return _v2(offload.save_task_canvas(int(task_id), msgs) if msgs else
                       {"canvas": "", "node_count": 0, "offloaded": 0, "offloaded_chars": 0,
                        "message": "任务无消息"})
        return _v2(dict(row))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---- Wiki 知识资产（对齐 TencentDB Wiki 资产） ----
@app.route("/api/v2/memory/wiki")
def api_v2_memory_wiki_list():
    """Wiki 列表：?q= 关键词，?visibility= 过滤。"""
    from src.memory import wiki
    return _v2({
        "wikis": wiki.list_wiki(
            q=request.args.get("q", ""),
            visibility=request.args.get("visibility", ""),
            limit=int(request.args.get("limit", 200)),
        )
    })


@app.route("/api/v2/memory/wiki", methods=["POST"])
def api_v2_memory_wiki_create():
    """创建 Wiki 条目。body: title/content/tags/source/visibility。"""
    from src.memory import wiki
    d = request.get_json(force=True) or {}
    wid = wiki.create_wiki(
        title=d.get("title", ""), content=d.get("content", ""),
        tags=d.get("tags", ""), source=d.get("source", ""),
        visibility=d.get("visibility", "private"),
        created_by=d.get("created_by", "manual"),
    )
    if not wid:
        return jsonify({"ok": False, "error": "title 必填"}), 400
    return _v2({"ok": True, "id": wid})


@app.route("/api/v2/memory/wiki/<wid>", methods=["DELETE"])
def api_v2_memory_wiki_delete(wid):
    """删除 Wiki 条目（联动资产登记）。"""
    from src.memory import wiki
    if not wiki.delete_wiki(wid):
        return jsonify({"ok": False, "error": "删除失败或不存在"}), 400
    return _v2({"ok": True})


@app.route("/api/v2/memory/wiki/<wid>", methods=["PATCH"])
def api_v2_memory_wiki_update(wid):
    """更新 Wiki 条目。body 可含 title/content/tags/visibility。"""
    from src.memory import wiki
    d = request.get_json(force=True) or {}
    if not wiki.update_wiki(wid, title=d.get("title", ""), content=d.get("content", ""),
                            tags=d.get("tags", ""), visibility=d.get("visibility", "")):
        return jsonify({"ok": False, "error": "更新失败"}), 400
    return _v2({"ok": True})


# ---- 记忆量化评测（对齐 TencentDB WideSearch/SWE-bench 收益度量） ----
@app.route("/api/v2/memory/bench")
def api_v2_memory_bench():
    """运行记忆评测，返回三维度报告（检索 Recall@K / 压缩收益 / 技能复用）。"""
    from src.memory import bench
    try:
        return _v2(bench.run_benchmark())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---- P9 统一待审核中心（唯一人工闸门） ----
@app.route("/api/v2/review/list")
def api_v2_review_list():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.pending_review_list(
        request.args.get("status", ""), request.args.get("type", "")))


@app.route("/api/v2/review/approve", methods=["POST"])
def api_v2_review_approve():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.pending_review_approve(d.get("type", ""), d.get("id", "")))


@app.route("/api/v2/review/reject", methods=["POST"])
def api_v2_review_reject():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.pending_review_reject(d.get("type", ""), d.get("id", "")))


@app.route("/api/v2/review/approve-all", methods=["POST"])
def api_v2_review_approve_all():
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.pending_review_approve_all())


# ---- M2/M4 事实记忆（结构化 + 冲突消解） ----
@app.route("/api/v2/memory/facts", methods=["GET"])
def api_v2_memory_facts():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.facts_query(
        request.args.get("entity", ""), request.args.get("ftype", ""),
        request.args.get("q", "")))


@app.route("/api/v2/memory/facts/pending")
def api_v2_memory_facts_pending():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.facts_pending())


@app.route("/api/v2/memory/facts", methods=["POST"])
def api_v2_memory_facts_add():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return jsonify(v2_bridge.facts_add(
            d.get("entity", ""), d.get("attr", ""), d.get("value", ""),
            d.get("ftype", "fact"), d.get("source", ""), d.get("approved", False)))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/memory/facts/approve", methods=["POST"])
def api_v2_memory_facts_approve():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return jsonify(v2_bridge.facts_approve(d.get("id", 0)))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/memory/facts/reject", methods=["POST"])
def api_v2_memory_facts_reject():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return jsonify(v2_bridge.facts_reject(d.get("id", 0)))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/memory/facts/approve-all", methods=["POST"])
def api_v2_memory_facts_approve_all():
    from src.gateway import bridge_compat as v2_bridge
    try:
        return jsonify(v2_bridge.facts_approve_all())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/memory/facts/extract", methods=["POST"])
def api_v2_memory_facts_extract():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.facts_extract(d.get("text", ""), d.get("source", "agent")))


# ---- M3 用户画像层 ----
@app.route("/api/v2/memory/profile")
def api_v2_memory_profile():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.profile_get(request.args.get("user_key", "local")))


@app.route("/api/v2/memory/profile/distill", methods=["POST"])
def api_v2_memory_profile_distill():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.profile_distill(d.get("user_key", "local")))


@app.route("/api/v2/memory/profile", methods=["POST"])
def api_v2_memory_profile_upsert():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    try:
        return jsonify(v2_bridge.profile_upsert(d.get("user_key", "local"),
                                                d.get("attr", ""), d.get("value", "")))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/v2/memory/profile", methods=["DELETE"])
def api_v2_memory_profile_remove():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.profile_remove(d.get("user_key", "local"),
                                            d.get("pid"), d.get("attr", "")))


# ---- H1 技能迭代提案 ----
@app.route("/api/v2/skills/updates/pending")
def api_v2_skills_updates_pending():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.skills_update_pending())


@app.route("/api/v2/skills/updates/approve", methods=["POST"])
def api_v2_skills_updates_approve():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.skills_update_approve(d.get("pid", 0)))


@app.route("/api/v2/skills/updates/reject", methods=["POST"])
def api_v2_skills_updates_reject():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.skills_update_reject(d.get("pid", 0)))


# ---- H2 自然语言定时任务 ----
@app.route("/api/v2/schedule")
def api_v2_schedule_list():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.schedule_list())


@app.route("/api/v2/schedule/parse", methods=["POST"])
def api_v2_schedule_parse():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.schedule_parse(d.get("text", "")))


@app.route("/api/v2/schedule", methods=["POST"])
def api_v2_schedule_add():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.schedule_add(d.get("title", ""), d.get("prompt", ""),
                                          d.get("mode", "craft")))


@app.route("/api/v2/schedule/<int:sid>/pause", methods=["POST"])
def api_v2_schedule_pause(sid):
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.schedule_pause(sid))


@app.route("/api/v2/schedule/<int:sid>/resume", methods=["POST"])
def api_v2_schedule_resume(sid):
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.schedule_resume(sid))


@app.route("/api/v2/schedule/<int:sid>", methods=["DELETE"])
def api_v2_schedule_remove(sid):
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.schedule_remove(sid))


@app.route("/api/v2/schedule/tick", methods=["POST"])
def api_v2_schedule_tick():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.schedule_tick())


# ---- H3 Cron 记忆（对齐 Hermes cron memory）----
@app.route("/api/v2/schedule/<int:sid>/notepad", methods=["GET"])
def api_v2_schedule_notepad_get(sid):
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.schedule_notepad(sid))


@app.route("/api/v2/schedule/<int:sid>/notepad", methods=["POST"])
def api_v2_schedule_notepad_set(sid):
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.schedule_notepad(sid, d.get("text", "")))


@app.route("/api/v2/schedule/<int:sid>/continuity", methods=["POST"])
def api_v2_schedule_continuity(sid):
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    on = str(d.get("on", "1")).lower() in ("1", "true", "yes", "on")
    return jsonify(v2_bridge.schedule_continuity(sid, on))


# ---- G1 显式规划器 ----
@app.route("/api/v2/plan/run", methods=["POST"])
def api_v2_plan_run():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.plan_run(
        d.get("text", ""), d.get("mode_hint", "interactive"),
        bool(d.get("execute", False))))


@app.route("/api/v2/plan/execute", methods=["POST"])
def api_v2_plan_execute():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.plan_execute(
        d.get("steps") or [], d.get("text", ""),
        bool(d.get("continue_on_error", False))))


# ---- G5 记忆知识图谱 ----
@app.route("/api/v2/memory/graph")
def api_v2_memory_graph():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.memory_graph_query(
        request.args.get("entity", ""), int(request.args.get("top_k", 10))))


@app.route("/api/v2/memory/graph", methods=["POST"])
def api_v2_memory_graph_add():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.memory_graph_add(
        d.get("entity_a", ""), d.get("rel", ""), d.get("entity_b", ""),
        d.get("source", ""), d.get("note", "")))


@app.route("/api/v2/memory/graph/extract", methods=["POST"])
def api_v2_memory_graph_extract():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.memory_graph_extract(d.get("text", "")))


@app.route("/api/v2/memory/graph/link-facts", methods=["POST"])
def api_v2_memory_graph_link_facts():
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.memory_graph_link_facts())


@app.route("/api/v2/memory/graph/neighbors")
def api_v2_memory_graph_neighbors():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.memory_graph_neighbors(
        request.args.get("entity", ""), int(request.args.get("depth", 1))))


# ---- G2 动态子代理 ----
@app.route("/api/v2/subagent", methods=["POST"])
def api_v2_subagent_spawn():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.subagent_spawn(d.get("task", ""), d.get("role_id", "R4"),
                                            d.get("name", "subagent")))


@app.route("/api/v2/subagent/collect", methods=["POST"])
def api_v2_subagent_collect():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.subagent_collect(d.get("sub_id", ""),
                                              float(d.get("timeout") or 60)))


@app.route("/api/v2/subagent")
def api_v2_subagent_list():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.subagent_list())


@app.route("/api/v2/subagent/parallel", methods=["POST"])
def api_v2_subagent_parallel():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.subagent_run_parallel(
        d.get("tasks") or [], d.get("role_id", "R4"), float(d.get("timeout") or 60)))


# ---- H4 子代理实时操控（对齐 Hermes subagent steering） ----
@app.route("/api/v2/subagent/running")
def api_v2_subagent_running():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.subagent_running())


@app.route("/api/v2/subagent/<sub_id>/steer", methods=["POST"])
def api_v2_subagent_steer(sub_id):
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.subagent_steer(sub_id, d.get("instruction", "")))


@app.route("/api/v2/subagent/<sub_id>/stop", methods=["POST"])
def api_v2_subagent_stop(sub_id):
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.subagent_stop(sub_id))


# ---- G7 MCP 双向 ----
@app.route("/api/v2/mcp/tools")
def api_v2_mcp_tools():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.mcp_tools())


@app.route("/api/v2/mcp", methods=["POST"])
def api_v2_mcp_handle():
    """MCP JSON-RPC 分发（initialize / tools/list / tools/call）。"""
    from src.gateway import bridge_compat as v2_bridge
    return jsonify(v2_bridge.mcp_handle(request.get_json(silent=True) or {}))


# ---- G8 技能打包/市场 ----
@app.route("/api/v2/market")
def api_v2_market_list():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.market_list(
        request.args.get("status", ""), request.args.get("source", "")))


@app.route("/api/v2/market/browse")
def api_v2_market_browse():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.market_browse(request.args.get("key", "")))


@app.route("/api/v2/market/export", methods=["POST"])
def api_v2_market_export():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.market_export(d.get("key", ""),
                                           bool(d.get("include_related", True))))


@app.route("/api/v2/market/import", methods=["POST"])
def api_v2_market_import():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.market_import(d.get("zip_path", "")))


@app.route("/api/v2/market/stats")
def api_v2_market_stats():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.market_stats())


# ---- G3 链路追踪 ----
@app.route("/api/v2/trace/query", methods=["GET", "POST"])
def api_v2_trace_query():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(silent=True) or {}
    return _v2(v2_bridge.trace_query(
        request.args.get("trace_id") or d.get("trace_id", ""),
        int(request.args.get("days") or d.get("days", 7))))


@app.route("/api/v2/trace/task", methods=["GET", "POST"])
def api_v2_trace_task():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(silent=True) or {}
    return _v2(v2_bridge.trace_task(
        int(request.args.get("task_id") or d.get("task_id", 0)),
        int(request.args.get("days") or d.get("days", 7))))


@app.route("/api/v2/trace/aggregate", methods=["GET", "POST"])
def api_v2_trace_aggregate():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(silent=True) or {}
    return _v2(v2_bridge.trace_aggregate(
        int(request.args.get("days") or d.get("days", 7)),
        request.args.get("type") or d.get("type", "")))


# ---- M5 三层摘要 ----
@app.route("/api/v2/memory/task-summary")
def api_v2_memory_task_summary():
    from src.gateway import bridge_compat as v2_bridge
    tid = request.args.get("tid")
    return _v2(v2_bridge.task_summary(int(tid) if tid else 0))


@app.route("/api/v2/memory/task-summary/save", methods=["POST"])
def api_v2_memory_task_summary_save():
    from src.gateway import bridge_compat as v2_bridge
    d = request.get_json(force=True) or {}
    return jsonify(v2_bridge.task_summary_save(int(d.get("tid", 0))))


# ---- S3-H1 goal 持久化目标（对标 Harness goal） ----
@app.route("/api/v2/goals")
def api_v2_goals():
    from src.memory import goals
    tid = request.args.get("tid")
    if tid:
        return jsonify({"items": goals.list_for_task(int(tid))})
    return jsonify({"items": goals.list_active(int(request.args.get("limit", 20)))})


@app.route("/api/v2/goals", methods=["POST"])
def api_v2_goals_post():
    """登记任务目标（幂等）；body: {task_id, objective, progress?, status?}"""
    from src.memory import goals
    d = request.get_json(force=True) or {}
    gid = goals.register(
        int(d.get("task_id", 0)),
        d.get("objective", ""),
        progress=int(d.get("progress", 100)),
        status=d.get("status", "completed"))
    return jsonify({"ok": True, "id": gid})


@app.route("/api/v2/goals/<int:gid>", methods=["PATCH"])
def api_v2_goals_patch(gid):
    """更新目标状态；body: {status, progress?}"""
    from src.memory import goals
    d = request.get_json(force=True) or {}
    ok = goals.update_status(gid, d.get("status", "in_progress"),
                             d.get("progress"))
    return jsonify({"ok": ok})


# ---- M6 检索意图路由（对齐 Intent-Aware Query Planning） ----
@app.route("/api/v2/memory/route-search")
def api_v2_memory_route_search():
    from src.gateway import bridge_compat as v2_bridge
    return _v2(v2_bridge.memory_route_search(
        request.args.get("q", ""), int(request.args.get("top_k", 5))))


# ---- M10 报告查询 ----
@app.route("/api/v2/reports")
def api_v2_reports_list():
    from src.gateway import bridge_compat as v2_bridge
    return _v2({"reports": v2_bridge.reports_list()})


@app.route("/api/v2/reports/learning-stats")
def api_v2_reports_learning_stats():
    """报告中心知识库面板：语料学习模式 + 报告沉淀统计。"""
    from src.gateway import bridge_compat as v2_bridge
    return _v2({"ok": True, "stats": v2_bridge.report_learning_stats()})


@app.route("/api/v2/reports/<rid>")
def api_v2_report_get(rid):
    from src.gateway import bridge_compat as v2_bridge
    d = v2_bridge.report_get(rid)
    if d is None:
        return jsonify({"ok": False, "error": "报告不存在"}), 404
    return _v2(d)


@app.route("/api/v2/reports/<rid>/export")
def api_v2_report_export(rid):
    """导出报告：?fmt=md 返回 Markdown；?fmt=docx 渲染 Word 下载。"""
    from src.gateway import bridge_compat as v2_bridge
    fmt = request.args.get("fmt", "md")
    d = v2_bridge.report_export(rid, fmt)
    if d is None:
        return jsonify({"ok": False, "error": "报告不存在"}), 404
    if fmt == "docx":
        from flask import send_file
        return send_file(d["path"], as_attachment=True, download_name=f"{rid}.docx")
    return Response(d["content"], mimetype="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{rid}.md"'})


def create_app():
    # 本机服务（SearXNG / OCR / 内部回调）直连，避免系统代理把 127.0.0.1 请求转发出去
    try:
        from src.core.net import ensure_local_no_proxy

        ensure_local_no_proxy()
    except Exception:
        pass
    db.init_db()
    seed.seed_if_empty()
    # 环境变量注入的模型凭据（EA_LLM_*，未设置则不改动任何数据）
    try:
        from src.core.db_v12.providers import apply_env_override

        apply_env_override()
    except Exception:
        pass
    _kb_startup_maintenance()
    _start_v2_scheduler()
    return app


def _start_v2_scheduler():
    """启动 H2 应用内定时任务后台线程（幂等，桌面常驻时生效）。"""
    import threading as _th

    try:
        from src.core.db import run_migrations
        run_migrations()  # 确保 task_schedule 表已迁移（幂等）
    except Exception:
        pass
    try:
        from src.scheduler import start_scheduler
        start_scheduler()
    except Exception:
        pass


def _kb_startup_maintenance():
    """启动维护(后台线程): 每日自动备份 + 缺失向量补嵌入"""
    import threading as _th

    def _run():
        try:
            db.kb_backup_if_due(interval_hours=24)
        except Exception:
            pass
        try:
            db.kb_embed_all(batch_size=20)
        except Exception:
            pass

    _th.Thread(target=_run, daemon=True).start()


if __name__ == "__main__":
    create_app()
    port = int(os.environ.get("PORT", "5837"))
    print(f"[生态Agent] http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
