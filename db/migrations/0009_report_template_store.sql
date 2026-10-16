-- 0009 报告模板库（P1 泛化基座：模板自学习 + 配置化）
-- 用户上传报告自动归纳为模板；内置模板冷启动兜底，可被用户模板覆盖

CREATE TABLE IF NOT EXISTS report_template(
  template_id    TEXT PRIMARY KEY,
  type           TEXT NOT NULL,          -- eia / monitoring / carbon / emergency …（自动归纳或内置）
  name           TEXT NOT NULL,
  sections       TEXT DEFAULT '[]',      -- json: [{name, desc}] 归纳出的节结构
  placeholders   TEXT DEFAULT '[]',      -- json: [字段占位符]
  prompt         TEXT DEFAULT '',        -- 生成提示词模板
  export_title   TEXT DEFAULT '',        -- 导出标题（如：环境监测报告 / 碳排放核查报告）
  docx_path      TEXT DEFAULT '',
  source_uploads TEXT DEFAULT '[]',      -- json: 来源上传报告 ids
  status         TEXT DEFAULT 'draft',   -- draft / published（R8 审核发布）
  builtin        INTEGER DEFAULT 0,
  created_at     TEXT DEFAULT (datetime('now','localtime'))
);

-- 内置模板（冷启动兜底，均保持既有结构）
INSERT OR IGNORE INTO report_template(template_id, type, name, sections, placeholders, prompt, export_title, docx_path, builtin, status) VALUES
('monitoring', 'monitoring', '环境监测报告', '[{"name":"项目概况","desc":"委托方、项目背景、监测目的"},{"name":"监测方案","desc":"点位、频次、项目、方法"},{"name":"质量控制","desc":"质控措施与结果"},{"name":"监测结果","desc":"数据结果表"},{"name":"结论与建议","desc":"评价结论"}]',
 '["project_name","points","items","standards","results","conclusion"]',
 '按环境监测报告规范生成 5 节结构：项目概况/监测方案/质量控制/监测结果/结论与建议。',
 '环境监测报告', 'templates/report_monitoring.docx', 1, 'published'),
('acceptance', 'acceptance', '验收监测报告', '[{"name":"项目概况","desc":"验收范围与依据"},{"name":"验收方案","desc":"点位/项目/标准"},{"name":"监测结果","desc":"数据结果"},{"name":"验收结论","desc":"达标判定"}]',
 '["project_name","acceptance_scope","standards","results","verdict"]',
 '按验收监测报告规范生成 4 节结构：项目概况/验收方案/监测结果/验收结论。',
 '验收监测报告', 'templates/report_acceptance.docx', 1, 'published'),
('eia', 'eia', '环境影响评价报告', '[{"name":"项目概述","desc":"项目基本信息与工程分析"},{"name":"环境现状","desc":"区域环境质量现状"},{"name":"影响预测","desc":"各要素影响预测"},{"name":"防治措施","desc":"环保措施与对策"},{"name":"评价结论","desc":"环评结论"}]',
 '["project_name","environment_baseline","impacts","measures","conclusion"]',
 '按环境影响评价报告规范生成 5 节结构：项目概述/环境现状/影响预测/防治措施/评价结论。',
 '环境影响评价报告', 'templates/report_eia.docx', 1, 'published');

-- 多状态机模板（P1：wf_template 表，决策点 7）
CREATE TABLE IF NOT EXISTS wf_template(
  key     TEXT PRIMARY KEY,
  name    TEXT NOT NULL,
  states  TEXT DEFAULT '[]',   -- json: [{id,label}]
  edges   TEXT DEFAULT '[]',   -- json: [{from,to,event,guard}]
  builtin INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

INSERT OR IGNORE INTO wf_template(key, name, states, edges, builtin) VALUES
('report_pipeline', '报告流水线',
 '[{"id":"collect","label":"材料收集"},{"id":"draft","label":"报告起草"},{"id":"review","label":"审核"},{"id":"iterate","label":"迭代修改"},{"id":"complete","label":"完成"},{"id":"archive","label":"归档学习"}]',
 '[{"from":"collect","to":"draft","event":"submit"},{"from":"draft","to":"review","event":"submit"},{"from":"review","to":"iterate","event":"fix"},{"from":"review","to":"complete","event":"approve"},{"from":"iterate","to":"review","event":"fixed"},{"from":"complete","to":"archive","event":"archive"},{"from":"archive","to":"done","event":"learn"}]', 1),
('document_pipeline', '通用文档流水线',
 '[{"id":"research","label":"调研"},{"id":"draft","label":"起草"},{"id":"review","label":"审核"},{"id":"final","label":"定稿"},{"id":"archive","label":"归档"}]',
 '[{"from":"research","to":"draft","event":"submit"},{"from":"draft","to":"review","event":"submit"},{"from":"review","to":"final","event":"approve"},{"from":"review","to":"draft","event":"fix"},{"from":"final","to":"archive","event":"archive"}]', 1),
('knowledge_pipeline', '知识入库流水线',
 '[{"id":"collect","label":"采集"},{"id":"clean","label":"清洗"},{"id":"review","label":"审核"},{"id":"publish","label":"发布"}]',
 '[{"from":"collect","to":"clean","event":"next"},{"from":"clean","to":"review","event":"submit"},{"from":"review","to":"publish","event":"approve"},{"from":"review","to":"clean","event":"fix"}]', 1);
