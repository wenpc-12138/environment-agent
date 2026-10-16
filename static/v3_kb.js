/* 02 知识库管理 */
"use strict";
EA._kbState = { seg: "search", cat: "", cur: null, mode: "view" };
EA._KB_CATS = [
  { v: "", label: "全部" },
  { v: "standard", label: "标准规范" },
  { v: "policy", label: "政策法规" },
  { v: "gov", label: "政府发布" },
  { v: "draft", label: "征求意见稿" },
  { v: "network", label: "网络资料" },
  { v: "other", label: "其他" },
];
EA._KB_CAT_LABEL = (v) => { const m = EA._KB_CATS.find((c) => c.v === v); return m ? m.label : (v || "其他"); };

EA.onView("kb", function () {
  document.getElementById("v-kb").innerHTML = `
  <div class="topbar">
    <h1>知识库管理</h1><span class="sp"></span>
    <button class="btn sm" id="btn-kb-import">导入文件</button>
    <button class="btn sm" id="btn-kb-qc">质量检查</button>
    <button class="btn sm" id="btn-kb-backup">备份</button>
    <button class="btn sm" id="btn-kb-export">导出</button>
    <button class="btn sm" id="btn-kb-batch-iv">批量解读</button>
    <button class="btn sm" id="btn-kb-batch-sum">批量总结</button>
    <button class="btn sm" id="btn-kb-imports">导入历史</button>
    <button class="btn sm" id="btn-kb-harvest">采集</button>
    <button class="btn sm" id="btn-kb-conflicts">冲突检测</button>
    <button class="btn sm" id="btn-kb-learn">学习文档</button>
    <button class="btn sm gold" id="btn-kb-new">+ 新建条目</button>
  </div>
  <div class="stat-row" id="kb-stats-row"></div>
  <div class="kb">
    <div class="kb-list">
      <div class="search-zone">
        <div class="seg" id="kb-seg">
          <button class="on" data-s="search">关键词</button><button data-s="hybrid">混合</button><button data-s="vector">向量</button>
        </div>
        <input class="input" id="kb-q" placeholder="检索标准号 / 关键词，如 HJ 166">
        <div class="cats" id="kb-cats"></div>
      </div>
      <div class="ent" id="kb-entries"></div>
    </div>
    <div class="kb-detail" id="kb-detail">
      <div style="color:var(--text-3);padding:40px;text-align:center">选择左侧条目查看详情</div>
    </div>
    <div class="kb-side" id="kb-side"></div>
  </div>`;
  renderKBCats();
  bindKBEvents();
  loadKBStats();
  loadKBList();
});

function renderKBCats() {
  const el = $("kb-cats");
  if (!el) return;
  const color = { "standard": "blue", "policy": "green", "gov": "gold", "draft": "gray", "network": "gray", "other": "gray" };
  el.innerHTML = EA._KB_CATS.map((c, i) =>
    `<span class="tag ${i === 0 ? "gray on" : color[c.v] || "gray"}" data-c="${c.v}">${c.label}</span>`).join("");
  el.querySelectorAll(".tag").forEach((t) => {
    t.onclick = () => {
      el.querySelectorAll(".tag").forEach((x) => x.classList.remove("on"));
      t.classList.add("on"); EA._kbState.cat = t.dataset.c; loadKBList();
    };
  });
}

function bindKBEvents() {
  const doSearch = debounce(() => loadKBList(), 350);
  $("kb-q").addEventListener("input", doSearch);
  document.querySelectorAll("#kb-seg button").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll("#kb-seg button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on"); EA._kbState.seg = b.dataset.s; loadKBList();
    };
  });
  $("btn-kb-new").onclick = () => {
    EA._kbState.mode = "new";
    $("kb-detail").innerHTML = `
      <div class="kb-head">
        <h2 style="font-size:18px">新建条目</h2><span class="sp" style="flex:1"></span>
        <button class="btn pri sm" id="btn-kb-save-new">保存</button>
      </div>
      <div class="kb-body">
        <input class="input" id="kb-new-title" placeholder="标题" style="width:100%;margin-bottom:8px">
        <select class="input" id="kb-new-cat" style="width:100%;margin-bottom:8px">
          ${EA._KB_CATS.filter((c) => c.v).map((c) => `<option value="${c.v}">${c.label}</option>`).join("")}
        </select>
        <textarea class="input" id="kb-new-content" style="width:100%;min-height:260px" placeholder="正文内容"></textarea>
      </div>`;
    $("btn-kb-save-new").onclick = async () => {
      try {
        await EA.api("POST", "/api/kb", {
          title: $("kb-new-title").value.trim(), category: $("kb-new-cat").value,
          content: $("kb-new-content").value,
        });
        EA.toast("已创建"); EA._kbState.mode = "view"; loadKBList();
      } catch (e) { EA.toast(e.message); }
    };
  };
  $("btn-kb-import").onclick = () => {
    const inp = document.createElement("input");
    inp.type = "file"; inp.multiple = true; inp.accept = ".pdf,.docx,.doc,.html,.htm,.txt,.md,.xlsx";
    inp.onchange = async () => {
      const fd = new FormData();
      for (const f of inp.files) fd.append("files", f);
      try {
        const r = await fetch("/api/kb/import", { method: "POST", body: fd });
        const j = await r.json();
        if (!r.ok) throw new Error(j.error || "导入失败");
        EA.toast(`导入完成：${j.imported || j.count || "完成"}`); loadKBStats(); loadKBList();
      } catch (e) { EA.toast(e.message); }
    };
    inp.click();
  };
  $("btn-kb-qc").onclick = async () => {
    try {
      const r = await EA.api("GET", "/api/kb/qc");
      const issues = Array.isArray(r) ? r : (r.issues || []);
      EA.modal("质量检查",
        `<div style="font-size:13px">共 ${issues.length} 项待处理</div>` +
        issues.slice(0, 20).map((i) =>
          `<div style="font-size:12px;color:var(--text-2);padding:6px 0;border-bottom:1px dashed var(--line)">${EA.esc(i.title || i.name || JSON.stringify(i).slice(0, 80))}</div>`).join(""),
        `<button class="btn" data-x>关闭</button>`);
      document.querySelector(".overlay [data-x]").onclick = () => document.querySelector(".overlay").remove();
    } catch (e) { EA.toast(e.message); }
  };
  $("btn-kb-backup").onclick = async () => {
    try { const r = await EA.api("POST", "/api/kb/backup"); EA.toast(r.path || r.message || "备份完成"); } catch (e) { EA.toast(e.message); }
  };
  // 批量解读：后台队列逐个联网查新（仅处理未查新过的条目）
  $("btn-kb-batch-iv").onclick = async () => {
    const b = $("btn-kb-batch-iv");
    b.disabled = true;
    try {
      const r = await EA.api("POST", "/api/kb/interpret-batch", { limit: 200, only_unchecked: true });
      b.textContent = "批量解读";
      b.disabled = false;
      EA.toast(r.message || `已加入查新队列（${r.processed || 0} 条，待查新 ${r.pending || 0} 条）`);
      loadKBList(); loadKBStats();
    } catch (e) { b.disabled = false; b.textContent = "批量解读"; EA.toast(e.message); }
  };
  // 批量总结：后台队列逐个生成智能总结（仅处理未总结过的条目）
  $("btn-kb-batch-sum").onclick = async () => {
    const b = $("btn-kb-batch-sum");
    b.disabled = true;
    try {
      const r = await EA.api("POST", "/api/kb/summarize-batch", { limit: 200, only_missing: true });
      b.disabled = false;
      EA.toast(r.message || `已加入总结队列（${r.processed || 0} 条）`);
      loadKBList(); loadKBStats();
    } catch (e) { b.disabled = false; EA.toast(e.message); }
  };
  // 导入历史：弹窗展示最近导入记录
  $("btn-kb-imports").onclick = async () => {
    try {
      const list = await EA.api("GET", "/api/kb/imports");
      const arr = Array.isArray(list) ? list : (list.items || []);
      const ov = EA.modal("导入历史",
        arr.length ? `<div style="max-height:320px;overflow:auto">${arr.map((r) =>
          `<div class="card" style="padding:8px 10px;margin-bottom:6px;font-size:12px">
             <b>${EA.esc(r.batch_name || r.name || "批量导入")}</b>
             <span class="tag ${r.status === "done" || r.status === "ok" ? "green" : "gold"}" style="margin-left:6px">${EA.esc(r.status || "")}</span>
             <div style="color:var(--text-3);margin-top:3px">${EA.esc(r.total || r.count || 0)} 条 · ${EA.fmtTime(r.created_at)}</div>
           </div>`).join("")}</div>`
          : '<div style="color:var(--text-3);padding:20px;text-align:center">暂无导入记录</div>',
        `<button class="btn" data-x>关闭</button>`);
      ov.querySelector("[data-x]").onclick = () => ov.remove();
    } catch (e) { EA.toast(e.message); }
  };
  // 文档学习：对文档/文本触发学习管线（提炼事实+技能），并查询管线状态
  $("btn-kb-learn").onclick = () => {
    const ov = EA.modal("文档学习",
      `<div class="form-row"><label>文档类型</label><select class="input" id="lr-type"><option value="标准">标准</option><option value="政策">政策</option><option value="技术方案">技术方案</option></select></div>
       <div class="form-row"><label>正文内容</label><textarea class="input" id="lr-text" style="min-height:120px" placeholder="粘贴文档正文…"></textarea></div>
       <div class="form-row"><label>来源</label><input class="input" id="lr-source" placeholder="如：生态环境部公告2026年第X号"></div>`,
      `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>开始学习</button>`);
    ov.querySelector("[data-x]").onclick = () => ov.remove();
    ov.querySelector("[data-ok]").onclick = async () => {
      const text = ov.querySelector("#lr-text").value.trim();
      if (!text) return EA.toast("请粘贴文档正文");
      try {
        const r = await EA.api("POST", "/api/v2/learning/learn", { report_type: ov.querySelector("#lr-type").value, text, source: ov.querySelector("#lr-source").value });
        ov.remove(); EA.toast(r.message || "学习完成"); loadKBList(); loadKBStats();
      } catch (e) { EA.toast(e.message); }
    };
  };
  $("btn-kb-harvest").onclick = () => {
    const ov = EA.modal("标准采集",
      `<div class="form-row"><label>采集主题</label><input class="input" id="hv-title" placeholder="如：2026年生态环境监测标准发布公告"></div>
       <div class="form-row"><label>问答对（JSON，可选）</label><textarea class="input" id="hv-qa" style="min-height:70px" placeholder='[{"q":"...","a":"..."}]'></textarea></div>
       <div style="color:var(--text-3);font-size:11px">从外部政策/标准源采集并入库知识库</div>`,
      `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>开始采集</button>`);
    ov.querySelector("[data-x]").onclick = () => ov.remove();
    ov.querySelector("[data-ok]").onclick = async () => {
      let qa = [];
      try { const t = ov.querySelector("#hv-qa").value.trim(); if (t) qa = JSON.parse(t); }
      catch (_) { return EA.toast("问答对 JSON 格式错误"); }
      try {
        const r = await EA.api("POST", "/api/kb/harvest", { title: ov.querySelector("#hv-title").value, qa_pairs: qa, prefs: {}, facts: [] });
        ov.remove(); EA.toast(r.message || "采集完成"); loadKBList(); loadKBStats();
      } catch (e) { EA.toast(e.message); }
    };
  };
  // 冲突检测：标准版本冲突列表
  $("btn-kb-conflicts").onclick = async () => {
    try {
      const list = await EA.api("GET", "/api/kb/conflicts");
      const arr = Array.isArray(list) ? list : (list.conflicts || []);
      const ov = EA.modal("冲突检测",
        arr.length ? `<div style="max-height:340px;overflow:auto">${arr.map((c) =>
          `<div class="card" style="padding:8px 10px;margin-bottom:6px;font-size:12px">
             <b>${EA.esc(c.title || c.name || "冲突条目")}</b>
             <span class="tag gold" style="margin-left:6px">${EA.esc(c.conflict_type || c.type || "版本冲突")}</span>
             <div style="color:var(--text-2);margin-top:3px">${EA.esc(c.detail || c.issue || "")}</div>
           </div>`).join("")}</div>`
          : '<div style="color:var(--text-3);padding:20px;text-align:center">未检测到冲突，知识库状态健康</div>',
        `<button class="btn" data-x>关闭</button>`);
      ov.querySelector("[data-x]").onclick = () => ov.remove();
    } catch (e) { EA.toast(e.message); }
  };
  // 导出：选择格式与领域范围，直接下载 zip
  $("btn-kb-export").onclick = () => {
    const ov = EA.modal("导出知识库",
      `<div class="form-row"><label>格式</label>
        <select class="input" id="exp-fmt">
          <option value="json">JSON（完整结构化）</option>
          <option value="md">Markdown（纯文本）</option>
        </select></div>
       <div class="form-row"><label>领域范围（留空=全部）</label>
        <select class="input" id="exp-domain">
          <option value="">全部领域</option>
          <option value="standard">标准规范</option>
          <option value="policy">政策法规</option>
          <option value="technology">技术导则</option>
        </select></div>`,
      `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>导出并下载</button>`);
    ov.querySelector("[data-x]").onclick = () => ov.remove();
    ov.querySelector("[data-ok]").onclick = () => {
      const fmt = ov.querySelector("#exp-fmt").value;
      const domain = ov.querySelector("#exp-domain").value;
      const url = `/api/kb/export/download?fmt=${fmt}${domain ? "&domain=" + encodeURIComponent(domain) : ""}`;
      // 新窗口触发下载
      const w = window.open(url, "_blank");
      if (!w) EA.toast("浏览器拦截了下载，请允许弹出窗口");
      else { ov.remove(); EA.toast("导出任务已开始"); }
    };
  };
}

function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

async function loadKBStats() {
  try {
    const s = await EA.api("GET", "/api/kb/stats");
    const total = s.total || s.count || 0;
    const cats = s.categories || s.by_category || {};
    const byItem = s.by_item_type || {};
    const std = cats.standard || s.std || 0;
    const policy = cats.policy || s.policy || 0;
    const gov = cats.gov || s.gov || 0;
    const draft = cats.draft || s.draft || 0;
    const net = cats.network || s.network || 0;
    $("kb-stats-row").innerHTML = `
      <div class="card stat"><div class="n">${EA.fmtNum(total)}</div><div class="l">条目总数</div></div>
      <div class="card stat"><div class="n">${EA.fmtNum(std)}</div><div class="l">标准规范</div></div>
      <div class="card stat"><div class="n">${EA.fmtNum(policy + gov)}</div><div class="l">政策法规</div></div>
      <div class="card stat"><div class="n" style="color:var(--amber)">${EA.fmtNum(draft)}</div><div class="l">征求意见稿</div></div>`;
  } catch (_) {}
}

async function loadKBList() {
  const q = $("kb-q").value.trim();
  const { seg, cat } = EA._kbState;
  let items = [];
  try {
    if (q) {
      const path = seg === "hybrid" ? "/api/kb/hybrid" : seg === "vector" ? "/api/kb/vector" : "/api/kb/search";
      const r = await EA.api("GET", `${path}?q=${encodeURIComponent(q)}${cat ? "&category=" + encodeURIComponent(cat) : ""}`);
      items = Array.isArray(r) ? r : (r.results || r.items || []);
    } else {
      const r = await EA.api("GET", `/api/kb${cat ? "?category=" + encodeURIComponent(cat) : ""}`);
      items = Array.isArray(r) ? r : (r.items || r.results || []);
    }
  } catch (_) { items = []; }
  const el = $("kb-entries");
  if (!el) return;
  el.innerHTML = items.map((e) => {
    const code = e.standard_code || e.std_no || "";
    const src = e.source || e.source_type || "";
    return `<div class="eitem ${EA._kbState.cur && EA._kbState.cur.id === e.id ? "on" : ""}" data-id="${e.id}">
      <div class="t" title="${EA.esc(e.title || "")}">${EA.esc(e.title || "未命名")}${code ? ` <span class="mono" style="font-size:11px;color:var(--text-3)">${EA.esc(code)}</span>` : ""}</div>
      <div class="m"><span class="tag blue" style="padding:0 6px">${EA._KB_CAT_LABEL(e.category)}</span>
      <span>${EA.esc(e.validity || "")}</span>
      ${e.score ? `<span class="tag amber" style="padding:0 6px">相关度 ${Math.round(e.score * 100)}%</span>` : ""}
      <span>${EA.esc(src)}</span></div>
    </div>`;
  }).join("") || '<div style="color:var(--text-3);font-size:12px;padding:20px;text-align:center">无匹配条目</div>';
  el.querySelectorAll(".eitem").forEach((it) => it.onclick = () => openKBEntry(Number(it.dataset.id)));
}

async function openKBEntry(eid) {
  try {
    const e = await EA.api("GET", `/api/kb/${eid}`);
    EA._kbState.cur = e;
    loadKBList();
    renderKBDetail(e);
    renderKBSide(e);
  } catch (err) { EA.toast(err.message); }
}

function renderKBDetail(e) {
  const d = $("kb-detail");
  d.innerHTML = `
    <div class="kb-head">
      <h2 style="font-size:18px">${EA.esc(e.title || e.name || "")}</h2>
      <span class="tag blue">${EA._KB_CAT_LABEL(e.category)}</span>
      <span class="tag ${(e.validity || "").includes("已废止") || (e.validity || "").includes("废止") ? "red" : "green"}">${EA.esc(e.validity || "现行")}</span>
      ${e.standard_code || e.std_no ? `<span class="tag amber mono">${EA.esc(e.standard_code || e.std_no)}</span>` : ""}
      <span class="sp" style="flex:1"></span>
      <button class="btn sm" id="btn-kb-edit">编辑</button>
      <button class="btn sm" id="btn-kb-correct">纠错</button>
      <button class="btn sm danger" id="btn-kb-del">删除</button>
    </div>
    <div class="kb-ai-wrap" id="kb-ai-wrap"><div class="kb-ai-box"></div><div class="kb-ai" id="kb-ai"></div></div>
    <div class="kb-body">
      <div class="body-text">${EA.esc(e.content || "")}</div>
      <div style="color:var(--text-2);font-size:13px;margin-top:12px">来源：${EA.esc(e.source || "—")} · 类型：${EA.esc(e.item_type || "—")} · 入库 ${EA.fmtTime(e.created_at)}</div>
    </div>`;
  loadKBAI(e.id);
  $("btn-kb-edit").onclick = () => {
    const t = e.title || "", c = e.content || "", cat = e.category || "其他";
    d.innerHTML = `
      <div class="kb-head">
        <h2 style="font-size:18px">编辑条目</h2><span class="sp" style="flex:1"></span>
        <button class="btn sm" id="btn-kb-save-edit">保存</button><button class="btn sm" id="btn-kb-cancel-edit">取消</button>
      </div>
      <div class="kb-body">
        <input class="input" id="kb-e-title" value="${EA.esc(t)}" style="width:100%;margin-bottom:8px">
        <select class="input" id="kb-e-cat" style="width:100%;margin-bottom:8px">
          ${EA._KB_CATS.filter((c) => c.v).map((c) => `<option value="${c.v}" ${cat === c.v ? "selected" : ""}>${c.label}</option>`).join("")}
        </select>
        <textarea class="input" id="kb-e-content" style="width:100%;min-height:280px">${EA.esc(c)}</textarea>
      </div>`;
    $("btn-kb-save-edit").onclick = async () => {
      try {
        await EA.api("PUT", `/api/kb/${e.id}`, { title: $("kb-e-title").value, category: $("kb-e-cat").value, content: $("kb-e-content").value });
        EA.toast("已保存"); openKBEntry(e.id);
      } catch (err) { EA.toast(err.message); }
    };
    $("btn-kb-cancel-edit").onclick = () => renderKBDetail(e);
  };
  $("btn-kb-del").onclick = () => EA.confirm("确认删除该条目？", async () => {
    try { await EA.api("DELETE", `/api/kb/${e.id}`); EA._kbState.cur = null; loadKBList(); $("kb-detail").innerHTML = '<div style="color:var(--text-3);padding:40px;text-align:center">条目已删除</div>'; $("kb-side").innerHTML = ""; loadKBStats(); } catch (err) { EA.toast(err.message); }
  });
  // 条目纠错：提交问题描述 + 修改建议，生成纠错记录待核验
  const correctBtn = $("btn-kb-correct");
  if (correctBtn) {
    correctBtn.onclick = () => {
      const ov = EA.modal("条目纠错",
        `<div class="form-row"><label>问题描述</label><textarea class="input" id="cor-issue" style="min-height:80px" placeholder="请描述发现的问题，如标准号/章节/数值有误"></textarea></div>
         <div class="form-row"><label>修改建议</label><textarea class="input" id="cor-sug" style="min-height:80px" placeholder="建议如何修正（可选）"></textarea></div>`,
        `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>提交纠错</button>`);
      ov.querySelector("[data-x]").onclick = () => ov.remove();
      ov.querySelector("[data-ok]").onclick = async () => {
        const issue = ov.querySelector("#cor-issue").value.trim();
        if (!issue) return EA.toast("请填写问题描述");
        try {
          await EA.api("POST", `/api/kb/${e.id}/correct`, { issue, suggestion: ov.querySelector("#cor-sug").value.trim(), corrected_content: "", reporter: "user" });
          ov.remove(); EA.toast("纠错已提交，等待核验");
        } catch (err) { EA.toast(err.message); }
      };
    };
  }
}

// 加载该条目已有的 AI 解读/摘要，展示在详情区头部下方（方案A：生成后立即可见）
async function loadKBAI(eid) {
  const ai = $("kb-ai");
  if (!ai) return;
  const wrap = $("kb-ai-wrap");
  const parts = [];
  try {
    const r = await EA.api("GET", `/api/kb/${eid}/interpret`);
    if (r && (r.interpret || r.report)) parts.push(`<b>解读：</b>${EA.esc(EA.kbAiText(r.interpret || r.report))}`);
  } catch (_) {}
  try {
    const r = await EA.api("GET", `/api/kb/${eid}/summarize`);
    if (r && r.summary) parts.push(`<b>摘要：</b>${EA.esc(EA.kbAiText(r.summary))}`);
  } catch (_) {}
  if (parts.length) {
    ai.innerHTML = parts.join('<div style="height:8px"></div>');
    ai.style.display = "block";
    if (wrap) wrap.style.display = "block";
  } else {
    ai.innerHTML = "";
    ai.style.display = "none";
    if (wrap) wrap.style.display = "none";
  }
}

async function renderKBSide(e) {
  const s = $("kb-side");
  s.innerHTML = `<h4>AI 解读</h4><div class="card" style="padding:12px;font-size:12px;color:var(--text-2)" id="kb-iv"></div>
    <h4>时效检查</h4><div class="card" style="padding:12px;font-size:12px" id="kb-cc"></div>
    <h4>分块与向量</h4><div id="kb-chunks"></div>
    <h4>操作</h4><div style="display:flex;gap:6px;flex-wrap:wrap" id="kb-side-ops"></div>`;
  const iv = s.querySelector("#kb-iv");
  // 生成解读 / 生成摘要按钮单行并排，结果区独立
  iv.innerHTML = '<div style="display:flex;gap:6px;margin-bottom:6px"><button class="btn sm" data-a="iv" style="flex:1;justify-content:center">生成解读</button><button class="btn sm" data-a="sum" style="flex:1;justify-content:center">生成摘要</button></div><div id="kb-iv-out" style="color:var(--text-3)">点击按钮，后台队列生成</div>';
  const ivOut = iv.querySelector("#kb-iv-out");
  const pollKb = (kind, title) => {
    const ep = kind === "iv" ? "interpret" : "summarize";
    let n = 0;
    const timer = setInterval(async () => {
      n++;
      try {
        const r = await EA.api("GET", `/api/kb/${e.id}/${ep}`);
        const raw = kind === "iv" ? (r.interpret || r.report || "") : (r.summary || "");
        const txt = EA.kbAiText(raw);
        if (txt) { ivOut.innerHTML = `<b>${EA.esc(title)}：</b>${EA.esc(txt)}`; loadKBAI(e.id); clearInterval(timer); return; }
      } catch (_) {}
      if (n >= 8) { clearInterval(timer); ivOut.textContent = "仍在后台生成中，稍后可重新打开条目查看"; }
    }, 1500);
  };
  iv.querySelector("[data-a=iv]").onclick = async () => {
    try { await EA.api("POST", `/api/kb/${e.id}/interpret`); ivOut.textContent = "已加入解读队列，正在生成…"; pollKb("iv", "解读"); }
    catch (err) { ivOut.textContent = err.message; }
  };
  iv.querySelector("[data-a=sum]").onclick = async () => {
    try { await EA.api("POST", `/api/kb/${e.id}/summarize`); ivOut.textContent = "已加入摘要队列，正在生成…"; pollKb("sum", "摘要"); }
    catch (err) { ivOut.textContent = err.message; }
  };
  const cc = s.querySelector("#kb-cc");
  cc.innerHTML = `<span class="tag green">${EA.esc(e.validity || "现行有效")}</span>
    <button class="btn sm" style="margin-top:6px" id="btn-cc-check">立即查新</button>`;
  cc.querySelector("#btn-cc-check").onclick = async () => {
    try { const r = await EA.api("POST", `/api/kb/${e.id}/currency-check`); cc.innerHTML = EA.esc(r.message || r.report || "查新完成"); } catch (err) { cc.textContent = err.message; }
  };
  const ch = s.querySelector("#kb-chunks");
  ch.innerHTML = '<button class="btn sm" style="width:100%;justify-content:center">查看分块</button>';
  ch.querySelector("button").onclick = async () => {
    try {
      const r = await EA.api("GET", `/api/kb/chunks/${e.id}`);
      const arr = Array.isArray(r) ? r : (r.chunks || []);
      ch.innerHTML = arr.map((c, i) =>
        `<div class="chunk"><b>#${i + 1}</b> ${EA.esc((c.text || c.content || "").slice(0, 90))}</div>`).join("") ||
        '<div class="chunk">暂无分块</div>';
    } catch (err) { ch.textContent = err.message; }
  };
  const ops = s.querySelector("#kb-side-ops");
  ops.innerHTML = `<button class="btn sm" data-o="rel">建立关联</button><button class="btn sm" data-o="audit">审计</button>`;
  ops.querySelector("[data-o=audit]").onclick = async () => { try { await EA.api("POST", "/api/kb/audit"); EA.toast("审计已触发"); } catch (err) { EA.toast(err.message); } };
  ops.querySelector("[data-o=rel]").onclick = () => {
    const ov = EA.modal("建立关联",
      `<div class="form-row"><label>目标条目 ID</label><input class="input" id="rel-target" placeholder="数字 ID"></div>
       <div class="form-row"><label>关系类型</label><input class="input" id="rel-type" value="引用"></div>`,
      `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>保存</button>`);
    ov.querySelector("[data-x]").onclick = () => ov.remove();
    ov.querySelector("[data-ok]").onclick = async () => {
      try {
        await EA.api("POST", `/api/kb/${e.id}/relation`, { target_id: Number(ov.querySelector("#rel-target").value), type: ov.querySelector("#rel-type").value });
        ov.remove(); EA.toast("已关联");
      } catch (err) { EA.toast(err.message); }
    };
  };
}
