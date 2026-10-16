# -*- coding: utf-8 -*-
"""S1-W5 db.py 拆分：任务/消息/断点/输出数据层（tasks 域）。

从根 db.py 原样搬移：task CRUD / checkpoint / message / task_outputs。
"""
from __future__ import annotations

import json
import os

from .base import q, w, TASK_OUTPUT_DIR

def create_task(title="新任务", mode="craft"):
    tid = w("INSERT INTO tasks(title,mode) VALUES(?,?)", (title, mode))
    # 每个任务自动生成独立输出文件夹, 存放对话导出与工具输出结果
    os.makedirs(os.path.join(TASK_OUTPUT_DIR, str(tid)), exist_ok=True)
    return tid


def list_tasks():
    return q(
        "SELECT t.*, (SELECT COUNT(*) FROM messages m WHERE m.task_id=t.id) msg_count,"
        " (SELECT COUNT(*) FROM messages m WHERE m.task_id=t.id AND m.role='assistant') reply_count"
        " FROM tasks t ORDER BY COALESCE(t.updated_at, t.created_at) DESC"
    )


def get_task(tid):
    return q("SELECT * FROM tasks WHERE id=?", (tid,), one=True)


def update_task(tid, **kw):
    allowed = {"title", "mode", "status"}
    # 仅当字段值真实变化才刷新 updated_at, 避免无关 PATCH 篡改任务排序
    cur = q("SELECT * FROM tasks WHERE id=?", (tid,), one=True)
    old = dict(cur) if cur else {}
    sets, args = [], []
    for k in kw:
        if k not in allowed:
            continue
        if str(old.get(k) or "") != str(kw[k] or ""):
            sets.append(f"{k}=?")
            args.append(kw[k])
    if not sets:
        return
    args.append(tid)
    w(f"UPDATE tasks SET {', '.join(sets)}, updated_at=datetime('now','localtime') WHERE id=?", args)


def delete_task(tid):
    w("DELETE FROM messages WHERE task_id=?", (tid,))
    w("DELETE FROM tasks WHERE id=?", (tid,))
    w("DELETE FROM task_checkpoints WHERE task_id=?", (tid,))
    # 删除任务时清理其输出文件夹
    import shutil
    shutil.rmtree(os.path.join(TASK_OUTPUT_DIR, str(tid)), ignore_errors=True)


def save_checkpoint(task_id, round_no=0, window_summary="", done_steps=None,
                    partial_outputs=None, status="paused"):
    """保存/更新任务断点（幂等 upsert）。status: paused=待恢复 / resumed=已恢复进行中。"""
    done_steps = done_steps if done_steps is not None else []
    partial_outputs = partial_outputs if partial_outputs is not None else {}
    return w(
        "INSERT INTO task_checkpoints(task_id,round,status,window_summary,done_steps,partial_outputs,updated_at)"
        " VALUES(?,?,?,?,?,?,datetime('now','localtime'))"
        " ON CONFLICT(task_id) DO UPDATE SET round=excluded.round,status=excluded.status,"
        " window_summary=excluded.window_summary,done_steps=excluded.done_steps,"
        " partial_outputs=excluded.partial_outputs,updated_at=datetime('now','localtime')",
        (task_id, int(round_no), status, window_summary or "",
         json.dumps(done_steps, ensure_ascii=False), json.dumps(partial_outputs, ensure_ascii=False)),
    )


def get_checkpoint(task_id):
    """读取任务断点；无则返回 None。"""
    return q("SELECT * FROM task_checkpoints WHERE task_id=?", (task_id,), one=True)


def checkpoint_set_status(task_id, status):
    """更新断点状态（paused/resumed/''）。"""
    w("UPDATE task_checkpoints SET status=?, updated_at=datetime('now','localtime') WHERE task_id=?",
      (status, task_id))


def clear_checkpoint(task_id):
    """清除断点（任务完成/放弃时）。"""
    w("DELETE FROM task_checkpoints WHERE task_id=?", (task_id,))


def add_message(task_id, role, content, meta=None, tokens=0):
    return w(
        "INSERT INTO messages(task_id,role,content,meta,tokens) VALUES(?,?,?,?,?)",
        (task_id, role, content, json.dumps(meta or {}, ensure_ascii=False), tokens),
    )


def get_messages(task_id):
    return q("SELECT * FROM messages WHERE task_id=? ORDER BY id ASC", (task_id,))


def last_message_id(task_id):
    r = q("SELECT MAX(id) mid FROM messages WHERE task_id=?", (task_id,), one=True)
    return r["mid"] or 0


def update_message_content(mid, content, meta=None, tokens=0):
    if meta is not None:
        w("UPDATE messages SET content=?, meta=?, tokens=? WHERE id=?", (content, json.dumps(meta, ensure_ascii=False), tokens, mid))
    else:
        w("UPDATE messages SET content=?, tokens=? WHERE id=?", (content, tokens, mid))


def task_output_dir(tid):
    """返回任务输出目录(自动创建): data/task_outputs/<task_id>/"""
    d = os.path.join(TASK_OUTPUT_DIR, str(tid))
    os.makedirs(d, exist_ok=True)
    return d


def task_output_save(tid, filename, content):
    """保存文件到任务输出目录, 返回相对路径; filename 可为 'chat.md' 或 'outputs/xxx.md'"""
    base = task_output_dir(tid)
    rel = filename.replace("\\", "/")
    if "../" in rel or rel.startswith("/"):
        rel = os.path.basename(rel)
    path = os.path.join(base, rel)
    os.makedirs(os.path.dirname(path) or base, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content or "")
    except OSError:
        return None
    return rel


def export_task_chat(tid):
    """把任务全部对话导出为 chat.md 存到任务输出文件夹, 返回相对路径或 None"""
    msgs = get_messages(tid)
    if not msgs:
        return None
    task = get_task(tid)
    lines = [f"# {task['title'] if task else ('任务 ' + str(tid))}", "", "## 对话记录", ""]
    for m in msgs:
        role = m.get("role") or ""
        content = m.get("content") or ""
        if role == "user":
            lines.append(f"### 用户")
        elif role == "assistant":
            lines.append(f"### 助手")
        elif role == "tool":
            meta = m.get("meta") or ""
            try:
                mm = json.loads(meta) if isinstance(meta, str) else (meta or {})
                tool = mm.get("name") or "tool"
            except Exception:
                tool = "tool"
            lines.append(f"### 工具: {tool}")
        else:
            continue
        lines.append(content)
        lines.append("")
    return task_output_save(tid, "chat.md", "\n".join(lines))


def list_task_outputs(tid):
    """列出任务输出目录下所有文件(相对路径/大小/修改时间)"""
    base = task_output_dir(tid)
    out = []
    for root, _dirs, files in os.walk(base):
        for fn in sorted(files):
            fp = os.path.join(root, fn)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            rel = os.path.relpath(fp, base).replace("\\", "/")
            out.append({
                "path": rel,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            })
    return out


def read_task_output(tid, relpath):
    """读取任务输出目录下的文件文本, 越界/不存在返回 None"""
    base = os.path.realpath(task_output_dir(tid))
    fp = os.path.realpath(os.path.join(base, relpath.replace("\\", "/")))
    if not fp.startswith(base + os.sep):
        return None
    if not os.path.isfile(fp):
        return None
    try:
        with open(fp, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None
