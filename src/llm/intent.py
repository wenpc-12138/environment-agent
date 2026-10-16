# -*- coding: utf-8 -*-
"""M03 意图路由（IntentRouter，contracts.md §3.M03）。

功能：
- `analyze(text, context)` -> `RouteResult`：基于领域关键词与意图模式的规则推断。
- 置信度三档映射（契约）：auto >=0.85 / interactive 0.50~0.84 / manual <0.50。
- 领域（D1..D6）与技能 ID 映射，供 M07 技能选择与 M06 RAG 过滤。

设计遵循 ADR-010 零硬依赖：纯规则实现，不依赖 LLM 调用；
LLM 版意图推断作为 `router_cls` 可注入增强（M03 落地 LLM 后替换）。
"""
from __future__ import annotations

from ..models.core import RouteResult

# 领域关键词表（v1.2 agent_core.infer_domain 的规则化重铸）
# 定位扩展（2026-08）：生态环境监测 -> 生态环境领域大类，D1-D6 不变，新增 D7-D10。
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    'D1': ['水', '废水', 'cod', '氨氮', '溶解氧', '水质', '地表水', '地下水', '河流', '湖泊', '污水', '排污'],
    'D2': ['大气', '废气', '烟气', '颗粒物', 'pm2.5', 'pm10', '二氧化硫', '氮氧化物', 'voc',
           '无组织', '有组织', '除臭', '恶臭', '异味', '臭气'],
    'D3': ['噪声', '振动', '分贝', '声级', 'db(', '夜间噪声', '敏感点'],
    'D4': ['土壤', '固废', '固体废物', '危废', '危险废物', '污泥', '重金属', '浸出', '场地', '地块', '修复'],
    'D5': ['生态', '生物', '浮游', '底栖', '群落', '样方', '植被', '两栖', '鱼类', '香农',
           '多样性', '物种', '栖息地', '湿地', '矿区', '自然保护区'],
    'D6': ['监测方案', '质控', '报告', 'cma', '内审', '管理', '验收', '审核', '合规', '实验室'],
    'D7': ['辐射', '放射性', '剂量', 'γ', '射线', '伴生', '电离', '核素', 'α', 'β'],
    'D8': ['碳', '温室', 'co2', 'co₂', '甲烷', 'ccer', '排放因子', '碳达峰', '碳中和', '碳核算',
           '碳足迹', '碳排放', '能耗', 'greenhouse', 'carbon'],
    'D9': ['应急预案', '突发环境', '泄漏', '应急池', '环境风险', '演练', '处置'],
    'D10': ['清洁生产', '绿色工厂', '环保管家', '节能', '循环经济', '绿色制造', '排污权'],
}

# 意图模式关键词（plan=方案规划 / ask=问答 / craft=执行类，默认 craft）
_PLAN_KEYWORDS = ['方案', '计划', '安排', '进度', '步骤', '怎么做', '如何开展', '流程', '规划', '时间表']
_ASK_KEYWORDS = ['是什么', '什么是', '解释', '说明', '区别', '为什么', '标准号', '查询', '有效', '废止']

# 领域 -> 建议技能（M07 现有技能 ID + 新增领域技能；未注册的技能 ID 由路由层容错忽略）
_DOMAIN_SKILLS: dict[str, list[str]] = {
    'D1': ['water-monitoring', 'ep-acceptance-report', 'sampling-plan'],
    'D2': ['air-monitoring', 'emission-limits', 'ep-acceptance-report'],
    'D3': ['noise-monitoring', 'ep-acceptance-report'],
    'D4': ['soil-monitoring', 'ep-acceptance-report'],
    'D5': ['ecology-evaluation', 'ep-acceptance-report'],
    'D6': ['data-qaqc', 'cma-compliance', 'report-writing', 'ep-acceptance-review'],
    'D7': ['radiation-monitoring'],
    'D8': ['carbon-accounting'],
    'D9': ['env-emergency'],
    'D10': ['cleaner-production'],
}


# 新增领域的专业词加权：D7 辐射/D8 碳/D9 应急/D10 清洁生产 的业务词（>=2 字）
# 权重 3，避免被 D6 通用词（报告/审核）等压过；单字符弱词（碳/γ/α/β）权重 1。
_STRONG_DOMAINS = ('D7', 'D8', 'D9', 'D10')


def _score_domain(text: str) -> tuple[str, float]:
    """对领域打分，返回 (最高分领域, 加权命中数)。"""
    low = text.lower()
    best, hits = '', 0
    for domain, kws in _DOMAIN_KEYWORDS.items():
        strong = domain in _STRONG_DOMAINS
        n = 0
        for kw in kws:
            if kw in low:
                n += 3 if (strong and len(kw) >= 2) else 1
        if n > hits:
            best, hits = domain, n
    return best, hits


def _match_intent(text: str) -> tuple[str, float]:
    """意图模式匹配，返回 (mode, 匹配关键词数)。plan > ask > craft(默认)。"""
    low = text.lower()
    plan = sum(1 for kw in _PLAN_KEYWORDS if kw in low)
    if plan:
        return 'plan', plan
    ask = sum(1 for kw in _ASK_KEYWORDS if kw in low)
    if ask:
        return 'ask', ask
    return 'craft', 0


class IntentRouter:
    """意图路由：文本 -> RouteResult（规则实现，零依赖）。"""

    # 契约 §3.M03：阈值可类级覆盖（LLM 增强版继承后调整）
    AUTO_THRESHOLD = 0.85
    INTERACTIVE_THRESHOLD = 0.50

    def analyze(self, text: str, context: dict | None = None) -> RouteResult:
        """分析输入文本，返回路由结果。

        - context 可携带 {"mode_hint": "auto|interactive|manual"} 强制档位（v1.2 前端模式）。
        - 置信度：领域命中 + 意图命中综合；无任何命中时 manual 且 domain=''。
        """
        text = (text or '').strip()
        if not text:
            return RouteResult(skill_ids=[], confidence=0.0, mode='manual', domain='')

        ctx = context or {}
        domain, d_hits = _score_domain(text)
        intent, i_hits = _match_intent(text)

        # 综合置信度：领域命中贡献主分，意图命中作加成
        base = 0.4 if d_hits else 0.0
        base += min(0.4, 0.2 * d_hits)
        base += min(0.2, 0.1 * i_hits)
        confidence = round(min(1.0, base), 3)

        # context 显式档位优先（v1.2 三模式对齐）
        hint = ctx.get('mode_hint')
        if hint in ('auto', 'interactive', 'manual'):
            mode = hint
            confidence = max(confidence, 0.5 if hint == 'interactive' else 0.85 if hint == 'auto' else 0.1)
        elif confidence >= self.AUTO_THRESHOLD:
            mode = 'auto'
        elif confidence >= self.INTERACTIVE_THRESHOLD:
            mode = 'interactive'
        else:
            mode = 'manual'

        skills = list(_DOMAIN_SKILLS.get(domain, [])) if domain else []
        return RouteResult(skill_ids=skills, confidence=confidence, mode=mode,
                           domain=domain, intent=intent)
