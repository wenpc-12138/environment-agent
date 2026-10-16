# -*- coding: utf-8 -*-
"""M03 推理引擎包：意图路由 + LLM 路由 + 反幻觉管线。

- `IntentRouter.analyze(text, context)` -> `RouteResult`（规则实现，零依赖）
- `LLMRouter.route(task, priority)` -> model 名；`LLMRouter.complete(model, messages, schema)`
- grounding：`label_claims` / `ground_spans` / `verify_claims`（CRAG 分级，可对接 M06）
"""
from .grounding import (EpistemicClaim, GroundedSpan, VerifiedClaim,
                        ground_spans, label_claims, verify_claims)
from .intent import IntentRouter
from .pool import ProviderPool, ProviderSpec
from .router import LLMRouter, extract_json
from ..models.core import RouteResult

__all__ = [
    'IntentRouter', 'LLMRouter', 'RouteResult', 'extract_json',
    'ProviderPool', 'ProviderSpec',
    'label_claims', 'ground_spans', 'verify_claims',
    'EpistemicClaim', 'GroundedSpan', 'VerifiedClaim',
]
