/* Environment Agent v3.0 核心 */
"use strict";
const EA = window.EA || {};
EA.state = { view: "chat", task: null, providers: [], skills: [], mode: "craft", effort: "low",
             selectedSkills: [], messages: [], busy: false };

/* ---------- 基础工具 ---------- */
EA.esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
EA.fmtTime = (t) => { if (!t) return ""; const d = new Date(t); return isNaN(d) ? String(t) : `${d.getMonth()+1}-${String(d.getDate()).padStart(2,"0")} ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`; };
EA.fmtNum = (n) => n == null ? "—" : Number(n).toLocaleString("zh-CN");
EA.fmtSize = (n) => { n = Number(n) || 0; if (n < 1024) return n + " B"; if (n < 1048576) return (n / 1024).toFixed(1) + " KB"; return (n / 1048576).toFixed(1) + " MB"; };
EA.api = async function (method, path, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  let r;
  try { r = await fetch(path, opt); }
  catch (e) { throw new Error("网络错误：" + e.message); }
  if (!r.ok) { let e = "请求失败"; try { const j = await r.json(); e = j.error || e; } catch (_) {} throw new Error(e); }
  return r.json();
};
EA.toast = (msg, ms) => {
  let t = document.getElementById("toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; document.body.appendChild(t); }
  t.textContent = msg; t.classList.add("show");
  clearTimeout(t._tm); t._tm = setTimeout(() => t.classList.remove("show"), ms || 2200);
};
EA.modal = function (title, bodyHtml, btnsHtml) {
  const ov = document.createElement("div");
  ov.className = "overlay";
  ov.innerHTML = `<div class="modal"><h3>${title}</h3>${bodyHtml}<div class="modal-btns">${btnsHtml || ""}</div></div>`;
  const close = () => { if (ov.isConnected) ov.remove(); };
  ov.addEventListener("click", (e) => { if (e.target === ov) close(); });
  // Esc 关闭弹窗（overlay 已移除时自清理监听）
  const onKey = (e) => { if (e.key === "Escape") { close(); if (!ov.isConnected) document.removeEventListener("keydown", onKey); } };
  document.addEventListener("keydown", onKey);
  document.body.appendChild(ov);
  return ov;
};
EA.confirm = function (msg, onOk, okText) {
  const ov = EA.modal("确认操作", `<div style="font-size:13px;color:var(--text-2)">${msg}</div>`,
    `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>${okText || "确认"}</button>`);
  ov.querySelector("[data-x]").onclick = () => ov.remove();
  ov.querySelector("[data-ok]").onclick = () => { ov.remove(); onOk && onOk(); };
};
EA.md = function (src) {
  if (!src) return "";
  let s = EA.esc(src);
  s = s.replace(/^#{1,4}\s+(.+)$/gm, (m, t) => `<h3>${t}</h3>`);
  s = s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>");
  s = s.replace(/`([^`]+)`/g, "<code style='font-family:var(--mono);background:#EEF1F6;padding:1px 5px;border-radius:4px;font-size:12px'>$1</code>");
  s = s.replace(/^-{1,3}\s+(.+)$/gm, "• $1");
  s = s.split(/\n{2,}/).map((p) => `<p>${p.replace(/\n/g, "<br>")}</p>`).join("");
  return s;
};

/* ---------- 导航 ---------- */
EA.showView = function (name) {
  EA.state.view = name;
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  const el = document.getElementById("v-" + name);
  if (el) el.classList.add("active");
  document.querySelectorAll("#rail-nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === name));
  if (location.hash !== "#" + name) { try { history.replaceState(null, "", "#" + name); } catch (_) {} }
  if (EA._viewInit[name] && !EA._viewInit[name].done) { EA._viewInit[name].done = true; EA._viewInit[name].fn(); }
  else if (EA["load_" + name]) EA["load_" + name]();
};
EA._viewInit = {};
EA.onView = function (name, fn) { EA._viewInit[name] = { fn, done: false }; };

/* ---------- 知识库 AI 解读/摘要格式化 ---------- */
// 后端返回的 interpret/summary 是嵌套对象，转为可读纯文本
EA.kbAiText = function (v) {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number") return String(v);
  if (Array.isArray(v)) return v.filter(Boolean).join("、");
  if (typeof v === "object") {
    const lines = [];
    const pick = (...keys) => { for (const k of keys) if (v[k] != null && String(v[k]).trim()) return String(v[k]).trim(); return ""; };
    const one = pick("summary", "one_liner");
    if (one) lines.push(one);
    const cn = pick("cn_name"); if (cn) lines.push("标准：" + cn);
    const no = pick("std_no"); if (no) lines.push("标准号：" + no);
    const cat = pick("category"); if (cat) lines.push("分类：" + cat);
    const pub = pick("publisher", "org"); if (pub) lines.push("发布：" + pub);
    const impl = pick("implement_date"); if (impl) lines.push("实施日期：" + impl);
    const repl = pick("replace"); if (repl) lines.push("替代：" + repl);
    const notes = pick("notes"); if (notes) lines.push("要点：" + notes);
    if (Array.isArray(v.revision_points) && v.revision_points.length) lines.push("修订要点：" + v.revision_points.filter(Boolean).join("；"));
    if (Array.isArray(v.refs) && v.refs.length) lines.push("参考标准：" + v.refs.filter(Boolean).join("、"));
    const core = v.core;
    if (core && typeof core === "object" && !Array.isArray(core)) {
      const entries = Object.entries(core).slice(0, 5)
        .map(([k, val]) => "[" + k + "] " + String(val == null ? "" : val).slice(0, 90));
      if (entries.length) lines.push(entries.join("\n"));
    }
    const tldr = pick("tldr"); if (tldr) lines.push("TL;DR：" + tldr);
    const long = pick("long_summary"); if (long) lines.push(long);
    return lines.filter(Boolean).join("\n\n");
  }
  return String(v);
};

/* ---------- 导航红点徽章 ---------- */
// 仅审核中心显示待办数（记忆中心/技能市场红点已取消，审批统一在审核中心处理）
EA.updateNavDots = function () {
  const setDot = (id, n) => {
    const d = document.getElementById(id);
    if (d) { d.style.display = n > 0 ? "flex" : "none"; d.textContent = n > 99 ? "99+" : n; }
  };
  try {
    EA.api("GET", "/api/v2/review/list").then((r) => {
      const arr = Array.isArray(r) ? r : (r.items || r.list || r.pending || []);
      setDot("rail-review-dot", Array.isArray(arr) ? arr.length : Number(arr) || 0);
    }).catch(() => {});
  } catch (_) {}
};

/* ---------- 窗口控制 ---------- */
function initWin() {
  const bind = (id, apiName) => {
    const el = document.getElementById(id);
    if (el) el.onclick = () => { try { window.pywebview && pywebview.api[apiName](); } catch (_) {} };
  };
  bind("btn-win-min", "minimize");
  bind("btn-win-max", "maximize");
  bind("btn-win-close", "close");
  const drag = document.querySelector(".tb-drag");
  if (drag) drag.addEventListener("mousedown", () => { try { window.pywebview && pywebview.api.dragWindow(); } catch (_) {} });
}

/* ---------- 初始化 ---------- */
document.addEventListener("DOMContentLoaded", () => {
  initWin();
  document.querySelectorAll("#rail-nav a").forEach((a) => {
    a.addEventListener("click", () => {
      document.querySelectorAll("#rail-nav a").forEach((x) => x.classList.remove("active"));
      a.classList.add("active");
      EA.showView(a.dataset.view);
      EA.updateNavDots();
    });
  });
  EA.updateNavDots();
  const h = (location.hash || "#chat").replace("#", "").split("/")[0];
  EA.showView(document.getElementById("v-" + h) ? h : "chat");
  window.addEventListener("hashchange", () => {
    const h2 = (location.hash || "").replace("#", "").split("/")[0];
    if (document.getElementById("v-" + h2)) EA.showView(h2);
  });
});
