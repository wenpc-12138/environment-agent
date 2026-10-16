# -*- coding: utf-8 -*-
"""M08 RBAC 权限工具：权限矩阵 + 单点校验（contracts.md §3.M08）。

- `can(blueprint, action)`：角色激活 + 具备动作权限（`*` 通配全部）。
- `allowed_actions(blueprint)`：列出角色可执行动作。
"""
from __future__ import annotations

from ..models.core import RoleBlueprint

WILDCARD = '*'


def can(blueprint: RoleBlueprint, action: str) -> bool:
    """单点 RBAC 校验（不要求 role 已激活，纯权限矩阵判定）。"""
    return blueprint.status == 'active' and (
        action in blueprint.permissions or WILDCARD in blueprint.permissions
    )


def allowed_actions(blueprint: RoleBlueprint) -> list[str]:
    """角色可执行动作列表（展开通配）。"""
    if WILDCARD in blueprint.permissions:
        return ['*']
    return list(blueprint.permissions)
