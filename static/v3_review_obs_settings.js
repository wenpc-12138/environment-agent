/* 10 审核中心 + 11 观测追踪 + 12 系统设置 */
"use strict";
EA._rvState = { type: "", cur: null };

/* ==================== 10 审核中心 ==================== */
EA.onView("review", function () {
  document.getElementById("v-review").innerHTML = `
  <div class="topbar">
    <h1>审核中心</h1><span class="crumb">所有待人工确认事项的聚合收件箱</span><span class="sp"></span>
    <button class="btn sm gold" id="btn-review-approve-all">批量批准本类</button>
  </div>
  <div class="rv">
    <div class="rv-list">
      <div class="tabs" id="review-tabs" style="padding:0 8px"></div>
      <div id="review-items"></div>
    </div>
    <div class="rv-detail" id="review-detail"></div>
  </div>`;
  $("btn-review-approve-all").onclick = async () => {
    try { await EA.api("POST", "/api/v2/review/approve-all", { type: EA._rvState.type }); EA.toast("已批量批准"); loadReview(); updateRailDot(); } catch (e) { EA.toast(e.message); }
  };
  loadReview();
});

async function loadReview() {
  let items = [];
  try {
    const r = await EA.api("GET", `/api/v2/review/list${EA._rvState.type ? "?type=" + encodeURIComponent(EA._rvState.type) : ""}`);
    items = Array.isArray(r) ? r : (r.items || r.list || r.pending || []);
  } catch (_) { items = []; }
  const types = [["全部", ""], ["报告", "report"], ["事实", "fact"], ["技能", "skill"], ["更新", "skill_update"]];
  const tabs = $("review-tabs");
  if (tabs) {
    const cnt = (label, ftype) => ftype === "" ? items.length : items.filter((x) => (x.type || "report") === ftype).length;
    tabs.innerHTML = types.map(([label, ftype]) => `<button class="${(!EA._rvState.type && !ftype) || EA._rvState.type === ftype ? "active" : ""}" data-f="${ftype}">${label} ${cnt(label, ftype)}</button>`).join("");
    tabs.querySelectorAll("button").forEach((b) => {
      b.onclick = () => { EA._rvState.type = b.dataset.f; loadReview(); };
    });
  }
  // 空状态提示（审核中心为空时）
  if (!items.length && $("review-items")) {
    $("review-items").innerHTML = '<div style="color:var(--text-3);font-size:12px;padding:20px;text-align:center">暂无待办，全部已处理</div>';
  }
  const list = $("review-items");
  if (list) {
    const rvLabel = { "report": "报告", "fact": "事实", "skill": "技能", "skill_update": "更新", "blueprint": "蓝图" };
    list.innerHTML = items.map((it, i) => {
      const tp = it.type || "report";
      const label = rvLabel[tp] || tp;
      return `<div class="ritem ${EA._rvState.cur && EA._rvState.cur === it ? "on" : ""}" data-i="${i}">
        <span class="tag ${rvTag(tp)}" style="flex-shrink:0">${label}</span>
        <div><div class="tt">${EA.esc(it.title || it.name || it.subject || "待办事项")}</div>
        <div class="mt">${EA.esc(it.source || it.actor || it.created_by || "")} · ${EA.fmtTime(it.ts || it.time || it.created_at)}</div></div>
      </div>`;
    }).join("") || '<div style="color:var(--text-3);font-size:12px;padding:20px;text-align:center">暂无待办</div>';
    list.querySelectorAll(".ritem").forEach((el) => {
      el.onclick = () => { EA._rvState.cur = items[Number(el.dataset.i)]; renderReviewDetail(); loadReview(); };
    });
  }
  updateRailDot(items.length);
}

function rvTag(t) { return { "报告": "amber", "fact": "blue", "skill": "gold", "skill_update": "green", "blueprint": "purple" }[t] || "gray"; }

function updateRailDot(n) {
  const dot = $("rail-review-dot");
  if (dot) { dot.style.display = n > 0 ? "flex" : "none"; dot.textContent = n > 99 ? "99+" : n; }
}

function renderReviewDetail() {
  const it = EA._rvState.cur;
  const d = $("review-detail");
  if (!it) { d.innerHTML = '<div style="color:var(--text-3);padding:40px;text-align:center">选择左侧待办查看详情</div>'; return; }
  const orig = it.original || it.old || it.content || "";
  const sugg = it.suggested || it.new || it.rewrite || "";
  d.innerHTML = `
    <div style="display:flex;gap:10px;align-items:center">
      <h2 style="font-size:17px">${EA.esc(it.title || it.name || "")}</h2>
      <span class="tag ${rvTag(it.type)}">${EA.esc(it.type || "报告")}</span><span class="sp" style="flex:1"></span>
    </div>
    <p style="font-size:13px;color:var(--text-2);margin-top:6px">${EA.esc(it.summary || it.comment || it.reason || "")}</p>
    <div class="diff">
      <div class="col"><h5>原文</h5>${EA.esc(orig || "（无原文）")}</div>
      <div class="col"><h5>AI 建议</h5>${EA.esc(sugg || "（无建议）")}</div>
    </div>
    <div class="opbar">
      <input class="input" id="rv-comment" style="flex:1" placeholder="审核意见（可选）…">
      <button class="btn danger" id="btn-rv-reject">拒绝并退回</button>
      <button class="btn gold" id="btn-rv-approve">批准通过</button>
    </div>`;
  $("btn-rv-approve").onclick = async () => {
    try { await EA.api("POST", "/api/v2/review/approve", { type: it.type || "report", id: it.id ?? it.item_id ?? it.rid ?? it.sid ?? it.pid, comment: $("rv-comment").value }); EA.toast("已批准"); EA._rvState.cur = null; loadReview(); } catch (e) { EA.toast(e.message); }
  };
  $("btn-rv-reject").onclick = async () => {
    try { await EA.api("POST", "/api/v2/review/reject", { type: it.type || "report", id: it.id ?? it.item_id ?? it.rid ?? it.sid ?? it.pid, reason: $("rv-comment").value }); EA.toast("已拒绝"); EA._rvState.cur = null; loadReview(); } catch (e) { EA.toast(e.message); }
  };
}

/* ==================== 11 观测与追踪 ==================== */
EA.onView("obs", function () {
  document.getElementById("v-obs").innerHTML = `
  <div class="topbar">
    <h1>观测与追踪</h1><span class="crumb">trace / usage / tools</span><span class="sp"></span>
    <select class="select" id="obs-range"><option value="today">今天</option><option value="7d">近 7 天</option><option value="30d">近 30 天</option></select>
  </div>
  <div class="stat-row" id="obs-stats"></div>
  <div class="content">
    <div class="cols2">
      <div class="card wf-box">
        <div style="display:flex;justify-content:space-between;gap:8px;margin-bottom:14px;flex-wrap:wrap">
          <b>Trace 瀑布</b>
          <div style="display:flex;gap:6px">
            <input class="input" id="obs-trace-filter" style="width:150px;padding:4px 10px" placeholder="任务号过滤">
            <input class="input" id="obs-trace-id" style="width:150px;padding:4px 10px" placeholder="trace ID 查询">
            <button class="btn sm" id="obs-trace-query">查询</button>
          </div>
        </div>
        <div id="trace-waterfall"></div>
      </div>
      <div style="display:flex;flex-direction:column;gap:14px">
        <div class="card" style="padding:16px 18px"><b style="font-size:13px">按 Provider 聚合</b><div id="obs-aggregate" style="margin-top:12px"></div></div>
        <div class="card" style="padding:16px 18px"><b style="font-size:13px">工具注册表</b><div id="obs-tools"></div></div>
      </div>
    </div>
  </div>`;
  $("obs-range").onchange = loadObs;
  $("obs-trace-filter").addEventListener("input", debounce(loadObs, 400));
  // 通用 trace 查询：按 trace_id 精确查单条调用链
  const doTraceQuery = async () => {
    const tid = $("obs-trace-id").value.trim();
    if (!tid) return loadObs();
    const wf = $("trace-waterfall");
    try {
      const r = await EA.api("GET", `/api/v2/trace/query?trace_id=${encodeURIComponent(tid)}&days=7`);
      const spans = (r.spans || r.traces || []).map((sp) => ({
        name: sp.name || "span-" + (sp.span_id || "").slice(0, 8),
        type: sp.type || "llm",
        duration_ms: sp.duration_ms || sp.duration || 0,
        status: sp.status,
        extra: `${EA.esc(sp.tool || sp.provider || "")} ${EA.esc(sp.task_id || "")} ${EA.esc(sp.error || "")}`,
      }));
      if (!spans.length) { wf.innerHTML = '<div style="color:var(--text-3);font-size:12px">未找到该 trace</div>'; return; }
      const maxDur = Math.max(0.5, ...spans.map((s) => s.duration_ms / 1000));
      wf.innerHTML = spans.map((sp) => {
        const cls = sp.status === "ok" || !sp.status ? "ok" : sp.status === "error" ? "err" : "run";
        const dur = (sp.duration_ms || 0) / 1000;
        return `<div class="wf-row"><span class="nm" title="${EA.esc(sp.extra || "")}">${EA.esc(sp.name)}</span>
          <div class="bar ${cls}" style="width:${Math.max(4, Math.round(dur / maxDur * 84))}%">${dur.toFixed(1)}s ${EA.esc(sp.extra || "")}</div>
          <span class="tag ${sp.status === "ok" || !sp.status ? "green" : sp.status === "error" ? "red" : "gray"}" style="padding:0 6px;flex-shrink:0">${EA.esc(sp.status || "ok")}</span></div>`;
      }).join("");
    } catch (e) { wf.innerHTML = '<div style="color:var(--text-3);font-size:12px">查询失败：' + EA.esc(e.message) + "</div>"; }
  };
  $("obs-trace-query").onclick = doTraceQuery;
  $("obs-trace-id").addEventListener("keydown", (e) => { if (e.key === "Enter") doTraceQuery(); });
  loadObs();
});

async function loadObs() {
  const range = $("obs-range").value;
  // ---- 统计卡：/api/stats.today + /api/usage.summary ----
  try {
    const s = await EA.api("GET", "/api/stats");
    const u = await EA.api("GET", "/api/usage?range=" + range);
    const today = s.today || {};
    const sum = u.summary || {};
    const reqs = sum.requests ?? today.requests ?? 0;
    const tokens = sum.tokens ?? (sum.prompt + sum.comp + sum.thinking) ?? 0;
    const hit = sum.hit_rate ?? today.hit_rate ?? 0;
    const cost = sum.cost ?? 0;
    $("obs-stats").innerHTML = `
      <div class="card stat"><div class="n">${EA.fmtNum(reqs)}</div><div class="l">${range === "today" ? "今日请求" : "请求总数"}</div></div>
      <div class="card stat"><div class="n">${fmtK(tokens)}</div><div class="l">Token 总量</div><div class="d">输入 ${fmtK(sum.prompt || 0)} / 输出 ${fmtK(sum.comp || 0)} / 思考 ${fmtK(sum.thinking || 0)}</div></div>
      <div class="card stat"><div class="n" style="color:var(--green)">${(hit * 100).toFixed(1)}%</div><div class="l">缓存命中率</div></div>
      <div class="card stat"><div class="n" style="color:var(--gold)">¥${Number(cost).toFixed(4)}</div><div class="l">估算费用</div><div class="d" style="color:var(--green)">${EA.fmtNum(sum.tasks ?? 0)} 任务</div></div>`;
  } catch (_) {}
  // ---- Trace 瀑布：有过滤词查任务 trace，否则展示全局 slowest ----
  const q = $("obs-trace-filter").value.trim();
  try {
    let spans = [];
    if (q) {
      const r = await EA.api("POST", "/api/v2/trace/task", { task_id: Number(q) || q });
      spans = (r.traces || []).map((t) => ({
        name: t.title || "trace-" + t.trace_id,
        type: "llm", duration_ms: t.duration_ms || 0, status: t.status,
        extra: `${t.span_count} spans · trace ${(t.trace_id || "").slice(0, 8)}`,
      }));
    } else {
      const r = await EA.api("POST", "/api/v2/trace/aggregate", { group_by: "type" });
      spans = (r.slowest || []).map((sp) => ({
        name: sp.name || "span", type: sp.type || "llm", duration_ms: sp.duration_ms || 0,
        status: sp.status, extra: "task " + sp.task_id,
      }));
    }
    const wf = $("trace-waterfall");
    if (wf) {
      const maxDur = Math.max(0.5, ...spans.map((s) => s.duration_ms / 1000));
      wf.innerHTML = spans.map((sp) => {
        const dur = sp.duration_ms / 1000;
        const cls = sp.type === "tool" || sp.type === "skill" ? "tool" : sp.type === "kb" ? "kb" : "llm";
        return `<div class="wf-row"><span class="nm" title="${EA.esc(sp.extra || "")}">${EA.esc(sp.name)}</span>
          <div class="bar ${cls}" style="width:${Math.max(4, Math.round(dur / maxDur * 84))}%">${dur.toFixed(1)}s ${EA.esc(sp.extra || "")}</div>
          <span class="tag ${sp.status === "ok" ? "green" : sp.status === "error" ? "red" : "gray"}" style="padding:0 6px;flex-shrink:0">${EA.esc(sp.status || "")}</span></div>`;
      }).join("") || '<div style="color:var(--text-3);font-size:12px">暂无 trace 数据（输入任务号可查看该任务）</div>';
    }
  } catch (_) {}
  // ---- Provider/类型聚合：/api/v2/trace/aggregate.by_type ----
  try {
    const r = await EA.api("POST", "/api/v2/trace/aggregate", { group_by: "type" });
    const byType = r.by_type || {};
    const agg = $("obs-aggregate");
    if (agg) {
      const entries = Object.entries(byType);
      const max = Math.max(1, ...entries.map(([, v]) => Number(v) || 0));
      agg.innerHTML = (entries.length ? entries.map(([k, v], i) => `
        <div style="font-size:12px;display:flex;justify-content:space-between;margin-top:6px"><span>${EA.esc(k)}</span><b>${EA.fmtNum(v)}</b></div>
        <div class="mbar"><i style="width:${Math.round(Number(v) / max * 100)}%;background:${["#1A365D", "#5B7BA6", "#2F9E6E", "#3B6FB5", "#C98A1B"][i % 5]}"></i></div>`).join("") : '<div style="color:var(--text-3);font-size:12px;margin-top:6px">暂无数据</div>') +
        `<div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-3);border-top:1px dashed var(--line);margin-top:10px;padding-top:8px">
          <span>trace ${r.trace_count ?? 0}</span><span>spans ${r.span_count ?? 0}</span>
          <span class="${r.errors ? "tag red" : "tag green"}" style="padding:0 6px">${r.errors ? "错误 " + r.errors : "无错误"}</span>
          <span>¥${(r.total_cost ?? 0).toFixed(4)}</span>
        </div>`;
    }
  } catch (_) {}
  // ---- 工具注册表：/api/v2/tools ----
  try {
    const r = await EA.api("GET", "/api/v2/tools");
    const arr = (r && r.tools) || (Array.isArray(r) ? r : []);
    $("obs-tools").innerHTML = arr.slice(0, 14).map((t) => `
      <div class="trow">
        <span><b>${EA.esc(t.name || t.id || t)}</b> <span class="tag blue" style="padding:0 6px">${EA.esc(t.capability || "内置")}</span></span>
        <span class="mono" style="font-size:11px;color:var(--text-3)">${EA.esc(t.sandbox || "")}</span>
      </div>
      <div style="font-size:11px;color:var(--text-2);padding:0 4px 8px" title="${EA.esc(t.description || "")}">${EA.esc((t.description || "").slice(0, 110))}${(t.description || "").length > 110 ? "…" : ""}</div>`).join("") ||
      '<div style="color:var(--text-3);font-size:12px">无工具</div>';
  } catch (_) {}
}

function fmtK(n) { n = Number(n) || 0; return n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n); }

// token 窗口紧凑显示:1M / 128K / 32K
function fmtCtx(n) {
  n = Number(n) || 0;
  if (n >= 1e6) return (n / 1e6).toFixed(n % 1e6 === 0 ? 0 : 1).replace(/\.0$/, "") + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(n % 1e3 === 0 ? 0 : 1).replace(/\.0$/, "") + "K";
  return String(n);
}

// Provider 弹窗共用的上下文长度表单行
function provCtxRow(val, ph) {
  return `<div class="form-row"><label>上下文长度</label>
    <input class="input" id="pf-ctx" type="number" min="0" step="1000" value="${val || 0}" placeholder="${ph || "0=自动识别"}">
    <span style="font-size:12px;color:var(--text-3);flex:0 0 auto">tokens，0=自动按模型识别</span></div>`;
}
function provCtxVal() {
  const el = document.getElementById("pf-ctx");
  const n = el ? Number(el.value) : 0;
  return Number.isFinite(n) && n > 0 ? Math.round(n) : 0;
}

/* ==================== 12 系统设置 ==================== */
EA._setTab = "provider";
EA.onView("settings", function () {
  // 支持深链：#settings/<tab>
  const sub = (location.hash || "").split("/")[1];
  if (sub && ["provider", "search", "ocr", "source", "general"].includes(sub)) EA._setTab = sub;
  document.getElementById("v-settings").innerHTML = `
  <div class="topbar"><h1>系统设置</h1><span class="sp"></span><span class="tag gray" id="set-ver">v2.0.4</span></div>
  <div class="st">
    <div class="st-nav" id="set-nav">
      <a class="on" data-s="provider">模型 Provider</a>
      <a data-s="search">搜索服务</a>
      <a data-s="ocr">OCR 服务</a>
      <a data-s="source">数据源</a>
      <a data-s="general">通用</a>
    </div>
    <div class="st-body" id="set-body"></div>
  </div>`;
  document.querySelectorAll("#set-nav a").forEach((a) => {
    if (a.dataset.s === EA._setTab) a.classList.add("on"); else a.classList.remove("on");
    a.onclick = () => {
      document.querySelectorAll("#set-nav a").forEach((x) => x.classList.remove("on"));
      a.classList.add("on"); EA._setTab = a.dataset.s; loadSetTab();
    };
  });
  loadMetaVer();
  loadSetTab();
});

async function loadMetaVer() {
  try { const m = await EA.api("GET", "/api/meta"); const v = $("set-ver"); if (v) v.textContent = m.version || v.textContent; } catch (_) {}
}

async function loadSetTab() {
  const body = $("set-body");
  if (!body) return;
  if (EA._setTab === "provider") {
    let providers = [];
    try { const r = await EA.api("GET", "/api/providers"); providers = Array.isArray(r) ? r : (r.providers || []); } catch (_) {}
    body.innerHTML = `<div class="sect">模型 Provider</div>` +
      providers.map((p) => `
      <div class="card prov" style="border-left:3px solid ${p.is_active ? "var(--green)" : "transparent"}">
        <div class="ic" style="background:var(--navy)">${EA.esc((p.name || "P").slice(0, 2).toUpperCase())}</div>
        <div style="flex:1"><div class="nm">${EA.esc(p.name || "")} ${p.is_active ? '<span class="tag green" style="margin-left:6px">激活中</span>' : ""}</div>
        <div class="url">${EA.esc(p.base_url || "")} · ${EA.esc(p.model || "")}${p.context_length ? `<span class="tag gray" style="padding:0 6px">窗口 ${fmtCtx(p.context_length)}</span>` : ""}</div></div>
        ${p.is_active ? "" : `<button class="btn sm pri" data-a="act" data-id="${p.id}">设为激活</button>`}
        <button class="btn sm" data-a="edit" data-id="${p.id}">编辑</button>
        <button class="btn sm danger" data-a="del" data-id="${p.id}">删除</button>
      </div>`).join("") + '<div style="margin-top:10px"><button class="btn sm gold" id="btn-prov-add">+ 新增 Provider</button></div>';
    body.querySelectorAll("[data-a]").forEach((b) => {
      b.onclick = async () => {
        const id = b.dataset.id, a = b.dataset.a;
        try {
          if (a === "act") { await EA.api("POST", `/api/providers/${id}/activate`); loadSetTab(); }
          if (a === "edit") {
            const p = providers.find((x) => String(x.id) === String(id)) || {};
            const ov = EA.modal("编辑 Provider",
              `<div class="form-row"><label>名称</label><input class="input" id="pf-name" value="${EA.esc(p.name || "")}"></div>
               <div class="form-row"><label>Base URL</label><input class="input" id="pf-base" value="${EA.esc(p.base_url || "")}"></div>
               <div class="form-row"><label>模型</label><input class="input" id="pf-model" value="${EA.esc(p.model || "")}"></div>
               ${provCtxRow(p.context_length, "0=自动识别")}
               <div class="form-row"><label>API Key</label><input class="input" id="pf-key" value="${EA.esc(p.api_key || "")}" placeholder="留空保持不变"></div>
               <div class="form-row"><label>内置联网搜索</label><label class="chk"><input type="checkbox" id="pf-ss" ${p.use_server_search ? "checked" : ""}> DeepSeek Responses API 内置 web_search（选用 DeepSeek 时服务端搜索）</label></div>
               <div class="form-row"><label></label><span id="pf-test-msg" style="font-size:12px;color:var(--text-3)"></span></div>`,
              `<button class="btn" data-x>取消</button><button class="btn" id="pf-test">测试连接</button><button class="btn pri" data-ok>保存</button>`);
            ov.querySelector("[data-x]").onclick = () => ov.remove();
            const pfKey = () => ov.querySelector("#pf-key").value || p.api_key || "";
            ov.querySelector("#pf-test").onclick = async () => {
              const btn = ov.querySelector("#pf-test");
              const msg = ov.querySelector("#pf-test-msg");
              btn.disabled = true; msg.textContent = "测试中…";
              try {
                const r = await EA.api("POST", "/api/providers/test", {
                  base_url: ov.querySelector("#pf-base").value, model: ov.querySelector("#pf-model").value,
                  api_key: pfKey(), kind: p.kind || "",
                });
                msg.textContent = r.ok ? ("[OK] 连接正常" + (r.detail && r.detail !== "连接成功" ? "：" + r.detail : "")) : ("[X] " + (r.detail || r.error || "连接失败"));
              } catch (e) { msg.textContent = "[X] " + e.message; }
              btn.disabled = false;
            };
            ov.querySelector("[data-ok]").onclick = async () => {
              try {
                await EA.api("PUT", `/api/providers/${id}`, {
                  name: ov.querySelector("#pf-name").value, base_url: ov.querySelector("#pf-base").value,
                  model: ov.querySelector("#pf-model").value, api_key: pfKey(),
                  kind: p.kind || "", reasoning_effort: p.reasoning_effort || "",
                  context_length: provCtxVal(),
                  use_server_search: ov.querySelector("#pf-ss") && ov.querySelector("#pf-ss").checked ? 1 : 0,
                });
                ov.remove(); EA.toast("已保存"); loadSetTab();
              } catch (e) { EA.toast(e.message); }
            };
          }
          if (a === "del") EA.confirm("删除该 Provider？", async () => { await EA.api("DELETE", `/api/providers/${id}`); loadSetTab(); });
        } catch (e) { EA.toast(e.message); }
      };
    });
    $("btn-prov-add").onclick = () => {
      const ov = EA.modal("新增 Provider",
        `<div class="form-row"><label>名称</label><input class="input" id="pf-name" placeholder="DeepSeek-V3"></div>
         <div class="form-row"><label>Base URL</label><input class="input" id="pf-base" placeholder="https://api.deepseek.com"></div>
         <div class="form-row"><label>模型</label><input class="input" id="pf-model" placeholder="deepseek-chat"></div>
         ${provCtxRow("", "0=自动识别")}
         <div class="form-row"><label>API Key</label><input class="input" id="pf-key" placeholder="sk-..."></div>`,
        `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>保存</button>`);
      ov.querySelector("[data-x]").onclick = () => ov.remove();
      ov.querySelector("[data-ok]").onclick = async () => {
        try {
          await EA.api("POST", "/api/providers", {
            name: ov.querySelector("#pf-name").value, base_url: ov.querySelector("#pf-base").value,
            model: ov.querySelector("#pf-model").value, api_key: ov.querySelector("#pf-key").value,
            context_length: provCtxVal(),
          });
          ov.remove(); EA.toast("已保存"); loadSetTab();
        } catch (e) { EA.toast(e.message); }
      };
    };
  } else if (EA._setTab === "search") {
    let s = {};
    try { s = await EA.api("GET", "/api/search/status"); } catch (_) {}
    const cfg = s.config || {};
    const on = s.available || (s.launcher && s.launcher.ready);
    const launcher = s.launcher || {};
    body.innerHTML = `<div class="sect">搜索服务（SearXNG）</div>
      <div class="card" style="padding:18px 20px">
        <div class="form-row"><label>服务地址</label><input class="input" id="sx-url" value="${EA.esc(cfg.base_url || "http://127.0.0.1:8080")}">
          <span class="tag ${on ? "green" : "red"}">${on ? "在线" : "离线"}</span></div>
        <div class="form-row"><label>状态详情</label><span style="font-size:12px;color:var(--text-2)">
          ${s.engine_chain ? "引擎链 " + EA.esc(s.engine_chain) : ""}
          ${launcher.pid ? " · PID " + launcher.pid : ""}
          ${launcher.port ? " · 端口 " + launcher.port : ""}
          ${s.mcp && s.mcp.ok ? " · MCP 通道 OK" : ""}
          ${s.available ? '<span class="tag green" style="margin-left:4px">可用</span>' : ""}
          ${launcher.last_err ? '<span class="tag red" style="margin-left:4px" title="' + EA.esc(launcher.last_err) + '">上次错误</span>' : ""}
        </span></div>
        <div class="form-row"><label>启用开关</label>
          <div class="sw ${cfg.enabled ? "on" : ""}" id="sx-enabled"></div>
          <span style="font-size:12px;color:var(--text-3)">${cfg.enabled ? "已启用" : "已停用"} · 自动启动 ${launcher.auto_start ? "开" : "关"}</span></div>
        <div style="display:flex;gap:8px">
          <button class="btn sm pri" id="btn-sx-save">保存配置</button>
          <button class="btn sm" id="btn-sx-status">检测状态</button>
          <button class="btn sm danger" id="btn-sx-restart">重启服务</button>
        </div>
      </div>`;
    $("btn-sx-save").onclick = async () => {
      try { await EA.api("POST", "/api/search/config", { base_url: $("sx-url").value.trim() }); EA.toast("已保存"); loadSetTab(); } catch (e) { EA.toast(e.message); }
    };
    $("sx-enabled").onclick = async () => {
      const next = !$("sx-enabled").classList.contains("on");
      try { await EA.api("POST", "/api/search/config", { enabled: next }); EA.toast(next ? "已启用搜索服务" : "已停用搜索服务"); loadSetTab(); } catch (e) { EA.toast(e.message); }
    };
    $("btn-sx-status").onclick = async () => { try { const r = await EA.api("GET", "/api/search/status"); EA.toast(r.available ? "在线" : "离线" + (r.launcher && r.launcher.last_err ? "：" + r.launcher.last_err : "")); loadSetTab(); } catch (e) { EA.toast(e.message); } };
    $("btn-sx-restart").onclick = () => EA.confirm("重启搜索服务？", async () => { try { await EA.api("POST", "/api/search/restart"); EA.toast("已重启"); loadSetTab(); } catch (e) { EA.toast(e.message); } });
  } else if (EA._setTab === "ocr") {
    let s = {};
    try { s = await EA.api("GET", "/api/ocr/status"); } catch (_) {}
    body.innerHTML = `<div class="sect">OCR 服务</div>
      <div class="card" style="padding:18px 20px;display:flex;gap:24px;align-items:center">
        <div><div style="font-size:12px;color:var(--text-3)">Worker 进程</div><b style="font-family:var(--mono)">${s.workers ?? s.worker ?? "—"} 运行中</b></div>
        <div><div style="font-size:12px;color:var(--text-3)">队列长度</div><b style="font-family:var(--mono)">${s.queue ?? s.queue_length ?? 0}</b></div>
        <span class="tag green" style="margin-left:auto">${s.online ? "健康" : "未知"}</span>
      </div>`;
  } else if (EA._setTab === "source") {
    let sources = [];
    try { const r = await EA.api("GET", "/api/v2/publicapi/sources"); sources = Array.isArray(r) ? r : (r.sources || []); } catch (_) {}
    let health = {};
    try { const r = await EA.api("GET", "/api/v2/publicapi/health"); health = (r && r.sources) || {}; } catch (_) {}
    const okN = Object.values(health).filter((h) => h && h.ok === true).length;
    body.innerHTML = `<div class="sect">公开数据源 <span class="tag green" style="margin-left:8px">${okN}/${sources.length} 可用</span></div>
      <div class="card" style="padding:6px 20px">
        ${sources.map((s) => {
          const h = health[s.source_id] || {};
          const st = h.ok === true ? ["green", "正常"] : h.ok === false ? ["red", "离线"] : ["amber", "未知"];
          const detail = h.latency ? ` · ${h.latency}ms` : "";
          return `
          <div class="form-row" style="border-bottom:1px dashed var(--line);padding:12px 0;margin:0">
            <label style="width:auto;flex:1">${EA.esc(s.name || s.source_id || "数据源")}
              <span class="mono" style="font-size:11px;color:var(--text-3);margin-left:6px">${EA.esc(s.source_id)}</span>
              <span style="font-size:11px;color:var(--text-3)">缓存 ${s.cache_ttl ? Math.round(s.cache_ttl / 60) : "—"} min</span>${detail}</label>
            <span class="tag ${st[0]}">${st[1]}</span>
            <button class="btn sm" data-id="${EA.esc(s.source_id)}">手动拉取</button>
          </div>`;
        }).join("") || '<div style="color:var(--text-3);padding:14px 0">暂无数据源</div>'}
      </div>`;
    body.querySelectorAll("[data-id]").forEach((b) => {
      b.onclick = async () => {
        try {
          const r = await EA.api("POST", "/api/v2/publicapi/fetch", { source_id: b.dataset.id });
          EA.toast(r.message || (r.ok ? "拉取完成" : "拉取失败：" + (r.error || "")));
          loadSetTab();
        } catch (e) { EA.toast(e.message); }
      };
    });
  } else {
    body.innerHTML = `<div class="sect">通用</div>
      <div class="card" style="padding:18px 20px">
        <div class="form-row"><label>演示模式</label><span class="tag blue">免密钥可完整体验</span></div>
        <div class="form-row"><label>关于</label><span id="set-about">Environment Agent — 生态环境特化型智能体</span></div>
      </div>
      <div class="sect">MCP 外部工具</div>
      <div class="card" style="padding:18px 20px">
        <div style="font-size:12px;color:var(--text-2);margin-bottom:8px">通过 MCP 协议连接的外部工具服务器（initialize / tools/list / tools/call）</div>
        <div id="mcp-tools" style="font-size:12px;color:var(--text-3)">加载中…</div>
        <button class="btn sm" id="btn-mcp-test" style="margin-top:10px">探测 MCP 工具</button>
      </div>`;
    const mcpBox = $("mcp-tools");
    const loadMcp = async () => {
      try {
        const r = await EA.api("GET", "/api/v2/mcp/tools");
        const arr = (r && r.tools) || (Array.isArray(r) ? r : []);
        mcpBox.innerHTML = arr.length
          ? arr.map((t) => `<div style="margin-bottom:6px">• <span class="mono">${EA.esc(t.name || t.tool || "")}</span> <span style="color:var(--text-3)">${EA.esc(t.description || "")}</span></div>`).join("")
          : '<span>未连接任何 MCP 工具服务器</span>';
      } catch (e) { mcpBox.innerHTML = "查询失败：" + EA.esc(e.message); }
    };
    loadMcp();
    $("btn-mcp-test").onclick = async () => {
      const b = $("btn-mcp-test"); b.disabled = true; b.textContent = "探测中…";
      try {
        const r = await EA.api("POST", "/api/v2/mcp", { jsonrpc: "2.0", id: 1, method: "tools/list", params: {} });
        const tools = (r && r.result && r.result.tools) || [];
        mcpBox.innerHTML = tools.length
          ? tools.map((t) => `<div style="margin-bottom:6px">• <span class="mono">${EA.esc(t.name || "")}</span> <span style="color:var(--text-3)">${EA.esc(t.description || "")}</span></div>`).join("")
          : '<span>工具列表为空</span>';
      } catch (e) { mcpBox.innerHTML = "探测失败：" + EA.esc(e.message); }
      b.disabled = false; b.textContent = "探测 MCP 工具";
    };
  }
}
