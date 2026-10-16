---
name: ep-acceptance-report
group: 报告输出
description: "This skill should be used when the user wants to compile, draft, or generate a construction project completion environmental protection acceptance report (also called 竣工环境保护验收报告 or 建设项目竣工环境保护验收监测报告), especially when the deliverable must be exported as a Word (.docx) document. It guides collecting the required materials from the user across six categories, enforces the three mandatory documents (环评 / 环评批复 / CMA 验收监测报告) by reminding the user to upload any missing ones before producing the formal report, structures them into the standard eight-section report template plus the acceptance opinion section, and renders a formatted Word file via a bundled python-docx generator."
agent_created: true
---

# 竣工环境保护验收报告生成技能

本技能用于将用户提供的项目资料，整理成符合现行自主验收制度（国务院令第 682 号、
国环规环评〔2017〕4 号、生态环境部公告 2018 年第 9 号）的**竣工环境保护验收报告**，
并导出为排版规范的 **Word (.docx)** 文件。适用范围：污染影响类为主的建设项目的
验收报告（表）编制；生态影响类项目可参照结构并替换相应技术规范。

## 何时使用

- 用户提出"写/生成/编制竣工环保验收报告""出一份验收报告 Word""根据资料做验收报告"等。
- 用户已拿到或准备提供：环评及批复、验收监测报告、排污许可证、环保设施与图纸等资料。
- 用户要求把已有验收报告/模板整理成可编辑的 Word 版本。

## 工作流程

### 第 1 步：确认报告类型与范围

先明确两项边界，再用 `AskUserQuestion` 向用户确认（避免后续返工）：

- 项目类别：污染影响类 / 生态影响类（默认污染影响类）。
- 成果形式：验收监测**报告书** / 验收监测**报告表**（依环评等级；报告表可简化）。
- 是否分期验收、是否存在重大变动（性质/规模/地点/工艺/防治措施）。
- 是否仅产出"验收报告正文"，还是连同"验收意见"一并生成（默认两者都生成）。

> 若用户已给出模板（如既有项目验收报告），以其章节结构为优先，本技能的
> `references/report_template.md`（验收报告书八章）作为兜底标准结构；
> 若为**验收监测报告表**项目（环评报告表项目），优先采用
> `references/report_table_template.md`（表一~表八结构，含封面、项目基本信息表、
> 验收监测依据及标准限值、工程建设内容、污染源处理、环评批复落实、质控、
> 监测内容、监测结果、验收监测结论等报告表特有章节）。

### 第 2 步：按清单收集资料（含必备三件套门控）

> **必备三件套（缺一不可，否则不得出具正式验收报告）**：
> ① 环境影响报告书（表）　② 环境影响评价批复　③ 验收监测报告（CMA 资质出具，须盖 CMA 章）。
> 其余材料按项目类型（污染影响类 / 生态影响类 / 加油站等）实际提供即可，缺失则以占位生成。

向用户呈现 `references/materials_checklist.md` 中的**六类材料清单**（其中前三件已标注 ★必备），
引导其提交：
可上传文件（环评 PDF/Word、批复、CMA 验收监测报告、排污许可证、平面/点位图、
设备清单、危废合同与联单、应急预案及备案等），也可直接口述/粘贴文字。

收集要点（每类对应报告章节见清单）：
1. 法定依据类：环评及批复、初设环保篇章、变更/重新报批文件。
2. 过程建设类：环保设施施工与竣工资料、设备合同发票、调试运行记录、图件。
3. 监测证据类：**CMA 验收监测报告（须盖 CMA 章）**、工况记录、在线监测联网证明、总量核算。
4. 管理合规类：排污许可证、危废管理计划/合同/联单/暂存间、应急预案及备案、环保台账。
5. 验收组织类：验收组单位与成员、公示材料、全国验收信息系统填报回执。
6. **图件与影像类（报告自动插图来源）**：地理位置图、四至图、敏感目标分布图、总平面布置图、
   监测布点图、公示截图（→ 附图）；营业执照、环评批复、排污许可证、危废合同/暂存间照片、
   CMA 报告章页、应急预案备案（→ 附件）；厂区全景与环保设施现场照片（→ 正文穿插）。
   用户提交图片文件（jpg/png）或 PDF 首页截图即可，技能按"附图/附件/现场照片"自动插入对应位置。

如用户仅给单一源文件（如整本验收报告 PDF 或既有 docx 模板），用 Read / python-docx 解析并抽取
对应字段；如给的是 OCR 扫描件，提示其核对表格与原数字。既有 docx 模板中的图片（附图/附件）
可用 `scripts/extract_docx_images.py` 思路提取后纳入 `figures`/`appendices`。

### 第 2.5 步：必备材料校验与缺件提醒（门控）

**收集结束后、生成正式报告前，必须执行本步**——这是本技能的核心门控：

1. 把已收集内容整理为 JSON（至少含三件套字段）后，运行校验脚本：
   ```bash
   .../envs/default/Scripts/python.exe \
     (skill_dir)/scripts/check_materials.py --data acceptance_data.json
   ```
2. **读取输出结论**：
   - 若存在 `[必备缺失]` 项 → **立即停止生成正式报告**，把《资料补齐清单》完整呈现给用户，
     逐项写明缺什么、对应报告哪个位置、需要用户上传什么格式的文件（如：
     "缺环评批复 → 请上传审批部门批复扫描件（jpg/png/PDF 首页截图）"），
     并等待用户补齐后再回到第 2 步继续；用户一次补齐多项的，可在同一轮提交多个文件。
   - 若 `[建议补充]` 项缺失 → 可继续，但生成时缺失项渲染占位框，并在交付时一并列出。
3. 用户补齐后，把新文件纳入 `acceptance_data.json`（更新 `eia_report` / `eia_approval` /
   `monitoring_report` 的 `path`，或将扫描件加入 `appendices`），**重新运行校验脚本确认
   三件套齐备**，再进入第 4 步生成。

> 三件套的 JSON 填写位置（顶层键）：
> - `eia_report`：环评报告书/表文件 `{"path": "...", "note": "..."}`
> - `eia_approval`：批复扫描件 `{"path": "...", "dept": "审批部门", "no": "批复文号", "date": "..."}`
> - `monitoring_report`：CMA 监测报告 `{"path": "...", "agency": "监测机构", "cma_no": "CMA编号", "date": "..."}`
>
> 校验脚本也会兼容"附件含批复/监测报告字样""审批信息已填文号"等间接填写方式，避免误判。

### 第 3 步：整理为结构化数据

将收集到的信息整理为 `references/report_template.md` 定义的 **JSON 数据模型**，
写入工作区文件（如 `acceptance_data.json`）。务必覆盖以下核心字段：
报告标题、建设单位、工程基本情况（地点/规模/投资/审批/验收范围）、
四张表格（工程组成、验收产品、原辅材料、设备）、环保设施建设情况、
调试效果与达标评价、验收结论、后续要求、署名与日期，以及验收意见段落；
**图件类**须填入 `figures` / `appendices` / `layout_photos` / `facility_photos`
（提供图片路径则自动插入，缺失则渲染占位框并汇总到待补清单）。

缺失且无替代来源的项，用占位提示（如"【待补充：XX】"）标注，并在交付时列出待补清单，
**不得编造监测数据与标准限值**。

### 第 4 步：生成 Word 报告

确保运行环境具备 `python-docx`（在托管 Python 的 venv 中安装：
`.../python.exe -m venv .../envs/default` 后 `.../envs/default/Scripts/pip install python-docx`）。
然后运行捆绑脚本并传入数据文件：

```bash
.../envs/default/Scripts/python.exe \
  (skill_dir)/scripts/generate_acceptance_docx.py \
  --data acceptance_data.json \
  --require-essentials \
  --out 竣工环境保护验收报告.docx
```

- **务必加 `--require-essentials`**：三件套缺失时脚本会拒绝生成并退出（退出码 2），
  保证不会漏出缺少环评/批复/监测报告的"空壳报告"。
- 若用户明确要求先出草稿（如仅需占位版用于内部讨论），可去掉该参数；
  此时三件套缺失项会以"【必备材料缺失：XX —— 待用户上传补齐】"写入文末待补清单。

脚本按模板渲染：封面标题、五类元信息、一~八章正文、四张表格、署名盖章行、
独立的"竣工环境保护验收意见"章节，以及自动插入的"附图/附件/现场照片"图件章节。
图片插入规则：提供 `path` 且文件存在则居中插入（按页宽 95% 自动缩放、下方图注）；
`path` 为 null 或文件缺失则渲染带边框占位框并登记到文末"待补充材料清单"，不中断生成。
样式采用深蓝(#1a365d)标题、宋体/黑体正文、表格边框，符合政务/商务公文观感。

### 第 5 步：校验与交付

- 打开生成的 .docx，核对章节完整性、表格数据与用户资料一致、无占位残留。
- 用 `deliver_attachments` 交付 Word 文件，并附"待补充材料清单"（若有）。
- 若本轮因缺件被门控拦截，交付的应是**《资料补齐清单》**而非报告，并明确提示
  "补齐后重发资料即可继续生成"。
- 提示用户：验收报告须由建设单位组织验收、签字确认、公示并录入全国验收信息系统；
  本报告为内容草稿，结论责任在建设单位。

## 捆绑资源

- `references/materials_checklist.md`：六类材料收集清单（三件套标注 ★必备，其余按项目类型）。
- `references/report_template.md`：验收报告书八章 + 验收意见的标准结构，及 JSON 数据模型字段说明。
- `references/report_table_template.md`：验收监测报告表（表一~表八）标准结构（报告表项目优先采用）。
- `scripts/check_materials.py`：必备材料校验脚本，输出《资料补齐清单》（生成前必跑）。
- `scripts/generate_acceptance_docx.py`：python-docx 生成器，读取 JSON 输出 Word（支持 --require-essentials 门控）。
- `scripts/extract_docx_images.py`：从既有 docx 模板批量提取图片并映射到附图/附件。

## 注意事项

- 监测数据、标准限值、总量指标须以用户提供的正式文件为准，严禁虚构。
- 重大变动未重新报批、无证排污、未验先投等属《暂行办法》第八条不通过情形，
  如资料体现此类问题，在报告中如实标注并在交付说明中警示。
- 行业有特殊验收技术规范（火电、造纸、水泥等）的，相关章节优先执行行业规范。
