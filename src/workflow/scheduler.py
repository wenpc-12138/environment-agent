# -*- coding: utf-8 -*-
"""M09 调度器（Cron / Webhook 占位，contracts.md §3.M09）。

- `next_run(cron_expr, base)`：解析 5 段 cron（分 时 日 月 周），返回下次触发时间；占位实现按分钟粒度。
- `WebhookTrigger.handle(payload)`：webhook 触发校验占位（签名验签留待接入波次）。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

CRON_RE = re.compile(r'^\s*(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$')


def _min_span(token: str, lo: int, hi: int, now: int) -> int:
    """cron 字段匹配检查（支持 * / 列表 / 范围 的子集）。"""
    token = token.strip()
    if token == '*':
        return True
    for part in token.split(','):
        part = part.strip()
        if '/' in part:
            base, step = part.split('/')
            step = int(step)
            if base in ('*', ''):
                if now % step == 0:
                    return True
            else:
                lo_b, hi_b = (int(base), int(base)) if '-' not in base else map(int, base.split('-'))
                if lo_b <= now <= hi_b and (now - lo_b) % step == 0:
                    return True
            continue
        if '-' in part:
            a, b = map(int, part.split('-'))
            if a <= now <= b:
                return True
        elif part.isdigit() and lo <= int(part) <= hi and int(part) == now:
            return True
    return False


def next_run(cron_expr: str, base: datetime | None = None) -> datetime:
    """返回 cron 表达式（分 时 日 月 周）的下一次触发时间（分钟粒度）。"""
    m = CRON_RE.match(cron_expr)
    if not m:
        raise ValueError(f'非法 cron 表达式: {cron_expr}')
    minute, hour, dom, month, dow = m.groups()
    t = (base or datetime.now(timezone.utc)).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 366):  # 最多扫描一年
        # cron dow：0=Sunday..6=Saturday；Python weekday()：0=Monday..6=Sunday
        cron_dow = (t.weekday() + 1) % 7
        if (_min_span(minute, 0, 59, t.minute) and _min_span(hour, 0, 23, t.hour)
                and _min_span(dom, 1, 31, t.day) and _min_span(month, 1, 12, t.month)
                and _min_span(dow, 0, 6, cron_dow)):
            return t
        t += timedelta(minutes=1)
    raise ValueError(f'一年内无匹配: {cron_expr}')


class WebhookTrigger:
    """Webhook 触发占位：仅校验 payload 非空并含 type。"""

    def handle(self, payload: dict) -> bool:
        return bool(payload) and ('type' in payload or 'event' in payload)
