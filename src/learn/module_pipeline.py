# -*- coding: utf-8 -*-
"""M15 角色自生成 + 模块流水线（contracts.md §3.M15）。

ModulePipeline:
- run(conversation, uploaded) -> ModuleBlueprint: 对话+上传材料 → 模块蓝图(pending_r8_review)
- search_regulations(domain) -> list[RegulationHit]: 联网官方源检索(McpClient; 离线降级内置表)
- ingest_materials(paths) -> list[ParsedDoc]: 材料解析(md/txt/html; docx/pdf/xlsx 尽力提取)

落库对接:
- 角色 → RoleRegistry.define(pending_r8_review, R8 审核后 activate)
- 技能 → ProceduralMemory.create_skill(pending_review, 待 R8 审核)
- 知识库 → StandardKB.ingest(文本材料导入, 条目 ID 记录于 blueprint.knowledge_base)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..kb.standards import StandardKB
from ..memory.procedural import ProceduralMemory
from ..models.core import (
    DomainEnum,
    ModuleBlueprint,
    ParsedDoc,
    RegulationHit,
    RoleBlueprint,
    SkillDef,
)
from ..roles.registry import RoleRegistry
from ..tools.mcp_client import McpClient

_SKILL_SEQ = {'n': 0}
_ROLE_SEQ = {'n': 0}

_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    'D1': ('环境监测', '监测', '采样', '检测', '数据', 'monitor', 'sampling'),
    'D2': ('排放', '排污', '废水', '废气', '噪声', '污染源', 'emission'),
    'D3': ('验收', '竣工', '环保验收', 'acceptance'),
    'D4': ('环评', '环境影响', '评价', 'eia'),
    'D5': ('合规', '资质', '认证', 'cma', '能力表', 'compliance'),
    'D6': ('管理', '制度', '计划', '治理', 'governance'),
}

_OFFICIAL_REGS: dict[str, list[tuple[str, str, str]]] = {
    'D1': [
        ('HJ 168-2020', '环境监测分析方法标准制订技术导则', 'https://www.mee.gov.cn/ywgz/fgbz/bz/bzwb/'),
        ('HJ/T 166-2004', '土壤环境监测技术规范', 'https://www.mee.gov.cn/ywgz/fgbz/bz/bzwb/'),
    ],
    'D2': [
        ('GB 8978-1996', '污水综合排放标准', 'https://openstd.samr.gov.cn/'),
        ('GB 16297-1996', '大气污染物综合排放标准', 'https://openstd.samr.gov.cn/'),
    ],
    'D3': [
        ('国务院令第682号', '建设项目环境保护管理条例', 'https://www.mee.gov.cn/'),
        ('国环规环评〔2017〕4号', '建设项目竣工环境保护验收暂行办法', 'https://www.mee.gov.cn/'),
    ],
    'D4': [
        ('HJ 2.1-2016', '建设项目环境影响评价技术导则 总纲', 'https://www.mee.gov.cn/ywgz/fgbz/bz/bzwb/'),
        ('HJ 2.3-2018', '环境影响评价技术导则 大气环境', 'https://www.mee.gov.cn/ywgz/fgbz/bz/bzwb/'),
    ],
    'D5': [
        ('RB/T 214-2017', '检验检测机构资质认定能力评价 检验检测机构通用要求', 'https://openstd.samr.gov.cn/'),
        ('CNAS-CL01:2018', '检测和校准实验室能力认可准则', 'https://www.cnas.org.cn/'),
    ],
    'D6': [
        ('GB/T 24001-2016', '环境管理体系 要求及使用指南', 'https://openstd.samr.gov.cn/'),
    ],
}

_DOMAIN_LABEL: dict[str, str] = {
    'D1': '环境监测', 'D2': '排放核查', 'D3': '竣工环保验收',
    'D4': '环评编制', 'D5': '合规资质', 'D6': '环境管理',
}
_DOMAIN_ROLE: dict[str, str] = {
    'D1': '监测采样专员', 'D2': '排放核查专员', 'D3': '验收审核专员',
    'D4': '环评编制专员', 'D5': '合规检查专员', 'D6': '环境管理专员',
}
_DOMAIN_SKILL: dict[str, str] = {
    'D1': 'monitoring-task', 'D2': 'emission-audit', 'D3': 'acceptance-review',
    'D4': 'eia-draft', 'D5': 'compliance-check', 'D6': 'env-governance',
}

_TEXT_EXTS = {'.md', '.txt', '.html', '.htm', '.csv', '.json', '.yaml', '.yml'}
_CODE_RE = re.compile(r'([A-Z]{1,5}\s*[-/]?\s*\d{1,5}(?:[.-]\d{1,4})?-\d{4})')


class ModulePipeline:
    """模块生成流水线：对话 + 上传材料 → 模块蓝图。"""

    def __init__(self, registry=None, memory=None, kb=None, mcp=None) -> None:
        self._registry = registry or RoleRegistry()
        self._memory = memory or ProceduralMemory()
        self._kb = kb or StandardKB()
        self._mcp = mcp or McpClient()

    def run(self, conversation: list[dict], uploaded: list[str]) -> ModuleBlueprint:
        """对话+上传材料 → 模块蓝图（待 R8 审核）。

        1) 解析上传材料; 2) 由对话+材料推断领域; 3) 自生成角色/技能并落库;
        4) 检索法规、汇总知识库/合规规则/工作流模板; 5) 返回 pending_r8_review 蓝图。
        """
        docs = self.ingest_materials(uploaded)
        text = self._conversation_text(conversation)
        text = f'{text}\n' + '\n'.join(d.content for d in docs if d.content)
        domain = self._infer_domain(text)

        roles = self._build_roles(domain, text)
        skills = self._build_skills(domain, text)
        regs = self.search_regulations(domain)
        knowledge_base = self._build_kb(docs, regs)

        for r in roles:
            self._registry.define(r)
        for s in skills:
            self._memory.create_skill(s)

        return ModuleBlueprint(
            domain=domain,
            roles=roles,
            skills=skills,
            knowledge_base=knowledge_base,
            compliance_rules=self._compliance_rules(domain),
            workflow_template=self._workflow_template(domain),
            status='pending_r8_review',
        )

    def approve_blueprint(self, blueprint: ModuleBlueprint, reviewer: str = 'R8') -> bool:
        """R8 一次性审批蓝图（第 8 波联动）：批量激活角色 + 技能。

        - 角色：RoleRegistry.activate（pending_r8_review → active）
        - 技能：ProceduralMemory.approve_skill（pending_review → active）
        - 全部成功后将 blueprint.status 置为 active。

        返回 False 表示：审核人非 R8 / 蓝图非待审 / 任一产物激活失败。
        """
        if reviewer != 'R8' or blueprint.status != 'pending_r8_review':
            return False
        for role in blueprint.roles:
            # 幂等注册（同 id 已存在则保留原状态），确保本实例注册表可见
            self._registry.define(role)
            if not self._registry.activate(role.id, reviewer):
                return False
        for skill in blueprint.skills:
            if not self._memory.approve_skill(skill.id, reviewer):
                return False
        blueprint.status = 'active'
        return True

    def search_regulations(self, domain: str) -> list[RegulationHit]:
        """联网检索官方源法规；无网/无结果时降级返回内置官方源。"""
        hits: list[RegulationHit] = []
        query = f'{_DOMAIN_LABEL.get(domain, domain)} 标准 法规'
        try:
            results = self._mcp.search(query, top_n=5)
            for r in list(results or [])[:5]:
                title = _field(r, ('title', 'name'))
                url = _field(r, ('url', 'link'))
                snippet = _field(r, ('snippet', 'description'))
                code = _extract_code(f'{title} {snippet}')
                hits.append(RegulationHit(code=code or (title or '')[:20], title=title or '',
                                          url=url or '', snippet=snippet or '', source='official'))
        except Exception:
            pass
        if not hits:
            for code, title, url in _OFFICIAL_REGS.get(domain, []):
                hits.append(RegulationHit(code=code, title=title, url=url, snippet='', source='official'))
        return hits

    def ingest_materials(self, paths: list[str]) -> list[ParsedDoc]:
        """解析上传材料；文件缺失/解析失败留空不中断。"""
        docs: list[ParsedDoc] = []
        for p in paths or []:
            path = Path(str(p))
            if not path.is_file():
                docs.append(ParsedDoc(path=str(p), title=Path(str(p)).stem, content='', sections=[], doc_type='missing'))
                continue
            ext = path.suffix.lower()
            title, content, sections = path.stem, '', []
            if ext in _TEXT_EXTS:
                content = _read_text(path)
                sections = _extract_sections(content)
                title = _first_title(content) or path.stem
            elif ext == '.docx':
                content = _read_docx(path)
                sections = _extract_sections(content)
            elif ext == '.pdf':
                content = _read_pdf(path)
            elif ext in ('.xlsx', '.xlsm'):
                content = _read_xlsx(path)
            docs.append(ParsedDoc(path=str(path), title=title, content=content,
                                  sections=sections, doc_type=ext.lstrip('.') if ext else 'unknown'))
        return docs

    # ---- 内部构建 ----
    def _build_roles(self, domain: str, text: str) -> list[RoleBlueprint]:
        """自生成领域角色（RoleRegistry.define 落库，pending_r8_review）。"""
        _ROLE_SEQ['n'] += 1
        return [RoleBlueprint(
            id=f'role-mod-{_ROLE_SEQ["n"]:03d}',
            name=_DOMAIN_ROLE.get(domain, '领域专员'),
            domain=domain,
            responsibilities=[
                f'{_DOMAIN_LABEL.get(domain, domain)}任务执行与质量控制',
                '依据现行标准/法规开展工作并留存证据',
                '配合 R8 审核与合规检查',
            ],
            required_skills=[_DOMAIN_SKILL.get(domain, '')],
            permissions=['read_data', 'generate_report', 'review_draft'],
            compliance=[_compliance_basis(domain)],
        )]

    def _build_skills(self, domain: str, text: str) -> list[SkillDef]:
        """自生成领域技能（ProceduralMemory.create_skill 落库，pending_review 待 R8 审核）。"""
        _SKILL_SEQ['n'] += 1
        skill_name = f'mod-{_DOMAIN_SKILL.get(domain, "generic")}'
        return [SkillDef(
            id=f'sk-mod-{_SKILL_SEQ["n"]:03d}',
            name=skill_name,
            level=2,
            role='R1',
            domain=domain,
            version='1.0.0',
            status='pending_review',
            definition=(
                f'name: {skill_name}\n'
                f'group: 模块自生成\n'
                f'description: {_DOMAIN_LABEL.get(domain, domain)}领域的自动生成执行技能，'
                f'覆盖任务执行、质量自查与报告产出。\n'
                f'domain: {domain}\n'
                f'agent_created: true'
            ),
            created_by='agent_oercr',
        )]

    def _build_kb(self, docs: list[ParsedDoc], regs: list[RegulationHit]) -> list[str]:
        """汇总知识库条目：文本材料导入 StandardKB（失败跳过）＋ 法规命中引用。"""
        entries: list[str] = []
        for d in docs:
            if not d.content or d.doc_type not in ('md', 'txt', 'html', 'htm'):
                continue
            try:
                eid = self._kb.ingest(d.path, '标准')
                entries.append(f'kb:{eid}|{d.title}')
            except Exception:
                entries.append(f'kb-missing:{d.path}')
        for r in regs:
            entries.append(f'ref:{r.code}|{r.title}')
        return entries

    @staticmethod
    def _conversation_text(conversation: list[dict]) -> str:
        parts = []
        for msg in conversation or []:
            if isinstance(msg, dict):
                content = msg.get('content') or msg.get('text') or ''
            else:
                content = getattr(msg, 'content', '') or ''
            if content:
                parts.append(str(content))
        return '\n'.join(parts)

    @staticmethod
    def _infer_domain(text: str) -> DomainEnum:
        if not text:
            return 'D1'
        lower = text.lower()
        scores = {d: sum(1 for kw in kws if kw in text or kw in lower)
                  for d, kws in _DOMAIN_KEYWORDS.items()}
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else 'D1'

    @staticmethod
    def _compliance_rules(domain: str) -> list[str]:
        rules = [
            '报告编制须依据现行有效标准与法规版本',
            '数据可溯源，原始记录与报告一致',
            '人员、设备、方法均应在资质能力范围内',
            '检测报告要素符合 CMA/RB/T 214-2017 要求',
        ]
        if domain == 'D3':
            rules.append('验收依据须含环评批复及验收暂行办法')
        elif domain == 'D4':
            rules.append('环评文件须符合 HJ 2.1-2016 总纲要求')
        elif domain == 'D2':
            rules.append('排放限值按 GB 8978/GB 16297 现行版本执行')
        return rules

    @staticmethod
    def _workflow_template(domain: str) -> dict:
        return {
            'name': f'module-{domain}',
            'trigger': 'manual',
            'state_machine': {
                'initial': 'drafting',
                'states': {
                    'drafting': {'submit': 'review', 'fail': 'escalate'},
                    'review': {'approve': 'compliance', 'reject': 'drafting'},
                    'compliance': {'pass': 'signoff', 'fail': 'drafting'},
                    'signoff': {'done': 'done'},
                    'escalate': {'resolve': 'drafting'},
                },
            },
        }


# ---- 模块级工具 ----
def _read_text(path: Path) -> str:
    for enc in ('utf-8', 'gb18030', 'utf-16'):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return path.read_text(encoding='utf-8', errors='replace')


def _read_docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(path))
        return '\n'.join(p.text for p in doc.paragraphs)
    except Exception:
        return ''


def _read_pdf(path: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            return '\n'.join((pg.extract_text() or '') for pg in pdf.pages)
    except Exception:
        return ''


def _read_xlsx(path: Path) -> str:
    try:
        from openpyxl import load_workbook
        wb = load_workbook(str(path), read_only=True, data_only=True)
        rows = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                rows.append('\t'.join('' if c is None else str(c) for c in row))
        return '\n'.join(rows)
    except Exception:
        return ''


def _extract_sections(text: str) -> list[str]:
    heads = []
    for line in text.splitlines():
        line = line.strip()
        if re.match(r'^(#{1,6}\s+|第[一二三四五六七八九十0-9]+[章节篇]|[0-9]+\.)', line):
            heads.append(line[:40])
    return heads[:20]


def _first_title(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('#') and not line.startswith('##'):
            return line.lstrip('# ').strip()[:40]
    return ''


def _field(obj: Any, keys: tuple[str, ...]) -> str:
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if v:
                return str(v)
    return ''


def _extract_code(text: str) -> str:
    m = _CODE_RE.search(text or '')
    return m.group(1).replace(' ', '') if m else ''


def _compliance_basis(domain: str) -> str:
    return f'{_DOMAIN_LABEL.get(domain, domain)}相关现行标准与法规'
