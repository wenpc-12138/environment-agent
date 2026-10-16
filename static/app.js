/* 生态Agent 前端逻辑 */
"use strict";

const $ = (s) => document.querySelector(s);
const state = {
  tasks: [],
  currentTask: null,
  mode: "craft",
  providers: [],
  streaming: false,
  controller: null,
  currentAssistant: null,
  currentToolCards: [],
  lastUsage: null,
  meta: null,
  kbCat: null,
  attachments: [],
  selectSeq: 0,        // 任务切换竞态守卫:递增序号,过期请求丢弃
  streamTaskId: null,  // 当前流式请求所属任务,用于 SSE 事件归属校验
  usagePanelTimer: null, // 实时 usage(live)事件的面板刷新节流定时器
  outTaskId: null,       // 当前打开输出文件夹面板的任务 id
};
// 消息流中完整显示思考过程与工具调用轨迹(知识检索/网络查找/知识入库等)
const SHOW_TOOL_TRACE = true;
// 工具中文名映射
const TOOL_CN = {
  kb_lookup: "知识检索", kb_hybrid: "知识检索(多路)", kb_vector: "语义检索", locate: "条目定位",
  kb_stats: "知识库统计", kb_correct: "知识库纠错", kb_relation: "知识关系", kb_import: "批量导入",
  kb_audit: "知识审计", kb_harvest: "对话收割", kb_export: "知识导出", kb_backup: "知识备份",
  kb_save: "知识入库", web_search: "网络查找", web_fetch: "网页抓取",
  memory_set: "记忆存储", memory_get: "记忆读取",
};
// 工具分类色: kb=知识检索(绿), save=知识入库(绿), web=网络查找(蓝), mem=记忆(紫)
const TOOL_KIND = {
  kb_lookup: "kb", kb_hybrid: "kb", kb_vector: "kb", locate: "kb", kb_stats: "kb", kb_correct: "kb",
  kb_relation: "kb", kb_import: "kb", kb_audit: "kb", kb_harvest: "kb", kb_export: "kb", kb_backup: "kb",
  kb_save: "save", web_search: "web", web_fetch: "web", memory_set: "mem", memory_get: "mem",
};
// 核心链路工具(知识检索/网络查找/知识入库)默认展开详情, 辅助工具默认收起
const TOOL_OPEN = new Set(["kb_lookup", "kb_hybrid", "kb_vector", "kb_save", "kb_import", "kb_harvest", "web_search", "web_fetch"]);

/* ---------- 工具 ---------- */
function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function toast(msg, ms = 2600) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), ms);
}

/* ---------- 通用 UI 对话框(替代 prompt/confirm) ---------- */
function uiDialog(opts) {
  return new Promise((resolve) => {
    const dlg = $("#ui-dialog");
    const title = dlg.querySelector(".dlg-title");
    const msg = dlg.querySelector(".dlg-msg");
    const input = dlg.querySelector(".dlg-input");
    const ok = dlg.querySelector(".dlg-ok");
    const cancel = dlg.querySelector(".dlg-cancel");
    title.textContent = opts.title || "";
    if (opts.message) { msg.textContent = opts.message; msg.classList.remove("hidden"); }
    else msg.classList.add("hidden");
    if (opts.input) {
      input.classList.remove("hidden");
      input.value = opts.value || "";
      input.placeholder = opts.placeholder || "";
    } else input.classList.add("hidden");
    ok.textContent = opts.okText || "确定";
    cancel.textContent = opts.cancelText || "取消";
    cancel.classList.toggle("hidden", opts.cancel === false);
    ok.classList.toggle("primary", !opts.danger);
    ok.classList.toggle("danger", !!opts.danger);
    dlg.classList.remove("hidden");
    let done = false;
    const onKey = (e) => {
      if (e.key === "Enter") {
        if (opts.input) {
          if (String(input.value).trim()) ok.click();
          else input.focus();
        } else ok.click();
      } else if (e.key === "Escape") finish(null);
    };
    const finish = (val) => {
      if (done) return;
      done = true;
      document.removeEventListener("keydown", onKey);
      dlg.classList.add("hidden");
      resolve(val);
    };
    ok.onclick = () => {
      if (opts.input && !String(input.value).trim()) { input.focus(); return; }
      finish(opts.input ? input.value : true);
    };
    cancel.onclick = () => finish(null);
    dlg.onclick = (e) => { if (e.target === dlg) finish(null); };
    document.addEventListener("keydown", onKey);
    if (opts.input) { input.focus(); input.select(); }
  });
}
async function api(path, opts = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || data.detail || `HTTP ${resp.status}`);
  return data;
}
const catLabel = { network: "网络资料", gov: "政府发布", standard: "标准规范", policy: "政策法规", draft: "征求意见稿", other: "其他", file: "本地文件" };

/* ---------- 自定义下拉(适配界面风格) ---------- */
function buildCSelect(holder, opts = {}) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "cselect-btn";
  btn.innerHTML = '<span class="cselect-label"></span><span class="cselect-caret"></span>';
  const menu = document.createElement("div");
  menu.className = "cselect-menu hidden";
  const list = document.createElement("ul");
  list.className = "cselect-list";
  menu.appendChild(list);
  if (opts.footer) {
    const foot = document.createElement("button");
    foot.type = "button";
    foot.className = "cselect-foot";
    foot.textContent = opts.footer;
    foot.addEventListener("click", (e) => {
      e.stopPropagation();
      close();
      if (opts.footerClick) opts.footerClick();
    });
    menu.appendChild(foot);
  }
  holder.classList.add("cselect");
  holder.appendChild(btn);
  holder.appendChild(menu);

  const labelEl = btn.querySelector(".cselect-label");
  let options = opts.options || [];
  let value = opts.value !== undefined ? opts.value : (options[0]?.value ?? "");
  let placeholder = opts.placeholder || "选择...";

  function current() { return options.find((o) => o.value === value); }
  function render() {
    const c = current();
    labelEl.textContent = c ? c.label : placeholder;
    btn.title = c?.title || "";
  }
  function renderList() {
    list.innerHTML = "";
    options.forEach((o) => {
      const li = document.createElement("li");
      li.className = "cselect-opt" + (o.value === value ? " active" : "");
      if (o.html) li.innerHTML = o.html;
      else li.textContent = o.label;
      if (o.title) li.title = o.title;
      if (o.onDel) {
        li.classList.add("has-del");
        const del = document.createElement("button");
        del.className = "opt-del";
        del.textContent = "删除";
        del.title = "删除该技能";
        del.addEventListener("click", (e) => {
          e.stopPropagation();
          o.onDel();
        });
        li.appendChild(del);
      }
      li.addEventListener("click", (e) => {
        e.stopPropagation();
        setValue(o.value);
        close();
      });
      list.appendChild(li);
    });
  }
  function close() { menu.classList.add("hidden"); menu.classList.remove("open"); }
  function open() {
    document.querySelectorAll(".cselect-menu.open").forEach((m) => {
      if (m !== menu) { m.classList.add("hidden"); m.classList.remove("open"); }
    });
    renderList();
    menu.classList.remove("hidden");
    menu.classList.add("open");
    // 统一上弹:菜单始终在按钮上方弹出
    menu.classList.add("up");
  }
  function toggle() { if (menu.classList.contains("open")) close(); else open(); }
  function setValue(v, silent = false) {
    if (value === v) { render(); return; }
    value = v;
    render();
    if (!silent) {
      if (opts.onChange) opts.onChange(v);
      holder.dispatchEvent(new CustomEvent("change", { bubbles: true }));
    }
  }
  btn.addEventListener("click", (e) => { e.stopPropagation(); toggle(); });
  holder._cselectClose = close;

  Object.defineProperty(holder, "value", { get: () => value, set: (v) => setValue(v, true) });
  holder.setOptions = (arr, keep = true) => {
    options = arr || [];
    if (!options.some((o) => o.value === value)) value = options.length ? options[0].value : "";
    render();
  };
  holder.placeholder = (t) => { placeholder = t; render(); };
  render();
  return holder;
}
document.addEventListener("click", (e) => {
  document.querySelectorAll(".cselect-menu.open").forEach((m) => { m.classList.add("hidden"); m.classList.remove("open"); });
  const ue = document.getElementById("usage-expand");
  if (ue && !ue.classList.contains("hidden") && !e.target.closest("#btn-usage") && !ue.contains(e.target)) {
    ue.classList.add("hidden");
  }
});

/* ---------- 模式 / 推理 / 模型候选 ---------- */
const MODE_OPTS = [
  { value: "craft", label: "craft" },
  { value: "ask", label: "ask" },
  { value: "plan", label: "plan" },
];
const REASONING_OPTS = [
  { value: "off", label: "off" },
  { value: "low", label: "low" },
  { value: "high", label: "high" },
  { value: "xhigh", label: "xhigh" },
  { value: "max", label: "max" },
];
const REASONING_LABEL = Object.fromEntries(REASONING_OPTS.map((o) => [o.value, o.label]));
function isDeepSeek(p) {
  return /deepseek/i.test((p.base_url || "") + " " + (p.model || ""));
}
function initCSelects() {
  buildCSelect($("#provider-select"), {
    options: [], placeholder: "未配置模型",
    footer: "Provider 设置", footerClick: () => openModal(),
    onChange: () => onProviderChange(),
  });
  buildCSelect($("#reasoning-select"), { options: REASONING_OPTS, value: "high", onChange: (v) => onReasoningChange(v) });
  buildCSelect($("#mode-select"), { options: MODE_OPTS, value: state.mode, onChange: (v) => setMode(v) });
  buildCSelect($("#skill-select"), {
    options: [{ value: "", label: "未启用" }], value: "",
    footer: "快速添加 Skill", footerClick: () => openSkillAdd(),
    onChange: (k) => toggleSkillFromSelect(k),
  });
  buildCSelect($("#pf-kind"), { options: [{ value: "openai", label: "OpenAI 兼容" }, { value: "mock", label: "演示模式" }], value: "openai" });
  buildCSelect($("#pf-reasoning"), { options: REASONING_OPTS, value: "high" });
  buildCSelect($("#kb-add-cat"), {
    options: [
      { value: "network", label: "网络资料" },
      { value: "gov", label: "政府发布" },
      { value: "standard", label: "标准规范" },
      { value: "policy", label: "政策法规" },
      { value: "draft", label: "征求意见稿" },
      { value: "other", label: "其他" },
    ],
    value: "network",
  });
}

/* ---------- 联网搜索状态(launcher mode/port/pid) ---------- */
const SRCH_MODE_LABEL = {
  managed: "托管运行", external: "外部实例", remote: "远程地址",
  idle: "空闲", disabled: "已禁用", not_installed: "未安装",
  error: "错误", searching: "搜索中",
};
const SRCH_MODE_CLASS = {
  managed: "cat-standard", external: "cat-gov", remote: "cat-policy",
  error: "cat-network", idle: "cat-other", disabled: "cat-other", not_installed: "cat-other",
};
async function loadSearchStatus() {
  try {
    const s = await api("/api/search/status");
    const l = s.launcher || {};
    const mode = l.mode || "idle";
    const tag = $("#srch-mode");
    tag.textContent = SRCH_MODE_LABEL[mode] || mode;
    tag.className = "cat-tag " + (SRCH_MODE_CLASS[mode] || "cat-other");
    $("#srch-ready").textContent = l.ready ? "[READY]" : "[NOT READY]";
    $("#srch-url").textContent = l.url
      ? l.url + (l.port ? " :" + l.port : "")
      : (l.port ? "127.0.0.1:" + l.port : "-");
    $("#srch-pid").textContent = l.pid || "-";
    $("#srch-err").textContent = l.last_err || "-";
  } catch (e) {
    $("#srch-mode").textContent = "不可用";
    $("#srch-ready").textContent = "[--]";
  }
}
async function restartSearXNG() {
  const btn = $("#btn-srch-restart");
  btn.disabled = true;
  btn.textContent = "重启中...";
  try {
    const r = await api("/api/search/restart", { method: "POST" });
    toast(r.ok ? "SearXNG 已重启" : ("重启失败: " + (r.detail || "未知错误")));
    await loadSearchStatus();
  } catch (e) {
    toast("重启失败: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "重启 SearXNG";
  }
}

/* ---------- 初始化 ---------- */
async function init() {
  try {
    state.meta = await api("/api/meta");
  } catch (e) { console.warn(e); }
  initCSelects();
  initTaskFilter();
  await Promise.all([loadProviders(), loadTasks(), loadSkills(), loadStats(), loadSearchStatus(), loadKbStats(), loadKb()]);
  bindEvents();
  // 打开界面默认开始新任务(无需手动新建):
  // 最新任务为空会话则直接复用(体验等同新任务, 避免刷新堆积空任务), 否则自动创建一个新任务。
  if (state.tasks.length === 0) {
    await createTask(true);
  } else {
    const top = state.tasks[0];
    if ((top.msg_count || 0) === 0) selectTask(top.id);
    else await createTask(true);
  }
  loadBudget();
}

/* ---------- 任务 ---------- */
function taskType(title) {
  if (/监测|检测|采样|点位/.test(title)) return "监测";
  if (/报告|编制|审核/.test(title)) return "报告";
  if (/合规|标准|法规/.test(title)) return "合规";
  return "起草";
}
function taskDay(ts) {
  if (!ts) return "更早";
  const d = new Date(ts.replace(" ", "T"));
  if (isNaN(d)) return "更早";
  const now = new Date();
  const y = new Date(); y.setDate(now.getDate() - 1);
  const today = d.toDateString() === now.toDateString();
  const yest = d.toDateString() === y.toDateString();
  return today ? "今天" : (yest ? "昨天" : "更早");
}
async function loadTasks() {
  state.tasks = await api("/api/tasks");
  const ul = $("#task-list");
  ul.innerHTML = "";
  const q = ($("#task-q") && $("#task-q").value.trim()) || "";
  const f = (document.querySelector("#task-filter .chip.active") || {}).dataset?.f || "all";
  const visible = state.tasks.filter((t) => {
    if (f !== "all" && taskType(t.title || "") !== f) return false;
    if (q && !(t.title || "").toLowerCase().includes(q.toLowerCase())) return false;
    return true;
  });
  const countEl = $("#task-count");
  if (countEl) countEl.textContent = visible.length;
  const groups = { 今天: [], 昨天: [], 更早: [] };
  visible.forEach((t) => groups[taskDay(t.updated_at || t.created_at)].push(t));
  ["今天", "昨天", "更早"].forEach((g) => {
    if (!groups[g].length) return;
    const gh = document.createElement("div");
    gh.className = "task-group";
    gh.textContent = g;
    ul.appendChild(gh);
    groups[g].forEach((t) => {
      const li = document.createElement("li");
      li.dataset.id = t.id;
      const tp = taskType(t.title || "");
      li.innerHTML = `
        <button class="task-out" title="输出文件夹">..</button>
        <button class="task-del" title="删除任务">x</button>
        <div class="task-title" title="双击重命名">${esc(t.title)}</div>
        <div class="task-meta">
          <span class="task-type" data-t="${tp}">${tp}</span>
          <span>${t.mode}</span><span>${t.reply_count || 0} 条回复</span>
          <span>${esc((t.updated_at || "").slice(5, 16))}</span>
        </div>`;
      if (state.currentTask && String(t.id) === String(state.currentTask.id)) li.classList.add("active");
      ul.appendChild(li);
    });
  });
  if (!visible.length) {
    const empty = document.createElement("div");
    empty.className = "task-empty dim";
    empty.textContent = "无匹配任务";
    ul.appendChild(empty);
  }
}
function initTaskFilter() {
  const q = $("#task-q");
  if (q) q.addEventListener("input", () => loadTasks());
  const box = $("#task-filter");
  if (box) box.addEventListener("click", (ev) => {
    const b = ev.target.closest(".chip");
    if (!b) return;
    box.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
    b.classList.add("active");
    loadTasks();
  });
}
async function createTask(auto = false) {
  let title = "新任务";
  if (!auto) {
    const name = await uiDialog({ title: "新建任务", input: true, placeholder: "新任务名称", value: "新任务", okText: "创建" });
    if (name === null) return;
    title = String(name).trim() || "新任务";
  }
  const data = await api("/api/tasks", { method: "POST", body: JSON.stringify({ title, mode: state.mode }) });
  await loadTasks();
  selectTask(data.id);
}
async function selectTask(id) {
  const seq = ++state.selectSeq;
  state.currentTask = state.tasks.find((t) => String(t.id) === String(id)) || null;
  if (!state.currentTask) return;
  // 流式生成中切换到其他任务:停止旧任务生成,避免后台流污染新任务界面
  if (state.streaming && String(state.streamTaskId) !== String(id)) {
    stopChat();
  }
  await loadTasks();
  const data = await api(`/api/tasks/${id}`);
  if (seq !== state.selectSeq) return; // 已被更新的切换覆盖,丢弃过期结果
  setMode(data.task.mode || "craft", false); // 切任务不写回, 模式本就在库中
  renderMessages(data.messages);
  loadBudget();
  if (state.usagePanelTimer) {
    clearTimeout(state.usagePanelTimer);
    state.usagePanelTimer = null;
  }
  loadTaskUsage(true); // 切任务刷新按钮累计 token 与面板(当前任务统计)
}
async function deleteTask(id) {
  const ok = await uiDialog({ title: "删除任务", message: "确定删除该任务及全部消息?", danger: true });
  if (!ok) return;
  await api(`/api/tasks/${id}`, { method: "DELETE" });
  state.tasks = await api("/api/tasks");
  // 没有任务时默认开始新任务, 无需手动新建
  if (state.tasks.length === 0) await createTask(true);
  else selectTask(state.tasks[0].id);
  loadTasks();
}

/* ---------- 任务输出文件夹 ---------- */
async function openOutputPanel(tid) {
  state.outTaskId = tid;
  const filesEl = $("#out-files");
  const preview = $("#out-preview");
  filesEl.innerHTML = '<div class="out-empty">加载中...</div>';
  preview.innerHTML = '<div class="out-preview-tip">点击左侧文件查看内容</div>';
  const sub = $("#out-sub");
  const task = state.tasks.find((t) => String(t.id) === String(tid));
  sub.textContent = task ? `#${tid} ${task.title}` : `#${tid}`;
  $("#out-panel").classList.remove("hidden");
  let files;
  try {
    files = await api(`/api/tasks/${tid}/outputs`);
  } catch (e) {
    filesEl.innerHTML = '<div class="out-empty">读取失败</div>';
    return;
  }
  if (state.outTaskId !== String(tid)) return;
  filesEl.innerHTML = "";
  if (!files.length) {
    filesEl.innerHTML = '<div class="out-empty">暂无输出文件</div>';
    return;
  }
  files.forEach((f) => {
    const item = document.createElement("div");
    item.className = "out-file-item";
    item.dataset.path = f.path;
    const size = f.size >= 1024 ? `${(f.size / 1024).toFixed(1)} KB` : `${f.size} B`;
    const d = new Date(f.mtime * 1000);
    const ts = `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    item.innerHTML = `<div class="out-file-name">${esc(f.path)}</div><div class="out-file-meta">${size} / ${ts}</div>`;
    item.onclick = () => viewOutputFile(tid, f.path, item);
    filesEl.appendChild(item);
  });
}
function closeOutputPanel() {
  state.outTaskId = null;
  $("#out-panel").classList.add("hidden");
}
async function viewOutputFile(tid, path, item) {
  document.querySelectorAll(".out-file-item").forEach((x) => x.classList.remove("active"));
  if (item) item.classList.add("active");
  const preview = $("#out-preview");
  preview.innerHTML = '<div class="out-preview-tip">加载中...</div>';
  try {
    const data = await api(`/api/tasks/${tid}/outputs/${encodeURIComponent(path)}`);
    preview.innerHTML = "";
    const pre = document.createElement("pre");
    pre.className = "out-preview-pre";
    pre.textContent = data.content || "(空文件)";
    preview.appendChild(pre);
  } catch (e) {
    preview.innerHTML = '<div class="out-preview-tip">读取失败</div>';
  }
}

/* ---------- 消息渲染 ---------- */
function msgEl(role) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  const main = document.createElement("div");
  main.className = "msg-main";
  const body = document.createElement("div");
  body.className = "msg-body";
  const text = document.createElement("div");
  text.className = "msg-text";
  body.appendChild(text);
  if (role === "assistant") {
    const av = document.createElement("div");
    av.className = "avatar";
    av.title = "Environment Agent";
    wrap.appendChild(av);
    const name = document.createElement("div");
    name.className = "msg-name";
    name.textContent = "Environment Agent";
    main.appendChild(name);
  }
  main.appendChild(body);
  wrap.appendChild(main);
  return { wrap, body, text };
}
function thinkBlock(content) {
  const blk = document.createElement("div");
  blk.className = "think-block";
  const head = document.createElement("div");
  head.className = "think-head";
  const label = document.createElement("span");
  label.textContent = "深度思考";
  const mark = document.createElement("span");
  mark.className = "think-mark";
  mark.textContent = "[-]";
  head.appendChild(label);
  head.appendChild(mark);
  const box = document.createElement("div");
  box.className = "think-content";
  // 思考文本与工具执行记录按时间顺序合并存放于同一折叠块内
  const txt = document.createElement("div");
  txt.className = "think-text";
  txt.textContent = content || "";
  box.appendChild(txt);
  const applyMark = () => {
    mark.textContent = box.style.display === "none" ? "[+]" : "[-]";
  };
  head.addEventListener("click", () => {
    box.style.display = box.style.display === "none" ? "" : "none";
    applyMark();
  });
  blk.appendChild(head);
  blk.appendChild(box);
  return blk;
}
/* Markdown 渲染: assistant 消息经 Vditor 渲染, 表格/代码/列表等正常显示 */
function renderMd(el, md) {
  const src = md || "";
  if (!window.Vditor || !Vditor.preview) { el.textContent = src; return; }
  el.innerHTML = "";
  if (!src.trim()) return;
  Vditor.preview(el, src, {
    cdn: "/static/vditor",
    mode: "light",
    lang: "zh_CN",
    hljs: { style: "github", lineNumber: false },
  });
}
function appendMd(el, md) {
  el.dataset.md = (el.dataset.md || "") + (md || "");
  renderMd(el, el.dataset.md);
}
function renderMessages(msgs) {
  const list = $("#msg-list");
  list.innerHTML = "";
  const arr = (msgs || []).filter((m) => m.role !== "tool");
  if (arr.length === 0) {
    // 空任务显示欢迎界面
    const w = document.createElement("div");
    w.className = "welcome";
    w.innerHTML = '<img src="/static/environment-agent.png" alt="Environment Agent" class="welcome-ico"><div class="welcome-text">欢迎使用 Environment Agent，请问有什么可以帮到你</div>';
    list.appendChild(w);
    _followBottom = true;
    return;
  }
  for (const m of arr) {
    if (m.role === "tool") continue;
    const { wrap, body, text } = msgEl(m.role);
    if (m.role === "assistant") {
      try {
        const meta = JSON.parse(m.meta || "{}");
        const traces = (meta.tool_trace || []).filter((t) => t && t.name);
        // 深度思考块: 思考文本 + 工具执行记录(按时间顺序)合并, 不再单独显示工具卡片
        if (meta.reasoning || (SHOW_TOOL_TRACE && traces.length)) {
          const blk = thinkBlock(meta.reasoning || "");
          body.insertBefore(blk, body.firstChild);
          if (SHOW_TOOL_TRACE && traces.length) {
            const box = blk.querySelector(".think-content");
            traces.forEach((t) => box.appendChild(toolCard(t.name, t.ok, t.output, !TOOL_OPEN.has(t.name), t.args)));
          }
        }
      } catch (e) {}
      renderMd(text, m.content);
    } else {
      text.textContent = m.content || "";
    }
    list.appendChild(wrap);
  }
  _followBottom = true;
  list.scrollTop = list.scrollHeight;
}
function toolCard(name, ok, output, collapsed, argsText) {
  const card = document.createElement("div");
  card.className = "tool-card";
  const head = document.createElement("div");
  head.className = "tool-head";
  const nm = document.createElement("span");
  nm.className = "tool-name tool-" + (TOOL_KIND[name] || "kb");
  nm.textContent = TOOL_CN[name] || name;
  nm.title = name; // 悬停显示原始工具名
  const st = document.createElement("span");
  st.className = "tool-status " + (ok ? "ok" : "fail");
  st.textContent = ok ? "[OK]" : "[FAIL]";
  const args = document.createElement("span");
  args.className = "tool-args";
  args.textContent = argsText || "";
  args.title = argsText || "";
  const fold = document.createElement("span");
  fold.className = "tool-fold";
  head.appendChild(nm);
  head.appendChild(st);
  head.appendChild(args);
  head.appendChild(fold);
  const out = document.createElement("div");
  out.className = "tool-out";
  out.textContent = output || "";
  const applyFold = () => {
    fold.textContent = out.style.display === "none" ? "[+]" : "[-]";
  };
  if (collapsed) out.style.display = "none";
  applyFold();
  head.addEventListener("click", () => {
    out.style.display = out.style.display === "none" ? "" : "none";
    applyFold();
  });
  card.appendChild(head);
  card.appendChild(out);
  return card;
}

/* ---------- 附件(文件拖入) ---------- */
const TEXT_EXT = /\.(txt|md|markdown|csv|json|js|ts|py|html|htm|xml|yaml|yml|log|ini|conf|sh|bat|css|sql|env)$/i;
const IMG_EXT = /\.(png|jpe?g|webp|bmp|tiff?)$/i;
function uploadPathToUrl(path) {
  // 上传绝对路径 -> /uploads/<文件名> 静态访问（图片缩略图）
  try { return "/uploads/" + encodeURIComponent(path.split(/[\\/]/).pop()); }
  catch (e) { return ""; }
}
async function uploadAttachment(f) {
  const fd = new FormData();
  fd.append("file", f);
  const r = await fetch("/api/upload", { method: "POST", body: fd });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || !j.path) throw new Error(j.error || "上传失败");
  return j.path;
}
async function attachFiles(files) {
  if (!state.attachments) state.attachments = [];
  let added = 0;
  for (const f of files) {
    const item = { name: f.name, size: f.size };
    if (IMG_EXT.test(f.name)) {
      // G6 图片附件: 上传后展示缩略图, 后端 chat 自动视觉理解注入
      try {
        item.path = await uploadAttachment(f);
        item.isImage = true;
        state.attachments.push(item);
        added++;
      } catch (e) {
        toast("图片上传失败: " + f.name + " (" + e.message + ")");
      }
    } else if (TEXT_EXT.test(f.name) && f.size < 100000) {
      // 小文本文件: 直接读文本内容随消息发送
      try {
        item.text = (await f.text()).slice(0, 20000);
      } catch (e) {
        item.text = "";
      }
      state.attachments.push(item);
      added++;
    } else {
      // 非文本(如 PDF/DOCX)或超大文本: 上传到服务端保存, 由后端解析(含扫描件 OCR), 避免二进制乱码
      try {
        item.path = await uploadAttachment(f);
        state.attachments.push(item);
        added++;
      } catch (e) {
        toast("附件上传失败: " + f.name + " (" + e.message + ")");
      }
    }
  }
  renderAttachments();
  if (added) toast("已添加附件 " + added + " 个");
}
function renderAttachments() {
  const row = $("#attach-row");
  row.innerHTML = "";
  if (!state.attachments?.length) { row.classList.add("hidden"); return; }
  row.classList.remove("hidden");
  state.attachments.forEach((a, i) => {
    const chip = document.createElement("div");
    chip.className = "attach-chip" + (a.isImage ? " attach-img" : "");
    const thumb = a.isImage && a.path
      ? `<img class="attach-thumb" src="${uploadPathToUrl(a.path)}" alt="" onclick="window.open('${uploadPathToUrl(a.path)}','_blank')">`
      : "";
    chip.innerHTML = `
      ${thumb}
      <span class="attach-name">${esc(a.name)}</span>
      <span class="attach-meta">${(a.size / 1024).toFixed(1)}KB</span>
      <button class="attach-del" data-i="${i}">x</button>`;
    chip.querySelector(".attach-del").onclick = () => {
      state.attachments.splice(i, 1);
      renderAttachments();
    };
    row.appendChild(chip);
  });
}

/* ---------- 发送与流式 ---------- */
async function sendMessage() {
  const input = $("#input");
  let content = input.value.trim();
  const attachments = state.attachments || [];
  if (attachments.length) {
    const parts = attachments.map((a) => a.path
      ? `[附件: ${a.name} 已保存到 ${a.path}]`
      : `[附件: ${a.name}]${a.text ? "\n" + a.text : ""}`).join("\n\n");
    content = (parts + "\n\n" + content).trim();
  }
  if (!content || state.streaming || !state.currentTask) return;
  // 新任务自动以本次提问命名（仅当任务仍为默认标题"新任务"时）
  if (state.currentTask.title === "新任务") {
    const q = (input.value.trim() || content).replace(/\s+/g, " ").trim();
    const title = q.length > 40 ? q.slice(0, 40) + "…" : q;
    if (title) {
      state.currentTask.title = title;
      api(`/api/tasks/${state.currentTask.id}`, { method: "PATCH", body: JSON.stringify({ title }) })
        .then(() => loadTasks())
        .catch(() => {});
    }
  }
  tryRemember(content); // 用户说"记住 XX"时自动写入任务记忆
  input.value = "";
  state.attachments = [];
  renderAttachments();
  // 发送后移除欢迎占位
  const _wel = $("#msg-list .welcome");
  if (_wel) _wel.remove();
  const { wrap, text } = msgEl("user");
  text.textContent = content;
  $("#msg-list").appendChild(wrap);
  _followBottom = true;
  scrollBottom();

  // 创建助手消息容器
  const aw = msgEl("assistant");
  $("#msg-list").appendChild(aw.wrap);
  state.currentAssistant = aw;
  state.currentToolCards = [];
  state.streamTaskId = state.currentTask.id;
  state.streaming = true;
  setBusy(true);
  state.controller = new AbortController();
  try {
    const resp = await fetch(`/api/tasks/${state.currentTask.id}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, mode: state.mode }),
      signal: state.controller.signal,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || "请求失败");
    }
    await readSSE(resp);
  } catch (e) {
    if (e.name !== "AbortError") {
      appendMd(aw.text, "\n[!] 发生错误: " + e.message);
    }
  } finally {
    state.streaming = false;
    setBusy(false);
    if (aw.text.textContent) aw.text.classList.remove("cursor");
    else aw.wrap.remove();
    loadTasks();
    loadBudget();
    loadStats();
  }
}
async function readSSE(resp) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      for (const line of frame.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        let d;
        try { d = JSON.parse(line.slice(6)); } catch (e) { continue; }
        handleEvent(d);
      }
    }
  }
}
function handleEvent(d) {
  // SSE 事件归属校验:事件必须属于当前展示的任务,防止后台任务流污染界面
  if (state.streamTaskId && state.currentTask && String(state.streamTaskId) !== String(state.currentTask.id)) return;
  const ev = d.event;
  // 知识库已变化(写库工具执行成功): 实时刷新知识库面板, 无需手动刷新页面
  if (ev === "kb_changed") { refreshKbOnChange(); return; }
  if (ev === "delta" && state.currentAssistant) {
    const a = state.currentAssistant;
    a.text.classList.add("cursor");
    appendMd(a.text, d.content);
    scrollBottom();
  } else if (ev === "reasoning" && state.currentAssistant) {
    const a = state.currentAssistant;
    if (!a.thinkBox) {
      const blk = thinkBlock("");
      a.thinkBox = blk.querySelector(".think-text");
      a.thinkContent = blk.querySelector(".think-content");
      a.body.insertBefore(blk, a.body.firstChild);
    }
    a.thinkBox.textContent += d.content || "";
    // 深度思考块内滚动跟随: 用户处于底部时自动滚到最新
    const tb = a.thinkBox;
    if (tb.scrollHeight - tb.scrollTop - tb.clientHeight < 40) tb.scrollTop = tb.scrollHeight;
    scrollBottom();
  } else if (ev === "tool_start") {
    if (!state.currentAssistant || !SHOW_TOOL_TRACE) return;
    const a = state.currentAssistant;
    // 无 reasoning 时也建深度思考块作为工具记录容器
    if (!a.thinkContent) {
      const blk = thinkBlock("");
      a.thinkBox = blk.querySelector(".think-text");
      a.thinkContent = blk.querySelector(".think-content");
      a.body.insertBefore(blk, a.body.firstChild);
    }
    const card = toolCard(d.name || "tool", true, "", !TOOL_OPEN.has(d.name), d.args || "");
    const st = card.querySelector(".tool-status");
    st.textContent = "[运行中]";
    st.className = "tool-status run";
    a.thinkContent.appendChild(card);
    a.toolCards = a.toolCards || [];
    a.toolCards.push(card);
    scrollBottom();
  } else if (ev === "tool_end") {
    if (!SHOW_TOOL_TRACE) return;
    const a = state.currentAssistant;
    if (!a || !a.toolCards || !a.toolCards.length) return;
    const card = a.toolCards.pop();
    const st = card.querySelector(".tool-status");
    st.textContent = d.ok ? "[OK]" : "[FAIL]";
    st.className = "tool-status " + (d.ok ? "ok" : "fail");
    const out = card.querySelector(".tool-out");
    out.textContent = d.output || "";
    scrollBottom();
  } else if (ev === "budget") {
    renderBudgetBar(d);
  } else if (ev === "usage") {
    state.lastUsage = d;
    updateUsageBtn(d); // 按钮实时显示当前任务累计 token
    if (usageExpanded()) {
      if (d.live) {
        // 实时预估事件:节流刷新面板,避免高频拉取统计接口
        if (!state.usagePanelTimer) {
          state.usagePanelTimer = setTimeout(() => {
            state.usagePanelTimer = null;
            loadTaskUsage();
          }, 1500);
        }
      } else {
        // 最终精确值:立即刷新并取消挂起的节流刷新
        if (state.usagePanelTimer) {
          clearTimeout(state.usagePanelTimer);
          state.usagePanelTimer = null;
        }
        loadTaskUsage();
      }
    }
  } else if (ev === "assistant_done") {
    if (state.currentAssistant) state.currentAssistant.text.classList.remove("cursor");
  } else if (ev === "done") {
    if (state.currentAssistant) state.currentAssistant.text.classList.remove("cursor");
    // 流结束:取消挂起的节流刷新并拉取最终统计
    if (state.usagePanelTimer) {
      clearTimeout(state.usagePanelTimer);
      state.usagePanelTimer = null;
    }
    if (usageExpanded()) loadTaskUsage();
    // 兜底:确保知识库实时反映本次对话的全部落库
    refreshKbOnChange();
  } else if (ev === "error") {
    if (state.currentAssistant) {
      state.currentAssistant.text.classList.remove("cursor");
      appendMd(state.currentAssistant.text, "\n\n[!] " + (d.message || "未知错误"));
    } else {
      toast("[!] " + (d.message || "未知错误"));
    }
    // 停止/出错:同样取消挂起节流并刷新最终统计
    if (state.usagePanelTimer) {
      clearTimeout(state.usagePanelTimer);
      state.usagePanelTimer = null;
    }
    if (usageExpanded()) loadTaskUsage();
  }
}
let _followBottom = true;
function scrollBottom() {
  if (!_followBottom) return;
  const list = $("#msg-list");
  list.scrollTop = list.scrollHeight;
}
function setBusy(b) {
  const st = $("#top-status");
  if (st) {
    st.textContent = b ? "生成中..." : "空闲";
    st.className = "tb-chip " + (b ? "status-busy" : "status-idle");
  }
  $("#btn-send").disabled = b;
  $("#btn-stop").classList.toggle("hidden", !b);
}
function stopChat() {
  if (state.controller) state.controller.abort();
  const tid = state.streamTaskId || (state.currentTask && state.currentTask.id);
  if (tid) {
    api(`/api/tasks/${tid}/stop`, { method: "POST" }).catch(() => {});
  }
}

/* ---------- 模式 ---------- */
const MODE_CN = { craft: "craft", ask: "ask", plan: "plan" };
function setMode(mode, persist = true) {
  const changed = state.mode !== mode;
  state.mode = mode;
  const sel = $("#mode-select");
  if (sel && sel.value !== mode) sel.value = mode;
  const badge = $("#top-mode");
  if (badge) {
    badge.textContent = mode;
    badge.className = "tb-chip mode-" + mode;
  }
  const rp = $("#rp-mode");
  if (rp) { rp.textContent = MODE_CN[mode] || mode; rp.className = "mode-label mode-" + mode; }
  // 仅模式真实变化且需要持久化时才写库, 避免切换任务触发 PATCH 篡改任务排序
  if (persist && changed && state.currentTask) {
    api(`/api/tasks/${state.currentTask.id}`, { method: "PATCH", body: JSON.stringify({ mode }) }).catch(() => {});
  }
}

/* ---------- Provider ---------- */
async function loadProviders() {
  state.providers = await api("/api/providers");
  const sel = $("#provider-select");
  sel.setOptions(state.providers.map((p) => {
    const label = (p.name ? p.name + " " : "") + p.model;
    return {
      value: p.id,
      label: label,
      title: (p.name || "") + (p.base_url ? " | " + p.base_url : ""),
      html: '<b class="csel-name">' + esc(label) + '</b><span class="csel-desc">' + esc(p.base_url || p.kind) + "</span>",
    };
  }));
  const active = state.providers.find((p) => p.is_active) || null;
  if (active) sel.value = active.id;
  const tp = $("#top-provider");
  if (tp) {
    tp.textContent = active ? (active.name ? active.name + " " : "") + active.model : "未配置模型";
    if (active && active.kind === "mock") tp.textContent = "演示模式";
  }
  // 推理强度下拉:仅 DeepSeek 显示
  const rSel = $("#reasoning-select");
  if (active && isDeepSeek(active)) {
    rSel.value = active.reasoning_effort || "high";
    rSel.classList.remove("hidden");
  } else {
    rSel.classList.add("hidden");
  }
}
async function onProviderChange() {
  const pid = $("#provider-select").value;
  if (!pid) return;
  await api(`/api/providers/${pid}/activate`, { method: "POST" });
  await loadProviders();
  toast("已切换模型");
}
async function onReasoningChange(v) {
  const pid = $("#provider-select").value;
  const p = state.providers.find((x) => String(x.id) === String(pid));
  if (!p || !v) return;
  p.reasoning_effort = v;
  await saveProviderData(p);
  toast("推理强度: " + (REASONING_LABEL[v] || v));
}
async function saveProviderData(p) {
  const data = {
    id: p.id,
    name: p.name,
    kind: p.kind,
    model: p.model,
    base_url: p.base_url,
    api_key: p.api_key,
    reasoning_effort: p.reasoning_effort,
  };
  await api(`/api/providers/${p.id}`, { method: "PUT", body: JSON.stringify(data) });
  await loadProviders();
}

/* ---------- Provider 设置弹窗 ---------- */
function openModal() {
  $("#modal-overlay").classList.remove("hidden");
  renderProviderList();
  renderPresets();
  clearProviderForm();
}
function closeModal() {
  $("#modal-overlay").classList.add("hidden");
  loadProviders();
}
function renderProviderList() {
  const box = $("#provider-list");
  box.innerHTML = "";
  state.providers.forEach((p) => {
    const div = document.createElement("div");
    div.className = "p-item";
    div.innerHTML = `
      <div class="p-name">
        <b>${esc(p.name)}</b>
        <span>${esc(p.kind)} | ${esc(p.model)} | ${esc(p.base_url || "-")} | key:${p.api_key ? "已设置" : "未设置"}</span>
      </div>
      <span class="p-active">${p.is_active ? "[ACTIVE]" : ""}</span>
      <div class="p-actions">
        <button data-act>激活</button>
        <button data-edit>编辑</button>
        <button data-del>删除</button>
      </div>`;
    div.querySelector("[data-act]").onclick = async () => {
      await api(`/api/providers/${p.id}/activate`, { method: "POST" });
      renderProviderList();
    };
    div.querySelector("[data-edit]").onclick = () => fillProviderForm(p);
    div.querySelector("[data-del]").onclick = async () => {
      const ok = await uiDialog({ title: "删除 Provider", message: "确定删除该 Provider?", danger: true });
      if (!ok) return;
      await api(`/api/providers/${p.id}`, { method: "DELETE" });
      state.providers = await api("/api/providers");
      renderProviderList();
    };
    box.appendChild(div);
  });
}
function clearProviderForm() {
  $("#pf-id").value = "";
  $("#pf-name").value = "";
  $("#pf-kind").value = "openai";
  $("#pf-reasoning").value = "high";
  $("#pf-model").value = "";
  $("#pf-base").value = "";
  $("#pf-key").value = "";
  $("#pf-result").textContent = "";
}
function fillProviderForm(p) {
  $("#pf-id").value = p.id;
  $("#pf-name").value = p.name;
  $("#pf-kind").value = p.kind;
  $("#pf-reasoning").value = p.reasoning_effort || "high";
  $("#pf-model").value = p.model;
  $("#pf-base").value = p.base_url || "";
  $("#pf-key").value = p.api_key || "";
  $("#pf-result").textContent = "";
}
function renderPresets() {
  const row = $("#preset-row");
  row.innerHTML = "";
  (state.meta?.presets || []).forEach((p) => {
    const b = document.createElement("button");
    b.className = "preset-chip";
    b.textContent = p.name;
    b.title = p.desc;
    b.onclick = () => {
      $("#pf-name").value = p.name;
      $("#pf-model").value = p.model;
      $("#pf-base").value = p.base_url;
      $("#pf-kind").value = "openai";
    };
    row.appendChild(b);
  });
}
async function saveProvider() {
  const data = {
    id: $("#pf-id").value || null,
    name: $("#pf-name").value.trim(),
    kind: $("#pf-kind").value,
    reasoning_effort: $("#pf-reasoning").value,
    model: $("#pf-model").value.trim(),
    base_url: $("#pf-base").value.trim(),
    api_key: $("#pf-key").value.trim(),
  };
  if (!data.name || !data.model) { toast("名称与模型必填"); return; }
  if (data.id) await api(`/api/providers/${data.id}`, { method: "PUT", body: JSON.stringify(data) });
  else await api("/api/providers", { method: "POST", body: JSON.stringify(data) });
  state.providers = await api("/api/providers");
  renderProviderList();
  clearProviderForm();
  toast("已保存");
}
async function testProvider() {
  const data = {
    kind: $("#pf-kind").value,
    model: $("#pf-model").value.trim(),
    base_url: $("#pf-base").value.trim(),
    api_key: $("#pf-key").value.trim(),
  };
  const out = $("#pf-result");
  out.textContent = "测试中...";
  try {
    const r = await api("/api/providers/test", { method: "POST", body: JSON.stringify(data) });
    out.textContent = (r.ok ? "[OK] " : "[FAIL] ") + (r.detail || "");
  } catch (e) {
    out.textContent = "[FAIL] " + e.message;
  }
}

/* ---------- 上下文 / 预算 ---------- */
async function loadBudget() {
  if (!state.currentTask) return;
  try {
    const b = await api(`/api/tasks/${state.currentTask.id}/budget`);
    const ctxTokens = $("#ctx-tokens");
    const ctxSoft = $("#ctx-soft");
    const ctxHard = $("#ctx-hard");
    const ctxKeep = $("#ctx-keep");
    if (ctxTokens) ctxTokens.textContent = b.estimated_tokens;
    if (ctxSoft) ctxSoft.textContent = b.soft_budget;
    if (ctxHard) ctxHard.textContent = b.hard_budget;
    if (ctxKeep) ctxKeep.textContent = b.keep_raw;
    const topTokens = $("#top-tokens");
    const topBudget = $("#top-budget");
    if (topTokens) topTokens.textContent = b.estimated_tokens;
    if (topBudget) topBudget.textContent = b.soft_budget;
    const pct = Math.min(100, (b.estimated_tokens / b.hard_budget) * 100);
    const fill = $("#ctx-budget-fill");
    if (fill) {
      fill.style.width = pct + "%";
      fill.style.background = b.over_hard ? "var(--red)" : b.over_soft ? "var(--warn)" : "";
    }
  } catch (e) {}
}
function renderBudgetBar(b) {
  if (!b || !state.currentTask) return;
  const ctxTokens = $("#ctx-tokens");
  if (ctxTokens) ctxTokens.textContent = b.estimated_tokens;
  const topTokens = $("#top-tokens");
  if (topTokens) topTokens.textContent = b.estimated_tokens;
  const pct = Math.min(100, (b.estimated_tokens / (b.hard_budget || b.soft_budget)) * 100);
  const fill = $("#ctx-budget-fill");
  if (fill) fill.style.width = pct + "%";
}
async function loadStats() {
  try {
    const s = await api("/api/stats");
    const t = s.today;
    const elReq = $("#st-requests");
    const elPro = $("#st-prompt");
    const elCom = $("#st-comp");
    if (elReq) elReq.textContent = t.requests;
    if (elPro) elPro.textContent = t.prompt_tokens;
    if (elCom) elCom.textContent = t.completion_tokens;
    const elHit = $("#st-hit");
    const elHitFill = $("#st-hitfill");
    if (elHit) elHit.textContent = `${t.cache_hit} (${(t.hit_rate * 100).toFixed(1)}%)`;
    if (elHitFill) elHitFill.style.width = (t.hit_rate * 100).toFixed(0) + "%";
    const box = $("#st-recent");
    if (box) {
      box.innerHTML = "";
      s.recent.slice(0, 5).forEach((r) => {
        const div = document.createElement("div");
        div.className = "req-item";
        div.innerHTML = `<b>${esc(r.model || "-")}</b> 提示${r.prompt_tokens} 生成${r.completion_tokens} 缓存命中${r.cache_hit}<br>${esc((r.created_at || "").slice(5, 19))} 任务#${r.task_id}`;
        box.appendChild(div);
      });
    }
  } catch (e) {}
}

/* ---------- 知识库 ---------- */
const KB_VALIDITY_CLASS = { 现行: "cat-standard", 被替代: "cat-warn", 废止: "cat-danger", 未知: "cat-other" };
function kbMetaTags(e) {
  const v = e.validity || "未知";
  const s = e.source_type || "原文";
  const parts = [
    `<span class="cat-tag ${KB_VALIDITY_CLASS[v] || "cat-other"}">${esc(v)}</span>`,
    `<span class="cat-tag cat-other">${esc(s)}</span>`,
  ];
  if (e.item_type && e.item_type !== "knowledge") parts.push(`<span class="cat-tag cat-gov">${esc(e.item_type)}</span>`);
  if (e.status === "flagged") parts.push(`<span class="cat-tag cat-warn">待复核</span>`);
  return parts.join("");
}
async function loadKbStats() {
  try {
    const s = await api("/api/kb/stats");
    if (!s.total) {
      $("#kb-stats").innerHTML = '<div class="kb-stats-empty dim">知识库为空，可让智能体落库或手动添加</div>';
      return;
    }
    const cells = [
      ["知识条目", s.total],
      ["平均置信", s.avg_confidence],
      ["待复核", s.flagged],
      ["关系", s.relations],
    ];
    $("#kb-stats").innerHTML =
      `<div class="kb-stats-grid">` + cells.map(([k, v]) =>
        `<div class="kb-stat-cell"><b>${esc(String(v))}</b><span>${k}</span></div>`).join("") + `</div>`;
  } catch (e) { $("#kb-stats").textContent = "统计加载失败"; }
}
// 知识库变更实时刷新:节流 600ms, 避免连续多个写库工具触发多次请求
let _kbRefreshTimer = null;
function refreshKbOnChange() {
  if (_kbRefreshTimer) return;
  _kbRefreshTimer = setTimeout(() => {
    _kbRefreshTimer = null;
    // 搜索框有内容时不打断当前搜索结果, 仅刷新统计
    if (!$("#kb-q").value.trim()) loadKb();
    loadKbStats();
  }, 600);
}
function renderKbEntry(e) {
  const div = document.createElement("div");
  div.className = "entry";
  div.innerHTML = `
    <div class="entry-title"><span class="entry-title-text" title="${esc(e.title)}">${esc(e.title)}</span><span class="cat-tag cat-${esc(e.category)}">${esc(catLabel[e.category] || e.category)}</span></div>
    <div class="entry-tags">${kbMetaTags(e)}</div>
    ${e.url && /^https?:\/\//i.test(e.url) ? `<div class="entry-url"><a href="${esc(e.url)}" target="_blank">${esc(e.url)}</a></div>` : ""}
    <div class="entry-content">${esc(e.content)}</div>
    <div class="entry-row">
      <span class="hint">${esc(e.source || "")} | ${esc((e.created_at || "").slice(0, 16))}</span>
      <button class="entry-mini" data-act="detail">详情</button>
      <button class="entry-mini" data-act="correct">纠错</button>
      <button class="entry-mini danger" data-act="del">删除</button>
    </div>`;
  div.querySelector('[data-act="detail"]').onclick = () => openKbDetail(e.id, e.title);
  div.querySelector('[data-act="correct"]').onclick = () => correctKbEntry(e.id, e.title);
  div.querySelector('[data-act="del"]').onclick = async () => {
    await api(`/api/kb/${e.id}`, { method: "DELETE" });
    loadKb(); loadKbStats();
  };
  return div;
}
function openKbDetail(id, title) {
  let ov = $("#kb-detail-overlay");
  if (!ov) {
    ov = document.createElement("div");
    ov.id = "kb-detail-overlay";
    ov.innerHTML = `
      <div class="kb-detail-modal">
        <div class="kb-detail-head">
          <div class="kb-detail-title" id="kb-detail-title"></div>
          <div class="kb-detail-ops">
            <button class="entry-mini" data-act="refresh">刷新</button>
            <button class="entry-mini danger" data-act="del">删除</button>
            <button class="kb-detail-close" id="kb-detail-close">关闭</button>
          </div>
        </div>
        <div class="kb-detail-body" id="kb-detail-body"><div class="hint">加载中...</div></div>
      </div>`;
    document.body.appendChild(ov);
    ov.addEventListener("click", (ev) => { if (ev.target === ov) closeKbDetail(); });
    $("#kb-detail-close").onclick = closeKbDetail;
    ov.querySelector('[data-act="refresh"]').onclick = () => openKbDetail(id, title);
    ov.querySelector('[data-act="del"]').onclick = async () => {
      if (!confirm(`确认删除「${title}」?`)) return;
      try {
        await api(`/api/kb/${id}`, { method: "DELETE" });
        closeKbDetail(); loadKb(); loadKbStats(); toast("已删除");
      } catch (e) { toast("删除失败: " + e.message); }
    };
    document.addEventListener("keydown", function kbEsc(e) {
      if (e.key === "Escape") { closeKbDetail(); document.removeEventListener("keydown", kbEsc); }
    });
  }
  ov.classList.remove("hidden");
  $("#kb-detail-title").textContent = title || `条目 #${id}`;
  _renderKbDetail(id);
}
function closeKbDetail() {
  const ov = $("#kb-detail-overlay");
  if (ov) ov.classList.add("hidden");
}
async function _renderKbDetail(id) {
  const box = $("#kb-detail-body");
  if (!box) return;
  box.innerHTML = '<div class="hint">加载中...</div>';
  try {
    const d = await api(`/api/kb/${id}`);
    const vChain = (d.versions || []).map((v) => `v${v.version} ${esc((v.created_at || "").slice(0, 16))} ${esc(v.note || "")}`).join("<br>") || "无";
    const corrs = (d.corrections || []).map((c) =>
      `<div class="hint">#${c.id} [${esc(c.status)}] ${esc(c.issue)} ${c.suggestion ? `-> ${esc(c.suggestion)}` : ""}</div>`).join("") || "无";
    const rels = (d.relations || []).map((r) =>
      `<div class="hint">--${esc(r.rel_type)}--> ${esc(r.to_title || `#${r.to_id}`)} ${r.note ? `(${esc(r.note)})` : ""}</div>`).join("") || "无";
    const srcs = (d.sources || []).map((s) => {
      const u = s.url || "";
      const isWeb = /^https?:\/\//i.test(u);
      const k = isWeb ? (s.kind || "web") : "用户上传";
      return `<div class="hint">[${esc(k)}] ${esc(s.name || "")} ${isWeb ? `<a href="${esc(u)}" target="_blank">${esc(u)}</a>` : ""}</div>`;
    }).join("") || "无";
    // 智能解读与联网查新
    let interpBlock = "";
    try {
      const it = await api(`/api/kb/${id}/interpret`);
      if (it && it.interpret) {
        const iv = it.interpret, cur = it.currency || {};
        const metaRows = [["标准号", iv.std_no], ["名称", iv.cn_name], ["英文", iv.en_name],
          ["类别", iv.category], ["替代关系", iv.replace], ["发布日期", iv.publish_date],
          ["实施日期", iv.implement_date], ["发布单位", iv.publisher],
          ["起草单位", iv.drafter], ["归口单位", iv.committee]]
          .filter((r) => r[1]).map((r) =>
            `<div class="kb-iv-item"><span>${esc(r[0])}</span>${esc(r[1])}</div>`).join("");
        const skeleton = (iv.skeleton || []).map((s) =>
          `<span class="tb-chip">${esc(s.no)} ${esc(s.title)}</span>`).join(" ");
        const core = Object.entries(iv.core || {}).filter(([, v]) => v).map(([k, v]) =>
          `<div class="hint"><b>${esc(k)}</b>: ${esc(v)}</div>`).join("");
        const rev = (iv.revision_points || []).map((r) =>
          `<div class="hint">- ${esc(r)}</div>`).join("");
        const refs = (iv.refs || []).map((r) =>
          `<span class="tb-chip cat-standard">${esc(r)}</span>`).join(" ");
        const validity = cur.validity || "";
        const vCls = validity.indexOf("现行") >= 0 ? "cat-standard"
          : (validity.indexOf("废止") >= 0 || validity.indexOf("替代") >= 0) ? "cat-policy" : "";
        const evid = (cur.evidence || []).map((ev) =>
          `<div class="hint">${ev.url ? `<a href="${esc(ev.url)}" target="_blank">${esc(ev.title || ev.url)}</a>` : esc(ev.title || "")}</div>`).join("");
        interpBlock = `
          <div class="kb-detail-hd">智能解读与查新
            <span class="cat-tag ${vCls}">${esc(validity || "未知")}</span>
            <span class="hint">引擎:${esc(iv.engine || "")} ${esc((iv.generated_at || "").slice(0, 16))}</span>
          </div>
          ${cur.note ? `<div class="hint">${esc(cur.note)} 查新时间 ${esc((cur.checked_at || "").slice(0, 16))}</div>` : ""}
          ${metaRows ? `<div class="kb-iv-grid">${metaRows}</div>` : ""}
          ${iv.summary ? `<div class="hint"><b>一句话总结:</b> ${esc(iv.summary)}</div>` : ""}
          ${skeleton ? `<div class="entry-tags">${skeleton}</div>` : ""}
          ${core ? `<div class="kb-iv-core">${core}</div>` : ""}
          ${rev ? `<div class="kb-iv-core"><div class="hint"><b>修订要点</b></div>${rev}</div>` : ""}
          ${refs ? `<div class="entry-tags">${refs}</div>` : ""}
          ${evid ? `<div class="kb-iv-core"><div class="hint"><b>查新证据</b></div>${evid}</div>` : ""}`;
      }
    } catch (e) { /* 忽略: 解读未生成或接口异常 */ }
    // 通用文档智能总结(适用于任意条目): 一句话/TL;DR/结构化长摘要/章节要点/关键参数 + 质量验证
    let summBlock = "";
    try {
      const sm = await api(`/api/kb/${id}/summarize`);
      if (sm && sm.summary) {
        const s = sm.summary, vf = s.verify || {};
        const vCls = vf.passed ? "cat-standard" : "cat-policy";
        const kps = (s.key_points || []).map((p) =>
          `<div class="hint">- ${esc(p)}</div>`).join("");
        const cps = (s.chapter_points || []).map((c) =>
          `<div class="hint">[${esc(c.no)}] ${esc(c.title)}: ${esc(c.point)}</div>`).join("");
        const params = (s.key_params || []).map((p) =>
          `<span class="tb-chip">${esc(p.v)}</span>`).join(" ");
        const refs = (s.refs || []).map((r) =>
          `<span class="tb-chip cat-standard">${esc(r)}</span>`).join(" ");
        summBlock = `
          <div class="kb-detail-hd">智能总结
            <span class="cat-tag ${vCls}">${vf.passed ? "验证通过" : "待复核"}</span>
            <span class="hint">引擎:${esc(s.engine || "")} 类型:${esc(s.doc_type || "")} ${esc((s.generated_at || "").slice(0, 16))}</span>
          </div>
          ${s.one_liner ? `<div class="hint"><b>一句话:</b> ${esc(s.one_liner)}</div>` : ""}
          ${s.tldr ? `<div class="kb-iv-core"><div class="hint"><b>TL;DR</b></div><div class="hint">${esc(s.tldr)}</div></div>` : ""}
          ${s.long_summary ? `<div class="kb-iv-core"><div class="hint"><b>结构化长摘要</b></div><div class="hint" style="white-space:pre-wrap">${esc(s.long_summary)}</div></div>` : ""}
          ${kps ? `<div class="kb-iv-core"><div class="hint"><b>核心要点</b></div>${kps}</div>` : ""}
          ${cps ? `<div class="kb-iv-core"><div class="hint"><b>章节要点</b></div>${cps}</div>` : ""}
          ${params ? `<div class="entry-tags">${params}</div>` : ""}
          ${refs ? `<div class="entry-tags">${refs}</div>` : ""}
          ${vf.note ? `<div class="hint">[验证] ${esc(vf.note)} 数字回校 ${vf.numbers_checked || 0} 个, 未回校 ${(vf.numbers_missing || []).length} 个</div>` : ""}`;
      }
    } catch (e) { /* 忽略: 总结未生成或接口异常 */ }
    const interpBtns = `
      <div class="hint">
        <button class="entry-mini" data-act="interpret">解读</button>
        <button class="entry-mini" data-act="check">查新</button>
        <button class="entry-mini" data-act="summarize">总结</button>
      </div>`;
    box.innerHTML = `
      <div class="kb-detail-md">
        <div class="kb-detail-hd">正文 (Markdown / Vditor)</div>
        <div class="kb-md-body" id="kb-detail-md"></div>
      </div>
      ${interpBlock || `<div class="kb-detail-hd">智能解读与查新</div>
        <div class="hint">尚未生成。可对标准/政策条目触发: 结构化解读 + 联网确认现行有效/废止。</div>`}
      ${summBlock || `<div class="kb-detail-hd">智能总结</div>
        <div class="hint">尚未生成。可对任意条目触发: 一句话/TL;DR/结构化长摘要 + 质量验证。</div>`}
      ${interpBtns}
      <div class="kb-detail-grid">
        <div><b>版本链</b>${vChain}</div>
        <div><b>纠错记录</b>${corrs}</div>
        <div><b>引用关系</b>${rels}</div>
        <div><b>来源</b>${srcs}</div>
      </div>`;
    box.querySelector('[data-act="interpret"]')?.addEventListener("click", async () => {
      try {
        await api(`/api/kb/${id}/interpret`, { method: "POST", body: "{}" });
        toast("已加入解读队列, 完成后刷新详情查看");
      } catch (e2) { toast("触发失败: " + e2.message); }
    });
    box.querySelector('[data-act="check"]')?.addEventListener("click", async () => {
      try {
        await api(`/api/kb/${id}/currency-check`, { method: "POST", body: "{}" });
        toast("已加入查新队列, 完成后刷新详情查看");
      } catch (e3) { toast("触发失败: " + e3.message); }
    });
    box.querySelector('[data-act="summarize"]')?.addEventListener("click", async () => {
      try {
        await api(`/api/kb/${id}/summarize`, { method: "POST", body: "{}" });
        toast("已加入智能总结队列, 完成后刷新详情查看");
      } catch (e4) { toast("触发失败: " + e4.message); }
    });
    renderVditorPreview("#kb-detail-md", d.content || "");
  } catch (e) { box.innerHTML = '<div class="hint">详情加载失败</div>'; }
}
function renderVditorPreview(sel, md) {
  const el = $(sel);
  if (!el) return;
  el.innerHTML = "";
  const mdText = (md || "").trim();
  if (!mdText) { el.innerHTML = '<span class="hint">(无正文)</span>'; return; }
  try {
    if (window.Vditor && Vditor.preview) {
      Vditor.preview(el, mdText, {
        cdn: "/static/vditor",
        mode: "light",
        lang: "zh_CN",
        hljs: { style: "github", lineNumber: false },
      });
    } else {
      el.textContent = mdText.slice(0, 500);
      el.insertAdjacentHTML("beforeend", '<span class="hint"> (Vditor 未加载,仅显示摘要)</span>');
    }
  } catch (e) {
    el.textContent = mdText.slice(0, 500);
  }
}
async function correctKbEntry(id, title) {
  const issue = prompt(`纠错: ${title}\n请输入发现的问题:`, "");
  if (issue === null || !issue.trim()) return;
  try {
    await api(`/api/kb/${id}/correct`, { method: "POST", body: JSON.stringify({ issue: issue.trim() }) });
    toast("纠错单已登记");
    loadKb(); loadKbStats();
  } catch (e) { toast("纠错登记失败: " + e.message); }
}
async function loadKb(category) {
  const cat = category !== undefined ? category : state.kbCat || null;
  const url = "/api/kb" + (cat ? `?category=${cat}` : "");
  const rows = await api(url);
  const box = $("#kb-list");
  box.innerHTML = "";
  if (!rows.length) { box.innerHTML = '<div class="hint">知识库为空</div>'; return; }
  rows.forEach((e) => box.appendChild(renderKbEntry(e)));
}
async function searchKb() {
  const q = $("#kb-q").value.trim();
  const cat = state.kbCat || null;
  if (q) {
    const rows = await api(`/api/kb/search?q=${encodeURIComponent(q)}&category=${cat || ""}`);
    const box = $("#kb-list");
    box.innerHTML = "";
    if (!rows.length) { box.innerHTML = '<div class="hint">无匹配结果</div>'; return; }
    rows.forEach((e) => box.appendChild(renderKbEntry(e)));
  } else {
    loadKb(cat);
  }
}
async function saveKbEntry() {
  const title = $("#kb-add-title").value.trim();
  const content = $("#kb-add-content").value.trim();
  if (!title || !content) { toast("标题与内容必填"); return; }
  await api("/api/kb", {
    method: "POST",
    body: JSON.stringify({
      title,
      url: $("#kb-add-url").value.trim(),
      category: $("#kb-add-cat").value,
      content,
    }),
  });
  $("#kb-add-title").value = "";
  $("#kb-add-url").value = "";
  $("#kb-add-content").value = "";
  $("#kb-add-form").classList.add("hidden");
  loadKb(); loadKbStats();
  toast("已添加");
}
async function searchKbHybrid() {
  const q = $("#kb-q").value.trim();
  if (!q) { toast("请输入检索词"); return; }
  $("#kb-recall").innerHTML = '<span class="hint">混合检索中(全文+向量+关系)...</span>';
  try {
    const rows = await api(`/api/kb/hybrid?q=${encodeURIComponent(q)}&top=5`);
    const box = $("#kb-list");
    box.innerHTML = "";
    if (!rows.length) { box.innerHTML = '<div class="hint">多路召回无命中</div>'; return; }
    $("#kb-recall").innerHTML = rows.length
      ? `<span class="hint">混合检索 ${rows.length} 条</span>`
      : "";
    rows.forEach((e) => {
      const tag = (e.recall || []).map((r) => ({ fts: "全文", vec: "向量", rel: "关系" }[r] || r)).join("+");
      const div = renderKbEntry(e);
      if (tag) {
        const t = document.createElement("div");
        t.className = "entry-row";
        t.innerHTML = `<span class="cat-tag cat-gov">召回:${esc(tag)}</span><span class="hint">分:${e.score ?? ""}</span>`;
        div.appendChild(t);
      }
      box.appendChild(div);
    });
  } catch (err) {
    $("#kb-recall").innerHTML = `<span class="cat-tag cat-danger">混合检索失败: ${esc(err.message)}</span>`;
  }
}
function toggleKbImport() {
  $("#kb-import-form").classList.toggle("hidden");
}
async function runKbImport() {
  const paths = $("#kb-import-paths").value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (!paths.length) { toast("请填写文档路径"); return; }
  $("#kb-recall").innerHTML = '<span class="hint">批量导入中(解析+分类+分块向量化)...</span>';
  try {
    const r = await api("/api/kb/import", {
      method: "POST",
      body: JSON.stringify({ paths, batch_name: "web" }),
    });
    $("#kb-import-form").classList.add("hidden");
    $("#kb-import-paths").value = "";
    $("#kb-recall").innerHTML = `<span class="cat-tag ${r.fail ? "cat-warn" : "cat-standard"}">导入完成: 成功 ${r.ok} / 失败 ${r.fail}</span>` +
      (r.errors && r.errors.length ? `<div class="hint">${esc(r.errors.slice(0, 3).join("; "))}</div>` : "");
    loadKb(); loadKbStats();
  } catch (err) {
    $("#kb-recall").innerHTML = `<span class="cat-tag cat-danger">导入失败: ${esc(err.message)}</span>`;
  }
}
async function runKbAudit() {
  $("#kb-recall").innerHTML = '<span class="hint">健康审计中...</span>';
  try {
    const r = await api("/api/kb/audit", { method: "POST" });
    const healthClass = r.health >= 80 ? "cat-standard" : (r.health >= 60 ? "cat-warn" : "cat-danger");
    $("#kb-audit-box").classList.remove("hidden");
    $("#kb-audit-box").innerHTML = `
      <div class="kb-audit-line">健康分 <span class="cat-tag ${healthClass}">${r.health}/100</span>
        <span class="hint">生成于 ${esc((r.generated_at || "").slice(0, 16))}</span></div>
      <div class="hint">条目 ${r.total} | 已分块 ${r.chunked} | QA ${r.qa_entries} | 记忆 ${r.memories} | 缓存 ${r.cache_entries}</div>
      <div class="hint">缺来源 ${r.no_source} | 缺机构 ${r.no_org} | 待复核 ${r.flagged} | 低置信 ${r.low_confidence}</div>
      <div class="hint">纠错待处理 ${r.pending_corrections} | 冲突 ${r.conflicts} | 重复标准号 ${r.duplicate_std}</div>`;
    $("#kb-recall").innerHTML = "";
  } catch (err) {
    $("#kb-recall").innerHTML = `<span class="cat-tag cat-danger">审计失败: ${esc(err.message)}</span>`;
  }
}
async function exportKb() {
  try {
    const r = await api("/api/kb/export?fmt=markdown");
    const a = document.createElement("a");
    a.href = `/api/kb/export/download?fmt=markdown`;
    a.download = r.filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast(`已导出 ${r.count} 条 (${r.size} 字节)`);
  } catch (err) { toast("导出失败: " + err.message); }
}

/* ---------- 记忆（对话触发写入） ---------- */
function extractMemory(text) {
  const s = (text || "").trim();
  if (!s) return null;
  // 否定表达: "别/不用/不要/不必/无需 记住..." 不触发
  if (/(?:别|不要|不用|不必|无需|可别)(?:记住|记得|记下|写入记忆|写进记忆)/.test(s)) return null;
  // 触发词按长度降序优先匹配, 取触发词之后的内容
  const TRIG = ["请记住", "帮我记住", "麻烦记住", "写入记忆", "写进记忆", "存进记忆", "记住", "记得", "记下"];
  let hit = null;
  for (const t of TRIG) {
    const i = s.indexOf(t);
    if (i !== -1) { hit = i + t.length; break; }
  }
  if (hit === null) return null;
  const content = s.slice(hit).replace(/^[:：,\s，。、]+/, "").replace(/[。.!！?？\s]+$/, "").trim();
  if (!content) return null;
  let key = content.replace(/[^\w\u4e00-\u9fa5-]/g, "").slice(0, 10) || "note";
  const now = new Date();
  const ymd = now.getFullYear() + String(now.getMonth() + 1).padStart(2, "0") + String(now.getDate()).padStart(2, "0");
  key += "-" + ymd;
  return { key, content };
}
async function tryRemember(text) {
  const mem = extractMemory(text);
  if (!mem) return;
  try {
    await api("/api/memory", { method: "POST", body: JSON.stringify({ key: mem.key, content: mem.content }) });
    const short = mem.content.length > 42 ? mem.content.slice(0, 42) + "..." : mem.content;
    toast("已记住: " + short);
  } catch (e) { console.warn("记忆写入失败", e); }
}

/* ---------- 技能 ---------- */
async function loadSkills() {
  const rows = await api("/api/skills");
  const sel = $("#skill-select");
  const prev = sel.value;
  const opts = [{ value: "", label: "未启用" }];
  const enabled = rows.filter((s) => s.enabled);
  const rp = $("#rp-skill");
  if (rp) rp.textContent = enabled.length ? enabled.map((s) => s.name).join(", ") : "未启用";
  rows.forEach((s) => {
    opts.push({
      value: s.key,
      label: s.name,
      title: s.key + (s.enabled ? " (启用)" : ""),
      html: '<span class="opt-main">' + (s.enabled ? "* " : "") + '<b class="csel-name">' + esc(s.name) + "</b><span class=\"csel-desc\">" + esc(s.description) + "</span></span>",
      onDel: () => deleteSkillFromSelect(s.key, s.name),
    });
  });
  sel.setOptions(opts);
  if (prev && opts.some((o) => o.value === prev)) sel.value = prev;
  // 管理区:列出全部技能,支持删除
  const mg = $("#skill-manage");
  if (mg) {
    mg.innerHTML = "";
    if (!rows.length) { mg.innerHTML = '<div class="hint">暂无技能</div>'; }
    rows.forEach((s) => {
      const div = document.createElement("div");
      div.className = "skill-manage-item";
      div.innerHTML = `
        <div class="skill-manage-name">${esc(s.name)}<span class="cat-tag cat-gov">${esc(s.group)}</span><span class="cat-tag cat-other">${s.enabled ? "已启用" : "未启用"}</span></div>
        <div class="skill-manage-desc">${esc(s.description)}</div>
        <div class="skill-manage-row">
          <span class="hint">${esc(s.key)} | ${s.body_len} 字符</span>
          <button class="btn-mini" data-del>删除</button>
        </div>`;
      div.querySelector("[data-del]").onclick = async () => {
        const ok = await uiDialog({ title: "删除技能", message: "确定删除技能 " + s.name + "?", danger: true });
        if (!ok) return;
        await api(`/api/skills/${encodeURIComponent(s.key)}`, { method: "DELETE" });
        if (sel.value === s.key) sel.value = "";
        loadSkills();
        toast("已删除 " + s.name);
      };
      mg.appendChild(div);
    });
  }
}
async function deleteSkillFromSelect(key, name) {
  const ok = await uiDialog({ title: "删除技能", message: "确定删除技能 " + name + "?", danger: true });
  if (!ok) return;
  await api(`/api/skills/${encodeURIComponent(key)}`, { method: "DELETE" });
  const sel = $("#skill-select");
  if (sel.value === key) sel.value = "";
  sel._cselectClose?.();
  loadSkills();
  toast("已删除 " + name);
}
async function toggleSkillFromSelect(key) {
  const rows = await api("/api/skills");
  const targets = key
    ? rows.map((s) => ({ key: s.key, enabled: String(s.key) === String(key) }))
    : rows.map((s) => ({ key: s.key, enabled: false }));
  for (const t of targets) {
    await api(`/api/skills/${encodeURIComponent(t.key)}/toggle`, { method: "POST", body: JSON.stringify({ enabled: t.enabled }) });
  }
  loadSkills();
}
function openSkillAdd() {
  const file = $("#sk-file");
  if (file) file.click();
  else {
    const form = $("#skill-add-form");
    if (form) form.classList.remove("hidden");
  }
}

/* ---------- 事件绑定 ---------- */
function bindEvents() {
  const mlist = $("#msg-list");
  mlist.addEventListener("scroll", () => {
    _followBottom = mlist.scrollHeight - mlist.scrollTop - mlist.clientHeight < 160;
  });
  $("#btn-new-task").onclick = createTask;
  // G4 会话断点续传：暂停(落断点) / 继续(注入恢复上下文)
  $("#btn-task-pause").onclick = async () => {
    if (!state.currentTask) { toast("请先选择任务"); return; }
    const r = await api(`/api/tasks/${state.currentTask.id}/pause`, { method: "POST" });
    toast(r.ok ? "已暂停，断点已保存" : (r.error || "暂停失败"));
  };
  $("#btn-task-resume").onclick = async () => {
    if (!state.currentTask) { toast("请先选择任务"); return; }
    const r = await api(`/api/tasks/${state.currentTask.id}/resume`, { method: "POST" });
    if (r.ok) {
      toast("已恢复，自动从断点继续执行");
      // 自动发送"继续任务"指令，驱动模型立即执行未完成步骤
      const input = $("#input");
      if (input && !state.streaming) {
        input.value = "继续执行上次暂停的任务，请直接从断点继续完成";
        sendMessage();
      }
    } else toast(r.error || "任务无断点");
  };
  $("#task-list").addEventListener("click", (e) => {
    const del = e.target.closest(".task-del");
    const out = e.target.closest(".task-out");
    const li = e.target.closest("li");
    if (!li) return;
    if (out) openOutputPanel(li.dataset.id);
    else if (del) deleteTask(li.dataset.id);
    else selectTask(li.dataset.id);
  });
  $("#btn-out-close").onclick = closeOutputPanel;
  $("#btn-out-refresh").onclick = () => { if (state.outTaskId) openOutputPanel(state.outTaskId); };
  $("#btn-out-open").onclick = async () => {
    if (!state.outTaskId) return;
    try {
      const r = await api(`/api/tasks/${state.outTaskId}/outputs/open`, { method: "POST" });
      if (!r.ok) toast(r.error || "打开失败");
    } catch (e) {
      toast("打开失败: " + (e.message || e));
    }
  };
  $("#out-panel").addEventListener("click", (e) => {
    if (e.target.id === "out-panel") closeOutputPanel();
  });
  $("#task-list").addEventListener("dblclick", (e) => {
    const li = e.target.closest("li");
    if (!li) return;
    renameTask(li.dataset.id);
  });
  $("#btn-skill-save").onclick = importSkill;
  const skFile = $("#sk-file");
  if (skFile) skFile.addEventListener("change", async () => {
    const file = skFile.files && skFile.files[0];
    if (!file) return;
    const body = await file.text();
    $("#sk-body").value = body;
    await importSkill();
    skFile.value = "";
  });
  $("#btn-modal-close").onclick = closeModal;
  $("#modal-overlay").onclick = (e) => { if (e.target.id === "modal-overlay") closeModal(); };
  $("#btn-pf-save").onclick = saveProvider;
  $("#btn-pf-test").onclick = testProvider;

  $("#btn-send").onclick = sendMessage;
  $("#btn-stop").onclick = stopChat;
  // G6 图片附件按钮
  $("#btn-img").onclick = () => $("#img-file").click();
  $("#img-file").onchange = (e) => {
    const files = [...(e.target.files || [])];
    if (files.length) attachFiles(files);
    e.target.value = "";
  };
  $("#btn-srch-refresh").onclick = loadSearchStatus;
  $("#btn-srch-restart").onclick = restartSearXNG;
  $("#btn-usage").onclick = openUsage;
  $("#input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // 文件拖入
  const composer = $("#composer");
  ["dragenter", "dragover"].forEach((ev) => {
    composer.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      composer.classList.add("drag-over");
    });
  });
  ["dragleave", "drop"].forEach((ev) => {
    composer.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      composer.classList.remove("drag-over");
    });
  });
  composer.addEventListener("drop", (e) => {
    const files = [...(e.dataTransfer?.files || [])];
    if (files.length) attachFiles(files);
  });

  // 右栏折叠区
  document.querySelectorAll(".fold-head").forEach((h) => {
    h.onclick = () => {
      const sec = h.closest(".fold");
      const willOpen = !sec.classList.contains("open");
      sec.classList.toggle("open");
      if (willOpen) {
        if (sec.id === "sec-kb") { loadKb(); loadKbStats(); }
        if (sec.id === "sec-srch") loadSearchStatus();
      }
    };
  });

  $("#btn-kb-search").onclick = searchKb;
  $("#btn-kb-hybrid").onclick = searchKbHybrid;
  $("#kb-q").addEventListener("keydown", (e) => { if (e.key === "Enter") searchKb(); });
  $("#btn-kb-add").onclick = () => $("#kb-add-form").classList.toggle("hidden");
  $("#btn-kb-import").onclick = toggleKbImport;
  $("#btn-kb-import-run").onclick = runKbImport;
  $("#btn-kb-audit").onclick = runKbAudit;
  $("#btn-kb-export").onclick = exportKb;
  $("#btn-kb-save").onclick = saveKbEntry;

}

/* ---------- Token 消耗实时面板(仿 Codex, cselect 上弹出式, 仅当前任务) ---------- */
function usageExpanded() {
  return !$("#usage-expand").classList.contains("hidden");
}
function openUsage() {
  if (!state.currentTask) { toast("请先选择任务"); return; }
  // 与其他下拉弹出行为一致:先收起已打开的下拉菜单
  document.querySelectorAll(".cselect-menu.open").forEach((m) => { m.classList.add("hidden"); m.classList.remove("open"); });
  const el = $("#usage-expand");
  const willOpen = el.classList.contains("hidden");
  el.classList.toggle("hidden");
  if (willOpen) loadTaskUsage();
}
function closeUsage() {
  $("#usage-expand").classList.add("hidden");
}
function updateUsageBtn(u) {
  const p = Number(u && u.prompt) || 0;
  const c = Number(u && (u.completion !== undefined ? u.completion : u.comp)) || 0;
  const total = p + c;
  $("#btn-usage").textContent = total > 0 ? `Token ${fmtNum(total)}` : "Token";
}
function fmtNum(n) {
  if (n === null || n === undefined) return "0";
  n = Number(n);
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(Math.round(n));
}
function fmtMs(ms) {
  ms = Number(ms) || 0;
  if (ms >= 60000) return (ms / 60000).toFixed(1) + "m";
  if (ms >= 1000) return (ms / 1000).toFixed(1) + "s";
  return ms + "ms";
}
async function loadTaskUsage(silent) {
  const tid = state.currentTask && state.currentTask.id;
  if (tid === null || tid === undefined) return;
  const data = await api(`/api/tasks/${tid}/usage`).catch(() => null);
  if (!data) {
    if (!silent) toast("统计加载失败");
    updateUsageBtn(null);
    return;
  }
  const s = data.summary || {};
  const lat = data.latency || {};
  const task = data.task || {};
  const prompt = s.prompt || 0, comp = s.comp || 0;
  const hit = s.hit || 0, miss = s.miss || 0;
  const creation = s.creation || 0, thinking = s.thinking || 0;
  const reply = Math.max(0, comp - thinking);
  const hitRate = Math.round((s.hit_rate || 0) * 100);

  updateUsageBtn({ prompt, completion: comp });
  $("#usage-task-name").textContent = task.title ? `当前任务: ${task.title}` : "";

  // ===== Token 消耗明细面板(仿 Codex 4.1) =====
  $("#usage-panel").innerHTML = `
    <div class="up-head">
      <span class="up-total">总计 ${fmtNum(prompt + comp)}</span>
    </div>
    <div class="up-body">
      <div class="up-sec">
        <div class="up-row up-main"><span class="up-dot up-in"></span><span>输入</span><span class="up-val">${fmtNum(prompt)}</span></div>
        <div class="up-row up-sub"><span class="up-dot up-hit"></span><span>缓存命中</span><span class="up-val">${fmtNum(hit)}</span></div>
        <div class="up-row up-sub"><span class="up-dot up-miss"></span><span>缓存未命中</span><span class="up-val">${fmtNum(miss)}</span></div>
        <div class="up-row up-sub"><span class="up-dot up-creat"></span><span>缓存写入</span><span class="up-val">${fmtNum(creation)}</span></div>
      </div>
      <div class="up-sec">
        <div class="up-row up-main"><span class="up-dot up-out"></span><span>输出</span><span class="up-val">${fmtNum(comp)}</span></div>
        <div class="up-row up-sub"><span class="up-dot up-think"></span><span>思考过程</span><span class="up-val">${fmtNum(thinking)}</span></div>
        <div class="up-row up-sub"><span class="up-dot up-reply"></span><span>回复内容</span><span class="up-val">${fmtNum(reply)}</span></div>
      </div>
      <div class="up-rate">
        <div class="up-rate-head"><span>缓存命中率</span><b>${hitRate}%</b></div>
        <div class="up-track"><div class="up-fill" style="width:${Math.min(100, hitRate)}%"></div></div>
        <div class="up-lat">平均 ${fmtMs(lat.avg_ms)} · p50 ${fmtMs(lat.p50_ms)} · p95 ${fmtMs(lat.p95_ms)}</div>
      </div>
    </div>`;
}
async function importSkill() {
  const body = $("#sk-body").value.trim();
  if (!body) { toast("SKILL.md 内容必填"); return; }
  const r = await api("/api/skills", {
    method: "POST",
    body: JSON.stringify({ body }),
  });
  if (r && r.ok === false) { toast(r.error || "导入失败"); return; }
  $("#sk-body").value = "";
  $("#skill-add-form").classList.add("hidden");
  await loadSkills();
  if (r.key) await toggleSkillFromSelect(r.key);
  toast("Skill 已导入");
}
async function renameTask(id) {
  const t = state.tasks.find((x) => String(x.id) === String(id));
  if (!t) return;
  const name = await uiDialog({ title: "重命名任务", input: true, value: t.title, okText: "保存" });
  if (!name || !String(name).trim()) return;
  await api(`/api/tasks/${id}`, { method: "PATCH", body: JSON.stringify({ title: name.trim() }) });
  await loadTasks();
  toast("已重命名");
}
function openSec(id) {
  const sec = document.getElementById(id);
  if (sec) sec.classList.add("open");
}

init();
