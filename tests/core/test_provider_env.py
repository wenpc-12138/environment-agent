# -*- coding: utf-8 -*-
"""环境变量注入模型凭据（EA_LLM_*）专项测试。

背景：API Key 不写进代码/仓库，除 UI 设置外，容器与 CI 场景可通过环境
变量注入。本组用例保证：
- 未设置任何 EA_LLM_* 变量时，数据零改动（演示模式保持激活）；
- 设置后写入目标 Provider 并自动激活，不会把真实密钥写到 mock 行上；
- 可通过 EA_LLM_PROVIDER 精确指定目标 Provider。
"""
from __future__ import annotations

import pytest

from src.core.db_v12 import base as v12_base
from src.core.db_v12 import providers as pv


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    """隔离库：直接替换 base.DB_PATH（模块级常量在 import 时确定）。"""
    monkeypatch.setattr(v12_base, 'DB_PATH', str(tmp_path / 'provider_env.db'))
    # init_db 会改写这两个跨模块全局标志，测试后必须还原，避免影响其它用例
    monkeypatch.setattr(v12_base, '_VEC_OK', v12_base._VEC_OK)
    monkeypatch.setattr(v12_base, '_VEC_METRIC', v12_base._VEC_METRIC)
    v12_base.close_db()
    v12_base.init_db()          # 建表 + 预置 6 个 Provider（密钥为空，演示模式激活）
    yield
    v12_base.close_db()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (pv.ENV_KEY, pv.ENV_BASE_URL, pv.ENV_MODEL, pv.ENV_PROVIDER):
        monkeypatch.delenv(k, raising=False)


def test_no_env_vars_changes_nothing(_db):
    """未设置 EA_LLM_* 时不改动任何数据。"""
    before = [dict(r) for r in pv.list_providers()]
    assert pv.apply_env_override() is None
    after = [dict(r) for r in pv.list_providers()]
    assert before == after
    assert pv.get_active_provider()['kind'] == 'mock'


def test_env_key_written_and_activated(_db, monkeypatch):
    """提供了密钥与 base_url 时写入非 mock Provider 并自动激活。"""
    monkeypatch.setenv(pv.ENV_KEY, 'sk-test-not-a-real-key')
    monkeypatch.setenv(pv.ENV_BASE_URL, 'https://api.example.com/v1')
    monkeypatch.setenv(pv.ENV_MODEL, 'test-model')

    pid = pv.apply_env_override()
    assert pid, '应返回被更新的 provider id'

    p = pv.get_provider(pid)
    assert p['api_key'] == 'sk-test-not-a-real-key'
    assert p['base_url'] == 'https://api.example.com/v1'
    assert p['model'] == 'test-model'
    assert p['kind'] != 'mock', '真实密钥不得写入演示 Provider'
    assert pv.get_active_provider()['id'] == pid, '注入凭据后应自动激活'


def test_env_provider_selects_by_name(_db, monkeypatch):
    """EA_LLM_PROVIDER 可按名称精确指定目标 Provider。"""
    monkeypatch.setenv(pv.ENV_PROVIDER, '智谱 GLM')
    monkeypatch.setenv(pv.ENV_KEY, 'sk-glm-placeholder')

    pid = pv.apply_env_override()
    p = pv.get_provider(pid)
    assert p['name'] == '智谱 GLM'
    assert p['api_key'] == 'sk-glm-placeholder'


def test_env_key_only_without_base_url_keeps_mock_active(_db, monkeypatch):
    """只给密钥、目标 Provider 无 base_url 时写入密钥但不激活（不可用不切换）。"""
    monkeypatch.setenv(pv.ENV_PROVIDER, 'OpenAI')
    monkeypatch.setenv(pv.ENV_KEY, 'sk-openai-placeholder')
    # OpenAI 预置 base_url 非空，此处改为清空以验证“无端点不激活”分支
    pv.w("UPDATE providers SET base_url='' WHERE name='OpenAI'")

    pid = pv.apply_env_override()
    assert pv.get_provider(pid)['api_key'] == 'sk-openai-placeholder'
    assert pv.get_active_provider()['kind'] == 'mock', '无 base_url 不应激活'
