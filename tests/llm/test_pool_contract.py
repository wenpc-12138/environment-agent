# -*- coding: utf-8 -*-
"""M03 Provider 池契约测试（第 7 波：真实 LLM Provider 池接入）。

对齐 contracts.md §3.M03 的 LLMRouter 契约，并冻结第 7 波新增的
`ProviderPool` / `ProviderSpec` 公开接口。
"""
import inspect

import pytest

from src.llm.pool import ProviderPool, ProviderSpec


def test_provider_spec_required_fields():
    fields = set(ProviderSpec.model_fields)
    for required in ('id', 'model', 'enabled'):
        assert required in fields
    for optional in ('name', 'kind', 'base_url', 'api_key', 'priority',
                     'cost_per_1k_in', 'cost_per_1k_out', 'quality', 'latency'):
        assert optional in fields


def test_provider_pool_contract_signatures():
    sigs = {
        'load': ['self'],
        'pick': ['self', 'priority'],
        'complete': ['self', 'model', 'messages', 'schema', 'priority'],
        'estimate_cost': ['self', 'model', 'in_tokens', 'out_tokens'],
        'health_check': ['self', 'provider_id'],
        'status': ['self'],
    }
    for method, names in sigs.items():
        params = list(inspect.signature(getattr(ProviderPool, method)).parameters)
        assert params == names, f'{method} 参数应为 {names}，实际 {params}'
    pick = inspect.signature(ProviderPool.pick).parameters['priority']
    assert pick.default == 'cost'


def test_provider_pool_constructor_injectable():
    pool = ProviderPool(providers=[], load_fn=lambda: [], caller=lambda p, m: 'x', probe=lambda p: True)
    assert pool.list(active_only=True) == []


def test_llm_router_accepts_provider_pool():
    from src.llm import LLMRouter

    params = inspect.signature(LLMRouter.__init__).parameters
    assert 'provider_pool' in params, 'LLMRouter 应支持 provider_pool 注入'
    # 既有兼容参数不丢失
    for legacy in ('pool', 'caller'):
        assert legacy in params


def test_provider_pool_exported_from_llm():
    import src.llm as llm

    assert llm.ProviderPool is ProviderPool
    assert llm.ProviderSpec is ProviderSpec
