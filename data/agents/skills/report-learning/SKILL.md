---
name: 报告分类学习与模板管理
group: 报告输出
description: 多类型报告(验收/监测/方法验证/不确定度/环评/质控)批量学习、自动分门别类、模板完善与生成。
---

# 报告分类学习与模板管理技能

## 触发条件
用户提供一批报告/文档（目录或多个文件路径）并要求以下任一动作时触发：
- "学习/总结这批报告"、"完善报告模板"、"把模板扩展到其他领域"
- 提供多类报告（验收、监测、方法验证、不确定度、环评等）需要分门别类处理
- 需要为新领域报告生成标准模板

## 报告类型体系
`skill_learn` 工具内置类型注册表（tools.py `_REPORT_TYPES`），当前支持：

| 类型 key | 中文名 | 模板文件 |
|---|---|---|
| acceptance | 验收报告 | report_table_template.md |
| monitoring | 监测报告 | monitoring_report_template.md |
| method-validation | 方法验证报告 | method_validation_template.md |
| uncertainty | 不确定度报告 | uncertainty_template.md |
| eia | 环评报告 | eia_template.md |
| qaqc | 质控报告 | qaqc_template.md |

### 动态类型自主学习
除内置类型外，`skill_learn` 会自动学习并注册**任意新类型**：
- 样本未被内置类型识别时，按关键词自动聚类（如"排污许可"→ 排污许可报告、"应急预案"→ 应急预案报告等，见 tools.py `_AUTO_TYPE_WORDS`）
- 自动注册到 `data/report_types.json`（动态注册表，持久化）
- 自动生成模板骨架到 `references/templates/<key>_template.md`（从高频章节提炼）
- 注册后 `report_build` 即可按该类型（支持中文名）直接生成报告骨架

手动新增类型：在 `data/report_types.json` 添加条目（key/label/template/sections 章节特征/hint 识别关键词），或直接用 skill_learn 学习样本自动注册。

## 执行流程
1. 确认样本范围：`skill_learn(paths=...)` 传入目录或逗号分隔文件列表（推荐绝对路径）。
2. 类型模式：`report_type=auto` 自动识别（默认）；若用户明确只要某类，传具体类型。
3. 调用 `skill_learn` 批量解析（扫描件 OCR 自动兜底）、入库、按类型提炼章节、与模板比对。
4. 依据学习报告完善模板：
   - 高频章节（≥50% 样本）必须覆盖；新发现章节补充进模板；缺失章节按需精简。
   - 把学习结论（必填/常见章节、编制要点）写入对应模板文件的头部统计区。
5. 答复用户：说明各类别样本数、模板更新点。

## 注意事项
- 扫描件 PDF 由 OCR 管线自动兜底（`/extract_pdf` 已修复：剔除页面注释后按真实文本判断）。
- 首次学习某类型时模板缺失，先按学习报告的高频章节生成模板骨架。
- 入库使用 `_kb_ingest_sync` 完整管道（解析/分类/入库/解读/总结后台异步）。
- 学习记录 JSON 自动写盘 `data/learn/report-learning_<时间戳>.json`，可复盘。
