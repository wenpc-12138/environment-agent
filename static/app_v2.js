// V2.0 功能（唯一 UI：嵌入 v1.2 主界面，视图切换集成）
"use strict";
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
const __VIEW_NAMES={main:"主界面",reports:"报告流水线",roles:"角色管理",workflow:"报告状态机",kb:"知识库管理",v2:"V2 模块"};
function showView(name){
  document.querySelectorAll(".v2-view,#view-main").forEach(el=>el.classList.add("hidden"));
  const t=document.getElementById("view-"+name); if(t)t.classList.remove("hidden");
  document.querySelectorAll(".tb-nav .nav-link").forEach(a=>a.classList.toggle("active",a.dataset.view===name));
  const vt=document.getElementById("view-title");
  if(vt)vt.textContent=__VIEW_NAMES[name]||name;
  if(name==="roles"&&!window.__v2RolesLoaded){window.__v2RolesLoaded=true;v2LoadRoles();}
  if(name==="kb"&&!window.__v2KbLoaded){window.__v2KbLoaded=true;v2KbLoad();}
}
async function updateTopStatus(){
  try{
    const [providers]=await Promise.all([
      (await fetch("/api/providers")).json(),
    ]);
    const act=(providers||[]).find(p=>p.is_active);
    const pe=document.getElementById("top-provider");
    if(pe)pe.textContent=act?`${act.name} · ${act.model}`:"Provider 未激活";
    const st=document.getElementById("top-status");
    if(st){st.textContent="[OK]";st.classList.add("on");}
  }catch(e){
    const st=document.getElementById("top-status");
    if(st){st.textContent="[OFF]";st.classList.remove("on");}
  }
}
updateTopStatus();
// ============ 角色 M08 ============
function v2StatusCls(s){return s==="active"?"status-active":s==="pending_r8_review"?"status-pending":"status-rejected";}
function v2RenderRoles(roles){
  const grid=document.getElementById("v2-role-grid");
  if(!roles.length){grid.innerHTML='<div class="dim">暂无角色</div>';return;}
  grid.innerHTML=roles.map(r=>`
    <div class="role-card"><div class="role-head">
      <span class="role-id">${esc(r.id)}</span><span style="font-weight:700">${esc(r.name)}</span>
      <span class="tb-chip role-domain">${esc(r.domain||"D1")}</span>
      <span class="tb-chip ${v2StatusCls(r.status)}" style="margin-left:auto">${esc(r.status)}</span></div>
      <div class="role-sec"><div class="rp-head">职责</div><div class="chip-row">${(r.responsibilities||[]).map(x=>`<span class="tb-chip">${esc(x)}</span>`).join("")||'<span class="dim">-</span>'}</div></div>
      <div class="role-sec"><div class="rp-head">权限</div><div class="chip-row">${(r.permissions||[]).map(x=>`<span class="tb-chip">${esc(x)}</span>`).join("")||'<span class="dim">-</span>'}</div></div>
      ${r.status==="pending_r8_review"?`<button class="btn-mini primary" onclick="v2ActivateRole('${esc(r.id)}')">R8 审核激活</button>`:""}
    </div>`).join("");
}
async function v2LoadRoles(){
  const grid=document.getElementById("v2-role-grid");
  try{const res=await fetch("/api/v2/roles");const d=await res.json();v2RenderRoles(d.roles||[]);}
  catch(e){grid.innerHTML=`<div class="dim">加载失败：${esc(e.message)}</div>`;}
}
async function v2DefineRole(){
  const msg=document.getElementById("v2-role-msg");
  const name=document.getElementById("v2-role-name").value.trim();
  if(!name){msg.textContent="[!] 请输入角色名称";return;}
  try{
    const res=await fetch("/api/v2/roles",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({name,domain:document.getElementById("v2-role-domain").value.trim()||"D1"})});
    const d=await res.json();
    if(!d.ok){msg.textContent="[!] "+(d.error||"定义失败");return;}
    msg.textContent=`已定义 ${d.role.id}（${d.role.status}），等待 R8 审核`;
    document.getElementById("v2-role-name").value="";v2LoadRoles();
  }catch(e){msg.textContent="[!] "+e.message;}
}
async function v2ActivateRole(id){
  const msg=document.getElementById("v2-role-msg");
  try{const res=await fetch(`/api/v2/roles/${encodeURIComponent(id)}/activate`,{method:"POST"});
    const d=await res.json();msg.textContent=d.ok?`已激活 ${id}`:"[!] 激活失败（须 R8 审核）";v2LoadRoles();}
  catch(e){msg.textContent="[!] "+e.message;}
}
// 报告档案已移除：报告查看/下载由任务输出目录（out-panel）与自动落盘 report.md/report.docx 覆盖
// ============ 知识库管理（18 空闲端点接入） ============
async function v2KbLoad(){v2KbStatus();v2KbEntries();}
async function v2KbStatus(){
  const ocrEl=document.getElementById("v2-ocr"),useEl=document.getElementById("v2-usage");
  try{const r=await(await fetch("/api/ocr/status")).json();ocrEl.textContent=`OCR: ${r.mode||"?"}${r.ok===false?" [ERR]":""}${r.last_err?(" "+r.last_err):""}`;}
  catch(e){ocrEl.textContent="OCR: 连接失败";}
  try{const r=await(await fetch("/api/usage?range=today")).json();useEl.textContent="今日用量: "+esc(JSON.stringify(r).slice(0,90));}
  catch(e){useEl.textContent="用量: 连接失败";}
  try{const r=await(await fetch("/api/search/config")).json();document.getElementById("v2-srch-cfg").textContent=`${r.mode||"-"} | ${r.base_url||"-"}`;document.getElementById("v2-srch-url").value=r.base_url||"";}
  catch(e){document.getElementById("v2-srch-cfg").textContent="加载失败";}
}
async function v2SaveSearchCfg(){
  const msg=document.getElementById("v2-kb-batch-msg");
  try{const r=await(await fetch("/api/search/config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({base_url:document.getElementById("v2-srch-url").value.trim()})})).json();
    msg.textContent=r.ok?"SearXNG 配置已保存":"[!] 保存失败";v2KbStatus();}
  catch(e){msg.textContent="[!] "+e.message;}
}
async function v2KbSearch(mode){
  const q=document.getElementById("v2-kb-q").value.trim(),box=document.getElementById("v2-kb-hits");
  if(!q){box.innerHTML='<div class="dim">请输入关键词</div>';box.classList.remove("hidden");return;}
  try{
    const url=mode==="vector"?`/api/kb/vector?q=${encodeURIComponent(q)}&top=5`:mode==="hybrid"?`/api/kb/hybrid?q=${encodeURIComponent(q)}&top=5`:`/api/kb/search?q=${encodeURIComponent(q)}&top=5`;
    const d=await(await fetch(url)).json();const rows=Array.isArray(d)?d:(d.hits||[]);
    box.innerHTML=rows.length?rows.map(x=>`<div class="issue-item"><b>${esc(x.title||"")}</b> <span class="tb-chip">${esc(x.std_no||x.standard_code||"")}</span> <span class="dim">score ${(x.score??0).toFixed(2)}</span></div>`).join(""):'<div class="dim">无结果</div>';
    box.classList.remove("hidden");
  }catch(e){box.innerHTML=`<div class="dim">检索失败：${esc(e.message)}</div>`;box.classList.remove("hidden");}
}
async function v2KbBatch(type){
  const msg=document.getElementById("v2-kb-batch-msg");
  const url=type==="interpret-batch"?"/api/kb/interpret-batch":"/api/kb/summarize-batch";
  try{const r=await(await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({limit:100})})).json();
    msg.textContent=(type==="interpret-batch"?"批量解读查新":"批量摘要")+"已入队："+JSON.stringify(r).slice(0,120);}
  catch(e){msg.textContent="[!] "+e.message;}
}
async function v2KbBackup(){
  const msg=document.getElementById("v2-kb-batch-msg");
  try{const r=await(await fetch("/api/kb/backup",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"})).json();
    msg.textContent="备份："+JSON.stringify(r).slice(0,120);}
  catch(e){msg.textContent="[!] "+e.message;}
}
async function v2KbPanel(name){
  const box=document.getElementById("v2-kb-panel");
  try{
    let d;
    if(name==="imports")d=await(await fetch("/api/kb/imports")).json();
    else if(name==="qc")d=await(await fetch("/api/kb/qc?limit=20")).json();
    else if(name==="backups")d=await(await fetch("/api/kb/backups?limit=10")).json();
    else if(name==="audit")d=await(await fetch("/api/kb/audit/latest")).json();
    else if(name==="conflicts")d=await(await fetch("/api/kb/conflicts")).json();
    else if(name==="memories")d=await(await fetch("/api/kb/memories")).json();
    else d=await(await fetch("/api/memory")).json();
    box.innerHTML=`<div class="dim" style="font-size:11px">${name}</div><pre style="white-space:pre-wrap;font-size:11px">${esc(JSON.stringify(d,null,1).slice(0,1500))}</pre>`;
    box.classList.remove("hidden");
  }catch(e){box.innerHTML=`<div class="dim">加载失败：${esc(e.message)}</div>`;box.classList.remove("hidden");}
}
async function v2KbEntries(){
  const box=document.getElementById("v2-kb-entries");
  try{
    const d=await(await fetch("/api/kb")).json();
    box.innerHTML=d.length?d.map(e=>`<div class="issue-item" style="cursor:pointer" onclick="v2EntryDetail(${e.id})"><b>${esc(e.title||"")}</b> <span class="tb-chip">${esc(e.std_no||e.standard_code||"-")}</span> <span class="dim">${esc(e.validity||"")}</span></div>`).join(""):'<div class="dim">空库</div>';
  }catch(e){box.innerHTML=`<div class="dim">加载失败：${esc(e.message)}</div>`;}
}
async function v2EntryDetail(id){
  const box=document.getElementById("v2-kb-detail");
  try{
    const d=await(await fetch(`/api/kb/${id}`)).json();
    box.style.display="block";
    box.innerHTML=`
      <div class="v2-card-title">条目 #${id} 操作</div>
      <div class="v2-form">
        <input id="v2-e-title" placeholder="标题" value="${esc(d.title||"")}" style="min-width:200px">
        <input id="v2-e-url" placeholder="URL" value="${esc(d.url||"")}" style="min-width:200px">
      </div>
      <div class="v2-form" style="margin-top:6px">
        <input id="v2-e-content" placeholder="正文（前 200 字）" value="${esc((d.content||"").slice(0,200))}" style="flex:1">
        <button class="btn-mini primary" onclick="v2EntrySave(${id})">保存 PUT</button>
        <button class="btn-mini" onclick="v2Chunks(${id})">分块</button>
        <button class="btn-mini" onclick="v2Embed(${id})">嵌入</button>
        <button class="btn-mini" onclick="v2EntryRelation(${id})">关系</button>
      </div>
      <div id="v2-e-out" class="dim" style="font-size:11px;margin-top:6px"></div>`;
  }catch(e){box.innerHTML=`<div class="dim">加载失败：${esc(e.message)}</div>`;}
}
async function v2EntrySave(id){
  const out=document.getElementById("v2-e-out");
  try{const r=await(await fetch(`/api/kb/${id}`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:document.getElementById("v2-e-title").value,url:document.getElementById("v2-e-url").value,content:document.getElementById("v2-e-content").value})})).json();
    out.textContent=r.ok?"已保存":"[!] 保存失败";}
  catch(e){out.textContent="[!] "+e.message;}
}
async function v2Chunks(id){
  const out=document.getElementById("v2-e-out");
  try{const d=await(await fetch(`/api/kb/chunks/${id}`)).json();
    out.textContent="分块 "+d.length+" 条："+d.map(c=>`[${c.index}]${(c.content||"").slice(0,40)}`).join(" | ").slice(0,600);}
  catch(e){out.textContent="[!] "+e.message;}
}
async function v2Embed(id){
  const out=document.getElementById("v2-e-out");
  try{const r=await(await fetch(`/api/kb/chunks/${id}`,{method:"POST"})).json();out.textContent=r.ok?"已嵌入(force)":"[!] 失败";}
  catch(e){out.textContent="[!] "+e.message;}
}
async function v2EntryRelation(id){
  const out=document.getElementById("v2-e-out");
  const to=window.prompt("关联目标条目 ID");if(!to)return;
  try{const r=await(await fetch(`/api/kb/${id}/relation`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({to_id:parseInt(to,10),rel_type:"related",note:""})})).json();
    out.textContent=r.ok?`已关联 → #${to}`:"[!] 失败";}
  catch(e){out.textContent="[!] "+e.message;}
}
// 输出面板导出按钮注入（/api/tasks/:id/outputs/export）
(function(){
  const holder=document.querySelector(".out-actions");
  if(!holder||document.getElementById("btn-out-export"))return;
  const btn=document.createElement("button");
  btn.className="btn-mini";btn.id="btn-out-export";btn.textContent="导出";
  btn.onclick=async()=>{
    if(!state.outTaskId)return;
    try{const r=await(await fetch(`/api/tasks/${state.outTaskId}/outputs/export`,{method:"POST"})).json();
      if(typeof toast==="function")toast(r.ok?`已导出 ${r.path||""}`:(r.error||"导出失败"));}
    catch(e){if(typeof toast==="function")toast("[!] "+e.message);}
  };
  holder.appendChild(btn);
})();
// ============ V2 模块总览（M13/M15/M14/M05/M07/M03/M04 全接入） ============
function v2Post(url,body){return fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body||{})}).then(r=>r.json());}
function v2Out(el,html){const b=document.getElementById(el);b.innerHTML=html;b.classList.remove("hidden");}
function v2Err(el,e){v2Out(el,`<div class="dim">[!] ${esc(e.message||e)}</div>`);}
// M13 OERCR
async function v2Observe(){
  try{const d=await v2Post("/api/v2/learn/observe",{task:document.getElementById("v2-obs-task").value,domain:document.getElementById("v2-obs-domain").value,outcome:document.getElementById("v2-obs-outcome").value});
    v2Out("v2-learn-out",`<b>观察</b><pre style="font-size:11px;white-space:pre-wrap">${esc(JSON.stringify(d.observation,null,1))}</pre>`);}
  catch(e){v2Err("v2-learn-out",e);}
}
async function v2Reflect(){
  try{const d=await v2Post("/api/v2/learn/reflect",{domain:document.getElementById("v2-obs-domain").value});
    v2Out("v2-learn-out",`<b>反思 ${d.count} 条</b>`+(d.reflections||[]).map(r=>`<div class="issue-item">[${esc(r.severity)}] ${esc(r.gap)}</div>`).join(""));}
  catch(e){v2Err("v2-learn-out",e);}
}
async function v2Crystallize(){
  try{const d=await v2Post("/api/v2/learn/crystallize",{level:2,role:"R4",domain:document.getElementById("v2-obs-domain").value});
    v2Out("v2-learn-out",`<b>结晶 ${d.created} 个（pending_review）</b>`+((d.skills||[]).map(s=>`<div class="issue-item">${esc(s.id)} ${esc(s.name)} [${esc(s.status)}]</div>`).join("")||`<div class="dim">${esc(d.error||"")}</div>`));}
  catch(e){v2Err("v2-learn-out",e);}
}
async function v2Reuse(){
  try{const d=await v2Post("/api/v2/learn/reuse",{task:document.getElementById("v2-obs-task").value,domain:document.getElementById("v2-obs-domain").value});
    v2Out("v2-learn-out",d.hit?`<b>命中</b> ${esc(d.hit.id)} ${esc(d.hit.name)} [${esc(d.hit.status)}]`:'<div class="dim">未命中（无 active 技能）</div>');}
  catch(e){v2Err("v2-learn-out",e);}
}
async function v2LearnPending(){
  try{const d=await(await fetch("/api/v2/learn/pending")).json();
    const sk=d.skills||[];
    v2Out("v2-learn-out",`<b>待审技能 ${sk.length} 个</b>`+sk.map(s=>`<div class="issue-item">${esc(s.id)} ${esc(s.name)} <button class="btn-mini" onclick="v2SkillApprove('${esc(s.id)}')">批准</button> <button class="btn-mini" onclick="v2SkillReject('${esc(s.id)}')">拒绝</button></div>`).join(""));}
  catch(e){v2Err("v2-learn-out",e);}
}
async function v2SkillApprove(id){await v2Post(`/api/v2/skills2/${encodeURIComponent(id)}/approve`);v2LearnPending();}
async function v2SkillReject(id){await v2Post(`/api/v2/skills2/${encodeURIComponent(id)}/reject`);v2LearnPending();}
async function v2ApproveAll(){
  try{const d=await v2Post("/api/v2/learn/approve-all");
    v2Out("v2-learn-out",`<b>激活 ${(d.activated||[]).length} 个</b>`+(d.activated||[]).map(s=>`<div class="issue-item">${esc(s.id)} ${esc(s.name)} [${esc(s.status)}]</div>`).join(""));}
  catch(e){v2Err("v2-learn-out",e);}
}
// M15 流水线
async function v2PipelineRun(){
  try{const d=await v2Post("/api/v2/pipeline/run",{conversation:document.getElementById("v2-pl-conv").value});
    const bp=d.blueprint||{};
    v2Out("v2-pl-out",`<b>蓝图 ${esc(bp.domain||"")} [${esc(bp.status)}]</b>
      <div>角色 ${(bp.roles||[]).length}：${(bp.roles||[]).map(r=>`${esc(r.id)}:${esc(r.name)}`).join("，")}</div>
      <div>技能 ${(bp.skills||[]).length}：${(bp.skills||[]).map(s=>esc(s.name)).join("，")}</div>
      <div class="dim" style="font-size:11px">知识库 ${(bp.knowledge_base||[]).length} 条 · 合规规则 ${(bp.compliance_rules||[]).length} 条</div>`);}
  catch(e){v2Err("v2-pl-out",e);}
}
async function v2PipelineApprove(){
  try{const d=await v2Post("/api/v2/pipeline/approve");
    v2Out("v2-pl-out",d.ok?`<b>[OK] 审批通过，状态 ${esc(d.status)}</b>`:`<div class="dim">[!] ${esc(d.error||"审批失败")}</div>`);}
  catch(e){v2Err("v2-pl-out",e);}
}
// M07 技能执行
async function v2SkillRun(){
  try{let params={};try{params=JSON.parse(document.getElementById("v2-sk-params").value||"{}");}catch(e){}
    const d=await v2Post("/api/v2/execute/skill",{skill_id:document.getElementById("v2-sk-id").value,params,context:{}});
    const r=d.result||{};
    v2Out("v2-sk-out",`<b>${r.ok?"[OK]":"[FAIL]"}</b> ${esc(r.trace_id||"")}<pre style="font-size:11px;white-space:pre-wrap">${esc(JSON.stringify(r.outputs||r,null,1).slice(0,900))}</pre>`);}
  catch(e){v2Err("v2-sk-out",e);}
}
// M03 意图路由
async function v2Intent(){
  try{const d=await v2Post("/api/v2/intent",{text:document.getElementById("v2-int-text").value});
    const r=d.route||{};
    v2Out("v2-int-out",`<b>mode=${esc(r.mode)} · domain=${esc(r.domain)} · confidence=${r.confidence}</b><div>skills: ${(r.skill_ids||[]).map(esc).join(", ")||"-"}</div>`);}
  catch(e){v2Err("v2-int-out",e);}
}
// M14 审计
async function v2AuditLog(){
  try{const d=await v2Post("/api/v2/audit",{who:document.getElementById("v2-au-who").value||"R4",action:document.getElementById("v2-au-action").value||"op",note:document.getElementById("v2-au-action").value||"op"});
    const e=d.entry||{};v2Out("v2-au-out",`<b>#${e.seq}</b> ${esc(e.action)} hash=${esc(String(e.hash).slice(0,16))}…`);}
  catch(e){v2Err("v2-au-out",e);}
}
async function v2AuditQuery(){
  try{const d=await(await fetch(`/api/v2/audit?limit=15&who=${encodeURIComponent(document.getElementById("v2-au-who").value)}&action=${encodeURIComponent(document.getElementById("v2-au-action").value)}`)).json();
    v2Out("v2-au-out",(d.entries||[]).map(e=>`<div class="issue-item">#${e.seq} ${esc(e.who)} ${esc(e.action)} ${esc(String(e.hash).slice(0,12))}…</div>`).join("")||'<div class="dim">无记录</div>');}
  catch(e){v2Err("v2-au-out",e);}
}
async function v2AuditVerify(){
  try{const d=await(await fetch("/api/v2/audit/verify")).json();
    v2Out("v2-au-out",`<b>[${d.ok?"PASS":"FAIL"}]</b> 链校验（${d.size} 条）`);}
  catch(e){v2Err("v2-au-out",e);}
}
// M05 三层记忆
async function v2WmSet(){
  try{const d=await v2Post("/api/v2/memory/working",{key:document.getElementById("v2-wm-key").value,value:document.getElementById("v2-wm-val").value});
    v2Out("v2-mem-out",d.ok?"working 已写入":"[!] 失败");}
  catch(e){v2Err("v2-mem-out",e);}
}
async function v2WmGet(){
  try{const d=await(await fetch(`/api/v2/memory/working?key=${encodeURIComponent(document.getElementById("v2-wm-key").value)}`)).json();
    v2Out("v2-mem-out",`working ${esc(document.getElementById("v2-wm-key").value)} = ${esc(JSON.stringify(d.value))}`);}
  catch(e){v2Err("v2-mem-out",e);}
}
async function v2EpiAdd(){
  try{const d=await v2Post("/api/v2/memory/episodic",{entity:document.getElementById("v2-ep-entity").value,event:document.getElementById("v2-ep-event").value});
    v2Out("v2-mem-out",`episodic 已记录 #${d.event_id}`);}
  catch(e){v2Err("v2-mem-out",e);}
}
async function v2EpiQuery(){
  try{const d=await(await fetch(`/api/v2/memory/episodic?q=${encodeURIComponent(document.getElementById("v2-ep-event").value)}&entity=${encodeURIComponent(document.getElementById("v2-ep-entity").value)}`)).json();
    const hits=d.hits||[];
    v2Out("v2-mem-out",hits.length?hits.map(h=>`<div class="issue-item">${esc(h.entity)} ${esc(h.snippet)} <span class="dim">${h.score.toFixed(2)}</span></div>`).join(""):`<div class="dim">${esc(d.summary||"无记录")}</div>`);}
  catch(e){v2Err("v2-mem-out",e);}
}
async function v2ProcList(){
  try{const d=await(await fetch("/api/v2/memory/procedural")).json();
    const sk=d.skills||[];
    v2Out("v2-mem-out",`<b>procedural 技能 ${sk.length} 个</b>`+sk.map(s=>`<div class="issue-item">${esc(s.id)} ${esc(s.name)} [${esc(s.status)}] R${esc(s.role||"")}</div>`).join("")||'<div class="dim">空</div>');}
  catch(e){v2Err("v2-mem-out",e);}
}
// M04 工具注册表
async function v2ToolsList(){
  try{const d=await(await fetch(`/api/v2/tools?capability=${encodeURIComponent(document.getElementById("v2-tool-cap").value)}`)).json();
    const ts=d.tools||[];
    v2Out("v2-tools-out",`<b>工具 ${ts.length} 个</b>`+ts.map(t=>`<div class="issue-item"><b>${esc(t.id)}</b> <span class="tb-chip">${esc(t.capability)}</span> <span class="dim">${esc(t.description||"")}</span></div>`).join(""));}
  catch(e){v2Err("v2-tools-out",e);}
}
async function v2ToolsExec(){
  try{let params={};try{params=JSON.parse(document.getElementById("v2-tool-params").value||"{}");}catch(e){}
    const d=await v2Post("/api/v2/tools",{tool_id:document.getElementById("v2-tool-id").value,params});
    const r=d.result||{};
    v2Out("v2-tools-out",`<b>${r.ok?"[OK]":"[FAIL]"}</b> ${esc(r.trace_id||"")}<pre style="font-size:11px;white-space:pre-wrap">${esc(JSON.stringify(r.data??r.error,null,1).slice(0,800))}</pre>`);}
  catch(e){v2Err("v2-tools-out",e);}
}
// P1 公式计算引擎
async function v2Calc(){
  try{
    let data={};try{data=JSON.parse(document.getElementById("v2-calc-data").value||"{}");}catch(e){}
    const d=await v2Post("/api/v2/calc",{standard:document.getElementById("v2-calc-std").value,calc_type:document.getElementById("v2-calc-type").value,data});
    const r=d.result||{};
    if(!r.ok){v2Out("v2-calc-out",`<div class="dim">[!] ${esc(r.error)}</div>`);return;}
    v2Out("v2-calc-out",`<b>[${esc(r.name)}] = ${r.value} ${esc(r.unit)}</b>
      <div>公式：${esc(r.expr)}（${esc(r.standard)} ${esc(r.clause||"")}）</div>
      <div class="dim" style="font-size:11px">过程：${(r.trace||[]).map(esc).join("；")}</div>`);
  }catch(e){v2Err("v2-calc-out",e);}
}
// P6 数据接入：数据源健康状态 + 取数（失败自动降级离线）
async function v2PublicSources(){
  try{
    const d=await fetch("/api/v2/publicapi/sources").then(r=>r.json());
    const srcs=d.sources||[];
    const sel=document.getElementById("v2-pub-source");
    sel.innerHTML='<option value="">选择数据源</option>'+srcs.map(s=>`<option value="${esc(s.source_id)}">${esc(s.name)}</option>`).join("");
    const st=s=>s.ok?'<span style="color:var(--green)">[ON]</span>':'<span style="color:var(--red)">[OFF]</span>';
    v2Out("v2-pub-srcs",
      `<div class="dim">数据源健康状态（${srcs.length} 个，refresh 探测接口可达性）：</div>`+
      '<table style="width:100%;font-size:12px;border-collapse:collapse;margin-top:6px">'+
      '<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>数据源</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>类型</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>状态</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>缓存</b></td></tr>'+
      srcs.map(s=>`<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.name)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.category)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${st(s)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${s.cache_ttl}s</td></tr>`).join("")+
      '</table>'+
      '<div class="dim" style="margin-top:6px">[ON] 接口可达；[OFF] 不可达时自动降级离线样例（degraded），报告流水线不受影响。</div>');
  }catch(e){v2Err("v2-pub-srcs",e);}
}
async function v2PublicFetch(){
  const sid=document.getElementById("v2-pub-source").value;
  if(!sid){v2Err("v2-pub-out",new Error("请先选择数据源"));return;}
  const raw=document.getElementById("v2-pub-param").value||"";
  const params={};
  raw.split(/[;,；]/).forEach(kv=>{const i=kv.indexOf("=");if(i>0)params[kv.slice(0,i).trim()]=kv.slice(i+1).trim();});
  try{
    const d=await v2Post("/api/v2/publicapi/fetch",{source_id:sid,...params});
    const flags=[esc(d.source||sid)];
    if(d.cached)flags.push("缓存");
    if(d.degraded)flags.push('<span style="color:var(--warn)">降级 offline</span>');
    if(d.error)flags.push('<span style="color:var(--red)">'+esc(d.error)+'</span>');
    v2Out("v2-pub-out",
      `<div class="dim">${flags.join(" | ")}</div>`+
      "<pre style='font-size:11px;white-space:pre-wrap;margin-top:6px'>"+esc(JSON.stringify(d.data,null,1))+"</pre>");
  }catch(e){v2Err("v2-pub-out",e);}
}

// G3 链路追踪：span 树查询（trace_id 或 task_id）+ 聚合统计
async function v2TraceQuery(){
  const traceId=document.getElementById("v2-trace-id").value.trim();
  const taskId=document.getElementById("v2-trace-task").value.trim();
  try{
    let d;
    if(taskId)d=await v2Post("/api/v2/trace/task?task_id="+encodeURIComponent(taskId));
    else if(traceId)d=await v2Post("/api/v2/trace/query?trace_id="+encodeURIComponent(traceId));
    else{v2Err("v2-trace-out",new Error("请输入 trace_id 或 task_id"));return;}
    if(!d.ok){v2Err("v2-trace-out",new Error(d.error||"查询失败"));return;}
    if(d.traces){
      // 按任务查：trace 摘要列表
      if(!d.traces.length){v2Out("v2-trace-out",'<div class="dim">该任务暂无链路记录（运行一次对话后产生）</div>');return;}
      v2Out("v2-trace-out",
        '<table style="width:100%;font-size:12px;border-collapse:collapse">'+
        '<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>trace_id</b></td>'+
        '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>耗时</b></td>'+
        '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>span数</b></td>'+
        '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>成本</b></td>'+
        '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>时间</b></td></tr>'+
        d.traces.map(t=>`<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(t.trace_id)}</td>`+
        `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${t.duration_ms}ms</td>`+
        `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${t.span_count}</td>`+
        `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">¥${t.cost}</td>`+
        `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(t.ts||"")}</td></tr>`).join("")+
        '</table>');
      return;
    }
    // 按 trace_id：span 树
    if(!d.trace){v2Out("v2-trace-out",'<div class="dim">未找到该 trace_id</div>');return;}
    const lines=[];
    const walk=(sp,depth)=>{lines.push(`${"  ".repeat(depth)}- [${esc(sp.type)}] ${esc(sp.name)} (${sp.duration_ms}ms, ${sp.status})${sp.model?" | "+esc(sp.model):""}${sp.in_tokens?` | in ${sp.in_tokens}/out ${sp.out_tokens}`:""}`);(sp.children||[]).forEach(c=>walk(c,depth+1));};
    (d.roots||[]).forEach(r=>walk(r,0));
    v2Out("v2-trace-out",
      `<div class="dim">trace ${esc(d.trace.trace_id)} | ${d.trace.duration_ms}ms | ${d.count} spans | ¥${d.trace.cost}</div>`+
      "<pre style='font-size:11px;white-space:pre-wrap;margin-top:6px'>"+esc(lines.join("\n"))+"</pre>");
  }catch(e){v2Err("v2-trace-out",e);}
}
async function v2TraceAggregate(){
  try{
    const d=await v2Post("/api/v2/trace/aggregate");
    if(!d.ok){v2Err("v2-trace-agg",new Error(d.error||"聚合失败"));return;}
    const by=d.by_type||{};
    const rows=Object.keys(by).map(k=>`<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(k)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${by[k]}</td></tr>`).join("");
    const slow=(d.slowest||[]).map(s=>`<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.name)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.type)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${s.duration_ms}ms</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.status)}</td></tr>`).join("");
    v2Out("v2-trace-agg",
      `<div>近7天：<b>${d.trace_count}</b> 次链路 / <b>${d.span_count}</b> spans / <b>${d.total_ms}ms</b> / <b>¥${d.total_cost}</b> / 错误 <b style="color:var(--red)">${d.errors}</b></div>`+
      '<div class="dim" style="margin-top:6px">span 类型分布：</div>'+
      '<table style="width:100%;font-size:12px;border-collapse:collapse">'+
      '<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>类型</b></td><td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>数量</b></td></tr>'+
      rows+'</table>'+
      '<div class="dim" style="margin-top:6px">慢调用 Top（耗时降序）：</div>'+
      '<table style="width:100%;font-size:12px;border-collapse:collapse">'+
      '<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>名称</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>类型</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>耗时</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>状态</b></td></tr>'+
      slow+'</table>');
  }catch(e){v2Err("v2-trace-agg",e);}
}

// G1 显式规划器：任务 -> 步骤列表 -> 一键执行
let __v2PlanSteps = [];
async function v2PlanRun(){
  const text=document.getElementById("v2-plan-text").value.trim();
  if(!text){v2Err("v2-plan-out",new Error("请输入任务描述"));return;}
  try{
    const d=await v2Post("/api/v2/plan/run",{text,mode_hint:"interactive",execute:false});
    if(!d.ok){v2Err("v2-plan-out",new Error("规划失败"));return;}
    __v2PlanSteps=d.steps||[];
    const r=d.route||{};
    const rows=(d.steps||[]).map(s=>`<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${s.seq}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.goal)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.action)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.target)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.note||"")}</td></tr>`).join("");
    v2Out("v2-plan-out",
      `<div class="dim">领域 D${esc(r.domain||"-")} | 意图 ${esc(r.intent||"craft")} | 共 ${(d.steps||[]).length} 步（点击"一键执行"顺序执行）</div>`+
      '<table style="width:100%;font-size:12px;border-collapse:collapse;margin-top:6px">'+
      '<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>#</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>目标</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>动作</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>目标</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>说明</b></td></tr>'+rows+'</table>');
  }catch(e){v2Err("v2-plan-out",e);}
}
async function v2PlanExecute(){
  if(!__v2PlanSteps.length){v2Err("v2-plan-out",new Error("请先生成计划"));return;}
  try{
    const text=document.getElementById("v2-plan-text").value.trim();
    const d=await v2Post("/api/v2/plan/execute",{steps:__v2PlanSteps,text});
    if(!d.ok){v2Err("v2-plan-out",new Error("执行失败"));return;}
    const marks={done:'<span style="color:var(--green)">PASS</span>',failed:'<span style="color:var(--red)">FAIL</span>',pending:'<span class="dim">SKIP</span>'};
    const rows=(d.steps||[]).map(s=>`<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${marks[s.status]||esc(s.status)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${s.seq}. ${esc(s.goal)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.target)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(String(s.result||"").slice(0,120))}</td></tr>`).join("");
    v2Out("v2-plan-out",
      `<div>成功 ${d.executed} / ${d.steps.length}，失败 ${d.failed}：</div>`+
      '<table style="width:100%;font-size:12px;border-collapse:collapse;margin-top:6px">'+
      '<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>状态</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>步骤</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>目标</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>结果</b></td></tr>'+rows+'</table>'+
      "<pre style='font-size:11px;white-space:pre-wrap;margin-top:6px'>"+esc(d.summary||"")+"</pre>");
  }catch(e){v2Err("v2-plan-out",e);}
}

// G2 动态子代理：派生子代理 / 回收 / 列表 / 并行起草
let __v2LastSub = '';
async function v2SubSpawn(){
  const task=document.getElementById("v2-sub-task").value.trim();
  const role=document.getElementById("v2-sub-role").value;
  if(!task){v2Err("v2-sub-out",new Error("请输入子任务"));return;}
  try{
    const d=await v2Post("/api/v2/subagent",{task,role_id:role});
    if(!d.ok){v2Err("v2-sub-out",new Error(d.error||"派生失败"));return;}
    __v2LastSub=d.sub_id;
    document.getElementById("v2-sub-id").value=d.sub_id;
    v2Out("v2-sub-out",`<div>已派生子代理 <b>${esc(d.sub_id)}</b>（${esc(d.name)}，角色 ${esc(d.role)}）后台执行中。点击"回收"获取结果。</div>`);
  }catch(e){v2Err("v2-sub-out",e);}
}
async function v2SubCollect(){
  const sid=document.getElementById("v2-sub-id").value.trim()||__v2LastSub;
  if(!sid){v2Err("v2-sub-out",new Error("缺少 sub_id"));return;}
  try{
    const d=await v2Post("/api/v2/subagent/collect",{sub_id:sid,timeout:60});
    if(!d.ok){v2Err("v2-sub-out",new Error(d.error||"回收失败"));return;}
    v2Out("v2-sub-out",
      `<div>子代理 <b>${esc(d.id)}</b> status=${esc(d.status)} | ok=${d.ok} | 角色 ${esc(d.role)} | 工具调用 ${d.tool_calls} 次 | 错误 ${d.errors}</div>`+
      `<div style="margin-top:6px">结果：</div>`+
      "<pre style='font-size:11px;white-space:pre-wrap;margin-top:6px'>"+esc(d.result||"")+"</pre>");
  }catch(e){v2Err("v2-sub-out",e);}
}
async function v2SubList(){
  try{
    const d=await v2Post("/api/v2/subagent");
    const rows=(d.subagents||[]).map(j=>`<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(j.id)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(j.status)}</td></tr>`).join("");
    v2Out("v2-sub-out",(rows?'<table style="width:100%;font-size:12px;border-collapse:collapse">'+
      '<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>sub_id</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>状态</b></td></tr>'+rows+'</table>'
      :'<div class="dim">无运行中子代理</div>'));
  }catch(e){v2Err("v2-sub-out",e);}
}
async function v2SubParallel(){
  const task=document.getElementById("v2-sub-task").value.trim()||"生成章节初稿";
  try{
    const d=await v2Post("/api/v2/subagent/parallel",{tasks:[task+"（第一章）",task+"（第二章）",task+"（第三章）"],role_id:"R4",timeout:60});
    if(!d.ok){v2Err("v2-sub-out",new Error(d.error||"并行执行失败"));return;}
    const rows=(d.results||[]).map((r,i)=>`<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px">子代理${i+1}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(r.status)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${r.ok?'PASS':'FAIL'}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc((r.result||"").slice(0,120))}</td></tr>`).join("");
    v2Out("v2-sub-out",'<div>3 个子代理并行执行：</div><table style="width:100%;font-size:12px;border-collapse:collapse;margin-top:6px">'+
      '<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>子代理</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>状态</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>结果</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>摘要</b></td></tr>'+rows+'</table>');
  }catch(e){v2Err("v2-sub-out",e);}
}

// G7 MCP 双向：工具清单 / 调用（JSON-RPC tools/call 语义）
async function v2McpList(){
  try{
    const d=await v2Post("/api/v2/mcp/tools");
    if(!d.ok){v2Err("v2-mcp-out",new Error(d.error||"获取失败"));return;}
    const rows=(d.tools||[]).map(t=>`<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(t.name)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc((t.description||"").slice(0,80))}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${Object.keys(t.inputSchema.properties||{}).length} 参数</td></tr>`).join("");
    v2Out("v2-mcp-out",`<div class="dim">暴露 ${d.count} 个工具给外部 MCP 客户端（Claude Code / Cursor 等）</div>`+
      '<table style="width:100%;font-size:12px;border-collapse:collapse;margin-top:6px">'+
      '<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>工具</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>说明</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>参数数</b></td></tr>'+rows+'</table>');
  }catch(e){v2Err("v2-mcp-out",e);}
}
async function v2McpCall(){
  const name=document.getElementById("v2-mcp-tool").value;
  const rawArgs=document.getElementById("v2-mcp-args").value.trim();
  let args={};
  if(rawArgs){try{args=JSON.parse(rawArgs);}catch(e){v2Err("v2-mcp-out",new Error("参数非合法JSON"));return;}}
  try{
    const d=await v2Post("/api/v2/mcp",{jsonrpc:"2.0",id:1,method:"tools/call",params:{name,arguments:args}});
    if(!d.result){v2Err("v2-mcp-out",new Error(d.error&&d.error.message||"调用失败"));return;}
    const text=(d.result.content&&d.result.content[0]&&d.result.content[0].text)||"";
    v2Out("v2-mcp-out",`<div>tools/call <b>${esc(name)}</b> → ${d.result.isError?'<span style="color:var(--red)">ERROR</span>':'<span style="color:var(--green)">OK</span>'}</div>`+
      "<pre style='font-size:11px;white-space:pre-wrap;margin-top:6px'>"+esc(text.slice(0,2000))+"</pre>");
  }catch(e){v2Err("v2-mcp-out",e);}
}

// G6 多模态输入：图片视觉理解 + Provider 能力检测
async function v2VisionRun(){
  const path=document.getElementById("v2-vision-path").value.trim();
  const q=document.getElementById("v2-vision-q").value.trim();
  if(!path){v2Err("v2-vision-out",new Error("请输入图片路径"));return;}
  try{
    const d=await v2Post("/api/vision/analyze",{path,question:q});
    if(!d.ok){v2Err("v2-vision-out",new Error((d.error||"分析失败")+(d.method==='ocr'?' [OCR兜底]':'')));return;}
    v2Out("v2-vision-out",
      `<div>识别方式：${esc(d.method==='vlm'?'VLM 视觉模型':'RapidOCR')} | 结果：</div>`+
      "<pre style='font-size:11px;white-space:pre-wrap;margin-top:6px'>"+esc(d.text)+"</pre>");
  }catch(e){v2Err("v2-vision-out",e);}
}
async function v2VisionSupported(){
  try{
    const r=await fetch("/api/v2/vision/supported").then(x=>x.json()).catch(()=>({supported:false}));
    v2Out("v2-vision-out",`<div>当前 Provider 多模态支持：${r.supported?'<span style="color:var(--green)">是（VLM 直读可用）</span>':'<span class="dim">否（回退 RapidOCR 文字提取）</span>'}</div>`);
  }catch(e){v2Err("v2-vision-out",e);}
}

// G8 技能市场：目录 / 详情 / 导出 zip / 导入（进 P9 待审）/ 统计
async function v2MktList(){
  try{
    const d=await v2Post("/api/v2/market");
    if(!d.ok){v2Err("v2-mkt-out",new Error(d.error||"获取失败"));return;}
    const rows=(d.items||[]).map(s=>`<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.id)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.name)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.source)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.status)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.version)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">公式${(s.formula_ids||[]).length}/标准${(s.standard_refs||[]).length}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.summary||"")}</td></tr>`).join("");
    v2Out("v2-mkt-out",`<div class="dim">技能市场共 ${d.count} 项（v2 技能库 + v1.2 file 技能）</div>`+
      '<table style="width:100%;font-size:12px;border-collapse:collapse;margin-top:6px">'+
      '<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>ID</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>名称</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>源</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>状态</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>版本</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>关联</b></td>'+
      '<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>摘要</b></td></tr>'+rows+'</table>');
  }catch(e){v2Err("v2-mkt-out",e);}
}
async function v2MktBrowse(){
  const key=document.getElementById("v2-mkt-key").value.trim();
  if(!key){v2Err("v2-mkt-out",new Error("请输入技能 id/key"));return;}
  try{
    const d=await v2Post("/api/v2/market/browse?key="+encodeURIComponent(key));
    if(!d.ok){v2Err("v2-mkt-out",new Error(d.error||"未找到"));return;}
    v2Out("v2-mkt-out",
      `<div>${esc(d.name)} [${esc(d.id)}] ${esc(d.source)} ${esc(d.status)} v${esc(d.version)}</div>`+
      `<div class="dim">领域 ${esc(d.domain||"-")} | 公式 ${(d.formula_ids||[]).join("、")||"-"} | 标准 ${(d.standard_refs||[]).join("、")||"-"}</div>`+
      "<pre style='font-size:11px;white-space:pre-wrap;margin-top:6px'>"+esc((d.definition||"").slice(0,1200))+"</pre>");
  }catch(e){v2Err("v2-mkt-out",e);}
}
async function v2MktExport(){
  const key=document.getElementById("v2-mkt-key").value.trim();
  if(!key){v2Err("v2-mkt-out",new Error("请输入技能 id/key"));return;}
  try{
    const d=await v2Post("/api/v2/market/export",{key,include_related:true});
    if(!d.ok){v2Err("v2-mkt-out",new Error(d.error||"导出失败"));return;}
    v2Out("v2-mkt-out",
      `<div>已导出：<b>${esc(d.name)}</b> → ${esc(d.path)}（${(d.size/1024).toFixed(1)}KB）</div>`+
      `<div class="dim">含公式 ${(d.formula_ids||[]).length} 个：${esc((d.formula_ids||[]).join("、"))}</div>`+
      `<div class="dim">含标准引用 ${(d.standard_refs||[]).length} 个：${esc((d.standard_refs||[]).join("、"))}</div>`);
  }catch(e){v2Err("v2-mkt-out",e);}
}
async function v2MktImport(){
  const zipPath=document.getElementById("v2-mkt-zip").value.trim();
  if(!zipPath){v2Err("v2-mkt-out",new Error("请输入 zip 完整路径"));return;}
  try{
    const d=await v2Post("/api/v2/market/import",{zip_path:zipPath});
    if(!d.ok){v2Err("v2-mkt-out",new Error(d.error||"导入失败"));return;}
    v2Out("v2-mkt-out",
      `<div>导入成功：<b>${esc(d.name)}</b> → ${esc(d.skill_id)}（${esc(d.domain)} v${esc(d.version)}）</div>`+
      `<div style="color:var(--blue)">状态：${esc(d.status)} — ${esc(d.note)}</div>`+
      `<div class="dim">请到 P9 待审核中心审批（R8）后激活。</div>`);
  }catch(e){v2Err("v2-mkt-out",e);}
}
async function v2MktStats(){
  try{
    const d=await v2Post("/api/v2/market/stats");
    if(!d.ok){v2Err("v2-mkt-out",new Error(d.error||"统计失败"));return;}
    v2Out("v2-mkt-out",`<div>技能总数 ${d.total}（v2: ${d.v2} + file: ${d.file}）| 已激活 ${d.active} | 待审 ${d.pending}</div>`+
      `<div class="dim">导出目录：${esc(d.exports_dir)}</div>`);
  }catch(e){v2Err("v2-mkt-out",e);}
}

// G5 记忆知识图谱：实体展开 / 关系管理 / 事实建图 / 实体抽取
async function v2GraphQuery(){
  const e=document.getElementById("v2-graph-entity").value.trim();
  if(!e){v2Err("v2-graph-out",new Error("请输入实体"));return;}
  try{
    const d=await v2Post("/api/v2/memory/graph?entity="+encodeURIComponent(e));
    if(!d.ok){v2Err("v2-graph-out",new Error(d.error||"查询失败"));return;}
    const rel=(d.relations||[]).map(r=>`<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(r.entity_a)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px"><b>${esc(r.rel)}</b></td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(r.entity_b)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">x${r.weight}</td></tr>`).join("");
    const facts=(d.facts||[]).map(f=>`<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(f.attr)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(f.value)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(f.ftype)}</td></tr>`).join("");
    const kb=(d.kb_hits||[]).slice(0,5).map(k=>`<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(k.title||k.std_no||k.code||"")}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(k.category||"")}</td></tr>`).join("");
    const sk=(d.skills||[]).map(s=>`<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.id)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.name)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(s.version)}</td></tr>`).join("");
    const dt=(d.decision_traces||[]).map(t=>`<tr><td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(t.entity_b)}</td>`+
      `<td style="border-bottom:1px solid var(--border-2);padding:3px 6px">${esc(t.source)}</td></tr>`).join("");
    v2Out("v2-graph-out",
      `<div class="dim">实体 [${esc(d.entity)}] 图谱展开</div>`+
      (rel?('<div class="dim" style="margin-top:6px">关系（${(d.relations||[]).length}）：</div><table style="width:100%;font-size:12px;border-collapse:collapse">'+rel+'</table>'):'')+
      (facts?('<div class="dim" style="margin-top:6px">关联事实（${(d.facts||[]).length}）：</div><table style="width:100%;font-size:12px;border-collapse:collapse">'+facts+'</table>'):'')+
      (kb?('<div class="dim" style="margin-top:6px">知识库命中：</div><table style="width:100%;font-size:12px;border-collapse:collapse">'+kb+'</table>'):'')+
      (sk?('<div class="dim" style="margin-top:6px">关联技能：</div><table style="width:100%;font-size:12px;border-collapse:collapse">'+sk+'</table>'):'')+
      (dt?('<div class="dim" style="margin-top:6px">决策痕迹（reasoning）：</div><table style="width:100%;font-size:12px;border-collapse:collapse">'+dt+'</table>'):''));
  }catch(e){v2Err("v2-graph-out",e);}
}
async function v2GraphAdd(){
  const a=document.getElementById("v2-graph-a").value.trim();
  const r=document.getElementById("v2-graph-rel").value.trim();
  const b=document.getElementById("v2-graph-b").value.trim();
  if(!a||!b){v2Err("v2-graph-out",new Error("实体A/B不能为空"));return;}
  try{
    const d=await v2Post("/api/v2/memory/graph",{entity_a:a,rel:r||"related",entity_b:b,source:"ui"});
    v2Out("v2-graph-out",`<div>已添加：${esc(d.entity_a)} -${esc(d.rel)}-> ${esc(d.entity_b)}（权重 ${d.weight}）</div>`);
  }catch(e){v2Err("v2-graph-out",e);}
}
async function v2GraphExtract(){
  const a=document.getElementById("v2-graph-a").value.trim()||"标准号 GB 3838-2002 与 COD 氨氮";
  try{
    const d=await v2Post("/api/v2/memory/graph/extract",{text:a});
    v2Out("v2-graph-out",`<div>抽取实体：${(d.entities||[]).map(esc).join("、")}</div>`);
  }catch(e){v2Err("v2-graph-out",e);}
}
async function v2GraphLinkFacts(){
  try{
    const d=await v2Post("/api/v2/memory/graph/link-facts");
    v2Out("v2-graph-out",`<div>从 memory_facts 建立关系 ${d.linked} 条</div>`);
  }catch(e){v2Err("v2-graph-out",e);}
}

// P9 待审核中心：统一审核 pending 技能 + 模块蓝图（唯一人工闸门）
async function v2RevList(){
  const t=document.getElementById("v2-rev-type").value;
  const s=document.getElementById("v2-rev-status").value;
  try{
    const d=await fetch("/api/v2/review/list?status="+encodeURIComponent(s)+"&type="+encodeURIComponent(t)).then(r=>r.json());
    const items=d.items||[];
    if(!items.length){v2Out("v2-rev-out",'<div class="dim">暂无待审核项（技能/蓝图已全部处理）</div>');return;}
    const cls=it=>it.type==='skill'?'<span style="color:var(--blue)">[技能]</span>':'<span style="color:var(--purple)">[蓝图]</span>';
    v2Out("v2-rev-out",
      '<div class="dim">待审核 '+items.length+' 项（也可在对话框中回复"审批通过"完成审核）</div>'+
      items.map(it=>
        `<div style="border:1px solid var(--border);border-radius:8px;padding:8px;margin-top:6px">
          <div><b>${esc(it.name)}</b> ${cls(it)} <span style="color:var(--text-dim);font-size:11px">${esc(it.status)} · ${esc(it.domain||'')} · ${esc(it.created_by||'')}</span></div>
          <div style="color:var(--text-dim);font-size:11px;margin-top:2px">${esc(it.summary||'')}</div>
          <div style="margin-top:6px">
            <button class="btn-mini primary" onclick="v2RevAct('approve','${it.type}','${esc(it.id)}')">批准</button>
            <button class="btn-mini" onclick="v2RevAct('reject','${it.type}','${esc(it.id)}')">拒绝</button>
          </div>
        </div>`).join(""));
  }catch(e){v2Err("v2-rev-out",e);}
}
async function v2RevAct(action,type,id){
  try{await v2Post("/api/v2/review/"+action,{type,id});v2RevList();}
  catch(e){v2Err("v2-rev-out",e);}
}
async function v2RevApproveAll(){
  try{
    const d=await v2Post("/api/v2/review/approve-all",{});
    v2Out("v2-rev-out",`<div class="dim">一键批量批准完成：技能 ${d.skills||0} 个激活，蓝图 ${d.blueprint?'已激活':'无待审'}。</div>`);
    v2RevList();
  }catch(e){v2Err("v2-rev-out",e);}
}

async function v2CalcFormulas(){
  try{
    const d=await(await fetch("/api/v2/calc/formulas")).json();
    const fs=d.formulas||[];
    v2Out("v2-calc-out",`<b>公式库 ${fs.length} 个</b>`+fs.map(f=>`<div class="issue-item"><b>${esc(f.id)}</b> ${esc(f.name)} <span class="tb-chip">${esc(f.standard)}</span> ${esc(f.calc_type||"")}</div>`).join(""));
  }catch(e){v2Err("v2-calc-out",e);}
}
