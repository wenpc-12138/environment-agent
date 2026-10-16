# -*- coding: utf-8 -*-
"""M03 Provider 池行为测试（第 7 波）：加载/选择/失败切换/成本/健康。"""
import pytest

from src.llm.pool import ProviderPool, ProviderSpec

# v1.2 providers 表风格行
V12_ROWS = [
    {'id': 1, 'name': 'deepseek', 'kind': 'openai', 'model': 'deepseek-chat',
     'base_url': 'https://api.deepseek.com', 'api_key': 'sk-1', 'is_active': True,
     'cost_per_1k_in': 0.001, 'cost_per_1k_out': 0.002, 'quality': 0.7, 'latency': 0.6},
    {'id': 2, 'name': 'glm', 'kind': 'openai', 'model': 'glm-4',
     'base_url': 'https://open.bigmodel.cn', 'api_key': 'sk-2', 'is_active': True,
     'cost_per_1k_in': 0.005, 'cost_per_1k_out': 0.005, 'quality': 0.8, 'latency': 1.0},
    {'id': 3, 'name': 'mock', 'kind': 'mock', 'model': 'mock-chat',
     'base_url': '', 'api_key': '', 'is_active': False},
]


def _pool(**kw) -> ProviderPool:
    kw.setdefault('providers', [dict(r) for r in V12_ROWS])
    return ProviderPool(**kw)


def test_load_normalizes_v12_rows():
    pool = _pool()
    specs = pool.load()
    assert len(specs) == 3
    assert isinstance(specs[0], ProviderSpec)
    assert specs[0].model == 'deepseek-chat'
    assert specs[2].enabled is False  # is_active=False -> enabled=False


def test_load_failure_degrades_to_empty():
    pool = ProviderPool(load_fn=lambda: (_ for _ in ()).throw(RuntimeError('db down')))
    assert pool.load() == []
    assert pool.last_errors


def test_list_active_only():
    pool = _pool()
    assert len(pool.list(active_only=True)) == 2
    assert len(pool.list(active_only=False)) == 3


def test_pick_cost_prefers_cheapest():
    spec = _pool().pick('cost')
    assert spec.model == 'deepseek-chat'  # 0.003 最便宜


def test_pick_quality_prefers_highest():
    spec = _pool().pick('quality')
    assert spec.model == 'glm-4'  # quality 0.8


def test_pick_latency_prefers_fastest():
    spec = _pool().pick('latency')
    assert spec.model == 'deepseek-chat'  # latency 0.6


def test_pick_unknown_priority_falls_back_to_cost():
    assert _pool().pick('weird').model == _pool().pick('cost').model


def test_pick_empty_pool_returns_none():
    assert ProviderPool(providers=[]).pick('cost') is None


def test_complete_success_via_caller():
    pool = _pool(caller=lambda prov, messages: 'ok-text')
    assert pool.complete('deepseek-chat', [{'role': 'user', 'content': 'hi'}]) == 'ok-text'


def test_complete_handles_tuple_result():
    pool = _pool(caller=lambda prov, messages: ('ok-text', {'tokens': 10}))
    assert pool.complete('deepseek-chat', []) == 'ok-text'


def test_complete_schema_validation_success():
    from pydantic import BaseModel

    class Out(BaseModel):
        answer: str

    pool = _pool(caller=lambda prov, messages: '{"answer": "42"}')
    out = pool.complete('deepseek-chat', [], schema=Out)
    assert isinstance(out, Out)
    assert out.answer == '42'


def test_complete_schema_failure_falls_back_to_next_candidate():
    """第一个候选 schema 校验失败 -> 切换下一候选。"""
    from pydantic import BaseModel, ValidationError

    class Out(BaseModel):
        answer: str

    calls = []

    def caller(prov, messages):
        calls.append(prov['model'])
        if prov['model'] == 'deepseek-chat':
            return 'not-json'
        return '{"answer": "switch"}'

    pool = _pool(caller=caller)
    out = pool.complete('deepseek-chat', [], schema=Out)
    assert out.answer == 'switch'
    assert calls == ['deepseek-chat', 'glm-4']


def test_complete_all_fail_returns_none_and_records_errors():
    pool = _pool(caller=lambda prov, messages: (_ for _ in ()).throw(RuntimeError('boom')))
    assert pool.complete('deepseek-chat', []) is None
    assert pool.last_errors


def test_complete_model_mismatch_still_tries_all():
    pool = _pool(caller=lambda prov, messages: f'from-{prov["model"]}')
    assert pool.complete('no-such-model', []) == 'from-deepseek-chat'


def test_estimate_cost_with_configured_price():
    pool = _pool()
    cost = pool.estimate_cost('deepseek-chat', 1000, 1000)
    assert cost == pytest.approx(0.003, abs=1e-9)


def test_estimate_cost_heuristic_fallback():
    pool = ProviderPool(providers=[])
    cost = pool.estimate_cost('unknown-model', 1000, 1000)
    assert cost == pytest.approx(0.004, abs=1e-9)  # _FALLBACK_PRICE (0.002, 0.002)


def test_health_check_with_probe():
    pool = _pool(probe=lambda prov: prov['model'] == 'glm-4')
    out = pool.health_check()
    assert out['1'] is False
    assert out['2'] is True
    assert out['3'] is False


def test_health_check_default_probe_offline_rules():
    pool = _pool()
    out = pool.health_check()
    assert out['1'] is True  # 有 base_url + api_key
    assert out['2'] is True
    assert out['3'] is False  # mock / 缺 base_url


def test_health_check_single_provider():
    pool = _pool(probe=lambda prov: True)
    assert pool.health_check(provider_id=1) == {'1': True}


def test_status_summary():
    out = _pool().status()
    assert out['total'] == 3
    assert out['active'] == 2
    assert 'deepseek-chat' in out['providers']


def test_refresh_reloads():
    pool = ProviderPool(load_fn=lambda: [{'id': 1, 'model': 'a', 'is_active': True}])
    assert pool.load()[0].model == 'a'
    pool._load_fn = lambda: [{'id': 2, 'model': 'b', 'is_active': True}]  # noqa: SLF001 测试内替换加载源
    assert pool.refresh()[0].model == 'b'
