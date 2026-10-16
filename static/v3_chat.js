/* 01 对话工作台 */
"use strict";
function $(id) { return document.getElementById(id); }

EA.onView("chat", function () {
  document.getElementById("v-chat").innerHTML = `
  <div class="topbar">
    <h1>对话工作台</h1>
    <span class="crumb" id="chat-crumb"></span><span class="sp"></span>
    <span class="tag green"><span class="dot-s" style="background:var(--green)"></span><span id="chat-provider">连接中…</span></span>
    <button class="btn sm" id="btn-chat-budget">任务预算</button>
    <button class="btn sm gold" id="btn-chat-export">导出产物</button>
  </div>
  <div class="ws">
    <div class="sess">
      <div class="hd"><b>会话列表</b><button class="btn sm pri" id="btn-task-new">+ 新建</button></div>
      <div class="list" id="task-list"></div>
    </div>
    <div class="chat">
      <div class="flow" id="msg-flow"></div>
      <div class="inputbar"><div class="inputbox">
        <div class="cfgbar">
          <div class="pk-wrap" id="wrap-provider">
            <div class="picker" id="picker-provider">
              <svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/></svg>
              <span class="val" id="cfg-provider-val">模型</span>
              <svg class="caret" width="12" height="12" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>
            </div>
            <div class="dd" id="dd-provider" style="display:none"></div>
          </div>
          <span class="sep"></span>
          <span class="lab">推理</span>
          <div class="effort" id="effort-sw">
            <button data-e="low" class="on">快速</button><button data-e="mid">标准</button><button data-e="high">深度</button>
          </div>
          <span class="sep"></span>
          <div class="pk-wrap" id="wrap-skills">
            <div class="picker" id="picker-skills">
              <svg viewBox="0 0 24 24"><path d="M12 2l3 6 7 .5-5.5 4.5L18.5 21 12 16.5 5.5 21l2-8L2 8.5 9 8z"/></svg>
              <span>技能</span><span class="val" id="cfg-skill-count">0</span>
              <svg class="caret" width="12" height="12" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>
            </div>
            <div class="dd" id="dd-skills" style="display:none"></div>
          </div>
          <span class="sk-chip-row" id="sk-chip-row"></span>
        </div>
        <div class="inputarea">
          <textarea id="chat-input" rows="2" placeholder="继续提问，或输入 / 调用技能…"></textarea>
          <div id="attach-row"></div>
        </div>
        <div class="row">
          <div class="mode-sw" id="mode-sw">
            <button data-m="craft" class="on">Craft</button><button data-m="ask">Ask</button><button data-m="plan">Plan</button>
          </div>
          <button class="btn ghost sm" id="btn-attach">附件</button>
          <input type="file" id="file-input" class="hidden" multiple>
          <button class="btn ghost sm" id="btn-extract">抽取事实</button>
          <span class="sp" style="flex:1"></span>
          <button class="btn sm" id="btn-pause">暂停</button>
          <button class="btn pri sm" id="btn-send">发送</button>
        </div>
      </div></div>
    </div>
    <div class="ctx" id="chat-ctx">
      <h4>Token 预算</h4><div class="card" style="padding:12px" id="ctx-budget">
        <div class="kv"><span>已用</span><b>— / —</b></div>
        <div class="meter"><i style="width:0%"></i></div>
        <div class="kv"><span>上下文压缩</span><b>0 次</b></div></div>
      <h4>本轮用量</h4><div class="card" style="padding:12px" id="ctx-usage">
        <div class="kv"><span>输入</span><b>—</b></div>
        <div class="kv"><span>输出</span><b>—</b></div>
        <div class="kv"><span>缓存命中</span><b>—</b></div>
        <div class="kv"><span>估算节省</span><b>—</b></div></div>
      <h4>引用来源</h4><div id="ctx-refs"></div>
      <h4>任务产物</h4><div id="ctx-outputs"></div>
      <button class="btn sm" style="width:100%;justify-content:center;margin-top:4px" id="btn-open-outdir">打开所在目录</button>
      <h4>资料缺口</h4><div class="card" style="padding:12px"><div id="ctx-gaps" style="font-size:12px;color:var(--text-3)">—</div>
        <button class="btn sm" style="width:100%;justify-content:center;margin-top:8px" id="btn-check-gaps">评估资料完整性</button></div>
    </div>
  </div>`;
  bindChatEvents();
  loadProviders();
  loadSkills();
  loadTasks();
});

function bindChatEvents() {
  $("btn-task-new").onclick = () => {
    // 懒创建：只在前台打开空白对话，发送首条消息时才真正创建任务，避免空任务堆积
    EA.state.task = null;
    EA.state.messages = [];
    resetPipelineCard();
    $("msg-flow").innerHTML = '<div style="text-align:center;color:var(--text-3);padding:60px 0">开始新的对话，输入指令让 Agent 工作</div>';
    $("chat-crumb").textContent = "新对话（发送首条消息后创建）";
    loadTasks();
    refreshCtx();
    const inp = $("chat-input");
    if (inp) { inp.value = ""; inp.focus(); }
  };
  // 发送 ↔ 结束 双态：空闲时点发送，忙时点结束（停止）
  $("btn-send").onclick = async () => {
    if (EA.state.busy) {
      EA.state.busy = false;
      try { if (EA.state.task) await EA.api("POST", `/api/tasks/${EA.state.task.id}/stop`); } catch (_) {}
      $("btn-send").textContent = "发送"; $("btn-send").classList.remove("danger");
      return;
    }
    sendMessage();
  };
  $("chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  // 暂停 ↔ 恢复 互斥
  $("btn-pause").onclick = async () => {
    if (!EA.state.task) return;
    const btn = $("btn-pause");
    if (btn.dataset.mode === "resume") {
      try {
        const r = await EA.api("POST", `/api/tasks/${EA.state.task.id}/resume`);
        if (!r.ok) { EA.toast(r.error || "恢复失败"); return; }
        btn.dataset.mode = ""; btn.textContent = "暂停"; btn.classList.remove("pri");
        EA.toast("已恢复，自动从断点继续执行");
        // 自动发送"继续任务"指令，驱动模型立即执行未完成步骤（后端会注入强执行指令）
        const input = $("chat-input");
        if (input && !EA.state.busy) {
          input.value = "继续执行上次暂停的任务，请直接从断点继续完成";
          sendMessage();
        }
      } catch (e) { EA.toast(e.message); }
    } else {
      try { await EA.api("POST", `/api/tasks/${EA.state.task.id}/pause`); btn.dataset.mode = "resume"; btn.textContent = "恢复"; btn.classList.add("pri"); EA.toast("已暂停并保存断点"); }
      catch (e) { EA.toast(e.message); }
    }
  };
  $("btn-attach").onclick = () => $("file-input").click();
  $("file-input").onchange = async (e) => {
    for (const f of e.target.files) { try { await uploadFile(f); } catch (err) { EA.toast(err.message); } }
    e.target.value = "";
  };
  // 抽取事实：从当前任务对话文本中提取结构化事实（进入审批队列）
  $("btn-extract").onclick = async () => {
    const b = $("btn-extract");
    const msgs = EA.state.messages || [];
    const text = msgs.map((m) => (m.role === "user" ? "[用户] " : "[Agent] ") + (m.content || "")).join("\n").slice(0, 6000);
    if (!text.trim()) return EA.toast("当前对话暂无内容可抽取");
    b.disabled = true;
    try {
      const r = await EA.api("POST", "/api/v2/memory/facts/extract", { text, source: "task" });
      b.disabled = false;
      const n = r.facts ? (Array.isArray(r.facts) ? r.facts.length : 0) : (r.count || 0);
      EA.toast(r.message || `已抽取 ${n} 条事实，进入审批队列`);
    } catch (e) { b.disabled = false; EA.toast(e.message); }
  };
  // 文件拖入：整个输入区可拖放附件
  const ib = document.querySelector(".inputbar .inputbox");
  if (ib) {
    ib.addEventListener("dragover", (e) => { e.preventDefault(); ib.classList.add("drag-over"); });
    ib.addEventListener("dragleave", (e) => { ib.classList.remove("drag-over"); });
    ib.addEventListener("drop", async (e) => {
      e.preventDefault(); ib.classList.remove("drag-over");
      const files = e.dataTransfer.files;
      if (!files || !files.length) return;
      for (const f of files) { try { await uploadFile(f); } catch (err) { EA.toast(err.message); } }
    });
  }
  $("btn-chat-budget").onclick = refreshCtx;
  $("btn-chat-export").onclick = async () => {
    if (!EA.state.task) return EA.toast("请先打开会话");
    try { await EA.api("POST", `/api/tasks/${EA.state.task.id}/outputs/export`); EA.toast("导出打包已生成"); } catch (e) { EA.toast(e.message); }
  };
  $("btn-open-outdir").onclick = async () => {
    if (!EA.state.task) return;
    try { await EA.api("POST", `/api/tasks/${EA.state.task.id}/outputs/open`); } catch (e) { EA.toast(e.message); }
  };
  $("btn-check-gaps").onclick = checkMaterialGaps;
  document.querySelectorAll("#mode-sw button").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll("#mode-sw button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on"); EA.state.mode = b.dataset.m;
      if (EA.state.task) EA.api("PATCH", `/api/tasks/${EA.state.task.id}`, { mode: EA.state.mode }).catch(() => {});
    };
  });
  document.querySelectorAll("#effort-sw button").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll("#effort-sw button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on"); EA.state.effort = b.dataset.e;
    };
  });
  $("picker-provider").onclick = () => toggleDD("provider");
  $("picker-skills").onclick = () => toggleDD("skills");
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#wrap-provider")) { const d = $("dd-provider"); if (d) d.style.display = "none"; }
    if (!e.target.closest("#wrap-skills")) { const d = $("dd-skills"); if (d) d.style.display = "none"; }
  });
}

function toggleDD(which) {
  const a = $("dd-provider"), b = $("dd-skills");
  const el = which === "provider" ? a : b;
  const open = el.style.display !== "none";
  a.style.display = "none"; b.style.display = "none";
  if (!open) el.style.display = "block";
}

async function loadProviders() {
  try {
    const list = await EA.api("GET", "/api/providers");
    const all = Array.isArray(list) ? list : (list.providers || []);
    // 只显示已配置 API Key 的 Provider（mock 演示类型除外），未配 Key 的模型不可用
    EA.state.providers = all.filter((p) => p.api_key || p.kind === "mock");
  } catch (_) { EA.state.providers = []; }
  const active = EA.state.providers.find((p) => p.is_active) || EA.state.providers[0] || null;
  const val = $("cfg-provider-val"), pill = $("chat-provider");
  if (val) val.textContent = active ? [active.name, active.model].filter(Boolean).join(" ") || "模型" : "演示模式";
  if (pill) pill.textContent = active ? (active.name || "") + " " + (active.model || "") : "演示模式";
  const dd = $("dd-provider");
  if (dd) {
    dd.innerHTML = '<div class="dd-h">选择模型</div>' +
      EA.state.providers.map((p) =>
        `<div class="opt ${active && active.id === p.id ? "on" : ""}" data-id="${p.id}">
           <b>${EA.esc(p.name || p.model)}</b>
           <span class="sub" style="margin-left:6px">${EA.esc(p.model || "")}</span>
           <span class="ck">${active && active.id === p.id ? "✓" : ""}</span>
         </div>`).join("") +
      (EA.state.providers.some((p) => p.kind === "mock") ? "" : '<div class="opt" data-id="0"><b>演示模式</b><span class="sub">免密钥</span></div>');
    dd.querySelectorAll(".opt").forEach((o) => {
      o.onclick = async () => {
        const pid = o.dataset.id;
        if (pid !== "0") { try { await EA.api("POST", `/api/providers/${pid}/activate`); } catch (_) {} }
        $("dd-provider").style.display = "none";
        await loadProviders();
      };
    });
  }
}

async function loadSkills() {
  try {
    const list = await EA.api("GET", "/api/skills");
    EA.state.skills = (Array.isArray(list) ? list : (list.skills || [])).filter((s) => s && s.enabled);
  } catch (_) { EA.state.skills = []; }
  renderSkillDD();
}

function renderSkillDD() {
  const dd = $("dd-skills");
  if (!dd) return;
  dd.innerHTML = '<div class="dd-h">选择技能（空 = 全部启用）</div>' +
    EA.state.skills.map((s) => {
      const on = EA.state.selectedSkills.includes(s.key);
      return `<div class="opt ${on ? "on" : ""}" data-k="${EA.esc(s.key)}">
        <span>${EA.esc(s.name || s.key)}</span>
        <span class="ck">${on ? "✓" : ""}</span></div>`;
    }).join("");
  dd.querySelectorAll(".opt").forEach((o) => {
    o.onclick = () => {
      const k = o.dataset.k;
      const i = EA.state.selectedSkills.indexOf(k);
      if (i >= 0) EA.state.selectedSkills.splice(i, 1); else EA.state.selectedSkills.push(k);
      renderSkillDD(); renderSkillChips();
    };
  });
  renderSkillChips();
}

function renderSkillChips() {
  const row = $("sk-chip-row");
  if (!row) return;
  $("cfg-skill-count").textContent = EA.state.selectedSkills.length;
  row.innerHTML = EA.state.selectedSkills.map((k) => {
    const s = EA.state.skills.find((x) => x.key === k);
    const nm = s ? (s.name || s.key) : k;
    return `<span class="sk-chip">${EA.esc(nm)}<svg viewBox="0 0 24 24" data-k="${EA.esc(k)}"><path d="M18 6L6 18M6 6l12 12"/></svg></span>`;
  }).join("");
  row.querySelectorAll("svg").forEach((sv) => {
    sv.onclick = () => {
      const k = sv.dataset.k;
      EA.state.selectedSkills = EA.state.selectedSkills.filter((x) => x !== k);
      renderSkillDD(); renderSkillChips();
    };
  });
}

async function uploadFile(f) {
  const fd = new FormData();
  fd.append("file", f);
  const r = await fetch("/api/upload", { method: "POST", body: fd });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || "上传失败");
  const chip = document.createElement("span");
  chip.className = "attach-chip";
  chip.textContent = f.name;
  // 图片附件：附带"分析"按钮（视觉理解）
  const isImg = /\.(png|jpe?g|gif|webp|bmp)$/i.test(f.name);
  if (isImg) {
    const ana = document.createElement("button");
    ana.textContent = "分析";
    ana.title = "视觉理解该图片";
    ana.onclick = async () => {
      ana.disabled = true; ana.textContent = "分析中…";
      try {
        const r = await EA.api("POST", "/api/vision/analyze", { path: j.path, question: "" });
        const txt = (r && (r.text || r.answer || r.result)) || "未识别出内容";
        EA.toast("分析完成");
        const ov = EA.modal("图片分析", `<div style="font-size:13px;white-space:pre-wrap;max-height:360px;overflow:auto;color:var(--text-2)">${EA.esc(txt)}</div>`, `<button class="btn" data-x>关闭</button>`);
        ov.querySelector("[data-x]").onclick = () => ov.remove();
      } catch (e) { EA.toast(e.message); }
      ana.disabled = false; ana.textContent = "分析";
    };
    chip.appendChild(ana);
  }
  const del = document.createElement("button");
  del.textContent = "x";
  del.onclick = () => chip.remove();
  chip.appendChild(del);
  $("attach-row").appendChild(chip);
}

async function loadTasks() {
  let tasks = [];
  try { tasks = await EA.api("GET", "/api/tasks"); } catch (_) {}
  const list = $("task-list");
  if (!list) return;
  list.innerHTML = tasks.map((t) => `
    <div class="sitem ${EA.state.task && EA.state.task.id === t.id ? "on" : ""}" data-id="${t.id}">
      <div class="t">${EA.esc(t.title || "未命名任务")}</div>
      <div class="m"><span class="tag ${t.mode === "plan" ? "blue" : t.mode === "ask" ? "gray" : "gold"}" style="padding:0 6px">${t.mode || "craft"}</span>
      <span>${EA.fmtTime(t.updated_at)}</span>
      <span class="ops"><button data-del title="删除">✕</button></span></div>
    </div>`).join("") || '<div style="color:var(--text-3);font-size:12px;padding:20px;text-align:center">暂无会话，点击 + 新建</div>';
  list.querySelectorAll(".sitem").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest("[data-del]")) {
        const id = Number(el.dataset.id);
        EA.confirm("删除该会话？", async () => {
          try {
            await EA.api("DELETE", `/api/tasks/${id}`);
            if (EA.state.task && EA.state.task.id === id) { EA.state.task = null; $("msg-flow").innerHTML = ""; $("chat-crumb").textContent = ""; }
            await loadTasks();
          } catch (err) { EA.toast(err.message); }
        });
        return;
      }
      openTask(Number(el.dataset.id));
    });
  });
}

async function openTask(id) {
  try {
    const r = await EA.api("GET", `/api/tasks/${id}`);
    resetPipelineCard();
    EA.state.task = r.task;
    EA.state.messages = r.messages || [];
    $("chat-crumb").textContent = `任务 #${r.task.id} · ${r.task.title || ""}`;
    const mb = document.querySelector(`#mode-sw button[data-m="${r.task.mode}"]`);
    if (mb) { document.querySelectorAll("#mode-sw button").forEach((x) => x.classList.remove("on")); mb.classList.add("on"); EA.state.mode = r.task.mode; }
    renderMessages();
    loadTasks();
    refreshCtx();
  } catch (e) { EA.toast(e.message); }
}

function renderMessages() {
  const flow = $("msg-flow");
  if (!flow) return;
  flow.innerHTML = "";
  if (!EA.state.messages.length) {
    flow.innerHTML = '<div style="text-align:center;color:var(--text-3);padding:60px 0">开始新的对话，输入指令让 Agent 工作</div>';
    return;
  }
  // 合并连续的 assistant 消息为一条（后端每轮循环各落库一条，避免重复结果）
  const merged = [];
  for (const m of EA.state.messages) {
    if (m.role === "assistant" && merged.length && merged[merged.length - 1].role === "assistant") {
      const last = merged[merged.length - 1];
      const c1 = last.content || "", c2 = m.content || "";
      last.content = c1 && c2 ? c1 + "\n\n" + c2 : (c1 || c2);
      const mm1 = parseMeta(last.meta) || {}, mm2 = parseMeta(m.meta) || {};
      last.meta = JSON.stringify({ ...mm1, ...mm2, tool_trace: [...(mm1.tool_trace || []), ...(mm2.tool_trace || [])] });
    } else {
      merged.push({ ...m });
    }
  }
  merged.forEach((m) => {
    if (m.role === "user") appendBubble("user", m.content, "");
    else if (m.role === "assistant") {
      const meta = parseMeta(m.meta);
      appendBubble("assistant", "", EA.md(m.content || ""), meta);
    }
  });
  flow.scrollTop = flow.scrollHeight;
}

function parseMeta(meta) {
  if (!meta) return null;
  if (typeof meta === "string") { try { return JSON.parse(meta); } catch (_) { return null; } }
  return meta;
}

function appendBubble(role, text, html, meta) {
  const flow = $("msg-flow");
  const div = document.createElement("div");
  div.className = "msg";
  const who = role === "user" ? "您" : `Agent · ${EA.state.mode} 模式`;
  let inner = html || EA.md(text);
  if (meta && meta.tool_trace && meta.tool_trace.length) {
    const tools = meta.tool_trace.map((t) =>
      `<div class="toolcard"><div class="tt"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#1A365D" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>${EA.esc(t.name || t.id || "tool")}</div>
       ${t.output ? `<div class="tool-out">${EA.esc(String(t.output).slice(0, 120))}</div>` : ""}</div>`).join("");
    inner = `<div class="toolzone">${tools}</div>` + inner;
  }
  div.innerHTML = `<div class="who">${who}</div><div class="bubble ${role}"><div class="md">${inner}</div></div>`;
  flow.appendChild(div);
  flow.scrollTop = flow.scrollHeight;
  return div.querySelector(".bubble .md");
}

async function sendMessage() {
  const input = $("chat-input");
  const content = input.value.trim();
  if (!content || EA.state.busy) return;
  // S3-H3 斜杠命令：/cmd [参数] 走命令解析（快捷指令 → 目标端点提示），不进入对话
  if (content.startsWith("/")) {
    try {
      const r = await fetch(`/api/v2/commands?text=${encodeURIComponent(content)}`);
      const j = await r.json();
      if (j.ok) {
        const hint = `[${j.label} 快捷指令] ${j.endpoint}${j.args ? `\n参数: ${j.args}` : ""}`;
        appendBubble("user", content, "");
        appendBubble("assistant", hint, "");
        input.value = "";
        return;
      }
      EA.toast(j.error || "未知命令");
      return;
    } catch (e) {
      EA.toast("命令解析失败: " + e.message);
      return;
    }
  }
  if (!EA.state.task) {
    try { const r = await EA.api("POST", "/api/tasks", { title: content.slice(0, 24), mode: EA.state.mode }); await openTask(r.id); }
    catch (e) { return EA.toast(e.message); }
  }
  const tid = EA.state.task.id;
  appendBubble("user", content, "");
  input.value = "";
  EA.state.busy = true;
  $("btn-send").textContent = "结束"; $("btn-send").classList.add("danger");

  const assist = document.createElement("div");
  assist.className = "msg";
  assist.innerHTML = `<div class="who">Agent · ${EA.state.mode} 模式</div><div class="bubble"><div class="thinkbox" style="display:none"><div class="think-head"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9.6 4.6A2 2 0 1 1 11 8H2"/><path d="M12.6 19.4A2 2 0 1 0 11 16H20"/><path d="M17.5 8a2.5 2.5 0 0 0 2 4H22"/><path d="M9.8 19.3a2.5 2.5 0 0 0 4.9.7"/></svg><span class="think-label">深度思考中</span><span class="think-dots"><i></i><i></i><i></i></span><span class="think-count"></span></div><div class="think-body"></div></div><div class="toolzone"></div><div class="md"></div></div>`;
  $("msg-flow").appendChild(assist);
  const toolZone = assist.querySelector(".toolzone");
  const mdEl = assist.querySelector(".md");
  const thinkBox = assist.querySelector(".thinkbox");
  const thinkBody = assist.querySelector(".think-body");
  const thinkHead = thinkBox.querySelector(".think-head");
  thinkHead.onclick = () => thinkBox.classList.toggle("open");
  const thinkCtx = { text: "" };
  let thinkDone = false;
  const typing = document.createElement("span");
  typing.className = "typing";
  typing.innerHTML = "<i></i><i></i><i></i>";
  mdEl.appendChild(typing);

  const body = { content, mode: EA.state.mode, effort: EA.state.effort };
  if (EA.state.selectedSkills.length) body.skills = EA.state.selectedSkills;

  try {
    const resp = await fetch(`/api/tasks/${tid}/chat`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!resp.ok) { const j = await resp.json().catch(() => ({})); throw new Error(j.error || "发送失败"); }
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "", acc = "", toolCards = [];
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, idx); buf = buf.slice(idx + 2);
        for (const line of chunk.split("\n")) {
          if (!line.startsWith("data:")) continue;
          let ev; try { ev = JSON.parse(line.slice(5).trim()); } catch (_) { continue; }
          handleSSE(ev, mdEl, (c) => {
            // 首个正文增量：深度思考结束，收起思考面板为可折叠摘要
            if (!thinkDone && thinkCtx.text) { thinkDone = true; finishThink(thinkBox, thinkCtx.text); }
            acc += c; mdEl.innerHTML = EA.md(acc); const f = $("msg-flow"); if (f) f.scrollTop = f.scrollHeight;
          }, toolCards, toolZone, thinkBox, thinkBody, thinkCtx);
        }
      }
    }
    mdEl.innerHTML = EA.md(acc);
  } catch (e) {
    mdEl.innerHTML = `<p style="color:var(--red)">${EA.esc(e.message)}</p>`;
  } finally {
    // 中途停止/异常时也收拢思考面板，保留已思考内容
    if (!thinkDone && thinkCtx && thinkCtx.text) { thinkDone = true; finishThink(thinkBox, thinkCtx.text); }
    EA.state.busy = false;
    $("btn-send").textContent = "发送"; $("btn-send").classList.remove("danger");
    refreshCtx(); loadTasks();
  }
}

// 深度思考结束：把思考面板收拢为一行"已思考 N 字"，点击可展开查看全文
function finishThink(thinkBox, text) {
  if (!thinkBox) return;
  if (!text) { thinkBox.style.display = "none"; return; }
  thinkBox.style.display = "block";
  thinkBox.classList.add("done");
  const label = thinkBox.querySelector(".think-label");
  const dots = thinkBox.querySelector(".think-dots");
  const cnt = thinkBox.querySelector(".think-count");
  if (label) label.textContent = "已思考";
  if (dots) dots.remove();
  if (cnt) cnt.textContent = text.length + " 字";
}

function handleSSE(ev, mdEl, onDelta, toolCards, toolZone, thinkBox, thinkBody, thinkCtx) {
  // 后端流式推送的预算/用量事件：实时更新侧栏，无需等回答结束
  if (ev.event === "budget") { renderCtxBudget(ev); return; }
  if (ev.event === "usage") { renderCtxUsage(ev); return; }
  // P2 对话进度卡：报告流水线阶段事件（collect/draft/review/complete/archive）
  if (ev.event === "pipeline_stage") { renderPipelineStage(ev); return; }
  // 深度思考过程：实时展示在可折叠面板中，让用户看到模型正在工作（不再忽略）
  if (ev.event === "reasoning") {
    if (thinkBox && thinkBody && thinkCtx) {
      if (thinkBox.style.display === "none") { thinkBox.style.display = "block"; thinkBox.classList.remove("done"); }
      thinkCtx.text += ev.content || "";
      thinkBody.textContent = thinkCtx.text;
      thinkBody.scrollTop = thinkBody.scrollHeight;
      const f = $("msg-flow"); if (f) f.scrollTop = f.scrollHeight;
    }
    return;
  }
  if (ev.event === "delta") { onDelta(ev.content || ""); }
  else if (ev.event === "web_search_status") {
    // DeepSeek 内置 web_search 服务端搜索进度展示
    const map = { in_progress: "正在初始化联网搜索…", searching: "正在联网搜索…", completed: "搜索完成" };
    const txt = map[ev.status] || "联网搜索中…";
    let el = document.getElementById("ss-status");
    if (!el) {
      el = document.createElement("div");
      el.id = "ss-status";
      el.className = "toolcard";
      el.innerHTML = `<div class="tt"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#1A365D" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>内置联网搜索</div>`;
      if (toolZone) toolZone.appendChild(el); else mdEl.appendChild(el);
    }
    const tt = el.querySelector(".tt");
    if (tt) {
      if (ev.status === "completed") tt.classList.add("done");
      let tag = tt.querySelector("span.tag");
      if (!tag) { tag = document.createElement("span"); tag.className = "tag blue"; tag.style.marginLeft = "auto"; tt.appendChild(tag); }
      tag.textContent = txt;
    }
    if (ev.status === "completed") setTimeout(() => { const s = document.getElementById("ss-status"); if (s) s.style.opacity = "0.5"; }, 1500);
  }
  else if (ev.event === "tool_start") {
    const card = document.createElement("div");
    card.className = "toolcard";
    card.innerHTML = `<div class="tt"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#1A365D" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>${EA.esc(ev.name || ev.id || "tool")} <code>${EA.esc((ev.args || "").slice(0, 60))}</code><span class="tag blue" style="margin-left:auto">运行中…</span></div>`;
    toolCards.push({ id: ev.id, el: card });
    if (toolZone) toolZone.appendChild(card); else mdEl.appendChild(card);
  }
  else if (ev.event === "tool_end") {
    const c = toolCards.find((x) => x.id === ev.id);
    if (c) {
      c.el.querySelector(".tag").className = "tag " + (ev.ok ? "green" : "red");
      c.el.querySelector(".tag").textContent = ev.ok ? "完成" : "失败";
      if (ev.output) {
        const o = document.createElement("div");
        o.className = "tool-out";
        o.textContent = String(ev.output).slice(0, 120);
        c.el.appendChild(o);
      }
    }
  }
  else if (ev.event === "error") {
    const p = document.createElement("p");
    p.style.cssText = "color:var(--red)";
    p.textContent = ev.message || "出错了";
    mdEl.appendChild(p);
  }
}

// 资料缺口：评估当前任务资料完整性
async function checkMaterialGaps() {
  const gaps = $("ctx-gaps");
  if (!gaps) return;
  if (!EA.state.task) { gaps.textContent = "请先创建/打开任务"; return; }
  gaps.textContent = "评估中…";
  try {
    const r = await EA.api("GET", `/api/v2/materials/status?task_id=${EA.state.task.id}`);
    const miss = r && (r.missing || r.gaps);
    const arr = Array.isArray(miss) ? miss : [];
    gaps.innerHTML = arr.length
      ? arr.map((g) => `<div style="margin-bottom:4px">• ${EA.esc(typeof g === "string" ? g : (g.name || g.desc || JSON.stringify(g)))}</div>`).join("")
        + (r.percent != null ? `<div style="color:var(--text-3);margin-top:4px">完整度 ${r.percent}%</div>` : "")
      : '<span style="color:var(--green)">资料完整，无缺口</span>';
  } catch (e) { gaps.textContent = e.message; }
}

// P2 对话进度卡：报告流水线阶段可视化（阶段节点 + 当前技能 + 描述）
const _PIPE_STAGES = [
  { id: "collect", label: "材料收集" },
  { id: "draft", label: "起草" },
  { id: "review", label: "审核" },
  { id: "complete", label: "完成" },
  { id: "archive", label: "归档" },
];
let _pipeEl = null;

function renderPipelineStage(ev) {
  // 创建/复用进度卡容器（固定在消息区顶部）
  const flow = $("msg-flow");
  if (!flow) return;
  if (!_pipeEl || !_pipeEl.isConnected) {
    _pipeEl = document.createElement("div");
    _pipeEl.className = "pipe-card";
    flow.insertBefore(_pipeEl, flow.firstChild);
  }
  const cur = ev.stage || "collect";
  const curIdx = _PIPE_STAGES.findIndex((s) => s.id === cur);
  const done = curIdx >= 0 ? _PIPE_STAGES.slice(0, curIdx + 1) : [];
  _pipeEl.innerHTML = `<div style="display:flex;align-items:center;gap:4px;flex-wrap:wrap;margin-bottom:6px">
      ${_PIPE_STAGES.map((s, i) => {
        const isDone = i <= curIdx;
        const isCur = i === curIdx;
        return `<span class="pipe-node ${isDone ? "on" : ""} ${isCur ? "cur" : ""}" style="display:flex;align-items:center;gap:3px;font-size:11px;padding:2px 8px;border-radius:10px;${isDone ? "background:var(--blue-soft);color:var(--navy);font-weight:600" : "background:var(--panel-2);color:var(--text-3)"}">
          ${isDone ? "●" : "○"} ${s.label}${isCur ? " <b>…</b>" : ""}</span>${i < _PIPE_STAGES.length - 1 ? '<span style="color:var(--text-3);font-size:10px">→</span>' : ""}`;
      }).join("")}</div>
    <div style="font-size:12px;color:var(--text-2)">${ev.desc || ""}${ev.skill ? ` <span class="tag blue" style="padding:0 6px">${EA.esc(ev.skill)}</span>` : ""}</div>`;
}

// 清理进度卡（新对话/打开任务时）
function resetPipelineCard() {
  _pipeEl = null;
}

// token 数紧凑格式化:1M / 128K / 32K
function fmtCompact(n) {
  n = Number(n || 0);
  if (n >= 1e6) return (n / 1e6).toFixed(n % 1e6 === 0 ? 0 : 1).replace(/\.0$/, "") + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(n % 1e3 === 0 ? 0 : 1).replace(/\.0$/, "") + "K";
  return String(n);
}

function renderCtxBudget(ev) {
  const bEl = $("ctx-budget");
  if (!bEl) return;
  const used = ev.estimated_tokens || ev.used || 0;
  const soft = ev.soft_budget || ev.soft || 0;
  const total = ev.hard_budget || ev.total || 0;
  const pct = used && soft ? Math.min(100, Math.round(used / soft * 100)) : 0;
  // 模型上下文窗口行:模型名 + 窗口大小(如 deepseek-v4-pro · 1M)
  const modelLabel = ev.model ? EA.esc(String(ev.model)) : "";
  const ctxLabel = ev.context_length ? fmtCompact(ev.context_length) : "";
  const winLine = (modelLabel || ctxLabel)
    ? `<div class="kv"><span>模型窗口</span><b>${modelLabel}${modelLabel && ctxLabel ? " · " : ""}${ctxLabel}</b></div>`
    : "";
  bEl.innerHTML = `<div class="kv"><span>已用</span><b>${EA.fmtNum(used)} / ${EA.fmtNum(soft || total)}</b></div>
    <div class="meter"><i style="width:${pct}%"></i></div>
    ${winLine}
    <div class="kv"><span>上下文压缩</span><b>${ev.compressed || 0} 次</b></div>`;
}

function renderCtxUsage(u) {
  const uEl = $("ctx-usage");
  if (!uEl) return;
  let hit = null;
  if (u.hit_rate != null) hit = Number(u.hit_rate);                 // 后端返回小数(0.2072) → 百分比
  else if (u.cache_hit != null) hit = Number(u.cache_hit);          // 兼容已是百分比的字段
  else if (u.hit != null) hit = (u.hit / ((u.hit + u.miss) || 1) * 100); // 命中数换算
  // hit_rate < 1 视为小数比率 → ×100
  const hitPct = hit != null ? (hit <= 1 ? hit * 100 : hit) : null;
  const save = u.saved_cost != null ? u.saved_cost : u.cost;
  uEl.innerHTML = `<div class="kv"><span>输入</span><b>${EA.fmtNum(u.prompt || u.input_tokens || u.input || 0)}</b></div>
    <div class="kv"><span>输出</span><b>${EA.fmtNum(u.completion || u.comp || u.output_tokens || u.output || 0)}</b></div>
    <div class="kv"><span>思考</span><b>${EA.fmtNum(u.thinking || 0)}</b></div>
    <div class="kv"><span>缓存命中</span><b>${hitPct != null ? hitPct.toFixed(1) + "%" : "—"}</b></div>
    <div class="kv"><span>估算节省</span><b>${save != null && save != 0 ? "¥" + Number(save).toFixed(4) : "—"}</b></div>`;
}

async function refreshCtx() {
  if (!EA.state.task) return;
  const tid = EA.state.task.id;
  try {
    const b = await EA.api("GET", `/api/tasks/${tid}/budget`);
    renderCtxBudget(b);
  } catch (_) {}
  try {
    const u = await EA.api("GET", `/api/tasks/${tid}/usage`);
    // 后端 usage 数据在 summary 子对象里
    renderCtxUsage(u.summary || u);
  } catch (_) {}
  try {
    const o = await EA.api("GET", `/api/tasks/${tid}/outputs`);
    const arr = Array.isArray(o) ? o : (o.outputs || []);
    const oEl = $("ctx-outputs");
    if (oEl) {
      oEl.innerHTML = arr.map((f) => {
        // f 可能是对象 {path,size,mtime} 或字符串
        const name = typeof f === "string" ? f : (f.path || f.relpath || f.name || String(f));
        const size = typeof f === "object" && f.size != null ? ` <span style="color:var(--text-3)">${EA.fmtSize(f.size)}</span>` : "";
        return `<div class="pitem"><svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/></svg>${EA.esc(name)}${size}</div>`;
      }).join("") || '<div style="font-size:12px;color:var(--text-3)">暂无产物</div>';
    }
  } catch (_) {}
}

/* H4 子代理实时操控（对齐 Hermes subagent steering）— v1.2 对话区状态条 */
EA._subTimer = null;
EA._subDraft = {};
function EA_subEnsureBar() {
  let bar = document.getElementById("ea-sub-bar");
  if (bar) return bar;
  const inputbar = document.querySelector("#v-chat .inputbar");
  if (!inputbar) return null;
  bar = document.createElement("div");
  bar.id = "ea-sub-bar";
  bar.style.cssText = "display:none;padding:4px 20px;max-height:120px;overflow:auto";
  inputbar.parentNode.insertBefore(bar, inputbar);
  return bar;
}
async function EA_subPoll() {
  const bar = EA_subEnsureBar();
  if (!bar) return;
  let run = [];
  try { const r = await EA.api("GET", "/api/v2/subagent/running"); run = r.running || []; } catch (_) {}
  if (!run.length) { bar.style.display = "none"; return; }
  bar.style.display = "block";
  bar.innerHTML = `<div style="font-size:11px;color:var(--text-2);margin-bottom:4px"><b>子代理运行中</b></div>` +
    run.map((s) => {
      const showInp = EA._subDraft.sid === s.id;
      return `<div style="border:1px solid var(--border);border-radius:6px;padding:6px 8px;margin-bottom:4px">
        <span class="tag blue">${EA.esc(s.name)}</span>
        <span style="font-size:11px;color:var(--text-3);margin-left:6px">${EA.esc(s.role)} · 第 ${s.round} 轮</span>
        <span style="float:right">
          <button class="btn sm" data-cty="steer" data-id="${s.id}">纠偏</button>
          <button class="btn sm danger" data-cty="stop" data-id="${s.id}">停止</button>
        </span>
        ${showInp ? `<input class="input" id="ea-sub-inp-${s.id}" placeholder="纠偏指令…" style="width:100%;margin-top:6px;font-size:12px">
          <button class="btn sm pri" data-cty="send" data-id="${s.id}" style="margin-top:4px">发送</button>` : ""}
      </div>`;
    }).join("");
  bar.querySelectorAll("[data-cty]").forEach((b) => {
    b.onclick = async () => {
      const id = b.dataset.id, a = b.dataset.cty;
      try {
        if (a === "steer") { EA._subDraft = { sid: id }; EA_subPoll(); return; }
        if (a === "send") {
          const inp = document.getElementById("ea-sub-inp-" + id);
          const txt = (inp && inp.value || "").trim();
          if (!txt) return EA.toast("请填写纠偏指令");
          await EA.api("POST", `/api/v2/subagent/${id}/steer`, { instruction: txt });
          EA._subDraft = {}; EA.toast("纠偏已发送"); EA_subPoll(); return;
        }
        if (a === "stop") {
          await EA.api("POST", `/api/v2/subagent/${id}/stop`);
          EA._subDraft = {}; EA.toast("已请求停止"); setTimeout(EA_subPoll, 1000); return;
        }
      } catch (e) { EA.toast(e.message); }
    };
  });
}
function EA_subStart() { if (!EA._subTimer) EA._subTimer = setInterval(EA_subPoll, 1500); EA_subPoll(); }
function EA_subStop() { if (EA._subTimer) { clearInterval(EA._subTimer); EA._subTimer = null; } }
// 在 sendMessage 派生子代理工具后启动轮询（tool_start 事件 name 含子代理）
const _origHandle = typeof handleSSE === "function" ? handleSSE : null;
if (typeof handleSSE === "function") {
  const _prev = handleSSE;
  handleSSE = function (ev, ...rest) {
    if (ev && ev.event === "tool_start" && (ev.name === "spawn_subagent" || (ev.name || "").includes("子代理"))) {
      EA_subStart();
    }
    return _prev.apply(this, [ev, ...rest]);
  };
}
