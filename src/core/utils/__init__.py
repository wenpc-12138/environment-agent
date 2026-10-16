# -*- coding: utf-8 -*-
"""core.utils：ID 生成、时间戳、路径安全等通用工具。"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime


def now_iso() -> str:
    """当前 UTC 时间 ISO 8601 字符串（Z 结尾，契约 §1）。"""
    return datetime.now(UTC).isoformat(timespec='seconds').replace('+00:00', 'Z')


def gen_seq_id(prefix: str, n: int = 3) -> str:
    """生成 `<prefix>-YYYYMMDD-NNN` 序列 ID（契约 §1：prj-20260806-001）。"""
    stamp = datetime.now().strftime('%Y%m%d')
    seq = str(uuid.uuid4().int % 10**n).zfill(n)
    return f'{prefix}-{stamp}-{seq}'


def safe_filename(name: str, fallback: str = 'file') -> str:
    """清理文件名中的非法字符（跨平台），空结果回退 fallback。"""
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', '_', name).strip('._')
    return cleaned or fallback
