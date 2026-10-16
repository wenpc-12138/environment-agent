/* 05 角色 + 06 工作流 */
"use strict";

EA.onView("roles", function () {
  document.getElementById("v-roles").innerHTML = `
  <div class="topbar">
    <h1>角色管理</h1>
    <span class="crumb">角色决定 Agent 在流程节点中的职责与工具权限</span><span class="sp"></span>
    <button class="btn sm gold" id="btn-role-new">+ 新建角色</button>
  </div>
  <div class="content"><div class="rgrid" id="role-grid"></div></div>`;
  $("btn-role-new").onclick = roleForm;
  loadRoles();
});

EA._ROLE_BUILTIN = new Set(["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]);
// 角色 required_skills 为业务技能 ID，映射为可读名称（技能库中不存在这些 key）
EA._SKILL_LABEL = {
  "sk-plan-001": "采样方案生成",
  "sk-report-001": "报告编制",
  "sk-review-001": "报告审核",
};
EA.skillLabel = (k) => EA._SKILL_LABEL[k] || String(k || "");

async function loadRoles() {
  let roles = [];
  try { const r = await EA.api("GET", "/api/v2/roles"); roles = Array.isArray(r) ? r : (r.roles || []); } catch (_) {}
  const grid = $("role-grid");
  grid.innerHTML = roles.map((role) => {
    const rid = role.id || role.role_id || role.name || "";
    const active = !!role.active || role.is_active || role.status === "active";
    const builtin = EA._ROLE_BUILTIN.has(rid);
    const resp = role.responsibilities || [];
    const perms = role.permissions || [];
    const comp = role.compliance || [];
    const skills = role.required_skills || [];
    const dsHtml = resp.slice(0, 3).map((r) => "• " + EA.esc(r)).join("<br>")
      + (resp.length > 3 ? '<span style="color:var(--text-3)"> …</span>' : "")
      || '<span style="color:var(--text-3)">暂无职责说明</span>';
    const permHtml = perms.slice(0, 4).join(" · ");
    return `<div class="card role ${active ? "active-role" : ""}">
      ${active ? '<span class="crown">当前激活</span>' : ""}
      <div class="avatar" style="background:${active ? "var(--gold)" : "var(--navy)"}">
        <svg viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>
      </div>
      <div class="role-hd">
        <div class="nm" title="${EA.esc(role.name || rid || "角色")}">${EA.esc(role.name || rid || "角色")}</div>
        <span class="tag gray mono" style="padding:0 5px">${EA.esc(rid)}</span>
        ${builtin ? '<span class="tag blue" style="padding:0 5px">内置</span>' : ""}
      </div>
      <div class="mid">
        <div class="ds">${dsHtml}</div>
        ${perms.length ? `<div class="rp" title="${EA.esc(perms.join(" · "))}">权限：<span class="mono">${EA.esc(permHtml)}</span>${perms.length > 4 ? " …" : ""}</div>` : ""}
        ${skills.length ? `<div class="tools">${skills.slice(0, 4).map((t) => `<span class="tag blue" title="${EA.esc(t)}">${EA.esc(EA.skillLabel(t))}</span>`).join("")}</div>` : ""}
      </div>
      <div class="ft">
        <span style="font-size:11px;color:var(--text-3)">${builtin ? "系统预置角色" : (role.status === "pending_r8_review" ? "待审核" : role.status || "")}</span>
        <span style="display:flex;gap:6px;align-items:center">
          ${builtin ? "" : `<button class="btn sm danger" data-del="${EA.esc(rid)}">删除</button>`}
          <div class="sw ${active ? "on" : ""}" data-id="${EA.esc(rid)}"></div>
        </span>
      </div>
    </div>`;
  }).join("") || '<div style="color:var(--text-3);text-align:center;padding:40px">暂无角色，点击 + 新建</div>';
  grid.querySelectorAll(".sw").forEach((sw) => {
    sw.onclick = async () => {
      try { await EA.api("POST", `/api/v2/roles/${sw.dataset.id}/activate`); EA.toast("已激活"); loadRoles(); } catch (e) { EA.toast(e.message); }
    };
  });
  grid.querySelectorAll("[data-del]").forEach((b) => {
    b.onclick = () => EA.confirm("确认删除该角色？删除后不可恢复。", async () => {
      try { await EA.api("DELETE", `/api/v2/roles/${b.dataset.del}`); EA.toast("已删除"); loadRoles(); } catch (e) { EA.toast(e.message); }
    });
  });
}

function roleForm(role) {
  const resp = role ? (role.responsibilities || []).join("\n") : "";
  const perms = role ? (role.permissions || []).join(", ") : "";
  const ov = EA.modal(role ? "编辑角色" : "新建角色",
    `<div class="form-row"><label>角色名称</label><input class="input" id="rf-name" value="${role ? EA.esc(role.name || "") : ""}" placeholder="如 分析员"></div>
     <div class="form-row"><label>领域</label><input class="input" id="rf-domain" value="${role ? EA.esc(role.domain || "D1") : "D1"}" placeholder="D1"></div>
     <div class="form-row" style="align-items:flex-start"><label>职责说明</label><textarea class="input" id="rf-desc" style="min-height:70px" placeholder="每行一条职责">${EA.esc(resp)}</textarea></div>
     <div class="form-row"><label>权限</label><input class="input" id="rf-perms" value="${EA.esc(perms)}" placeholder="用逗号分隔，如 read_data, generate_report"></div>`,
    `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>保存</button>`);
  ov.querySelector("[data-x]").onclick = () => ov.remove();
  ov.querySelector("[data-ok]").onclick = async () => {
    try {
      await EA.api("POST", "/api/v2/roles", {
        name: ov.querySelector("#rf-name").value.trim(),
        domain: ov.querySelector("#rf-domain").value.trim() || "D1",
        responsibilities: ov.querySelector("#rf-desc").value.split("\n").map((s) => s.trim()).filter(Boolean),
        permissions: ov.querySelector("#rf-perms").value.split(",").map((s) => s.trim()).filter(Boolean),
      });
      ov.remove(); EA.toast("角色已创建"); loadRoles();
    } catch (e) { EA.toast(e.message); }
  };
}

/* ==================== 06 工作流 ==================== */
EA.onView("workflow", function () {
  document.getElementById("v-workflow").innerHTML = `
  <div class="topbar">
    <h1>工作流</h1><span class="crumb">报告全生命周期状态机</span><span class="sp"></span>
    <button class="btn sm" id="btn-wf-auto">自动推进</button>
    <button class="btn sm gold" id="btn-wf-start">发起新流程</button>
  </div>
  <div class="wf">
    <div class="canvas">
      <div style="margin-bottom:16px"><div style="font-size:13px;font-weight:700;margin-bottom:8px">进行中实例</div><div id="wf-instances"></div></div>
      <div style="font-size:13px;font-weight:700;margin-bottom:8px">状态机定义</div>
      <div id="wf-lanes"></div>
      <div style="display:flex;gap:10px;margin-top:16px">
        <button class="btn pri" id="btn-wf-next">流转到下一节点</button>
        <button class="btn" id="btn-wf-back">退回上一节点</button>
        <button class="btn" id="btn-wf-approve">流水线批准</button>
      </div>
    </div>
    <div class="ev">
      <div class="hd"><span class="live"></span>实时事件流</div>
      <div class="list" id="wf-events"></div>
      <div style="padding:12px 16px;border-top:1px solid var(--line)">
        <button class="btn sm" style="width:100%;justify-content:center" id="btn-wf-audit">查看审计链</button>
        <button class="btn sm" style="width:100%;justify-content:center;margin-top:6px" id="btn-wf-sub">子代理</button>
      </div>
    </div>
  </div>`;
  $("btn-wf-auto").onclick = async () => {
    try { const r = await EA.api("POST", "/api/v2/workflow/auto", {}); EA.toast(r.message || "已尝试自动推进"); loadWorkflow(); } catch (e) { EA.toast(e.message); }
  };
  $("btn-wf-start").onclick = async () => {
    const ov = EA.modal("发起新流程",
      `<div class="form-row"><label>报告 ID</label><input class="input" id="wf-rid" placeholder="如 ZS-2026-0812"></div>`,
      `<button class="btn" data-x>取消</button><button class="btn pri" data-ok>启动</button>`);
    ov.querySelector("[data-x]").onclick = () => ov.remove();
    ov.querySelector("[data-ok]").onclick = async () => {
      try { await EA.api("POST", "/api/v2/workflow/start", { report_id: ov.querySelector("#wf-rid").value }); ov.remove(); EA.toast("流程已启动"); loadWorkflow(); } catch (e) { EA.toast(e.message); }
    };
  };
  $("btn-wf-next").onclick = () => wfTransition("next");
  $("btn-wf-back").onclick = () => wfTransition("back");
  // 流水线批准：当前节点人工批准，推进流水线
  $("btn-wf-approve").onclick = async () => {
    const b = $("btn-wf-approve");
    b.disabled = true;
    try {
      const r = await EA.api("POST", "/api/v2/pipeline/approve");
      b.disabled = false;
      EA.toast(r.message || r.ok === false ? (r.error || "批准失败") : "已批准，流水线推进");
      loadWorkflow();
    } catch (e) { b.disabled = false; EA.toast(e.message); }
  };
  $("btn-wf-audit").onclick = async () => {
    try {
      const r = await EA.api("GET", "/api/v2/audit/verify");
      const ok = r.ok ?? r.verified;
      EA.toast(ok ? "审计链完整" : "审计链校验失败");
    } catch (e) { EA.toast(e.message); }
  };
  // 子代理：派发动态子代理 + 列表 + 收集结果
  $("btn-wf-sub").onclick = () => {
    const ov = EA.modal("子代理",
      `<div class="form-row"><label>子代理任务</label><input class="input" id="sub-task" placeholder="如：检索北京2026年排污标准"></div>
       <div class="form-row"><label>角色</label><select class="input" id="sub-role"><option>R4</option><option>R5</option><option>R8</option></select></div>
       <div style="display:flex;gap:6px;margin-bottom:8px">
         <button class="btn sm pri" id="sub-spawn" style="flex:1;justify-content:center">派发子代理</button>
         <button class="btn sm" id="sub-list" style="flex:1;justify-content:center">查看列表</button>
       </div>
       <div id="sub-out" style="font-size:12px;color:var(--text-2);max-height:220px;overflow:auto"></div>`,
      `<button class="btn" data-x>关闭</button>`);
    ov.querySelector("[data-x]").onclick = () => ov.remove();
    const out = ov.querySelector("#sub-out");
    ov.querySelector("#sub-spawn").onclick = async () => {
      out.textContent = "派发中…";
      try {
        const r = await EA.api("POST", "/api/v2/subagent", { task: ov.querySelector("#sub-task").value, role_id: ov.querySelector("#sub-role").value, name: "sub-" + Date.now().toString(36) });
        const sub = r.subagent || r.sub || r;
        out.innerHTML = `<div class="card" style="padding:8px 10px">子代理已派发 <span class="mono">${EA.esc(sub.sub_id || sub.id || "")}</span><div style="color:var(--text-3);margin-top:3px">${EA.esc(sub.task || "")}</div>
          <button class="btn sm" id="sub-collect" style="margin-top:6px">收集结果</button></div>`;
        const c = ov.querySelector("#sub-collect");
        if (c) c.onclick = async () => {
          try {
            const rc = await EA.api("POST", "/api/v2/subagent/collect", { sub_id: sub.sub_id || sub.id, timeout: 60 });
            out.innerHTML += `<div style="margin-top:8px;white-space:pre-wrap">${EA.esc(rc.result || rc.output || rc.message || "无结果")}</div>`;
          } catch (e) { out.innerHTML += '<div style="color:var(--red);margin-top:8px">' + EA.esc(e.message) + "</div>"; }
        };
      } catch (e) { out.innerHTML = '<div style="color:var(--red)">' + EA.esc(e.message) + "</div>"; }
    };
    ov.querySelector("#sub-list").onclick = async () => {
      try {
        const r = await EA.api("GET", "/api/v2/subagent");
        const arr = (r && r.subagents) || (Array.isArray(r) ? r : []);
        out.innerHTML = arr.length
          ? arr.map((s) => `<div style="padding:4px 0">• <span class="mono">${EA.esc(s.sub_id || s.id || "")}</span> <span style="color:var(--text-3)">${EA.esc(s.status || "")}</span> ${EA.esc(s.task || "")}</div>`).join("")
          : '<span style="color:var(--text-3)">暂无子代理</span>';
      } catch (e) { out.innerHTML = '<div style="color:var(--red)">' + EA.esc(e.message) + "</div>"; }
    };
  };
  loadWorkflow();
  listenWorkflowEvents();
});

async function loadWorkflow() {
  let sm = null;
  try { const r = await EA.api("GET", "/api/v2/workflow/states"); sm = r.sm || r.states || r; } catch (_) {}
  const lanes = $("wf-lanes");
  if (lanes) {
    if (sm && (sm.states || sm.nodes || sm.lanes)) {
      const states = sm.states || sm.nodes || [];
      const laneGroups = sm.lanes || (sm.roles ? sm.roles.map((rn) => ({ role: rn, nodes: states.filter(() => true) })) : [{ role: "流程", nodes: states }]);
      lanes.innerHTML = (Array.isArray(laneGroups) ? laneGroups : []).map((lg) => `
        <div class="lane">
          <div class="lh"><span class="dot-s" style="background:var(--gold)"></span>${EA.esc(lg.role || lg.name || "流程")}</div>
          <div class="nodes">${(lg.nodes || []).map((n, i) => {
            const name = typeof n === "string" ? n : (n.name || n.label || "");
            const st = typeof n === "string" ? "" : (n.status || n.state || "");
            const cls = typeof n === "string" ? "" : (n.current ? "cur" : n.done || n.status === "done" ? "done" : "");
            return `${i > 0 ? '<span class="arrow"></span>' : ""}<div class="node ${cls}">${EA.esc(name)}<span class="st">${EA.esc(st)}</span></div>`;
          }).join("")}</div>
        </div>`).join("") || '<div style="color:var(--text-3)">暂无状态定义</div>';
    } else {
      lanes.innerHTML = '<div style="color:var(--text-3)">状态机定义为空，发起流程后可见</div>';
    }
  }
  loadAudit();
}

async function loadAudit() {
  try {
    const r = await EA.api("GET", "/api/v2/audit");
    const arr = Array.isArray(r) ? r : (r.audit || r.events || r.items || []);
    const ev = $("wf-events");
    if (ev) ev.innerHTML = arr.slice(0, 12).map((a) =>
      `<div class="evt"><span class="t">${EA.fmtTime(a.ts || a.time || a.created_at)}</span>
       <div><b>${EA.esc(a.actor || a.role || "系统")}</b> ${EA.esc(a.action || a.event || a.message || "")}</div></div>`).join("") ||
      '<div style="color:var(--text-3);font-size:12px">暂无事件</div>';
  } catch (_) {}
}

async function wfTransition(dir) {
  const inst = EA._wfInst;
  if (!inst) return EA.toast("请先在对话工作台打开一个报告任务");
  try {
    const r = await EA.api("POST", "/api/v2/workflow/transition", { instance_id: inst.id || inst.report_id, to_state: dir });
    EA.toast(r.message || "已流转"); loadWorkflow();
  } catch (e) { EA.toast(e.message); }
}

function listenWorkflowEvents() {
  const es = new EventSource("/api/v2/workflow/events");
  es.onmessage = (e) => {
    let d; try { d = JSON.parse(e.data); } catch (_) { return; }
    const list = $("wf-events");
    if (list) {
      const div = document.createElement("div");
      div.className = "evt";
      div.innerHTML = `<span class="t">${EA.fmtTime(Date.now())}</span><div><b>${EA.esc(d.actor || d.role || "系统")}</b> ${EA.esc(d.message || d.action || "事件")}</div>`;
      list.insertBefore(div, list.firstChild);
      while (list.children.length > 20) list.lastChild.remove();
    }
  };
  es.onerror = () => { try { es.close(); } catch (_) {} setTimeout(listenWorkflowEvents, 8000); };
}
