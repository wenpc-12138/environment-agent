# -*- coding: utf-8 -*-
"""M08 角色系统行为测试：R1-R8 预定义 / define / activate / RBAC 校验。"""
from __future__ import annotations

from src.models.core import RoleBlueprint
from src.roles import RoleRegistry
from src.roles.permissions import allowed_actions, can


def test_predefined_eight_roles_active() -> None:
    reg = RoleRegistry()
    roles = reg.list()
    assert [r.id for r in roles] == [f'R{i}' for i in range(1, 9)]
    assert all(r.status == 'active' for r in roles)


def test_predefined_blueprints_match_architecture() -> None:
    reg = RoleRegistry()
    r4 = reg.get('R4')
    assert r4 is not None and r4.name == '编制员'
    assert 'generate_report' in r4.permissions and 'fill_table' in r4.permissions
    r8 = reg.get('R8')
    assert r8 is not None and 'approve_role' in r8.permissions and 'manage_skills' in r8.permissions
    r5 = reg.get('R5')
    assert r5 is not None and 'approve' in r5.permissions and '授权签字人' in r5.compliance


def test_define_new_role_pending_review() -> None:
    reg = RoleRegistry()
    rid = reg.define(RoleBlueprint(
        id='R9', name='碳排核查员', domain='D7',
        responsibilities=['碳排放核算'], required_skills=['sk-co2-001'],
        permissions=['generate_report', 'read_data'], compliance=['温室气体核查员资质'],
    ))
    assert rid == 'R9'
    assert reg.get('R9').status == 'pending_r8_review'
    assert not reg.check_permission('R9', 'generate_report'), 'pending 角色不可用'


def test_activate_requires_r8_approval() -> None:
    reg = RoleRegistry()
    reg.define(RoleBlueprint(id='R9', name='碳排核查员', domain='D7'))
    assert not reg.activate('R9', 'R5'), '非 R8 审核不通过'
    assert reg.get('R9').status == 'pending_r8_review'
    assert reg.activate('R9', 'R8'), 'R8 审核 + 用户确认后激活'
    assert reg.get('R9').status == 'active'


def test_activate_idempotent_and_missing() -> None:
    reg = RoleRegistry()
    assert not reg.activate('R1', 'R8'), '内置角色已激活，重复激活返回 False'
    assert not reg.activate('R99', 'R8'), '角色不存在返回 False'


def test_check_permission_rbac() -> None:
    reg = RoleRegistry()
    assert reg.check_permission('R4', 'generate_report')
    assert not reg.check_permission('R4', 'approve'), '编制员无权审批'
    assert reg.check_permission('R5', 'approve')
    assert reg.check_permission('R8', 'manage_skills')
    assert not reg.check_permission('R8', 'compliance_check')
    assert not reg.check_permission('R1', 'review_report')


def test_permission_helper_wildcard_and_inactive() -> None:
    reg = RoleRegistry()
    r = reg.get('R4')
    assert r is not None and can(r, 'generate_report')
    pending = RoleBlueprint(id='RX', name='x', domain='D1', permissions=['read_data'])
    assert not can(pending, 'read_data'), '未激活不可用'
    assert allowed_actions(r) == r.permissions
