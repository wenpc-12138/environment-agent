# -*- coding: utf-8 -*-
"""G7 MCP 双向（server 侧）：initialize/tools/list/tools/call + 错误处理。"""
from __future__ import annotations

import json

import pytest

from src.gateway.mcp_server import McpServer, handle_jsonrpc, tools_list


class TestJsonRpcDispatch:
    def test_initialize(self):
        r = handle_jsonrpc({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                            'params': {'clientInfo': {'name': 'test'}}})
        assert r['id'] == 1
        info = r['result']['serverInfo']
        assert info['name'] == 'environment-agent'
        assert r['result']['capabilities']['tools']

    def test_tools_list(self):
        r = handle_jsonrpc({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}})
        tools = r['result']['tools']
        assert len(tools) > 0
        names = [t['name'] for t in tools]
        assert 'kb_lookup' in names
        assert all('inputSchema' in t for t in tools)

    def test_tools_call_ok(self):
        r = handle_jsonrpc({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                            'params': {'name': 'kb_lookup',
                                       'arguments': {'query': 'GB 3838', 'top_n': 2}}})
        assert r['id'] == 3
        assert r['result']['isError'] is False
        assert r['result']['content'][0]['type'] == 'text'

    def test_tools_call_unknown_tool(self):
        r = handle_jsonrpc({'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
                            'params': {'name': 'no_such_tool', 'arguments': {}}})
        assert r['result']['isError'] is True

    def test_invalid_request(self):
        r = handle_jsonrpc({'foo': 1})
        assert r['error']['code'] == -32600

    def test_unsupported_method(self):
        r = handle_jsonrpc({'jsonrpc': '2.0', 'id': 5, 'method': 'resources/list', 'params': {}})
        assert r['error']['code'] == -32603

    def test_ping(self):
        r = handle_jsonrpc({'jsonrpc': '2.0', 'id': 6, 'method': 'ping', 'params': {}})
        assert r['result'] == {}

    def test_mcp_tool_schema_conversion(self):
        schema = {'type': 'function',
                  'function': {'name': 'calc_formula', 'description': 'd',
                               'parameters': {'type': 'object', 'properties': {'x': {}}}}}
        assert McpServer  # 引用
        tools = tools_list()
        match = [t for t in tools['tools'] if t['name'] == 'calc_formula']
        assert match and match[0]['inputSchema']['type'] == 'object'


class TestDirectHandle:
    def test_server_instance(self):
        s = McpServer()
        r = s.handle({'jsonrpc': '2.0', 'id': 'a', 'method': 'ping', 'params': {}})
        assert r['result'] == {}
