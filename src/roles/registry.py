# -*- coding: utf-8 -*-
"""M08 角色系统：R1-R8 预定义蓝图 + 注册 / 激活 / RBAC 校验（contracts.md §3.M08）。

- `RoleRegistry`：`define`（新角色登记，status=pending_r8_review）、`activate`（仅 R8 审核通过 +
  调用方确认即用户确认，见 architecture.md §4）、`check_permission`（角色须 active 且具备动作权限）。
- R1-R8 为系统内置角色，初始化即 active；M15 自生成的角色必须经 R8 审核 + 用户确认才激活。
"""
from __future__ import annotations

from ..models.core import RoleBlueprint

# ---- R1-R8 预定义角色（architecture.md §4）----
PREDEFINED_ROLES: dict[str, RoleBlueprint] = {
    'R1': RoleBlueprint(
        id='R1', name='项目经理', domain='D1',
        responsibilities=['委托接收', '项目工单', '全流程协调'],
        required_skills=[],
        permissions=['receive_project', 'create_project', 'coordinate', 'read_data'],
        compliance=[], status='active',
    ),
    'R2': RoleBlueprint(
        id='R2', name='方案员', domain='D1',
        responsibilities=['采样/监测方案生成'],
        required_skills=['sk-plan-001'],
        permissions=['generate_plan', 'edit_plan', 'read_data'],
        compliance=['CMA 资质范围'], status='active',
    ),
    'R3': RoleBlueprint(
        id='R3', name='分析员', domain='D1',
        responsibilities=['数据校核', '质控判断（LIMS 数据或手动上传）'],
        required_skills=[],
        permissions=['ingest_data', 'validate_data', 'read_data'],
        compliance=['CMA 资质范围'], status='active',
    ),
    'R4': RoleBlueprint(
        id='R4', name='编制员', domain='D1',
        responsibilities=['报告编制（监测/验收/环评）', '模板填充'],
        required_skills=['sk-report-001'],
        permissions=['generate_report', 'fill_table', 'search_standard', 'read_data'],
        compliance=['CMA 资质范围'], status='active',
    ),
    'R5': RoleBlueprint(
        id='R5', name='审核员', domain='D1',
        responsibilities=['P0/P1/P2 分级审核', '结构化反馈', '自动修复'],
        required_skills=['sk-review-001'],
        permissions=['review_report', 'approve', 'auto_fix', 'read_data'],
        compliance=['授权签字人'], status='active',
    ),
    'R6': RoleBlueprint(
        id='R6', name='合规员', domain='D1',
        responsibilities=['CMA 合规检查（标准有效性/资质/方法/人员/分包）'],
        required_skills=[],
        permissions=['compliance_check', 'read_data'],
        compliance=['CMA 资质范围'], status='active',
    ),
    'R7': RoleBlueprint(
        id='R7', name='标准员', domain='D1',
        responsibilities=['标准检索', '适用性验证'],
        required_skills=[],
        permissions=['search_standard', 'validate_standard', 'read_data'],
        compliance=[], status='active',
    ),
    'R8': RoleBlueprint(
        id='R8', name='知识管理员', domain='D1',
        responsibilities=['Skill 审核入库', '版本管理', 'OERCR 闸门'],
        required_skills=[],
        permissions=['manage_skills', 'approve_role', 'manage_versions', 'oercr_gate'],
        compliance=[], status='active',
    ),
}


class RoleRegistry:
    """角色注册表：R1-R8 内置 + 新角色 define/activate/check_permission。"""

    def __init__(self) -> None:
        self._roles: dict[str, RoleBlueprint] = dict(PREDEFINED_ROLES)

    # ---- 注册 ----
    def define(self, blueprint: RoleBlueprint) -> str:
        """登记角色蓝图，返回 role_id。

        新角色默认 pending_r8_review（须 R8 审核 + 用户确认后 activate）；
        重复 id 视为更新（保持原状态）。
        """
        if blueprint.id not in self._roles:
            blueprint.status = 'pending_r8_review'
        self._roles[blueprint.id] = blueprint
        return blueprint.id

    # ---- 激活 ----
    def activate(self, role_id: str, approved_by: str) -> bool:
        """激活角色：仅 R8 审核通过（approved_by=='R8'），调用方确认即用户确认。

        返回 False 表示：角色不存在 / 审核人非 R8 / 非待审角色重复激活。
        """
        if approved_by != 'R8':
            return False
        blueprint = self._roles.get(role_id)
        if blueprint is None:
            return False
        if blueprint.status == 'active':
            return False
        blueprint.status = 'active'
        return True

    # ---- RBAC 校验 ----
    def check_permission(self, role_id: str, action: str) -> bool:
        """角色须已激活且具备动作权限；`*` 通配代表全部权限。"""
        blueprint = self._roles.get(role_id)
        if blueprint is None or blueprint.status != 'active':
            return False
        return action in blueprint.permissions or '*' in blueprint.permissions

    # ---- 删除（仅允许删除自定义角色，R1-R8 内置角色不可删）----
    def remove(self, role_id: str) -> bool:
        if role_id in PREDEFINED_ROLES:
            return False
        return self._roles.pop(role_id, None) is not None

    # ---- 查询 ----
    def get(self, role_id: str) -> RoleBlueprint | None:
        return self._roles.get(role_id)

    def list(self, status: str | None = None) -> list[RoleBlueprint]:
        roles = list(self._roles.values())
        if status is not None:
            roles = [r for r in roles if r.status == status]
        return sorted(roles, key=lambda r: r.id)
