/* 07 记忆中心 + 08 技能 + 09 计划调度 */
"use strict";

/* ==================== 07 记忆中心 ==================== */
EA.onView("memory", function () {
  document.getElementById("v-memory").innerHTML = `
  <div class="topbar">
    <h1>记忆中心</h1><span class="crumb">四层记忆 · 事实审批 · 记忆图谱</span><span class="sp"></span>
    <button class="btn sm" id="btn-mem-route">跨层检索</button>
    <button class="btn sm danger" id="btn-mem-clear">清空画像</button>
  </div>
  <div class="content">
    <div class="tabs" id="mem-tabs" style="margin-bottom:16px">
      <button data-t="working">工作记忆</button><button data-t="episodic" class="active">情景记忆</button>
      <button data-t="procedural">程序记忆</button><button data-t="profile">用户画像</button>
      <button data-t="facts">事实审批 <span class="tag red" style="margin-left:4px" id="mem-fact-count">0</span></button>
      <button data-t="graph">记忆图谱</button>
      <button data-t="assets">资产治理</button>
      <button data-t="wiki">知识库 Wiki</button>
      <button data-t="bench">评测报告</button>
    </div>
    <div id="mem-body"></div>
  </div>`;
  document.querySelectorAll("#mem-tabs button").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll("#mem-tabs button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active"); loadMemTab(b.dataset.t);
    };
  });
  $("btn-mem-route").onclick = async () => {
    const ov = EA.modal("跨层检索", `<div class="form-row"><label>关键词</label><input class="input" id="mr-q" placeholder="跨层统一检索"></div>`,
      `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>检索</button>`);
    ov.querySelector("[data-x]").onclick = () => ov.remove();
    ov.querySelector("[data-ok]").onclick = async () => {
      try {
        const r = await EA.api("GET", `/api/v2/memory/route-search?q=${encodeURIComponent(ov.querySelector("#mr-q").value)}`);
        ov.remove();
        const arr = Array.isArray(r) ? r : (r.results || []);
        EA.modal("检索结果", arr.slice(0, 15).map((x) =>
          `<div style="font-size:12px;color:var(--text-2);padding:6px 0;border-bottom:1px dashed var(--line)">${EA.esc(x.text || x.content || x.key || JSON.stringify(x).slice(0, 100))}</div>`).join("") || "<div style='color:var(--text-3)'>无结果</div>",
          `<button class="btn" data-x>关闭</button>`);
        document.querySelector(".overlay [data-x]").onclick = () => document.querySelector(".overlay").remove();
      } catch (e) { EA.toast(e.message); }
    };
  };
  $("btn-mem-clear").onclick = () => EA.confirm("清空用户画像？此操作不可恢复。", async () => {
    try { await EA.api("DELETE", "/api/v2/memory/profile"); EA.toast("已清空"); loadMemTab("profile"); } catch (e) { EA.toast(e.message); }
  });
  loadMemTab("episodic");
});

async function loadMemTab(tab) {
  const body = $("mem-body");
  if (!body) return;
  body.innerHTML = '<div style="color:var(--text-3);padding:20px">加载中…</div>';
  if (tab === "working") {
    try { const r = await EA.api("GET", "/api/v2/memory/working"); const arr = Array.isArray(r) ? r : (r.working || r.items || []); body.innerHTML = memKVList(arr); } catch (e) { body.innerHTML = "<div style='color:var(--red)'>" + EA.esc(e.message) + "</div>"; }
  } else if (tab === "episodic") {
    try { const r = await EA.api("GET", "/api/v2/memory/episodic"); const arr = Array.isArray(r) ? r : (r.episodic || r.events || []); body.innerHTML = `<div class="card mcard"><div class="hd"><b>情景记忆 · 时间轴</b></div><div class="tl">${arr.map((x) => `<div class="it"><b>${EA.fmtTime(x.time || x.ts || x.created_at)}</b> ${EA.esc(x.event || x.content || x.text || "")}</div>`).join("") || '<div class="empty">暂无情景记忆</div>'}</div></div>`; } catch (e) { body.innerHTML = "<div style='color:var(--red)'>" + EA.esc(e.message) + "</div>"; }
  } else if (tab === "procedural") {
    try { const r = await EA.api("GET", "/api/v2/memory/procedural"); const arr = Array.isArray(r) ? r : (r.procedural || r.items || []); body.innerHTML = `<div class="card mcard"><div class="hd"><b>程序记忆（SOP）</b></div>${arr.map((x) => `<div class="kvline"><span>${EA.esc(x.name || x.key || "")}</span><b>${EA.esc(x.summary || x.desc || "")}</b></div>`).join("") || '<div class="empty">暂无程序记忆</div>'}</div>`; } catch (e) { body.innerHTML = "<div style='color:var(--red)'>" + EA.esc(e.message) + "</div>"; }
  } else if (tab === "profile") {
    try {
      const r = await EA.api("GET", "/api/v2/memory/profile");
      const p = r.profile || r || {};
      body.innerHTML = `<div class="card mcard"><div class="hd"><b>用户画像</b><button class="btn sm" id="btn-prof-distill">蒸馏更新</button></div>
        ${Object.entries(p).filter(([k]) => k !== "ok").map(([k, v]) => `<div class="kvline"><span>${EA.esc(k)}</span><b>${EA.esc(typeof v === "object" ? JSON.stringify(v) : v)}</b></div>`).join("") || '<div class="empty">画像为空，可进行蒸馏</div>'}</div>`;
      const d = $("btn-prof-distill");
      if (d) d.onclick = async () => { try { await EA.api("POST", "/api/v2/memory/profile/distill"); EA.toast("已蒸馏"); loadMemTab("profile"); } catch (e) { EA.toast(e.message); } };
    } catch (e) { body.innerHTML = "<div style='color:var(--red)'>" + EA.esc(e.message) + "</div>"; }
  } else if (tab === "facts") {
    try {
      const r = await EA.api("GET", "/api/v2/memory/facts/pending");
      const arr = Array.isArray(r) ? r : (r.pending || r.facts || []);
      $("mem-fact-count").textContent = arr.length;
      // 事实审批已统一移入审核中心；此处展示待审批列表 + 一键批量通过（conclusion 类除外）
      body.innerHTML = `<div class="card mcard"><div class="hd"><b>待审批事实（${arr.length}）</b>
        <div style="display:flex;gap:6px"><button class="btn sm" id="btn-facts-add">新增事实</button><button class="btn sm" id="btn-facts-summary">任务摘要</button>
        <button class="btn sm gold" id="btn-facts-approve-all">全部通过</button>
        <a class="btn sm" href="#review" style="text-decoration:none">去审核中心逐条处理</a></div></div>
        <div style="font-size:11px;color:var(--text-3);padding:0 12px 8px">标准编号事实已自动沉淀激活；偏好/约束可"全部通过"一键批量激活（结论类保留人工核对）</div>
        ${arr.map((f, i) => `<div class="fact"><span class="s">${EA.esc(f.subject || f.s || "")}</span><span class="p">${EA.esc(f.predicate || f.p || "→")}</span><span>${EA.esc(f.object || f.o || "")}</span></div>`).join("") || '<div class="empty">暂无待审批事实</div>'}</div>`;
      // 手动提交事实
      $("btn-facts-add").onclick = () => {
        const ov = EA.modal("新增事实",
          `<div class="form-row"><label>主体</label><input class="input" id="f-s" placeholder="如：某污水处理厂"></div>
           <div class="form-row"><label>谓词</label><input class="input" id="f-p" placeholder="如：COD 排放浓度"></div>
           <div class="form-row"><label>客体</label><input class="input" id="f-o" placeholder="如：32 mg/L"></div>
           <div class="form-row"><label>置信度</label><input class="input" id="f-c" type="number" min="0" max="1" step="0.1" value="0.9"></div>`,
          `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>提交</button>`);
        ov.querySelector("[data-x]").onclick = () => ov.remove();
        ov.querySelector("[data-ok]").onclick = async () => {
          try {
            await EA.api("POST", "/api/v2/memory/facts", {
              entity: ov.querySelector("#f-s").value, attr: ov.querySelector("#f-p").value,
              value: ov.querySelector("#f-o").value,
            });
            ov.remove(); EA.toast("事实已提交"); loadMemTab("facts"); EA.updateNavDots();
          } catch (e) { EA.toast(e.message); }
        };
      };
      // V3 批量审批：一键通过全部 pending 事实（conclusion 类由后端跳过）
      const ba = $("btn-facts-approve-all");
      if (ba) ba.onclick = async () => {
        try {
          const r = await EA.api("POST", "/api/v2/memory/facts/approve-all");
          EA.toast(`已通过 ${(r.approved || []).length} 条，保留 ${r.skipped || 0} 条待人工核对`);
          loadMemTab("facts"); EA.updateNavDots();
        } catch (e) { EA.toast(e.message); }
      };
      // 任务摘要：三层记忆摘要（工作/情景/程序）
      $("btn-facts-summary").onclick = async () => {
        try {
          const r = await EA.api("GET", "/api/v2/memory/task-summary");
          const s = r && typeof r === "object" ? (r.summary || r) : {};
          const mk = (k, v) => v ? `<div style="font-size:12px;color:var(--text-2);margin-bottom:6px"><b>${EA.esc(k)}</b><div style="white-space:pre-wrap;margin-top:2px">${EA.esc(String(v).slice(0, 200))}</div></div>` : "";
          const body = [mk("工作摘要", s.work || s.work_summary), mk("情景摘要", s.situational || s.context), mk("程序摘要", s.procedural || s.procedure)].join("") || '<div style="color:var(--text-3)">暂无任务摘要</div>';
          const ov = EA.modal("任务摘要", body, `<button class="btn" data-x>关闭</button>`);
          ov.querySelector("[data-x]").onclick = () => ov.remove();
        } catch (e) { EA.toast(e.message); }
      };
    } catch (e) { body.innerHTML = "<div style='color:var(--red)'>" + EA.esc(e.message) + "</div>"; }
  } else if (tab === "graph") {
    body.innerHTML = `<div class="card mcard graph-box"><div class="hd"><b>记忆图谱</b><div><button class="btn sm" id="btn-g-link">自动连边</button> <button class="btn sm" id="btn-g-extract">抽取建图</button></div></div>
      <div style="position:relative;height:320px;overflow:hidden" id="mem-graph"></div></div>`;
    $("btn-g-link").onclick = async () => { try { await EA.api("POST", "/api/v2/memory/graph/link-facts"); EA.toast("已连边"); loadMemTab("graph"); } catch (e) { EA.toast(e.message); } };
    $("btn-g-extract").onclick = async () => {
      const ov = EA.modal("从文本抽取建图", `<textarea class="input" id="g-text" style="width:100%;min-height:120px" placeholder="粘贴文本"></textarea>`,
        `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>抽取</button>`);
      ov.querySelector("[data-x]").onclick = () => ov.remove();
      ov.querySelector("[data-ok]").onclick = async () => { try { await EA.api("POST", "/api/v2/memory/graph/extract", { text: ov.querySelector("#g-text").value }); ov.remove(); EA.toast("已抽取"); loadMemTab("graph"); } catch (e) { EA.toast(e.message); } };
    };
    loadGraph();
  } else if (tab === "assets") {
    loadMemAssets();
  } else if (tab === "wiki") {
    loadMemWiki();
  } else if (tab === "bench") {
    loadMemBench();
  }
}

async function loadMemAssets() {
  const body = $("mem-body");
  if (!body) return;
  body.innerHTML = '<div style="color:var(--text-3);padding:20px">加载中…</div>';
  const stSel = $("ass-status");
  const st = stSel ? stSel.value : "active";
  try {
    const r = await EA.api("GET", "/api/v2/memory/assets?status=" + encodeURIComponent(st));
    const assets = r.assets || [];
    const stats = r.stats || { by_type: {}, by_visibility: {}, total: 0 };
    const typeCn = { episodic: "情景", fact: "事实", skill: "技能", profile: "画像", summary: "摘要", wiki: "知识库", canvas: "画布" };
    const visCn = { private: "私密", team: "团队", agent: "全局" };
    const statCard = (label, n, color) => `<div class="stat-card"><span class="sc-n" style="color:${color}">${n}</span><span class="sc-l">${label}</span></div>`;
    const typeColors = { episodic: "#2b6cb0", fact: "#2f855a", skill: "#b7791f", profile: "#805ad5", summary: "#c53030", wiki: "#0e7490", canvas: "#64748b" };
    const cards = Object.entries({ ...typeCn }).map(([k, l]) => statCard(l, stats.by_type[k] || 0, typeColors[k] || "#64748b")).join("");
    body.innerHTML = `
      <div class="stat-grid">${statCard("全部资产", stats.total, "var(--navy)")}${cards}</div>
      <div class="mem-toolbar">
        <input class="input" id="ass-q" placeholder="搜索标题/预览/ID" style="flex:1;min-width:140px">
        <select class="input" id="ass-type" style="width:110px"><option value="">全部类型</option><option>episodic</option><option>fact</option><option>skill</option><option>profile</option><option>summary</option><option>wiki</option><option>canvas</option></select>
        <select class="input" id="ass-vis" style="width:100px"><option value="">全部可见性</option><option value="private">私密</option><option value="team">团队</option><option value="agent">全局</option></select>
        <select class="input" id="ass-status" style="width:110px"><option value="active">仅活跃</option><option value="archived">已归档</option><option value="">全部</option></select>
        <button class="btn sm" id="ass-refresh">刷新</button>
        <button class="btn sm gold" id="ass-summaries">任务摘要</button>
      </div>
      <div class="card mcard" style="padding:0;overflow:hidden">
        <table class="mem-table"><thead><tr><th>类型</th><th>标题 / 内容预览</th><th>可见性</th><th>使用</th><th>状态</th><th>更新时间</th><th style="width:130px">操作</th></tr></thead>
        <tbody>${assets.map((a) => {
          const aid = EA.esc(a.asset_id);
          return `<tr data-id="${aid}"><td><span class="tag" style="background:${typeColors[a.asset_type] || "#64748b"};color:#fff">${typeCn[a.asset_type] || a.asset_type}</span></td>
          <td><b>${EA.esc(a.title || "")}</b>${a.content_preview ? `<div class="cell-preview">${EA.esc(a.content_preview)}</div>` : ""}</td>
          <td><select class="input vis-sel" data-id="${aid}">${Object.entries(visCn).map(([k, l]) => `<option value="${k}" ${a.visibility === k ? "selected" : ""}>${l}</option>`).join("")}</select></td>
          <td>${a.use_count || 0}</td><td>${a.status === "archived" ? '<span class="tag gray">已归档</span>' : '<span class="tag" style="background:var(--green);color:#fff">活跃</span>'}</td>
          <td class="mono-sm">${EA.fmtTime(a.updated_at)}</td>
          <td><button class="btn sm mini-btn ${a.status === "archived" ? "" : "gold"}" data-arch="${aid}" data-cur="${a.status}">${a.status === "archived" ? "恢复" : "归档"}</button> <button class="btn sm mini-btn danger" data-del="${aid}">删除</button></td></tr>`;
        }).join("") || '<tr><td colspan="7" class="empty" style="text-align:center;padding:24px">暂无资产，完成任务后自动沉淀</td></tr>'}</tbody></table>
      </div>`;
    // 搜索 / 过滤
    const applyFilter = () => {
      const q = ($("ass-q").value || "").toLowerCase();
      const t = $("ass-type").value, v = $("ass-vis").value;
      document.querySelectorAll("#mem-body tbody tr").forEach((tr) => {
        const a = assets.find((x) => x.asset_id === tr.dataset.id);
        if (!a) return;
        const hitQ = !q || (a.title || "").toLowerCase().includes(q) || (a.content_preview || "").toLowerCase().includes(q) || (a.asset_id || "").toLowerCase().includes(q);
        const hitT = !t || a.asset_type === t, hitV = !v || a.visibility === v;
        tr.style.display = hitQ && hitT && hitV ? "" : "none";
      });
    };
    ["ass-q", "ass-type", "ass-vis"].forEach((id) => { const el = $(id); if (el) el.addEventListener("input", applyFilter); });
    // 状态过滤：重新拉取
    const assSt = $("ass-status");
    if (assSt) assSt.addEventListener("change", () => loadMemAssets());
    // 刷新
    const rf = $("ass-refresh");
    if (rf) rf.onclick = () => loadMemAssets();
    // 任务摘要
    const sm = $("ass-summaries");
    if (sm) sm.onclick = () => openSummariesModal();
    // 可见性修改
    document.querySelectorAll("#mem-body .vis-sel").forEach((sel) => {
      sel.onchange = async () => {
        try { await EA.api("PATCH", "/api/v2/memory/assets/" + encodeURIComponent(sel.dataset.id), { visibility: sel.value }); EA.toast("已更新可见性"); } catch (e) { EA.toast(e.message); }
      };
    });
    // 归档/恢复
    document.querySelectorAll("#mem-body [data-arch]").forEach((b) => {
      b.onclick = async () => {
        const next = b.dataset.cur === "archived" ? "active" : "archived";
        try { await EA.api("PATCH", "/api/v2/memory/assets/" + encodeURIComponent(b.dataset.arch), { status: next }); loadMemAssets(); } catch (e) { EA.toast(e.message); }
      };
    });
    // 删除
    document.querySelectorAll("#mem-body [data-del]").forEach((b) => {
      b.onclick = () => EA.confirm("删除该资产登记？（仅删资产目录，底层记忆保留）", async () => {
        try { await EA.api("DELETE", "/api/v2/memory/assets/" + encodeURIComponent(b.dataset.del)); EA.toast("已删除"); loadMemAssets(); } catch (e) { EA.toast(e.message); }
      });
    });
  } catch (e) {
    body.innerHTML = "<div style='color:var(--red)'>" + EA.esc(e.message) + "</div>";
  }
}

async function openSummariesModal() {
  const ov = EA.modal("任务摘要（L2 场景记忆）", '<div id="sums-body" style="color:var(--text-3)">加载中…</div>',
    `<button class="btn" data-x>关闭</button>`);
  ov.querySelector("[data-x]").onclick = () => ov.remove();
  try {
    const r = await EA.api("GET", "/api/v2/memory/summaries");
    const sums = r.summaries || [];
    const box = ov.querySelector("#sums-body");
    if (!sums.length) { box.innerHTML = '<div class="empty" style="text-align:center;padding:24px">暂无任务摘要</div>'; return; }
    box.innerHTML = sums.map((s) => `
      <div class="sum-item">
        <div class="sum-hd"><b>${EA.esc(s.title || s.task_id || "")}</b><span class="mono-sm">${EA.fmtTime(s.created_at)}</span></div>
        <div class="sum-ab">${EA.esc((s.abstract || "").slice(0, 120))}</div>
        <div class="sum-ops">
          <button class="btn sm mini-btn" data-view="${EA.esc(s.task_id)}">查看全文</button>
          <button class="btn sm mini-btn danger" data-del="${EA.esc(s.task_id)}">删除</button>
        </div>
      </div>`).join("") || '<div class="empty" style="text-align:center;padding:24px">暂无任务摘要</div>';
    box.querySelectorAll("[data-view]").forEach((b) => {
      b.onclick = () => {
        const s = sums.find((x) => String(x.task_id) === String(b.dataset.view));
        if (!s) return;
        const ov2 = EA.modal("任务摘要全文", `<div style="font-size:12px;color:var(--text-2);line-height:1.8"><b>${EA.esc(s.title || "")}</b><div style="margin:8px 0;color:var(--text-3)">${EA.fmtTime(s.created_at)}</div><div style="white-space:pre-wrap">${EA.esc(s.overview || s.abstract || "（无正文）")}</div></div>`, `<button class="btn" data-x>关闭</button>`);
        ov2.querySelector("[data-x]").onclick = () => ov2.remove();
      };
    });
    box.querySelectorAll("[data-del]").forEach((b) => {
      b.onclick = () => EA.confirm("删除该任务摘要？", async () => {
        try { await EA.api("DELETE", "/api/v2/memory/summaries/" + encodeURIComponent(b.dataset.del)); ov.remove(); EA.toast("已删除"); } catch (e) { EA.toast(e.message); }
      });
    });
  } catch (e) {
    const box = ov.querySelector("#sums-body");
    if (box) box.innerHTML = "<div style='color:var(--red)'>" + EA.esc(e.message) + "</div>";
  }
}

async function loadMemWiki() {
  const body = $("mem-body");
  if (!body) return;
  body.innerHTML = '<div style="color:var(--text-3);padding:20px">加载中…</div>';
  try {
    const r = await EA.api("GET", "/api/v2/memory/wiki");
    const wikis = r.wikis || [];
    body.innerHTML = `
      <div class="mem-toolbar">
        <input class="input" id="wiki-q" placeholder="搜索标题/正文/标签" style="flex:1;min-width:160px">
        <button class="btn sm" id="wiki-search">搜索</button>
        <button class="btn sm gold" id="wiki-new">新建条目</button>
      </div>
      <div class="card mcard" style="padding:0;overflow:hidden">
        <table class="mem-table"><thead><tr><th>标题</th><th>摘要</th><th>标签</th><th>来源</th><th>可见性</th><th>使用</th><th>更新时间</th><th style="width:120px">操作</th></tr></thead>
        <tbody>${wikis.map((w) => `<tr data-id="${EA.esc(w.id)}">
          <td><b>${EA.esc(w.title || "")}</b></td>
          <td class="cell-preview">${EA.esc((w.content || "").replace(/[#*>_\-]/g, "").slice(0, 80))}</td>
          <td>${EA.esc(w.tags || "")}</td><td>${EA.esc(w.source || "-")}</td>
          <td><span class="tag" style="background:var(--navy-soft);color:var(--navy)">${w.visibility === "team" ? "团队" : w.visibility === "agent" ? "全局" : "私密"}</span></td>
          <td>${w.use_count || 0}</td><td class="mono-sm">${EA.fmtTime(w.updated_at)}</td>
          <td><button class="btn sm mini-btn" data-view="${EA.esc(w.id)}">查看</button>
          <button class="btn sm mini-btn danger" data-del="${EA.esc(w.id)}">删除</button></td></tr>`).join("") ||
          '<tr><td colspan="8" class="empty" style="text-align:center;padding:24px">暂无 Wiki 条目，点击「新建条目」沉淀文档知识</td></tr>'}</tbody></table>
      </div>`;
    $("wiki-search").onclick = () => loadMemWiki();
    $("wiki-q").addEventListener("keydown", (e) => { if (e.key === "Enter") loadMemWiki(); });
    $("wiki-new").onclick = () => {
      const ov = EA.modal("新建 Wiki 条目",
        `<div class="form-row"><label>标题 *</label><input class="input" id="w-title" placeholder="条目标题"></div>
         <div class="form-row"><label>标签</label><input class="input" id="w-tags" placeholder="逗号分隔"></div>
         <div class="form-row"><label>可见性</label><select class="input" id="w-vis"><option value="private">私密</option><option value="team">团队</option><option value="agent">全局</option></select></div>
         <div class="form-row"><label>正文</label><textarea class="input" id="w-content" rows="8" placeholder="Markdown 正文"></textarea></div>`,
        `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>保存</button>`);
      ov.querySelector("[data-x]").onclick = () => ov.remove();
      ov.querySelector("[data-ok]").onclick = async () => {
        const title = ov.querySelector("#w-title").value.trim();
        if (!title) { EA.toast("标题必填"); return; }
        try {
          await EA.api("POST", "/api/v2/memory/wiki", { title, tags: ov.querySelector("#w-tags").value, visibility: ov.querySelector("#w-vis").value, content: ov.querySelector("#w-content").value });
          ov.remove(); EA.toast("已创建"); loadMemWiki();
        } catch (e) { EA.toast(e.message); }
      };
    };
    document.querySelectorAll("#mem-body [data-view]").forEach((b) => {
      b.onclick = () => {
        const w = wikis.find((x) => x.id === b.dataset.view);
        if (!w) return;
        const ov2 = EA.modal("Wiki: " + (w.title || ""),
          `<div style="font-size:12px;color:var(--text-2);line-height:1.8;white-space:pre-wrap">${EA.esc(w.content || "（无正文）")}</div>
           <div class="mono-sm" style="margin-top:10px">来源: ${EA.esc(w.source || "-")} · 标签: ${EA.esc(w.tags || "-")} · 使用 ${w.use_count || 0} 次</div>`,
          `<button class="btn" data-x>关闭</button>`);
        ov2.querySelector("[data-x]").onclick = () => ov2.remove();
      };
    });
    document.querySelectorAll("#mem-body [data-del]").forEach((b) => {
      b.onclick = () => EA.confirm("删除该 Wiki 条目？", async () => {
        try { await EA.api("DELETE", "/api/v2/memory/wiki/" + encodeURIComponent(b.dataset.del)); EA.toast("已删除"); loadMemWiki(); } catch (e) { EA.toast(e.message); }
      });
    });
  } catch (e) {
    body.innerHTML = "<div style='color:var(--red)'>" + EA.esc(e.message) + "</div>";
  }
}

async function loadMemBench() {
  const body = $("mem-body");
  if (!body) return;
  body.innerHTML = '<div style="color:var(--text-3);padding:20px">评测运行中（离线规则集）…</div>';
  try {
    const r = await EA.api("GET", "/api/v2/memory/bench");
    const d = r.dimensions || [];
    const get = (k, def) => (d.find((x) => x.suite === k) || {}).get ?? def;
    const pct = (v) => (v * 100).toFixed(1) + "%";
    body.innerHTML = `
      <div class="card mcard" style="margin-bottom:12px">
        <div style="font-weight:700;font-size:13px;margin-bottom:10px">EA 记忆评测 · 对齐 TencentDB-Agent-Memory 收益度量</div>
        <div class="stat-grid">
          ${[["检索命中 Recall@K", get("retrieval", 0) && r.dimensions[0].recall != null ? pct(r.dimensions[0].recall) : pct(get("retrieval", 0)), "var(--green)"],
             ["上下文压缩节省", pct(get("compression", 0)), "var(--navy)"],
             ["技能复用命中率", pct(get("skill_reuse", 0)), "var(--gold)"]].map(([l, v, c]) => `<div class="stat-card"><span class="sc-n" style="color:${c}">${v}</span><span class="sc-l">${l}</span></div>`).join("")}
        </div>
        <div class="mono-sm">说明：离线规则评测集，真实数据积累后可在 CLI 扩展。运行 python -m src.memory.bench 获取完整 JSON。</div>
      </div>
      <div class="card mcard" style="padding:0;overflow:hidden">
        <table class="mem-table"><thead><tr><th>维度</th><th>状态</th><th>指标</th><th>样本</th></tr></thead>
        <tbody>${d.map((x) => `<tr><td><b>${x.suite}</b></td><td>${x.ok ? '<span class="tag" style="background:var(--green);color:#fff">通过</span>' : '<span class="tag gray">跳过</span>'}</td>
          <td class="mono-sm">${x.recall != null ? "Recall@" + (x.top_k || 5) + "=" + x.recall : x.token_save != null ? "token_save=" + pct(x.token_save) : x.hit_rate != null ? "hit=" + pct(x.hit_rate) : (x.error || "-")}</td>
          <td>${x.total || 0}</td></tr>`).join("") || '<tr><td colspan="4" class="empty">无数据</td></tr>'}</tbody></table>
      </div>`;
  } catch (e) {
    body.innerHTML = "<div style='color:var(--red)'>" + EA.esc(e.message) + "</div>";
  }
}

function memKVList(arr) {
  return `<div class="card mcard"><div class="hd"><b>工作记忆（当前会话）</b></div>
    ${arr.map((x) => `<div class="kvline"><span>${EA.esc(x.key || "")}</span><b>${EA.esc(x.value || "")}</b></div>`).join("") || '<div class="empty">暂无工作记忆</div>'}</div>`;
}

async function loadGraph() {
  try {
    const r = await EA.api("GET", "/api/v2/memory/graph");
    const nodes = r.nodes || [], edges = r.edges || [];
    const box = $("mem-graph");
    if (!box) return;
    if (!nodes.length) { box.innerHTML = '<div class="empty" style="padding:40px;text-align:center">图谱为空，可执行"抽取建图"</div>'; return; }
    const W = box.clientWidth || 600, H = 300;
    const cx = W / 2, cy = H / 2;
    const pos = nodes.map((n, i) => {
      const a = (i / nodes.length) * Math.PI * 2;
      return { x: cx + Math.cos(a) * (W * 0.32), y: cy + Math.sin(a) * (H * 0.32) };
    });
    const edgesSvg = edges.map((e) => {
      const fi = nodes.findIndex((n) => (n.id ?? n.name) === (e.from ?? e.source));
      const ti = nodes.findIndex((n) => (n.id ?? n.name) === (e.to ?? e.target));
      if (fi < 0 || ti < 0) return "";
      return `<div class="gedge" style="left:${pos[fi].x}px;top:${pos[fi].y}px;width:${Math.max(40, Math.hypot(pos[ti].x - pos[fi].x, pos[ti].y - pos[fi].y))}px;transform:rotate(${Math.atan2(pos[ti].y - pos[fi].y, pos[ti].x - pos[fi].x) * 180 / Math.PI}deg)"></div>`;
    }).join("");
    const nodesHtml = nodes.map((n, i) => {
      const sz = Math.min(100, Math.max(60, String(n.name || n.subject || n.id).length * 14));
      return `<div class="gnode" style="left:${pos[i].x - sz / 2}px;top:${pos[i].y - sz / 2}px;width:${sz}px;height:${sz}px;background:${nodeColor(i)}">${EA.esc(n.name || n.subject || n.id)}</div>`;
    }).join("");
    box.innerHTML = edgesSvg + nodesHtml;
    box.querySelectorAll(".gnode").forEach((g) => g.onclick = async () => {
      try { const nn = await EA.api("GET", `/api/v2/memory/graph/neighbors?id=${encodeURIComponent(g.textContent)}`); EA.modal("邻居", (nn.neighbors || nn.nodes || []).map((x) => `<div style="font-size:12px;padding:4px 0">${EA.esc(x.name || x.id || x)}</div>`).join("") || "<div style='color:var(--text-3)'>无邻居</div>", `<button class="btn" data-x>关闭</button>`); document.querySelector(".overlay [data-x]").onclick = () => document.querySelector(".overlay").remove(); } catch (_) {}
    });
  } catch (_) {}
}

function nodeColor(i) { return ["#1A365D", "#5B7BA6", "#2F9E6E", "#3B6FB5", "#C98A1B", "#6B7B93"][i % 6]; }

/* ==================== 08 技能与市场 ==================== */
EA.onView("skills", function () {
  document.getElementById("v-skills").innerHTML = `
  <div class="topbar">
    <h1>技能与市场</h1><span class="sp"></span>
    <button class="btn sm" id="btn-sk-import">导入技能包</button>
    <button class="btn sm" id="btn-sk-stats">统计</button>
    <button class="btn sm" id="btn-sk-updates">改进提案</button>
    <button class="btn sm gold" id="btn-sk-market">浏览市场</button>
  </div>
  <div class="content">
    <div class="card" style="padding:14px 18px;margin-bottom:18px;display:flex;align-items:center;gap:18px;flex-wrap:wrap">
      <b style="font-size:13px">学习闭环</b>
      <div class="pipe" id="learn-pipe">
        <span class="pstep">观察 --</span><span class="parr"></span>
        <span class="pstep">反思 --</span><span class="parr"></span>
        <span class="pstep hot">结晶待审 0</span><span class="parr"></span>
        <span class="pstep">已固化 0</span>
      </div>
      <span class="sp" style="flex:1"></span>
      <span class="tag green" id="learn-health">管线健康</span>
      <button class="btn sm" id="btn-learn-observe">观察</button>
      <button class="btn sm" id="btn-learn-reflect">反思</button>
      <button class="btn sm" id="btn-learn-crystallize">结晶</button>
      <button class="btn sm" id="btn-learn-reuse">复用</button>
    </div>
    <div class="card queue" style="margin-bottom:18px" id="crystal-queue">
      <b style="font-size:14px">结晶待审（Agent 自学产出）</b>
      <div style="color:var(--text-3);font-size:12px;padding:8px 0">加载中…</div>
    </div>
    <div class="page-head"><h2>已启用技能</h2><span class="sub">GET /api/skills</span></div>
    <div class="sk-grid" style="margin-bottom:24px" id="skill-grid"></div>
    <div class="page-head"><h2>技能市场</h2><span class="sub">GET /api/v2/market/browse</span></div>
    <div style="display:flex;flex-direction:column;gap:10px" id="market-list"></div>
  </div>`;
  // 学习闭环手动触发（观察/反思/结晶/复用）
  $("btn-learn-observe").onclick = () => {
    const ov = EA.modal("触发观察",
      `<div class="form-row"><label>任务描述</label><input class="input" id="ob-task" placeholder="本次任务做什么"></div>
       <div class="form-row"><label>结果</label><select class="input" id="ob-outcome"><option value="partial">部分达成</option><option value="success">成功</option><option value="failed">失败</option></select></div>
       <div class="form-row"><label>反馈</label><input class="input" id="ob-feedback" placeholder="经验教训（可选）"></div>`,
      `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>提交观察</button>`);
    ov.querySelector("[data-x]").onclick = () => ov.remove();
    ov.querySelector("[data-ok]").onclick = async () => {
      try {
        const r = await EA.api("POST", "/api/v2/learn/observe", { task: ov.querySelector("#ob-task").value, outcome: ov.querySelector("#ob-outcome").value, feedback: ov.querySelector("#ob-feedback").value });
        ov.remove(); EA.toast(r.message || r.observation || "观察已记录"); loadSkillsView();
      } catch (e) { EA.toast(e.message); }
    };
  };
  $("btn-learn-reflect").onclick = () => {
    const ov = EA.modal("触发反思",
      `<div class="form-row"><label>领域</label><input class="input" id="rf-domain" placeholder="如 环境监测"></div>
       <div class="form-row"><label>差距/问题</label><textarea class="input" id="rf-gap" style="min-height:60px" placeholder="描述能力差距"></textarea></div>`,
      `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>提交反思</button>`);
    ov.querySelector("[data-x]").onclick = () => ov.remove();
    ov.querySelector("[data-ok]").onclick = async () => {
      try {
        const r = await EA.api("POST", "/api/v2/learn/reflect", { domain: ov.querySelector("#rf-domain").value, gap: ov.querySelector("#rf-gap").value });
        ov.remove(); EA.toast(r.message || "反思完成"); loadSkillsView();
      } catch (e) { EA.toast(e.message); }
    };
  };
  $("btn-learn-crystallize").onclick = () => {
    const ov = EA.modal("触发结晶",
      `<div class="form-row"><label>沉淀等级</label><select class="input" id="cr-level"><option value="1">L1 原始经验</option><option value="2" selected>L2 半结构化</option><option value="3">L3 技能化</option></select></div>
       <div class="form-row"><label>适用角色</label><select class="input" id="cr-role"><option>R4</option><option>R5</option><option>R8</option></select></div>`,
      `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>开始结晶</button>`);
    ov.querySelector("[data-x]").onclick = () => ov.remove();
    ov.querySelector("[data-ok]").onclick = async () => {
      try {
        const r = await EA.api("POST", "/api/v2/learn/crystallize", { level: ov.querySelector("#cr-level").value, role: ov.querySelector("#cr-role").value });
        ov.remove(); EA.toast(r.message || "已进入结晶队列"); loadSkillsView();
      } catch (e) { EA.toast(e.message); }
    };
  };
  $("btn-learn-reuse").onclick = () => {
    const ov = EA.modal("触发复用",
      `<div class="form-row"><label>任务描述</label><input class="input" id="ru-task" placeholder="新任务场景"></div>
       <div class="form-row"><label>领域</label><input class="input" id="ru-domain" placeholder="如 环境监测"></div>`,
      `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>开始复用</button>`);
    ov.querySelector("[data-x]").onclick = () => ov.remove();
    ov.querySelector("[data-ok]").onclick = async () => {
      try {
        const r = await EA.api("POST", "/api/v2/learn/reuse", { task: ov.querySelector("#ru-task").value, domain: ov.querySelector("#ru-domain").value });
        ov.remove(); EA.toast(r.message || "复用评估完成"); loadSkillsView();
      } catch (e) { EA.toast(e.message); }
    };
  };
  $("btn-sk-import").onclick = () => {
    const inp = document.createElement("input");
    inp.type = "file"; inp.accept = ".zip,.json,.tar.gz";
    inp.onchange = async () => {
      const fd = new FormData();
      for (const f of inp.files) fd.append("file", f);
      try { const r = await fetch("/api/v2/market/import", { method: "POST", body: fd }); const j = await r.json(); if (!r.ok) throw new Error(j.error || "导入失败"); EA.toast("导入成功"); loadSkillsView(); } catch (e) { EA.toast(e.message); }
    };
    inp.click();
  };
  $("btn-sk-market").onclick = loadMarket;
  // 市场统计：技能市场数据概览
  $("btn-sk-stats").onclick = async () => {
    try {
      const r = await EA.api("GET", "/api/v2/market/stats");
      const s = r && typeof r === "object" ? r : {};
      const rows = [
        ["总技能数", s.total_skills ?? s.total ?? 0],
        ["已启用", s.enabled ?? s.active ?? 0],
        ["待审", s.pending ?? 0],
        ["下载总量", s.total_downloads ?? s.downloads ?? 0],
        ["开发者", s.developers ?? s.authors ?? 0],
      ].filter(([k, v]) => v != null);
      const ov = EA.modal("技能市场统计",
        rows.map(([k, v]) => `<div class="card" style="padding:8px 12px;margin-bottom:6px;display:flex;justify-content:space-between;font-size:13px"><span style="color:var(--text-2)">${EA.esc(String(k))}</span><b>${EA.fmtNum(v)}</b></div>`).join("") || '<div style="color:var(--text-3)">暂无统计数据</div>',
        `<button class="btn" data-x>关闭</button>`);
      ov.querySelector("[data-x]").onclick = () => ov.remove();
    } catch (e) { EA.toast(e.message); }
  };
  // 技能改进提案：待审提案列表 + 批准/拒绝
  $("btn-sk-updates").onclick = async () => {
    try {
      const r = await EA.api("GET", "/api/v2/skills/updates/pending");
      const arr = Array.isArray(r) ? r : (r.pending || r.updates || r.items || []);
      const ov = EA.modal("技能改进提案",
        arr.length ? `<div style="max-height:340px;overflow:auto">${arr.map((u, i) =>
          `<div class="card" style="padding:8px 10px;margin-bottom:6px;font-size:12px">
             <b>${EA.esc(u.skill || u.name || "技能")}</b> <span class="tag blue" style="padding:0 6px">${EA.esc(u.ver || u.version || "")}</span>
             <div style="color:var(--text-2);margin:3px 0">${EA.esc(String(u.proposal || u.suggestion || u.desc || "").slice(0, 120))}</div>
             <span style="display:flex;gap:6px"><button class="btn sm" data-i="${i}" data-a="ap">批准</button><button class="btn sm danger" data-i="${i}" data-a="rj">拒绝</button></span>
           </div>`).join("")}</div>`
          : '<div style="color:var(--text-3);padding:20px;text-align:center">暂无改进提案</div>',
        `<button class="btn" data-x>关闭</button>`);
      ov.querySelector("[data-x]").onclick = () => ov.remove();
      ov.querySelectorAll("[data-a]").forEach((b) => {
        b.onclick = async () => {
          const u = arr[Number(b.dataset.i)];
          const pid = u.pid ?? u.id;
          try {
            await EA.api("POST", b.dataset.a === "ap" ? "/api/v2/skills/updates/approve" : "/api/v2/skills/updates/reject", { pid });
            EA.toast("已处理"); ov.remove(); $("btn-sk-updates").click();
          } catch (e) { EA.toast(e.message); }
        };
      });
    } catch (e) { EA.toast(e.message); }
  };
  loadSkillsView();
});

async function loadSkillsView() {
  let skills = [];
  try { const r = await EA.api("GET", "/api/skills"); skills = Array.isArray(r) ? r : (r.skills || []); } catch (_) {}
  const grid = $("skill-grid");
  if (grid) grid.innerHTML = skills.map((s) => `
    <div class="card sk">
      <div class="hd"><div class="ic" style="background:${s.source === "内置" ? "var(--navy)" : "var(--gold)"}"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg></div>
      <div><div class="nm">${EA.esc(s.name || s.key || "技能")}</div><div class="src">${EA.esc(s.source || s.description || "")}</div></div></div>
      <div class="ds" title="${EA.esc(s.description || "")}">${EA.esc(s.description || "")}</div>
      <div class="ft"><span class="tag gray">${EA.esc(s.version || "v1")}</span>
      <div class="sw ${s.enabled ? "on" : ""}" data-k="${EA.esc(s.key)}"></div></div>
    </div>`).join("") || '<div style="color:var(--text-3);padding:20px">暂无技能</div>';
  if (grid) grid.querySelectorAll(".sw").forEach((sw) => {
    sw.onclick = async () => {
      try { await EA.api("POST", `/api/skills/${sw.dataset.k}/toggle`, { enabled: !sw.classList.contains("on") }); loadSkillsView(); } catch (e) { EA.toast(e.message); }
    };
  });
  try {
    // 结晶待审已统一移入审核中心处理；此处仅只读展示待审列表
    const r = await EA.api("GET", "/api/v2/learn/pending");
    const arr = Array.isArray(r) ? r : (r.skills || []);
    const q = $("crystal-queue");
    if (q) q.innerHTML = `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px"><b style="font-size:14px">结晶待审（Agent 自学产出，${arr.length}）</b>
      <a class="btn sm gold" href="#review" style="text-decoration:none">去审核中心处理</a></div>
      <div style="font-size:11px;color:var(--text-3);margin-bottom:6px">技能批准/拒绝已统一在"审核中心"完成，此处仅供查看</div>` +
      (arr.map((s) => `<div class="qrow"><span class="tag gold">新</span><b>${EA.esc(s.name || s.sid || "技能")}</b>
      <span class="qdesc" title="${EA.esc(s.description || "")}">${EA.esc(s.description || "")}</span></div>`).join("") || '<div style="color:var(--text-3);font-size:12px;padding:8px 0">暂无结晶待审</div>');
  } catch (_) {}
  try {
    const r = await EA.api("GET", "/api/v2/learn/pending");
    const n = typeof r === "number" ? r
      : (r.pending ?? r.count ?? (Array.isArray(r.skills) ? r.skills.length : 0));
    const pipe = $("learn-pipe");
    if (pipe) pipe.innerHTML = `<span class="pstep">观察 ${r.observed ?? "--"}</span><span class="parr"></span><span class="pstep">反思 ${r.reflected ?? "--"}</span><span class="parr"></span><span class="pstep hot">结晶待审 ${n}</span><span class="parr"></span><span class="pstep">已固化 ${r.crystallized ?? "--"}</span>`;
  } catch (_) {}
}

async function loadMarket() {
  try {
    const r = await EA.api("GET", "/api/v2/market/browse");
    const arr = Array.isArray(r) ? r : (r.market || r.items || []);
    const ml = $("market-list");
    if (ml) ml.innerHTML = arr.map((m) => `
      <div class="card mk">
        <div class="th"><svg viewBox="0 0 24 24"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg></div>
        <div style="flex:1;min-width:0"><b>${EA.esc(m.name || m.title || "技能包")}</b>
        <div class="mdesc" title="${EA.esc(m.description || m.desc || "")}">${EA.esc(m.description || m.desc || "")}</div></div>
        <span class="tag gray">${EA.esc(m.downloads ? "下载 " + m.downloads : "")}</span>
        <button class="btn sm" data-export="${EA.esc(m.key || m.name || "")}">导出</button>
      </div>`).join("") || '<div style="color:var(--text-3)">市场暂无内容</div>';
    ml.querySelectorAll("[data-export]").forEach((b) => {
      b.onclick = async () => {
        try {
          const r = await EA.api("POST", "/api/v2/market/export", { key: b.dataset.export, include_related: true });
          EA.toast(r.path || r.file || r.message || "已导出技能包");
        } catch (e) { EA.toast(e.message); }
      };
    });
  } catch (_) {}
}

/* ==================== 09 计划与调度 ==================== */
EA.onView("planner", function () {
  document.getElementById("v-planner").innerHTML = `
  <div class="topbar">
    <h1>计划与调度</h1><span class="sp"></span>
    <button class="btn sm" id="btn-pl-pipeline">预设管线</button>
    <button class="btn sm gold" id="btn-sch-new">+ 新建调度</button>
  </div>
  <div class="pl">
    <div class="plan-zone">
      <div class="parse-bar">
        <input class="input" id="plan-input" style="flex:1" placeholder="用自然语言描述目标…">
        <button class="btn pri" id="btn-plan-run">拆解计划</button>
        <button class="btn" id="btn-plan-exec">执行计划</button>
      </div>
      <div id="plan-steps"></div>
    </div>
    <div class="sched-zone">
      <div class="parse-bar">
        <input class="input" id="sch-parse-input" style="flex:1" placeholder="用自然语言描述时间，如：每周一上午9点">
        <button class="btn" id="btn-sch-parse">解析</button>
      </div>
      <div id="sch-parse-preview"></div>
      <div id="sched-list"></div>
    </div>
  </div>`;
  $("btn-plan-run").onclick = async () => {
    const text = $("plan-input").value.trim();
    if (!text) return;
    $("plan-steps").innerHTML = '<div style="color:var(--text-3)">拆解中…</div>';
    try {
      const r = await EA.api("POST", "/api/v2/plan/run", { text, mode_hint: "interactive", execute: false });
      const steps = r.steps || r.plan || [];
      if (Array.isArray(steps) && steps.length) {
        $("plan-steps").innerHTML = steps.map((s, i) => `
          <div class="step st-wait"><div class="nd">${i + 1}</div><div class="bd">
            <b>${EA.esc(s.title || s.name || s.task || "步骤 " + (i + 1))}</b>
            <div style="font-size:12px;color:var(--text-2);margin-top:4px">${EA.esc(s.desc || s.detail || s.instruction || "")}</div>
          </div></div>`).join("");
      } else {
        $("plan-steps").innerHTML = `<div class="step st-ok"><div class="nd">1</div><div class="bd"><b>计划生成</b><div style="font-size:12px;color:var(--text-2);margin-top:4px">${EA.esc(r.text || r.message || JSON.stringify(r).slice(0, 200))}</div></div></div>`;
      }
    } catch (e) { $("plan-steps").innerHTML = "<div style='color:var(--red)'>" + EA.esc(e.message) + "</div>"; }
  };
  // 执行计划：拆解 + 逐步骤执行
  $("btn-plan-exec").onclick = async () => {
    const text = $("plan-input").value.trim();
    if (!text) return EA.toast("请输入计划目标");
    const b = $("btn-plan-exec");
    b.disabled = true; b.textContent = "执行中…";
    $("plan-steps").innerHTML = '<div style="color:var(--text-3)">拆解并执行中…</div>';
    try {
      const r = await EA.api("POST", "/api/v2/plan/run", { text, mode_hint: "interactive", execute: true });
      const steps = r.steps || r.plan || [];
      if (Array.isArray(steps) && steps.length) {
        $("plan-steps").innerHTML = steps.map((s, i) => {
          const ok = s.status === "done" || s.status === "ok" || s.result;
          return `<div class="step ${ok ? "st-ok" : "st-wait"}"><div class="nd">${i + 1}</div><div class="bd">
            <b>${EA.esc(s.title || s.name || "步骤 " + (i + 1))}</b>
            <div style="font-size:12px;color:var(--text-2);margin-top:4px">${EA.esc(s.desc || s.detail || "")}</div>
            ${s.result ? `<div style="font-size:11px;color:var(--text-3);margin-top:4px">结果：${EA.esc(String(s.result).slice(0, 150))}</div>` : ""}
            ${ok ? '<span class="tag green" style="margin-top:4px">完成</span>' : ""}
          </div></div>`;
        }).join("");
      } else {
        $("plan-steps").innerHTML = `<div class="step st-ok"><div class="nd">1</div><div class="bd"><b>执行完成</b><div style="font-size:12px;color:var(--text-2);margin-top:4px">${EA.esc(r.message || r.result || JSON.stringify(r).slice(0, 200))}</div></div></div>`;
      }
    } catch (e) { $("plan-steps").innerHTML = "<div style='color:var(--red)'>" + EA.esc(e.message) + "</div>"; }
    b.disabled = false; b.textContent = "执行计划";
  };
  $("btn-pl-pipeline").onclick = async () => {
    try { const r = await EA.api("POST", "/api/v2/pipeline/run", { pipeline: { name: "检测报告管线", steps: ["采样", "分析", "报告"] } }); EA.toast(r.message || "管线已运行"); } catch (e) { EA.toast(e.message); }
  };
  $("btn-sch-parse").onclick = async () => {
    const text = $("sch-parse-input").value.trim();
    if (!text) return;
    try {
      const r = await EA.api("POST", "/api/v2/schedule/parse", { text });
      const prev = $("sch-parse-preview");
      const rrule = r.rrule || r.rule || "";
      const next = r.next_run || r.next || "";
      prev.innerHTML = `解析结果：<b>${EA.esc(rrule)}</b> · 下次运行 ${EA.fmtTime(next)}
        <button class="btn sm gold" style="margin-left:8px" id="btn-sch-confirm">确认创建</button>`;
      $("btn-sch-confirm").onclick = async () => {
        try {
          await EA.api("POST", "/api/v2/schedule", { title: text.slice(0, 20), prompt: text, mode: "craft" });
          prev.innerHTML = '<span style="color:var(--green)">已创建调度</span>';
          loadSchedules();
        } catch (e) { EA.toast(e.message); }
      };
    } catch (e) { EA.toast(e.message); }
  };
  $("btn-sch-new").onclick = () => { document.getElementById("v-planner").querySelector("#sch-parse-input").focus(); };
  loadSchedules();
});

async function loadSchedules() {
  let items = [];
  try { const r = await EA.api("GET", "/api/v2/schedule"); items = Array.isArray(r) ? r : (r.schedules || r.items || []); } catch (_) {}
  const list = $("sched-list");
  if (!list) return;
  // H3 Cron 记忆：卡片显示上次运行摘要 + 连续性标签（对齐后端 task_schedule 字段）
  list.innerHTML = `<b style="font-size:13px">调度列表（H3 跨运行记忆）</b>` +
    items.map((s) => `
    <div class="card sch">
      <div class="nm">${EA.esc(s.title || "调度")} <span class="tag ${s.enabled ? "green" : "gray"}">${s.enabled ? "运行中" : "已暂停"}</span></div>
      <div class="cr">${EA.esc(s.cron_desc || "")}</div>
      ${s.last_summary ? `<div style="font-size:11px;color:var(--text-2);margin-top:6px;padding:4px 6px;background:var(--bg-2);border-radius:4px"><b>上次摘要</b>：${EA.esc(String(s.last_summary).slice(0, 120))}</div>` : ""}
      <div style="display:flex;gap:6px;margin-top:10px;align-items:center">
        <span style="font-size:12px;color:var(--text-3)">下次：${EA.fmtTime(s.next_run)}</span>
        <span class="tag ${s.continuity ? "blue" : "gray"}" style="cursor:pointer" data-cty="${s.id}" title="上次运行摘要注入下次（H3）">连续性${s.continuity ? "开" : "关"}</span>
        <span style="margin-left:auto">
          <button class="btn sm" data-a="${s.enabled ? "pause" : "resume"}" data-id="${s.id}">${s.enabled ? "暂停" : "恢复"}</button>
          <button class="btn sm" data-a="tick" data-id="${s.id}">手动触发</button>
          <button class="btn sm danger" data-a="del" data-id="${s.id}">删除</button>
        </span>
      </div>
    </div>`).join("") || '<div style="color:var(--text-3);font-size:12px;padding:12px 0">暂无调度，用自然语言创建一个</div>';
  list.querySelectorAll("[data-a]").forEach((b) => {
    b.onclick = async () => {
      const id = b.dataset.id, a = b.dataset.a;
      try {
        if (a === "del") return EA.confirm("删除该调度？", async () => { await EA.api("DELETE", `/api/v2/schedule/${id}`); loadSchedules(); });
        if (a === "pause") await EA.api("POST", `/api/v2/schedule/${id}/pause`);
        if (a === "resume") await EA.api("POST", `/api/v2/schedule/${id}/resume`);
        if (a === "tick") await EA.api("POST", "/api/v2/schedule/tick", { sid: id });
        EA.toast("已执行"); loadSchedules();
      } catch (e) { EA.toast(e.message); }
    };
  });
  // H3：连续性开关（点击切换）
  list.querySelectorAll("[data-cty]").forEach((el) => {
    el.onclick = async () => {
      const id = el.dataset.cty;
      try {
        const cur = items.find((s) => String(s.id) === String(id));
        await EA.api("POST", `/api/v2/schedule/${id}/continuity`, { on: !(cur && cur.continuity) });
        EA.toast("连续性已切换"); loadSchedules();
      } catch (e) { EA.toast(e.message); }
    };
  });
}
