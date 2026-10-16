# -*- coding: utf-8 -*-
"""M02 平台适配器契约测试（第 7 波：平台适配器落地）。"""
import inspect

import pytest

from src.gateway.adapters import (ChannelAdapter, AdapterRegistry,
                                  get_adapter, register_adapter)


def test_channel_adapter_base_contract():
    """基类暴露 send / receive 抽象契约。"""
    assert inspect.iscoroutinefunction(ChannelAdapter.send) is False
    assert 'send' in dir(ChannelAdapter)
    assert 'receive' in dir(ChannelAdapter)


def test_default_adapters_registered():
    """内置适配器 http / cli 在包导入后即可用（幂等注册）。"""
    assert get_adapter('http') is not None
    assert get_adapter('cli') is not None


def test_adapter_names():
    assert get_adapter('http').name == 'http'
    assert get_adapter('cli').name == 'cli'


def test_custom_adapter_register_and_get():
    class Fake(ChannelAdapter):
        name = 'fake'

        def send(self, target, content, **kw):
            return {'ok': True}

        def receive(self, **kw):
            return []

    register_adapter(Fake())
    assert get_adapter('fake').name == 'fake'


def test_http_adapter_send_receive_signature():
    from src.gateway.adapters.http_channel import HttpChannelAdapter

    send_params = list(inspect.signature(HttpChannelAdapter.send).parameters)
    assert send_params[:2] == ['self', 'target']
    receive_params = list(inspect.signature(HttpChannelAdapter.receive).parameters)
    assert receive_params[0] == 'self'


def test_cli_adapter_send_receive_signature():
    from src.gateway.adapters.cli_channel import CliChannelAdapter

    send_params = list(inspect.signature(CliChannelAdapter.send).parameters)
    assert send_params[:2] == ['self', 'target']
    receive_params = list(inspect.signature(CliChannelAdapter.receive).parameters)
    assert receive_params[0] == 'self'
