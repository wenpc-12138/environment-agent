# 竣工环境保护验收报告 — 标准结构与 JSON 数据模型

> 本文件定义验收报告的章节结构（以污染影响类为基准，参考金美特搬迁项目模板，并兼容
> 广东中宝加油站等更完整的"附图+附件"型模板）与生成脚本所需的 JSON 字段。
> 脚本 `scripts/generate_acceptance_docx.py` 读取此模型输出 Word，并自动插入图件。

## 一、报告正文八章结构 + 图件章节

- **一、工程建设基本情况**
  - 1、建设地点、规模、主要建设内容（含工程组成表1）
  - 2、建设过程、环保审批、竣工环保验收情况
  - 3、投资情况
  - 4、验收范围（含验收产品表2、原辅材料表3、设备表4）
- **二、工程变动情况**（无变动 / 变动说明）
- **三、环境保护设施建设情况**
  - （一）废水 （二）废气 （三）噪声 （四）固体废物 （五）其他（风险防范/在线监测/其他设施）
- **四、环境保护设施调试效果**
  - （一）环保设施处理效率（废水/废气/噪声/固废）
  - （二）污染物排放情况（废水/废气/噪声/固废/污染物排放总量）
- **五、工程建设对环境的影响**
- **六、制度落实情况**（组织机构、风险预案及备案、监测计划）
- **七、验收结论**
- **八、后续要求**
- 建设单位（盖章）：XXX 　 日期
- **附图**（自动插图章节，`figures` 提供时渲染）：附图1 地理位置图、附图2 四至图、
  附图3 敏感目标分布图、附图4 总平面布置图、附图5 监测布点图、附图6 公示截图
- **附件**（自动插图章节，`appendices` 提供时渲染）：附件1 营业执照、附件2 环评批复、
  附件3 排污许可证、附件4 危废合同/暂存间照片、附件5 CMA 监测报告章页、附件6 应急预案备案
- 正文穿插照片：`layout_photos`（一.1 之后，平面布置/厂区全景）、`facility_photos`（三 之后，环保设施现场照片）

## 二、验收意见章节（正文之后独立成章）

- 标题：XX项目竣工环境保护验收意见
- 一、工程建设基本情况 　二、工程变动情况 　三、环境保护设施建设情况
- 四、环境保护设施调试效果 　五、工程建设对环境的影响
- 六、验收结论（验收组同意通过验收） 　七、后续要求
- 验收组名单（附后）

---

## 三、JSON 数据模型（字段说明）

脚本读取的根对象字段如下；数组型表格字段为对象列表。

```jsonc
{
  "meta": {
    "report_title": "中山市XXX公司XXX项目（一期）竣工环境保护验收报告",
    "build_unit": "建设单位全称",
    "prepared_by": "编制单位（默认同建设单位）",
    "date": "2026-07-17",
    "source_note": "可选说明，如资料来源",
    "project_type": "污染影响类 | 生态影响类 | 加油站/油气回收"
  },

  // ============ 必备三件套（门控校验依据，缺失则提醒上传、暂停生成正式报告） ============
  // 三个键均为顶层；path 为文件绝对路径（缺失置 null），也可填 note/文号作为已提供佐证。
  "eia_report": {
    "path": "C:/.../环评报告表.pdf",
    "note": "环评报告表（项目全称）"
  },
  "eia_approval": {
    "path": "C:/.../环评批复.png",
    "dept": "审批部门全称",
    "no": "批复文号（如 中环审〔2026〕XX号）",
    "date": "批复日期"
  },
  "monitoring_report": {
    "path": "C:/.../验收监测报告.pdf",
    "agency": "监测机构全称（CMA 资质）",
    "cma_no": "CMA 证书编号",
    "date": "报告日期"
  },

  "section1_basic": {
    "location": "建设地点",
    "industry": "行业/主要产品",
    "total_capacity": "总设计产能（如 年产五金件1300吨）",
    "phase_capacity": "本次验收（一期）规模",
    "land_area": "用地面积",
    "building_area": "建筑面积",
    "employees": "员工人数",
    "workdays": "年工作天数",
    "workschedule": "生产班次与时间",
    "has_canteen_dorm": "宿舍/食堂情况",
    "project_components_table": [
      {"category":"主体工程","name":"生产车间","ep_content":"环评建设内容","remark":"与环评一致"}
    ],
    "approval": {
      "eia_unit": "环评编制单位",
      "eia_approve_dept": "审批部门",
      "eia_approve_no": "审批文号",
      "eia_approve_date": "审批日期",
      "permit_no": "排污许可证编号",
      "permit_date": "排污许可证取得日期",
      "completion_date": "竣工日期",
      "debug_start": "调试开始",
      "debug_end": "调试结束",
      "monitor_unit": "验收监测单位",
      "monitor_date": "监测日期",
      "monitor_report_name": "验收监测报告名称"
    },
    "investment": {"total":"总投资(万元)","env":"环保投资(万元)"},
    "acceptance_scope": "验收范围描述",
    "product_table": [
      {"name":"五金件","eia_capacity":"1300吨/年","phase_capacity":"934吨/年","remaining":"366吨/年"}
    ],
    "material_table": [
      {"no":1,"name":"铝锭","eia_scale":"1250t/a","phase_scale":"875t/a","remaining":"375t/a"}
    ],
    "equipment_table": [
      {"no":1,"name":"压铸机","model":"160T","qty":1,"accepted":1,"unaccepted":0}
    ]
  },

  "section2_change": "工程变动情况（如：无变动。）",

  "section3_facilities": {
    "wastewater": ["废水治理措施1","废水治理措施2"],
    "wastegas": ["废气治理措施1","废气治理措施2"],
    "noise": "噪声治理措施",
    "solidwaste": "固体废物治理措施（一般固废/危废分别说明）",
    "other": {
      "risk": "环境风险防范措施",
      "onlinemonitor": "在线监测装置（无/有及说明）",
      "others": "其他设施（以新带老/绿化等，无则写'无'）"
    }
  },

  "section4_debug": {
    "efficiency": {
      "wastewater":"处理效率说明","wastegas":"处理效率说明",
      "noise":"无","solidwaste":"无"
    },
    "emission": {
      "wastewater":"废水达标说明（引用标准）",
      "wastegas":"废气达标说明（引用标准与限值）",
      "noise":"噪声达标说明（引用标准）",
      "solidwaste":"固废处置说明",
      "total":"污染物排放总量核算（实际 vs 审批）"
    }
  },

  "section5_impact": "工程建设对环境的影响（概述）",
  "section6_system": {
    "org": "环保组织机构及规章制度",
    "risk_plan": "环境风险应急预案及备案编号",
    "monitor_plan": "环境监测计划"
  },
  "section7_conclusion": "验收结论（明确是否合格）",
  "section8_followup": ["后续要求1","后续要求2"],

  "signoff": {
    "build_unit_seal": "建设单位（盖章）：XXX公司",
    "date": "2026年07月17日"
  },

  // ============ 图件与影像（自动插入，缺失则渲染占位框并登记待补） ============
  // path 为图片文件绝对路径（jpg/png）；缺省或文件不存在 → 占位框 + 待补清单。
  "figures": [
    {"title":"项目地理位置图","path":"C:/.../fig1_geo.png","caption":"项目地理位置示意图"},
    {"title":"项目四至图","path":null,"caption":"厂区四至及相邻关系图"},
    {"title":"项目环境敏感目标分布图","path":"C:/.../fig3.png","caption":"敏感目标分布"},
    {"title":"厂区总平面布置图","path":"C:/.../fig4.png","caption":"总平面布置（含环保设施）"},
    {"title":"项目监测布点示意图","path":"C:/.../fig5.png","caption":"验收监测布点"},
    {"title":"公示","path":"C:/.../fig6_publicity.png","caption":"验收报告公示截图"}
  ],

  "appendices": [
    {"title":"营业执照","path":"C:/.../app1_license.png","caption":"营业执照（统一社会信用代码）"},
    {"title":"环评批复","path":"C:/.../app2_eia_approval.png","caption":"环评批复扫描件"},
    {"title":"排污许可证","path":null,"caption":"排污许可证副本"},
    {"title":"危废处置合同","path":"C:/.../app4_hw.png","caption":"危废处置合同及暂存间照片"}
  ],

  // 正文穿插照片（可选）
  "layout_photos": [
    {"path":"C:/.../site_panorama.jpg","caption":"厂区全景照片"}
  ],
  "facility_photos": [
    {"path":"C:/.../wwtp.jpg","caption":"废水处理设施"},
    {"path":"C:/.../wg_photo.jpg","caption":"废气治理设施"}
  ],

  "acceptance_opinion": {
    "date": "验收意见日期",
    "group_intro": "由建设单位、环保咨询单位、验收检测单位和专家组成的验收组",
    "group_members": ["建设单位：XXX","环保咨询单位：XXX","验收检测单位：XXX","专家：XXX"],
    "basic": "工程建设基本情况（可简述或复用正文要点）",
    "change": "工程变动情况",
    "facilities": "环保设施建设情况",
    "debug": "调试效果",
    "impact": "对环境的影响",
    "conclusion": "验收组同意项目通过环境保护验收",
    "followup": ["后续要求1","后续要求2"],
    "member_list": "验收组名单（附后）"
  }
}
```

## 四、生成脚本约定

- **门控**：生成前先跑 `scripts/check_materials.py --data xxx.json` 校验三件套；
  生成时加 `--require-essentials`，三件套缺失则拒绝生成（退出码 2）。
- 表1~表4 为数组，缺表时跳过该表但保留章节文字。
- 图件字段：`figures` / `appendices` 渲染为独立的"附图""附件"章节（仅在其非空时输出）；
  `layout_photos` / `facility_photos` 穿插在正文对应位置。图片 `path` 存在且可读则居中插入
  （自动按页宽 95% 缩放、下方图注）；`path` 为 null 或文件缺失则渲染带边框占位框，并登记到
  文末"待补充材料清单"，不中断生成。
- 支持图件类型：jpg / png / 其他 python-docx 支持的图片格式；PDF 请先转为图片再提交。
- 字符串字段支持多段：用 "\n" 分段；列表字段（如 wastewater）逐条成段。
- 占位符统一用"【待补充：字段说明】"，脚本原样输出并在文末汇总"待补充清单"。
- 样式：标题深蓝 #1a365d 加粗、正文宋体小四、表格带边框、A4 纵向。
