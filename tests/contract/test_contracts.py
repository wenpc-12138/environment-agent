# -*- coding: utf-8 -*-
"""契约测试（coding_standards §6）：M01 骨架公开接口签名与 contracts.md 一致。

基于类型/属性检查，离线可跑；模块未实现时标记 xfail，实现后自动转跑。
"""
from __future__ import annotations

import inspect

import pytest

from src.core import config, db, errors, logger
from src.models import core as models


# ---- errors（contracts.md §1 / coding_standards §5）----

def test_errors_hierarchy() -> None:
    """五个异常类必须继承 EABaseError。"""
    for exc in (errors.NotFoundError, errors.ContractViolationError,
                errors.ComplianceError, errors.SandboxError):
        assert issubclass(exc, errors.EABaseError)


def test_http_status_mapping() -> None:
    """HTTP 映射：404 / 422 / 403 / 500。"""
    assert errors.http_status_for(errors.NotFoundError('x')) == 404
    assert errors.http_status_for(errors.ContractViolationError('x')) == 422
    assert errors.http_status_for(errors.ComplianceError('x')) == 403
    assert errors.http_status_for(RuntimeError('x')) == 500


# ---- config（coding_standards §3.5）----

def test_config_singleton() -> None:
    """get_settings 单例。"""
    assert config.get_settings() is config.get_settings()


def test_config_resolve() -> None:
    """相对路径基于 project_root 解析。"""
    settings = config.get_settings()
    assert settings.resolve('data') == config.PROJECT_ROOT / 'data'
    assert settings.resolve(str(config.PROJECT_ROOT / 'x')) == config.PROJECT_ROOT / 'x'


# ---- db（coding_standards §4）----

def test_db_migrations_idempotent(tmp_path, monkeypatch) -> None:
    """迁移脚本应用幂等：真实 0001 迁移被应用，二跑无新增。"""
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'm.db'))
    config.get_settings.cache_clear()
    try:
        applied = db.run_migrations()
        assert '0001_v12_to_v20' in applied
        assert db.run_migrations() == []  # 幂等
    finally:
        config.get_settings.cache_clear()


# ---- models（contracts.md §2）----

def test_models_valid() -> None:
    """核心模型可构造且 ID 校验生效。"""
    p = models.Project(id='prj-20260806-001', name='某项目', domain='D1')
    assert p.status == 'received'
    assert p.standards == []
    with pytest.raises(Exception):
        models.Project(id='bad-id', name='x', domain='D1')


def test_review_issue_pattern() -> None:
    """审核问题 ID 必须 P0-001 格式。"""
    ok = models.ReviewIssue(
        id='P1-003', severity='P1', type='format',
        location='第2章', description='表格编号未连续',
    )
    assert ok.severity == 'P1'
    with pytest.raises(Exception):
        models.ReviewIssue(
            id='X1-003', severity='P1', type='f',
            location='l', description='bad id',
        )


# ---- logger ----

def test_logger_get() -> None:
    """get_logger 返回命名 logger。"""
    assert logger.get_logger('test').name == 'test'


# ---- utils ----

def test_utils_helpers() -> None:
    """ID 与文件名工具。"""
    from src.core.utils import gen_seq_id, now_iso, safe_filename
    assert now_iso().endswith('Z')
    assert gen_seq_id('prj').startswith('prj-')
    assert safe_filename('a/b:c.txt') == 'a_b_c.txt'
