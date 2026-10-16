# -*- coding: utf-8 -*-
"""v2.0 核心数据模型（contracts.md §2，Pydantic v2）。

模块间业务数据一律使用本文件类型，禁止裸 dict 传递（coding_standards §3.2）。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DomainEnum = Literal['D1', 'D2', 'D3', 'D4', 'D5', 'D6']
ProjectStatus = Literal[
    'received', 'planned', 'sampled', 'analyzed',
    'drafting', 'review', 'compliance', 'signoff', 'done',
]
ReportType = str  # 领域泛化：不再限定三类型枚举，由模板库按类型取用（碳/应急/生态等）
ReportStatus = Literal[
    'drafting', 'review', 'auto_fix', 'compliance', 'signoff', 'learn', 'done', 'escalate',
]

_ID_PATTERNS = ConfigDict(str_strip_whitespace=True)


class StandardRef(BaseModel):
    """标准引用（来源：kb 知识库 / official 官方检索 / pending 待核实）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str  # "HJ 166-2026"
    clause: str | None = None  # 条款号，如 "5.1.3"
    valid: bool = True  # 是否现行有效
    source: str = 'kb'


class Project(BaseModel):
    """监测项目（委托）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=r'^prj-\d{8}-\d{3}$')
    name: str
    domain: DomainEnum
    client: str | None = None
    status: ProjectStatus = 'received'
    standards: list[StandardRef] = Field(default_factory=list)
    capacity: list[str] = Field(default_factory=list)  # 资质/能力范围（M12 check_scope）
    meta: dict[str, Any] = Field(default_factory=dict)


class Report(BaseModel):
    """监测/验收/环评报告。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=r'^rpt-\d{8}-\d{3}$')
    type: ReportType
    project_id: str
    version: int = 1
    docx_path: str | None = None
    content: str = ''  # 报告正文快照（M11 auto_fix 产物落此处）
    status: ReportStatus = 'drafting'
    data_sources: list[str] = Field(default_factory=list)  # 数据来源链（原始记录 ID）
    created_by: str = 'R4'  # 角色 ID
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewIssue(BaseModel):
    """单条审核问题（P0/P1/P2）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=r'^P[012]-\d{3}$')  # P0-001 / P1-003
    severity: Literal['P0', 'P1', 'P2']
    type: str  # image_misplaced / format / data_inconsistency / standard_invalid / ...
    location: str
    description: str
    suggested_fix: str = ''
    auto_fixable: bool = False  # R5 可自动修复标志


class ReviewFeedback(BaseModel):
    """一次审核的完整反馈。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    version: int  # 被审核版本号
    issues: list[ReviewIssue] = Field(default_factory=list)
    summary: str = ''


class SkillDef(BaseModel):
    """技能定义（M07，contracts.md §2）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=r'^sk-[a-z]{3,6}-\d{3}$')  # sk-mon-001
    name: str
    level: int = Field(ge=1, le=4)  # L1..L4
    role: str = Field(pattern=r'^R[1-8]$')  # R1..R8
    domain: str
    version: str = '1.0.0'
    status: Literal['active', 'pending_review', 'rejected', 'deprecated'] = 'active'
    definition: str = ''  # YAML 定义
    created_by: Literal['manual', 'agent_oercr'] = 'manual'


class MemoryHit(BaseModel):
    """情景记忆检索命中（M05）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    entity: str
    snippet: str
    score: float
    ts: str


class SkillUpdateProposal(BaseModel):
    """H1 技能迭代提案：同 gap 技能已存在时的升级建议（R8 审批后 update_skill 演进版本）。"""
    id: int = 0
    skill_id: str = ''
    base_version: str = ''
    new_definition: str = ''
    reason: str = ''
    status: str = 'pending'        # pending / approved / rejected
    created_at: str = ''


class ProfileItem(BaseModel):
    """M3 用户画像：跨会话蒸馏的稳定用户属性。"""
    id: int = 0
    user_key: str = ''
    attr: str = ''
    value: str = ''
    weight: int = 0
    updated_at: str = ''


class MemoryFact(BaseModel):
    """M2/M4 事实记忆：结构化事实/偏好/约束/结论（含时间维度与冲突消解）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: int = 0
    entity: str
    attr: str
    value: str
    ftype: str = 'fact'            # fact / preference / constraint / conclusion
    source: str = ''
    valid_from: str = ''
    valid_until: str | None = None
    status: str = 'pending'        # pending / active / rejected
    created_at: str = ''


class KBHit(BaseModel):
    """知识库检索命中（M06）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    doc_id: str
    clause: str | None = None
    snippet: str
    score: float


class ValidityInfo(BaseModel):
    """标准有效性（M06）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str
    status: str  # 现行有效 / 已废止 / 即将实施 / 未知
    effective_date: str | None = None
    note: str = ''


class StandardDoc(BaseModel):
    """标准文档（M06 get_standard 返回值）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str
    title: str
    content: str = ''
    category: str = ''
    validity: str = '未知'
    effective_date: str | None = None
    source: str = ''


class SkillResult(BaseModel):
    """技能执行结果（M07）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    ok: bool
    outputs: dict
    trace_id: str
    usage_tokens: int | None = None


class RouteResult(BaseModel):
    """意图路由结果（M03，contracts.md §3.M03）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    skill_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    mode: Literal['auto', 'interactive', 'manual'] = 'manual'
    # auto: confidence>=0.85; interactive: 0.50~0.84; manual: <0.50 或用户指定
    domain: str = ''  # 推断领域（D1..D6），供 skill 选择与 RAG 过滤
    intent: str = 'craft'  # 意图模式（plan/ask/craft），供 M6 检索源分发


class PlanStep(BaseModel):
    """G1 显式规划步骤（Plan-Execute，对齐 LangGraph Plan 范式）。

    - action：tool=工具 / skill=技能 / llm=文本汇总（无 LLM 时规则降级）。
    - target：工具名或技能 id；params 中 `$prev` 由上一步 outputs 注入。
    - outputs_name：本步产出的键名（注入下一步 $prev.<outputs_name>）。
    - status：pending -> running -> done / failed；失败可中断（continue_on_error=False）。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    seq: int = 0
    goal: str = ''                        # 本步目标（自然语言）
    action: Literal['tool', 'skill', 'llm'] = 'tool'
    target: str = ''                      # 工具名 / 技能 id
    params: dict = Field(default_factory=dict)
    outputs_name: str = ''                # 产出键名
    status: Literal['pending', 'running', 'done', 'failed'] = 'pending'
    result: Any = None                    # 步骤结果快照
    note: str = ''


class RoleBlueprint(BaseModel):
    """角色蓝图（M08，contracts.md §3.M08；architecture.md §4 R1-R8）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str  # R1..R8（内置）；新角色（M15 自生成）可扩展
    name: str
    domain: str
    responsibilities: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)  # read_data/generate_report/approve/...
    compliance: list[str] = Field(default_factory=list)  # 资质约束
    status: Literal['pending_r8_review', 'active'] = 'pending_r8_review'


class WorkflowSpec(BaseModel):
    """工作流规格（M09，contracts.md §3.M09）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    trigger: str  # manual / webhook / auto_router
    state_machine: dict = Field(default_factory=dict)  # {'initial':..., 'states': {状态: {事件: 目标状态}}}


class StateResult(BaseModel):
    """状态流转结果（M09）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    from_state: str
    to_state: str
    retry_count: int = 0
    escalated: bool = False


class ReportTemplate(BaseModel):
    """报告模板（M10，contracts.md §3.M10）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    type: str  # monitoring / acceptance / eia
    docx_path: str = ''
    placeholders: list[str] = Field(default_factory=list)


class ReportSection(BaseModel):
    """报告章节（M10 generator 产物）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    content: str
    refs: list[str] = Field(default_factory=list)  # 引用标准号列表


class Violation(BaseModel):
    """合规违规项（M12，contracts.md §3.M12）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    rule_id: str  # CMA-001..，来自规则包
    severity: Literal['P0', 'P1', 'P2'] = 'P1'
    message: str
    location: str = ''  # 违规位置（报告章节/数据行）


class ComplianceResult(BaseModel):
    """合规检查结果（M12）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    passed: bool
    violations: list[Violation] = Field(default_factory=list)
    retry_allowed: bool = False  # P1 可整改重检；P0 不可


class AuditEntry(BaseModel):
    """审计条目（M14，contracts.md §3.M14）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    seq: int = 0  # 链序号（从 1 起）
    who: str
    action: str
    input_hash: str = ''
    output_hash: str = ''
    prev_hash: str = 'GENESIS'  # 首条为 GENESIS 占位
    ts: str = ''
    hash: str = ''  # 本条 SHA-256 摘要（前链头）


class Observation(BaseModel):
    """OERCR 观察（M13，contracts.md §3.M13 observe 产物）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    obs_id: str = ''  # obs-YYYYMMDD-NNN
    episode_id: str = ''
    task: str
    domain: str = ''
    task_log: dict = Field(default_factory=dict)  # 原始任务日志
    outcome: str = ''  # success / partial / failed
    user_feedback: str = ''  # 用户反馈（R5 审核意见等）
    ts: str = ''


class Reflection(BaseModel):
    """OERCR 反思（M13，contracts.md §3.M13 reflect 产物）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    ref_id: str = ''  # refl-YYYYMMDD-NNN
    obs_id: str = ''
    domain: str = ''  # 继承自 Observation，供结晶时保留真实领域
    gap: str  # 反思结论/差距描述
    pattern_hint: str = ''  # 可沉淀的模式提示
    severity: Literal['P0', 'P1', 'P2'] = 'P2'
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ModuleBlueprint(BaseModel):
    """模块蓝图（M15，contracts.md §3.M15 模块生成流水线产物）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    domain: DomainEnum
    roles: list[RoleBlueprint] = Field(default_factory=list)
    skills: list[SkillDef] = Field(default_factory=list)
    knowledge_base: list[str] = Field(default_factory=list)  # 知识库条目/来源
    compliance_rules: list[str] = Field(default_factory=list)  # 合规规则引用
    workflow_template: dict = Field(default_factory=dict)  # DAG/状态机模板
    status: str = 'pending_r8_review'  # R8 审核后 active


class RegulationHit(BaseModel):
    """官方源检索命中（M15 search_regulations 产物）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str  # 标准号
    title: str
    url: str = ''
    snippet: str = ''
    source: str = 'official'


class ParsedDoc(BaseModel):
    """材料解析结果（M15 ingest_materials 产物）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    path: str
    title: str = ''
    content: str = ''
    sections: list[str] = Field(default_factory=list)  # 章节标题
    doc_type: str = ''  # md / txt / pdf / docx ...
