/* 03/04 报告中心 + 编辑器 */
"use strict";
EA._repState = { status: "", cur: null };

EA.onView("reports", function () {
  document.getElementById("v-reports").innerHTML = `
  <div class="topbar">
    <h1>报告中心</h1><span class="sp"></span>
    <span class="btn sm kb-hint" title="报告由任务列表自动生成并沉淀，反复学习提炼后反哺后续报告">自动沉淀知识库</span>
    <button class="btn sm gold" id="btn-report-blank">+ 空白报告</button>
  </div>
  <div class="content">
    <div class="kb-strip" id="report-kb"></div>
    <div class="tabs" id="report-tabs" style="margin-bottom:18px"></div>
    <div class="grid" id="report-grid"></div>
  </div>`;
  $("btn-report-blank").onclick = async () => {
    try { const r = await EA.api("POST", "/api/v2/reports/generate", { type: "blank", project_id: "P-DEMO" }); EA.toast("空白报告已创建"); loadReports(); } catch (e) { EA.toast(e.message); }
  };
  loadLearningStats();
  loadReports();
});

// 报告中心 = 知识库：展示语料学习模式与报告沉淀统计（反复学习、提炼、结晶）
async function loadLearningStats() {
  const el = $("report-kb");
  if (!el) return;
  el.innerHTML = `<div class="kb-item kb-loading">知识库统计加载中…</div>`;
  try {
    const r = await EA.api("GET", "/api/v2/reports/learning-stats");
    const s = r.stats || {};
    const p = s.patterns || {}, kb = s.kb || {};
    const typeName = { monitoring: "监测", acceptance: "验收", eia: "环评" };
    let items = `<div class="kb-item kb-title">📚 知识库</div>`;
    for (const [k, nm] of Object.entries(typeName)) {
      const pat = p[k] || {};
      items += `<div class="kb-item"><b>${pat.source_count || 0}</b><span>${nm}报告语料</span></div>`;
    }
    items += `<div class="kb-item"><b>${kb.report_entries || 0}</b><span>报告沉淀条目</span></div>`;
    items += `<div class="kb-item"><b>${kb.total || 0}</b><span>知识库总量</span></div>`;
    // 已提炼的章节模式（结晶成果）
    const learned = [];
    for (const [k, nm] of Object.entries(typeName)) {
      const secs = (p[k] || {}).sections || [];
      if (secs.length) learned.push(`${nm}: ${secs.map((x) => x.name).slice(0, 3).join("、")}`);
    }
    if (learned.length) items += `<div class="kb-item kb-tip" title="${EA.esc(learned.join("\n"))}">已提炼: ${EA.esc(learned[0])}${learned.length > 1 ? " …" : ""}</div>`;
    el.innerHTML = items;
  } catch (_) {
    el.innerHTML = `<div class="kb-item">知识库暂不可用</div>`;
  }
}

async function loadReports() {
  let reports = [];
  try { const r = await EA.api("GET", "/api/v2/reports"); reports = r.reports || []; } catch (_) {}
  // Tab 与后端状态机对齐：中文状态由英文 status 聚合而来，计数/过滤均基于英文值
  const TABS = [
    { k: "", label: "全部" },
    { k: "draft", label: "草稿", match: ["drafting"] },
    { k: "review", label: "审核中", match: ["review", "auto_fix", "compliance", "escalate"] },
    { k: "done", label: "已归档", match: ["signoff", "learn", "done"] },
    { k: "exported", label: "已导出", exported: true },
  ];
  const cur = EA._repState.status || "";
  const count = (t) => reports.filter((x) => matchReport(x, t)).length;
  const tabs = $("report-tabs");
  tabs.innerHTML = TABS.map((t) =>
    `<button class="${t.k === cur ? "active" : ""}" data-s="${t.k}">${t.label} (${count(t)})</button>`).join("");
  tabs.querySelectorAll("button").forEach((b) => {
    b.onclick = () => { EA._repState.status = b.dataset.s; loadReports(); };
  });
  const tabObj = TABS.find((t) => t.k === cur) || TABS[0];
  const list = reports.filter((x) => matchReport(x, tabObj));
  const grid = $("report-grid");
  grid.innerHTML = list.map((r) => `
    <div class="card rcard">
      <div style="display:flex;justify-content:space-between;align-items:start">
        <div class="tt">${EA.esc(r.title || r.report_id || "未命名报告")}</div>
        <span class="tag ${statusTag(r.status)}">${EA.esc(r.status_name || statusName(r.status))}</span>
      </div>
      <div class="meta"><span>任务 #${r.task_id || "—"}</span><span>${EA.fmtTime(r.updated_at)}</span></div>
      <div class="ft">
        <span style="font-size:12px;color:var(--text-3)">${EA.esc(r.workflow_node || "")}</span>
        <span style="display:flex;gap:6px">
          <button class="btn sm" data-expert="${r.report_id || r.rid || ""}">专家意见</button>
          <button class="btn sm pri" data-open="${r.report_id || r.rid || ""}">打开编辑器</button>
        </span>
      </div>
    </div>`).join("") || emptyReports(tabObj);
  grid.querySelectorAll("[data-open]").forEach((b) => {
    b.onclick = () => openReportEditor(b.dataset.open);
  });
  // P3 专家意见回流：提交意见 → 写入原任务对话 → 对话工作台自动修改
  grid.querySelectorAll("[data-expert]").forEach((b) => {
    b.onclick = () => {
      const rid = b.dataset.expert;
      const ov = EA.modal("提交专家意见",
        `<div style="font-size:12px;color:var(--text-2);margin-bottom:8px">意见将写入该报告的关联任务对话，Agent 会按意见逐条修改并复审报告 <b>${EA.esc(rid)}</b>。</div>
         <div class="form-row"><label>专家意见</label><textarea class="input" id="ex-msg" style="min-height:100px" placeholder="如：第三章监测数据缺少质控信息，请补充质控措施及判定依据…"></textarea></div>`,
        `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>提交并修改</button>`);
      ov.querySelector("[data-x]").onclick = () => ov.remove();
      ov.querySelector("[data-ok]").onclick = async () => {
        const msg = ov.querySelector("#ex-msg").value.trim();
        if (!msg) return EA.toast("请填写专家意见");
        try {
          const r = await EA.api("POST", "/api/v2/reports/expert-opinion", { report_id: rid, opinion: msg });
          ov.remove();
          if (r.ok) { EA.toast("已提交，返回对话工作台查看修改（任务 #" + r.task_id + "）"); loadReports(); }
          else EA.toast(r.error || "提交失败");
        } catch (e) { EA.toast(e.message); }
      };
    };
  });
}

// tab 过滤：后端英文状态聚合到分组（draft/review/done），exported 为导出动作标记
function matchReport(x, tab) {
  if (!tab || !tab.k) return true;
  if (tab.exported) return !!x.exported;
  return (tab.match || []).includes(x.status);
}

// 空态引导：不同 tab 给出对应操作提示
function emptyReports(tab) {
  const tips = {
    "": "暂无报告，任务对话完成后将自动生成并沉淀至报告中心，亦可「+ 空白报告」手动起草",
    draft: "暂无草稿报告，任务对话结束后自动生成，亦可「+ 空白报告」手动起草",
    review: "暂无审核中的报告，任务自动生成的报告将在此排队审核",
    done: "暂无已归档报告，完成审核签发后自动归档学习",
    exported: "暂无已导出的报告，在编辑器点击「导出 Word」后出现在这里",
  };
  return `<div class="empty-report"><div class="ico">📄</div><div class="txt">${tips[tab.k] || tips[""]}</div></div>`;
}

function statusTag(s) {
  return { drafting: "gray", review: "amber", auto_fix: "amber", compliance: "amber", escalate: "red", signoff: "green", learn: "green", done: "green" }[s] || "gray";
}

function statusName(s) {
  return { drafting: "草稿", review: "审核中", auto_fix: "修订中", compliance: "合规审核", escalate: "已升级", signoff: "已签收", learn: "归档学习", done: "已归档" }[s] || (s || "草稿");
}

async function openReportEditor(rid) {
  let r = null;
  try { r = await EA.api("GET", `/api/v2/reports/${rid}`); } catch (e) { return EA.toast(e.message); }
  EA._repState.cur = r;
  document.getElementById("v-reports").classList.remove("active");
  const ed = document.getElementById("v-rep-editor");
  // 注入编辑器骨架（v-rep-editor 为空 section，动态创建完整编辑器）
  ed.innerHTML = `
    <div class="ed-top">
      <button class="btn sm" id="btn-ed-back">返回</button>
      <h2 id="ed-title" style="margin:0;font-size:16px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></h2>
      <span class="tag" id="ed-status"></span>
      <span class="sp" style="flex:1"></span>
      <button class="btn sm" id="btn-ed-compliance">合规检查</button>
      <button class="btn sm pri" id="btn-ed-export">导出 Word</button>
    </div>
    <div class="ed-body">
      <div class="outline"><h4>大纲</h4><div id="ed-outline"></div></div>
      <div class="paper"><div class="sheet" id="ed-sheet"></div></div>
      <div class="side" id="ed-side"></div>
    </div>`;
  ed.classList.add("active");
  document.querySelectorAll("#rail-nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === "reports"));
  const title = r.title || r.report_id || rid;
  $("ed-title").textContent = title;
  $("ed-status").textContent = r.status_name || statusName(r.status);
  $("ed-status").className = "tag " + statusTag(r.status);
  let content = typeof r.content === "string" ? r.content : (r.body || "");
  // 正文兜底：content 为空时由章节拼装（report_get 已做一次，此处兼容旧缓存）
  if (!content.trim() && Array.isArray(r.sections)) {
    content = r.sections.map((s) => `## ${s.name || ""}\n\n${s.content || ""}`).join("\n\n");
  }
  $("ed-sheet").innerHTML = `<h1>${EA.esc(title)}</h1><div class="sub2">报告编号 ${EA.esc(r.report_id || rid)}</div><p>${EA.md(content)}</p>`;
  renderOutline(content);
  renderEdSide(r);
  $("btn-ed-back").onclick = () => {
    ed.classList.remove("active");
    document.getElementById("v-reports").classList.add("active");
    document.querySelectorAll("#rail-nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === "reports"));
    loadReports();
  };
  $("btn-ed-export").onclick = () => { window.open(`/api/v2/reports/${rid}/export?fmt=docx`, "_blank"); };
  $("btn-ed-compliance").onclick = async () => {
    try {
      const res = await EA.api("POST", "/api/v2/reports/compliance", { report_id: rid, content: content });
      const out = res.result || res.feedback || res;
      EA.toast("合规检查完成");
      renderCompliance(out);
    } catch (e) { EA.toast(e.message); }
  };
}

function renderOutline(content) {
  const ol = $("ed-outline");
  const lines = (content || "").split("\n").filter((l) => /^#{1,4}\s/.test(l) || l.trim().startsWith("附件") || l.trim().startsWith("附表"));
  ol.innerHTML = lines.map((l, i) => {
    const level = (l.match(/^#+/) || [""])[0].length;
    return `<div class="ol ${level > 2 ? "sub" : ""}" data-i="${i}">${EA.esc(l.replace(/^#+\s*/, ""))}</div>`;
  }).join("") || '<div style="color:var(--text-3);font-size:12px">暂无大纲</div>';
  // 大纲点击跳转到正文对应章节
  ol.querySelectorAll(".ol").forEach((o) => {
    o.onclick = () => {
      ol.querySelectorAll(".ol").forEach((x) => x.classList.remove("on"));
      o.classList.add("on");
      const h1 = $("ed-sheet").querySelectorAll("h1, h2, h3, h4")[Number(o.dataset.i) + 1];
      if (h1) h1.scrollIntoView({ behavior: "smooth", block: "start" });
    };
  });
}

function renderCompliance(out) {
  const s = $("ed-side");
  let txt = "";
  if (typeof out === "string") txt = out;
  else if (out && out.annotations) txt = out.annotations.map((a) => (a.severity ? "[" + a.severity + "] " : "") + (a.note || a.message || "")).join("\n");
  else txt = JSON.stringify(out, null, 2);
  s.insertAdjacentHTML("afterbegin", `<h4>合规批注</h4><div class="cmt">${EA.esc(txt.slice(0, 500))}</div>`);
}

function renderEdSide(r) {
  const s = $("ed-side");
  s.innerHTML = `
    <h4>合规总览</h4>
    <div class="card" style="padding:12px;text-align:center">
      <div style="font-size:28px;font-weight:700;font-family:var(--mono);color:var(--green)">${r.compliance_score || r.score || "—"}</div>
      <div style="font-size:12px;color:var(--text-2)">CMA 合规评分</div>
    </div>
    <h4>数据与材料</h4>
    <div class="card" style="padding:12px">
      <button class="btn sm" style="width:100%;justify-content:center" id="btn-ed-calc">插入计算结果</button>
      <button class="btn sm" style="width:100%;justify-content:center;margin-top:6px" id="btn-ed-materials">材料核验</button>
      <button class="btn sm" style="width:100%;justify-content:center;margin-top:6px" id="btn-ed-ground">报告溯源</button>
    </div>`;
  $("btn-ed-calc").onclick = async () => {
    try {
      const r = await EA.api("GET", "/api/v2/calc/formulas");
      const arr = Array.isArray(r) ? r : (r.formulas || []);
      const names = arr.map((f) => f.name || f).slice(0, 20).join("，");
      EA.modal("公式库", `<div style="font-size:12px;color:var(--text-2)">${EA.esc(names || "暂无公式")}</div>`,
        `<button class="btn" data-x>关闭</button>`);
      document.querySelector(".overlay [data-x]").onclick = () => document.querySelector(".overlay").remove();
    } catch (e) { EA.toast(e.message); }
  };
  $("btn-ed-materials").onclick = async () => {
    try {
      if (!EA.state.task) return EA.toast("请先在对话工作台打开任务");
      const r = await EA.api("POST", "/api/v2/materials/check", { task_id: EA.state.task.id });
      EA.toast(r.message || "材料核验已触发");
    } catch (e) { EA.toast(e.message); }
  };
  // 报告溯源：对正文做论断分类 + 知识库依据溯源
  $("btn-ed-ground").onclick = async () => {
    const b = $("btn-ed-ground");
    b.disabled = true; b.textContent = "溯源中…";
    try {
      const content = typeof EA._repState.cur === "object" ? (EA._repState.cur.content || "") : "";
      const res = await EA.api("POST", "/api/v2/reports/ground", { content });
      const claims = res.claims || [];
      const spans = res.spans || [];
      const ov = EA.modal("报告溯源",
        `<div style="font-size:12px;color:var(--text-2);margin-bottom:10px">论断 ${claims.length} 条 · 溯源片段 ${spans.length} 条</div>
         ${claims.length ? `<div style="margin-bottom:10px"><b style="font-size:13px">论断分类</b>${claims.map((c) =>
           `<div class="card" style="padding:8px 10px;margin-top:6px;font-size:12px">${EA.esc(c.text || c.claim || "")} <span class="tag ${c.passed ? "green" : "red"}" style="margin-left:6px">${EA.esc(c.label || c.kind || (c.passed ? "可溯源" : "不可溯源"))}</span></div>`).join("")}</div>` : ""}
         ${spans.length ? `<div><b style="font-size:13px">依据片段</b>${spans.map((s) =>
           `<div class="card" style="padding:8px 10px;margin-top:6px;font-size:12px;color:var(--text-2)">${EA.esc(String(s.text || s.quote || "").slice(0, 120))}${s.source ? ` <span class="tag blue">${EA.esc(s.source)}</span>` : ""}</div>`).join("")}</div>` : ""}
         <div style="color:var(--text-3);font-size:11px;margin-top:10px">无结果时将提示未检出溯源依据</div>`,
        `<button class="btn" data-x>关闭</button>`);
      ov.querySelector("[data-x]").onclick = () => ov.remove();
      if (!claims.length && !spans.length) EA.toast("未检出溯源论断");
    } catch (e) { EA.toast(e.message); }
    b.disabled = false; b.textContent = "报告溯源";
  };
}
