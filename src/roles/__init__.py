# -*- coding: utf-8 -*-
"""M08 角色系统：R1-R8 注册 / RBAC 权限校验。"""
from .registry import PREDEFINED_ROLES, RoleBlueprint, RoleRegistry
from .permissions import allowed_actions, can

__all__ = ['PREDEFINED_ROLES', 'RoleBlueprint', 'RoleRegistry', 'allowed_actions', 'can']
