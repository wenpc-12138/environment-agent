# -*- coding: utf-8 -*-
"""G3 LLM 链路可观测性（对齐 LangSmith / OpenTelemetry GenAI span 思路）。

- `Tracer`：threading.local 维护 span 栈；`begin_trace` / `end_trace` / `span` 上下文管理器。
- span 记录：ts / duration_ms / type(llm|tool|skill|agent|orchestrate) / status / model / tokens / cost。
- 落盘：JSONL 追加 `data/logs/traces/traces-YYYYMMDD.jsonl`（按日分文件，防单文件膨胀）。
- 查询：`query_trace(trace_id)` 还原 span 树 / `query_task(task_id)` / `aggregate(range)` 聚合。
- 与 M14 审计互补：审计保证"完整性/防篡改"，Trace 提供"性能/成本/失败定位"。

实现完全自研（threading.local + JSONL），零新增依赖；埋点通过 try/except 包裹，
Tracer 不可用时静默降级，不影响主链路。
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from ..core.config import get_settings

_tl = threading.local()

# 粗略成本单价（元/1K tokens，供未配置 Provider 成本字段时兜底估算）
_HEURISTIC_PRICE = {
    'deepseek': (0.014, 0.028),
    'gpt-4': (0.03, 0.06),
    'gpt-3.5': (0.0005, 0.0015),
    'claude': (0.003, 0.015),
    'qwen': (0.001, 0.002),
    'glm': (0.002, 0.004),
}
_DEFAULT_PRICE = (0.01, 0.02)


def _traces_dir() -> Path:
    base = get_settings().data_dir_path / 'logs' / 'traces'
    base.mkdir(parents=True, exist_ok=True)
    return base


def _heuristic_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    model = (model or '').lower()
    p_in, p_out = _DEFAULT_PRICE
    for key, price in _HEURISTIC_PRICE.items():
        if key in model:
            p_in, p_out = price
            break
    return (in_tokens / 1000.0) * p_in + (out_tokens / 1000.0) * p_out


def _now_iso() -> str:
    return datetime.now().isoformat(timespec='milliseconds')


def _span_id() -> str:
    return uuid.uuid4().hex[:12]


class Tracer:
    """进程内链路追踪器（threading.local 单例）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # -- 会话生命周期 ------------------------------------------------
    def begin_trace(self, task_id: int = 0, title: str = '', trace_id: str | None = None) -> str:
        tid = trace_id or _span_id()
        _tl.trace = {
            'trace_id': tid,
            'task_id': task_id,
            'title': title,
            'ts': _now_iso(),
            't0': time.time(),
            'spans': [],
            'stack': [],   # 父 span_id 栈
        }
        return tid

    def current_trace(self) -> dict | None:
        return getattr(_tl, 'trace', None)

    def end_trace(self, status: str = 'ok') -> dict | None:
        """结束当前 trace：写 trace 头事件 + 落盘 JSONL。返回 trace 摘要。"""
        tr = getattr(_tl, 'trace', None)
        if tr is None:
            return None
        duration_ms = int((time.time() - tr['t0']) * 1000)
        summary = {
            'type': 'trace',
            'trace_id': tr['trace_id'],
            'task_id': tr['task_id'],
            'title': tr['title'][:200],
            'ts': tr['ts'],
            'duration_ms': duration_ms,
            'status': status,
            'span_count': len(tr['spans']),
            'cost': round(sum(s.get('cost') or 0 for s in tr['spans']), 6),
        }
        for sp in tr['spans']:
            _append_jsonl(summary['type'], sp)
        _append_jsonl('trace', summary)
        try:
            delattr(_tl, 'trace')
        except AttributeError:
            pass
        return summary

    # -- span --------------------------------------------------------
    @contextmanager
    def span(self, span_type: str, name: str, **meta: Any) -> Iterator[dict]:
        """记录一个 span（上下文管理器）；trace 未开启时静默空转。"""
        tr = getattr(_tl, 'trace', None)
        if tr is None:
            yield {}
            return
        span_id = _span_id()
        parent_id = tr['stack'][-1] if tr['stack'] else ''
        record = {
            'span_id': span_id,
            'parent_id': parent_id,
            'trace_id': tr['trace_id'],
            'task_id': tr['task_id'],
            'type': span_type,
            'name': str(name)[:200],
            'ts': _now_iso(),
            't0': time.time(),
            'duration_ms': 0,
            'status': 'ok',
            'model': meta.pop('model', ''),
            'in_tokens': int(meta.pop('in_tokens', 0) or 0),
            'out_tokens': int(meta.pop('out_tokens', 0) or 0),
            'cost': float(meta.pop('cost', 0) or 0),
            'meta': meta,
        }
        tr['spans'].append(record)
        tr['stack'].append(span_id)
        try:
            yield record
        except Exception as exc:  # noqa: BLE001 span 内异常仍记录后上抛
            record['status'] = f'error:{type(exc).__name__}'
            raise
        finally:
            tr['stack'].pop()
            record['duration_ms'] = int((time.time() - record['t0']) * 1000)
            if record['in_tokens'] or record['out_tokens']:
                # 显式给了 tokens -> 按模型单价估算成本
                record['cost'] = round(
                    _heuristic_cost(record['model'], record['in_tokens'], record['out_tokens']), 6)

    # -- 写入 --------------------------------------------------------
    def flush_span(self, span_id: str, **fields: Any) -> None:
        """就地补充 span 字段（如流式结束后填 model/tokens）。"""
        tr = getattr(_tl, 'trace', None)
        if tr is None:
            return
        for sp in tr['spans']:
            if sp['span_id'] == span_id:
                for k, v in fields.items():
                    if k in ('model', 'in_tokens', 'out_tokens', 'cost', 'status', 'meta'):
                        sp[k] = v
                if sp.get('in_tokens') or sp.get('out_tokens'):
                    sp['cost'] = round(_heuristic_cost(sp.get('model', ''), sp['in_tokens'], sp['out_tokens']), 6)
                break


# ---------------- 落盘与查询 ----------------

def _append_jsonl(record_type: str, record: dict) -> None:
    """追加一条 JSONL 到当日文件。"""
    try:
        fname = _traces_dir() / f'traces-{datetime.now().strftime("%Y%m%d")}.jsonl'
        payload = {'type': record_type, 'ts': record.get('ts') or _now_iso(), **record}
        with open(fname, 'a', encoding='utf-8') as f:
            f.write(json.dumps(payload, ensure_ascii=False) + '\n')
    except Exception:  # noqa: BLE001 落盘失败静默
        pass


def _load_events(days: int = 7) -> list[dict]:
    """读取近 N 天 trace 文件中的事件。"""
    events: list[dict] = []
    base = _traces_dir()
    cutoff = (datetime.now().timestamp() - days * 86400)
    for path in sorted(base.glob('traces-*.jsonl')):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            continue
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
    return events


def query_trace(trace_id: str, days: int = 7) -> dict | None:
    """按 trace_id 还原 span 树（trace 头 + 全部 span）。"""
    events = [e for e in _load_events(days) if e.get('trace_id') == trace_id]
    if not events:
        return None
    head = next((e for e in events if e.get('type') == 'trace'), events[0])
    spans = [e for e in events if e.get('type') != 'trace']
    by_id = {s['span_id']: s for s in spans}
    roots, children = [], {}
    for s in spans:
        pid = s.get('parent_id')
        if pid and pid in by_id:
            children.setdefault(pid, []).append(s)
        else:
            roots.append(s)
    for s in spans:
        s['children'] = children.get(s['span_id'], [])
    return {'trace': head, 'spans': spans, 'roots': roots, 'count': len(spans)}


def query_task(task_id: int, days: int = 7) -> list[dict]:
    """按任务查全部 trace 摘要。"""
    return [e for e in _load_events(days)
            if e.get('type') == 'trace' and e.get('task_id') == task_id]


def aggregate(days: int = 7, span_type: str = '') -> dict:
    """聚合统计：span 数 / 总耗时 / 总成本 / 按类型分布 / 慢调用 Top。"""
    events = _load_events(days)
    spans = [e for e in events if e.get('type') != 'trace']
    if span_type:
        spans = [s for s in spans if s.get('type') == span_type]
    total_ms = sum(int(s.get('duration_ms') or 0) for s in spans)
    total_cost = round(sum(float(s.get('cost') or 0) for s in spans), 6)
    by_type: dict[str, int] = {}
    errors = 0
    for s in spans:
        by_type[s.get('type', '?')] = by_type.get(s.get('type', '?'), 0) + 1
        if str(s.get('status', '')).startswith('error'):
            errors += 1
    slow = sorted(spans, key=lambda s: int(s.get('duration_ms') or 0), reverse=True)[:10]
    return {
        'trace_count': len([e for e in events if e.get('type') == 'trace']),
        'span_count': len(spans),
        'total_ms': total_ms,
        'total_cost': total_cost,
        'errors': errors,
        'by_type': by_type,
        'slowest': [{'type': s.get('type'), 'name': s.get('name'), 'duration_ms': s.get('duration_ms'),
                     'status': s.get('status'), 'task_id': s.get('task_id')} for s in slow],
    }


# 模块级单例
_tracer: Tracer | None = None


def get_tracer() -> Tracer:
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer
