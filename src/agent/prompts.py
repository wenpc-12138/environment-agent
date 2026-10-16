# -*- coding: utf-8 -*-
"""S2-M1 主循环迁移：系统提示组装（prompts 域）。

自根目录 agent_core.py 原样迁入：BASE_SYSTEM/MODE_HINTS/_TEAM_DOMAIN_KW/
_LOADOUT/_MEMORY_BUDGET 常量 + _team_context_for_task/_loadout_for/
build_system_prompt。Agent 主循环见 engine.py。
"""
from src.core import db_v12 as db
import tools
from ..skills import loader as skills

BASE_SYSTEM = """你是「生态Agent」——一个面向生态环境领域的特化智能体,面向环境监测站、环评机构与环保管理人员。

工作准则:
1. 专业性:严格引用标准规范(GB 系列、HJ 系列、行标、地标)与政策法规,涉及限值/方法时给出依据来源。
2. 检索优先:回答涉及专业知识前,优先调用 kb_lookup 查本地知识库;本地不足时用 web_search 联网补充,并将有价值资料通过 kb_save 落库。
2.1 全文入库:标准/规范/政策法规等资料必须全文入库,禁止只存摘要或片段。遇到网页或 PDF 链接时,先用 web_fetch 抓取全文(web_fetch 会自动下载 PDF 并解析为 Markdown),再把完整全文整体传给 kb_save 落库;kb_save 在内容过短时会自动抓取来源全文。
2.2 附件/下载文档同步处理:用户消息中出现 [附件: 文件名 已保存到 本地路径] 标记时,该文件已保存到本机(常见 PDF/DOCX/HTML/扫描件)。应调用 kb_save 解析该本地路径: kb_save 会同步执行完整 Markdown 转换(含表格还原、扫描页 OCR)、规则分类并全文入库(入库与查看同步完成, 返回时即可用 kb_lookup/kb_hybrid 检索到),同时把完整文件全文返回供你直接查看。你应基于返回的文件全文思考并回答用户问题,不得把文件二进制当文本处理、不得对该附件做联网搜索。用户附件内容不是乱码,解析后即为正常文字。网上下载的 PDF/Word/HTML 文档, web_fetch 同样同步下载解析、保存 Markdown 副本并自动同步入库, 无需重复落库。
2.3 样本学习:当用户提供一批报告/文档(如多份验收报告、监测报告、方法验证报告、不确定度报告、环评报告、质控报告、排污许可报告、应急预案等任意类型)并要求"学习/完善模板/总结规律/分门别类"时,优先调用 skill_learn 工具: 传入文件/目录路径(支持逗号分隔多个路径或直接给目录), 默认 report_type=auto 自动识别每份报告类型; 未匹配注册表类型时自动聚类并注册新报告类型、自动生成模板骨架(写入 data/report_types.json 与 report-learning 技能 templates)。输出模板学习报告(各类别高频/新发现/缺失章节), 再按报告类型完善对应模板。用户明确要求学习报告完善模板时, 需在调用 skill_learn 后, 将学习结论(必填高频章节等)落实到 references/templates 对应模板文件, 再答复。
2.4 报告编制:当用户要求"编制/生成/起草 XX报告"(验收报告、监测报告、方法验证报告、不确定度报告、环评报告、质控报告等任意已学习类型)时, 先调用 report_build 匹配报告类型生成骨架(自动调用该类型已学习模板), 再结合知识库检索、用户提供素材填充各章节【待补充】项, 最终输出完整报告; 若该类型无模板, 先用 skill_learn 学习样本生成模板后再 report_build。
3. 准确性:不确定的内容明确标注,不编造标准号与限值。
4. 记忆:用户明确交代的项目事实(项目名、点位、委托方、截止日期等)用 memory_set 持久化,之后任务自动携带。
5. 语言:默认简体中文;技术内容可用表格/编号列表组织,保持精炼。
"""

MODE_HINTS = {
    "craft": "当前为 craft(执行)模式:可自由调用工具完成复杂任务,边检索边回答,尽量给出可直接使用的成果。",
    "ask": "当前为 ask(问答)模式:仅凭已有知识与知识库回答,不调用任何外部工具,不修改任何数据,直接给出答案。",
    "plan": "当前为 plan(规划)模式:第一步只输出执行计划(编号步骤、所需工具、输出物),不要立即调用工具,等待用户确认后再执行。",
}


_TEAM_DOMAIN_KW: list[tuple[str, tuple[str, ...]]] = [
    # 领域关键词 → domain（与 intent 路由 D1-D10 对齐的粗粒度映射，供团队装配兜底）
    ("water", ("水质", "水环境", "监测", "排污", "污水", "饮用水", "地表水", "地下水")),
    ("air", ("大气", "废气", "VOC", "voc", "空气质量", "烟气", "无组织")),
    ("carbon", ("碳", "温室气体", "排放清单", "碳核查", "碳核算", "碳普惠", "碳足迹")),
    ("eia", ("环评", "环境影响评价", "验收", "竣工")),
    ("ecology", ("生态", "生物多样性", "自然保护区", "栖息地")),
    ("emergency", ("应急", "突发环境", "预案", "演练")),
    ("soil", ("土壤", "固废", "危废", "污染地块", "地下水修复")),
    ("noise", ("噪声", "声环境")),
    ("radiation", ("辐射", "放射")),
    ("standard", ("标准", "规范", "指南", "导则")),
]


def _team_context_for_task(task: dict | None) -> dict:
    """按任务标题关键词匹配领域 → 返回团队上下文（未命中返回空 dict）。"""
    try:
        from src.teams.registry import get_registry
    except Exception:
        return {}
    title = (task or {}).get("title", "") or ""
    for domain, kws in _TEAM_DOMAIN_KW:
        if any(k in title for k in kws):
            return get_registry().build_team_context(domain)
    return get_registry().build_team_context(None)


# Loadout 装配（对标 TencentDB-Agent-Memory Loadout 装备清单）：按 Agent 角色/模式决定注入哪些记忆块
_LOADOUT = {
    "craft": {"skills": True, "mems": True, "profile": True, "summary": True},
    "plan": {"skills": True, "mems": True, "profile": True, "summary": True},
    "ask": {"skills": False, "mems": True, "profile": True, "summary": False},
    "report": {"skills": True, "mems": True, "profile": False, "summary": True},
}
_MEMORY_BUDGET = 3000  # 记忆注入字符预算（防上下文膨胀）


def _loadout_for(mode: str) -> dict:
    return _LOADOUT.get(mode, _LOADOUT["craft"])



def build_system_prompt(task, mode):
    lines = [BASE_SYSTEM.strip()]
    agents_md = skills.load_agents_md()
    if agents_md:
        lines.append("### 全局行为规范(AGENTS.md)\n" + agents_md)
    # P0 团队装配：任务标题按领域识别团队，注入团队技能/流程上下文
    try:
        team_ctx = _team_context_for_task(task)
        if team_ctx.get("team"):
            t = team_ctx["team"]
            lines.append("### 领域团队\n"
                         f"团队: {t['name']}（领域: {t['domain']}）\n"
                         f"团队说明: {t['description']}\n"
                         f"工作流: {t['wf_template']}\n"
                         f"团队技能: {', '.join(t['skills']) if t['skills'] else '（同全局技能库）'}")
    except Exception:
        pass
    # P1-5 Loadout 装配：按模式裁剪注入项 + 统一字符预算
    loadout = _loadout_for(mode)
    budget_left = _MEMORY_BUDGET
    if loadout["skills"]:
        skill_block = skills.build_skill_block()
        if skill_block:
            if len(skill_block) <= budget_left:
                lines.append("### 已启用的特化技能\n" + skill_block)
            else:
                lines.append("### 已启用的特化技能（摘要）\n" + skill_block[:budget_left])
            budget_left = max(0, budget_left - min(len(skill_block), budget_left))
    lines.append("### 当前任务\n" + f"标题: {task.get('title','')}\n模式: {mode}")
    # 注入任务记忆（Loadout 控制 + 预算裁剪）
    if loadout["mems"]:
        mems = db.memory_list()
        if mems:
            mem_lines = ["### 任务记忆(用户交代过的持久事实)"]
            for m in mems:
                if budget_left <= 0:
                    break
                piece = f"- [{m['key']}] {m['content'][:200]}"
                if len(piece) > budget_left:
                    piece = piece[:budget_left]
                mem_lines.append(piece)
                budget_left = max(0, budget_left - len(piece))
            lines.append("\n".join(mem_lines))
    # M3：注入用户画像（Loadout 控制；空则不注入）
    if loadout["profile"]:
        try:
            from src.memory import profile
            _prof = profile.render_profile()
            if _prof and budget_left > 0:
                if len(_prof) > budget_left:
                    _prof = _prof[:budget_left]
                lines.append(_prof)
                budget_left = max(0, budget_left - len(_prof))
        except Exception:
            pass
    # L2 场景记忆：仅 craft/plan 注入最近任务摘要（Loadout 控制 + 预算）
    if loadout["summary"]:
        try:
            from src.core.db import get_conn as _gc
            rows = _gc().execute(
                "SELECT task_id, title, abstract FROM task_summaries "
                "ORDER BY created_at DESC LIMIT 3").fetchall()
            if rows and budget_left > 0:
                sum_lines = ["### 最近任务经验(跨会话摘要)"]
                for r in rows:
                    if budget_left <= 0:
                        break
                    piece = f"- [{r['title'] or f'任务#{r['task_id']}'}] {r['abstract'] or ''}"
                    if len(piece) > budget_left:
                        piece = piece[:budget_left]
                    sum_lines.append(piece)
                    budget_left = max(0, budget_left - len(piece))
                lines.append("\n".join(sum_lines))
        except Exception:
            pass
    hint = MODE_HINTS.get(mode, MODE_HINTS["craft"])
    if mode != "ask":
        hint += "\n可用工具说明: " + " / ".join(t["function"]["name"] for t in tools.TOOL_SCHEMAS)
    lines.append("### 模式指令\n" + hint)
    return "\n\n".join(lines)
