-- 0008 领域团队注册表（P0 团队基座）
-- 角色降级为团队内流程节点标签；团队承载领域技能/流程/报告模板/工具白名单
CREATE TABLE IF NOT EXISTS team(
  team_id     TEXT PRIMARY KEY,
  domain      TEXT UNIQUE,
  name        TEXT NOT NULL,
  description TEXT DEFAULT '',
  roles       TEXT DEFAULT '[]',   -- json: [{node_id,label,tools}]
  skills      TEXT DEFAULT '[]',   -- json: [skill keys]
  wf_template TEXT DEFAULT 'report_pipeline',
  report_tmpls TEXT DEFAULT '[]',  -- json: [{type,template_id}]
  tools       TEXT DEFAULT '[]',   -- json: 工具白名单
  status      TEXT DEFAULT 'active', -- active / onboarding
  created_at  TEXT DEFAULT (datetime('now','localtime'))
);

-- 初始种子：默认通用生态团队（覆盖 12 大类冷启动）
INSERT OR IGNORE INTO team(team_id, domain, name, description, roles, skills, wf_template, report_tmpls, tools, status) VALUES
('T-ecology-001', 'ecology', '通用生态环境团队',
 '覆盖水/大气/声/土壤/生态/辐射/碳/环评/监测/执法/咨询/标准法规 12 大类的默认团队，新领域自举前的兜底',
 '[]', '[]', 'report_pipeline', '[]', '["kb_lookup","kb_hybrid","kb_save","kb_stats","kb_audit","kb_backup","locate","calc_formula","web_search","web_fetch","publicapi_fetch","report_generate","report_review","report_compliance","memory_extract","learn_observe","learn_reflect","learn_crystallize","learn_reuse"]',
 'active');
