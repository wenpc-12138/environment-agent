# -*- coding: utf-8 -*-
"""M08 角色系统契约测试（contracts.md §3.M08）。

src/roles/ 未实现时自动 skip；实现后自动激活。
"""
from __future__ import annotations

import inspect

import pytest


def test_role_blueprint_fields() -> None:
    """RoleBlueprint 字段与契约一致。"""
    registry = pytest.importorskip('src.roles.registry', reason='M08 RoleRegistry 未实现')
    fields = registry.RoleBlueprint.model_fields
    assert {'id', 'name', 'domain', 'responsibilities', 'required_skills',
            'permissions', 'compliance', 'status'} <= set(fields)


def test_role_registry_signatures() -> None:
    """RoleRegistry.define / activate / check_permission。"""
    registry = pytest.importorskip('src.roles.registry', reason='M08 RoleRegistry 未实现')
    assert list(inspect.signature(registry.RoleRegistry.define).parameters)[:2] == ['self', 'blueprint']
    act = inspect.signature(registry.RoleRegistry.activate)
    assert list(act.parameters)[:3] == ['self', 'role_id', 'approved_by']
    perm = inspect.signature(registry.RoleRegistry.check_permission)
    assert list(perm.parameters)[:3] == ['self', 'role_id', 'action']
