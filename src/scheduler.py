# -*- coding: utf-8 -*-
"""H2 自然语言定时任务调度器（零新增依赖，对齐 Hermes 内置调度器）。

能力：
- `parse_nl(text)`：自然语言 -> cron_desc（"每天9点" -> "daily 09:00"）
- `next_run_at(cron_desc, from_ts)`：计算下次执行时刻（本地时区）
- `ScheduleManager`：add / list / pause / resume / remove / tick（到期触发）
- `start_scheduler()`：后台守护线程（每 30s 扫描一次，桌面常驻时生效）

cron_desc 四类（与 0006_task_schedule.sql 注释一致）：
- `daily HH:MM`      每天固定时刻（如 "daily 09:00"）
- `weekly W HH:MM`   每周星期 W 固定时刻（W=0..6，周一=0）
- `hourly MM`        每小时的 MM 分（如 "hourly 00"）
- `interval N`       每 N 分钟（如 "interval 30"）

边界说明：与 IDE 层 automation 解耦——本调度器是应用内独立表，仅在应用进程运行时生效，
适合桌面常驻 / 打包 EXE 场景；不依赖任何外部服务。
"""
from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta

from .core.db import get_conn

_TICK_INTERVAL_S = 30          # 后台扫描周期
_REENTRY_GUARD_S = 60          # 同任务两次触发最小间隔（防 tick 重入）
_WEEKDAY_CN = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6}
_WEEKDAY_EN = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}
_TS_FMT = '%Y-%m-%dT%H:%M:%S'


# ---------------- 自然语言 -> cron_desc ----------------

def parse_nl(text: str) -> tuple[bool, str, str]:
    """解析自然语言为 cron_desc；失败返回 (False, '', 原因)。

    支持（示例）：
    - 每天9点 / 每日上午10:30    -> daily 09:00 / daily 10:30
    - 每周一10:30 / 每周五晚上8点 -> weekly 0 10:30 / weekly 4 20:00
    - 每小时 / 每小时整点        -> hourly 00
    - 每30分钟 / 每隔5分钟       -> interval 30 / interval 5
    - 兜底（含"每天"但不含时刻）  -> daily 09:00（歧义默认每天，方案 §五）
    """
    if not text or not text.strip():
        return False, '', '描述为空'
    t = re.sub(r'\s+', '', text.strip().lower())

    # ---- 每 N 分钟 / 每隔 N 分钟 ----
    m = re.search(r'每(?:隔)?(\d{1,3})分钟', t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 1440:
            return True, f'interval {n}', f'每{n}分钟'
        return False, '', f'间隔分钟数 {n} 超出支持范围(1-1440)'

    # ---- 每小时 ----
    if '每小时' in t or '每个小时' in t:
        mm = _extract_minute(t)
        return True, f'hourly {mm:02d}', f'每小时第{mm}分'
    if t == '每小时整点' or '每整点' in t:
        return True, 'hourly 00', '每小时整点'

    # ---- 每周 X HH:MM（支持 10:30 冒号与 早上/晚上 等时段修饰词）----
    if '每周' in t or '每个周' in t:
        m = re.search(r'每周([一二三四五六日天]|[a-z]{3})'
                      r'(早上|上午|中午|下午|晚上|傍晚|凌晨)?'
                      r'\s*(\d{1,2})[点时:](\d{1,2})?分?', t)
        if not m:
            # 提取"每周"后首字预检，给出明确星期错误
            w0 = re.search(r'每周(.)', t)
            if w0 and _weekday_num(w0.group(1)) is None:
                return False, '', f'无法识别星期: {w0.group(1)}'
            return False, '', '无法识别周描述（示例：每周一10:30）'
        w = _weekday_num(m.group(1))
        hh, mm = _normalize_hhmm(_adjust_hour(int(m.group(3)), m.group(2)),
                                 int(m.group(4) or 0))
        if hh is None:
            return False, '', f'小时 {int(m.group(3))} 超出 0-23'
        return True, f'weekly {w} {hh:02d}:{mm:02d}', f'每周{_weekday_cn(w)} {hh:02d}:{mm:02d}'

    # ---- 每天/每日 HH:MM（支持 10:30 冒号与时段修饰词）----
    m = re.search(r'(?:每天|每日)'
                  r'(早上|上午|中午|下午|晚上|傍晚|凌晨)?'
                  r'\s*(\d{1,2})[点时:](\d{1,2})?分?', t)
    if m:
        hh, mm = _normalize_hhmm(_adjust_hour(int(m.group(2)), m.group(1)),
                                 int(m.group(3) or 0))
        if hh is None:
            return False, '', f'小时 {int(m.group(2))} 超出 0-23'
        return True, f'daily {hh:02d}:{mm:02d}', f'每天 {hh:02d}:{mm:02d}'

    # ---- 仅"每天/每日"（无时刻）-> 兜底每天 09:00 ----
    if '每天' in t or '每日' in t:
        return True, 'daily 09:00', '每天 09:00（未指定时刻，默认早9点）'

    return False, '', '无法识别时间描述（支持：每天9点 / 每周一10:30 / 每小时 / 每30分钟）'


def _weekday_num(word: str) -> int | None:
    if word in _WEEKDAY_CN:
        return _WEEKDAY_CN[word]
    return _WEEKDAY_EN.get(word)


def _weekday_cn(w: int) -> str:
    for k, v in _WEEKDAY_CN.items():
        if v == w and k != '天':
            return k
    return '日'


def _extract_minute(text: str) -> int:
    """从文本提取分钟（每小时XX分）；缺省整点。"""
    m = re.search(r'(\d{1,2})分', text)
    return int(m.group(1)) if m and 0 <= int(m.group(1)) <= 59 else 0


def _normalize_hhmm(hh: int, mm: int) -> tuple[int | None, int]:
    if not 0 <= hh <= 23:
        return None, 0
    if mm < 0 or mm > 59:
        mm = 0
    return hh, mm


def _adjust_hour(hh: int, period: str | None) -> int:
    """时段修饰词转 24 小时制：下午/晚上/傍晚 -> +12（12点视为午夜0点）。"""
    if not period:
        return hh
    if period in ('下午', '晚上', '傍晚'):
        if hh == 12:
            return 0   # 晚上12点 = 次日凌晨
        if hh < 12:
            return hh + 12
    return hh


# ---------------- cron_desc -> 下次执行时刻 ----------------

def _parse_cron(cron_desc: str) -> tuple[str, Any]:
    """解析 cron_desc -> (kind, params)；非法返回 ('', None)。"""
    if not cron_desc:
        return '', None
    parts = cron_desc.strip().split()
    kind = parts[0]
    try:
        if kind == 'daily' and len(parts) == 2:
            hh, mm = (int(x) for x in parts[1].split(':'))
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                return 'daily', (hh, mm)
        if kind == 'weekly' and len(parts) == 3:
            w = int(parts[1])
            hh, mm = (int(x) for x in parts[2].split(':'))
            if 0 <= w <= 6 and 0 <= hh <= 23 and 0 <= mm <= 59:
                return 'weekly', (w, hh, mm)
        if kind == 'hourly' and len(parts) == 2:
            mm = int(parts[1])
            if 0 <= mm <= 59:
                return 'hourly', (mm,)
        if kind == 'interval' and len(parts) == 2:
            n = int(parts[1])
            if 1 <= n <= 1440:
                return 'interval', (n,)
    except (ValueError, IndexError):
        pass
    return '', None


def next_run_at(cron_desc: str, from_ts: datetime) -> datetime | None:
    """计算 cron_desc 在 from_ts 之后的最近执行时刻（本地时间）；非法返回 None。"""
    kind, params = _parse_cron(cron_desc)
    if kind == '':
        return None
    if kind == 'daily':
        hh, mm = params
        cand = from_ts.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if cand <= from_ts:
            cand += timedelta(days=1)
        return cand
    if kind == 'weekly':
        w, hh, mm = params
        days_ahead = (w - from_ts.weekday()) % 7
        cand = (from_ts + timedelta(days=days_ahead)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if cand <= from_ts:
            cand += timedelta(days=7)
        return cand
    if kind == 'hourly':
        mm = params[0]
        cand = from_ts.replace(minute=mm, second=0, microsecond=0)
        if cand <= from_ts:
            cand += timedelta(hours=1)
        return cand
    if kind == 'interval':
        return from_ts + timedelta(minutes=params[0])
    return None


# ---------------- 调度管理器 ----------------

class ScheduleManager:
    """task_schedule 表的管理与到期触发。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # -- 读 -----------------------------------------------------------
    def list(self, enabled_only: bool = False) -> list[dict]:
        sql = ('SELECT id,title,cron_desc,prompt,mode,enabled,next_run,last_run,last_status,'
               'notepad,continuity,last_summary,created_at,updated_at FROM task_schedule')
        if enabled_only:
            sql += ' WHERE enabled=1'
        sql += ' ORDER BY id DESC'
        return [dict(r) for r in get_conn().execute(sql).fetchall()]

    def _get(self, sid: int) -> dict | None:
        row = get_conn().execute(
            'SELECT * FROM task_schedule WHERE id=?', (sid,)).fetchone()
        return dict(row) if row else None

    # -- H3 Cron 记忆（对齐 Hermes cron memory） --------------------------
    def set_continuity(self, sid: int, on: bool) -> dict:
        """开启/关闭 continuity：下次 run 是否注入上次运行摘要（默认开）。"""
        task = self._get(sid)
        if not task:
            return {'ok': False, 'error': f'调度任务不存在: {sid}'}
        conn = get_conn()
        with self._lock:
            conn.execute(
                "UPDATE task_schedule SET continuity=?, updated_at=datetime('now','localtime')"
                ' WHERE id=?', (1 if on else 0, sid))
            conn.commit()
        return {'ok': True, 'id': sid, 'continuity': bool(on)}

    def set_notepad(self, sid: int, text: str) -> dict:
        """写 job 级持久草稿本（跨 run 保留，供 Agent 经 schedule_task 工具维护）。"""
        task = self._get(sid)
        if not task:
            return {'ok': False, 'error': f'调度任务不存在: {sid}'}
        conn = get_conn()
        with self._lock:
            conn.execute(
                "UPDATE task_schedule SET notepad=?, updated_at=datetime('now','localtime')"
                ' WHERE id=?', (str(text or '')[:8000], sid))
            conn.commit()
        return {'ok': True, 'id': sid, 'notepad': str(text or '')[:8000]}

    def get_notepad(self, sid: int) -> dict:
        task = self._get(sid)
        if not task:
            return {'ok': False, 'error': f'调度任务不存在: {sid}'}
        return {'ok': True, 'id': sid, 'notepad': task.get('notepad') or ''}

    def set_last_summary(self, sid: int, summary: str) -> dict:
        """写本次运行输出摘要（供下次 continuity 注入 / monitor 去重）。"""
        conn = get_conn()
        with self._lock:
            conn.execute(
                "UPDATE task_schedule SET last_summary=?, updated_at=datetime('now','localtime')"
                ' WHERE id=?', (str(summary or '')[:4000], sid))
            conn.commit()
        return {'ok': True, 'id': sid}

    # -- 写 -----------------------------------------------------------
    def add(self, title: str, cron_desc: str, prompt: str = '',
            mode: str = 'craft', enabled: bool = True) -> dict:
        """新增调度任务：cron_desc 显式传入优先，否则从自然语言 title 解析。"""
        if cron_desc:
            desc, human = cron_desc.strip(), cron_desc.strip()
        else:
            ok, desc, human = parse_nl(title)
            if not ok:
                return {'ok': False, 'error': human}
        nxt = next_run_at(desc, datetime.now())
        if nxt is None:
            return {'ok': False, 'error': f'非法 cron 描述：{desc}'}
        now = datetime.now().strftime(_TS_FMT)
        conn = get_conn()
        with self._lock:
            cur = conn.execute(
                'INSERT INTO task_schedule(title,cron_desc,prompt,mode,enabled,next_run,created_at)'
                ' VALUES(?,?,?,?,?,?,?)',
                (title, desc, prompt or '', mode or 'craft', 1 if enabled else 0,
                 nxt.strftime(_TS_FMT), now))
            conn.commit()
        return {'ok': True, 'id': cur.lastrowid, 'cron_desc': desc,
                'next_run': nxt.strftime(_TS_FMT), 'human': human}

    def pause(self, sid: int) -> dict:
        return self._set_enabled(sid, 0)

    def resume(self, sid: int) -> dict:
        return self._set_enabled(sid, 1)

    def remove(self, sid: int) -> dict:
        conn = get_conn()
        with self._lock:
            cur = conn.execute('DELETE FROM task_schedule WHERE id=?', (sid,))
            conn.commit()
        return {'ok': bool(cur.rowcount), 'id': sid}

    def _set_enabled(self, sid: int, enabled: int) -> dict:
        task = self._get(sid)
        if not task:
            return {'ok': False, 'error': f'调度任务不存在: {sid}'}
        now = datetime.now()
        nxt = task.get('next_run')
        if enabled and (not nxt or nxt <= now.strftime(_TS_FMT)):
            nxt = next_run_at(task['cron_desc'], now)
            nxt_s = nxt.strftime(_TS_FMT) if nxt else None
        else:
            nxt_s = nxt
        conn = get_conn()
        with self._lock:
            conn.execute(
                'UPDATE task_schedule SET enabled=?, next_run=?, updated_at=? WHERE id=?',
                (enabled, nxt_s, now.strftime(_TS_FMT), sid))
            conn.commit()
        return {'ok': True, 'id': sid, 'enabled': enabled, 'next_run': nxt_s}

    # -- 到期触发 -------------------------------------------------------
    def tick(self) -> list[dict]:
        """扫描到期任务：为每个到期任务建任务并后台触发 agent，原子推进 next_run。"""
        now = datetime.now()
        fired: list[dict] = []
        conn = get_conn()
        rows = conn.execute(
            'SELECT * FROM task_schedule WHERE enabled=1 AND next_run IS NOT NULL'
            ' AND next_run <= ?', (now.strftime(_TS_FMT),)).fetchall()
        for row in rows:
            task = dict(row)
            # 防重入：上次触发距今 < _REENTRY_GUARD_S 则跳过
            last = task.get('last_run')
            if last:
                try:
                    last_dt = datetime.strptime(last, _TS_FMT)
                    if (now - last_dt).total_seconds() < _REENTRY_GUARD_S:
                        continue
                except ValueError:
                    pass
            nxt = next_run_at(task['cron_desc'], now)
            if nxt is None:
                continue
            with self._lock:
                conn.execute(
                    'UPDATE task_schedule SET last_run=?, next_run=?, updated_at=? WHERE id=?',
                    (now.strftime(_TS_FMT), nxt.strftime(_TS_FMT), now.strftime(_TS_FMT), task['id']))
                conn.commit()
            fired.append({'id': task['id'], 'title': task['title'], 'prompt': task['prompt'],
                          'mode': task['mode'], 'next_run': nxt.strftime(_TS_FMT),
                          # H3：携带记忆字段供 _trigger_task 注入/回写
                          'continuity': bool(task.get('continuity', 1)),
                          'last_summary': task.get('last_summary') or '',
                          'notepad': task.get('notepad') or ''})
        for item in fired:
            _trigger_task(item)
        return fired


# ---------------- 触发执行 ----------------

def _continuity_messages(item: dict) -> list[tuple[str, str]]:
    """H3：根据调度 item 生成待注入的 system 消息列表 [(role, content)]。

    纯函数（不依赖 DB），便于单测：
    - continuity=1 且 last_summary 非空 → 注入「上次运行摘要」；
    - notepad 非空 → 注入「调度任务草稿本」。
    """
    out: list[tuple[str, str]] = []
    if item.get('continuity') and item.get('last_summary'):
        out.append(('system',
                    '【上次运行摘要（连续性参考，供去重/汇报"变化"）】\n'
                    + str(item['last_summary'])[:800]))
    if item.get('notepad'):
        out.append(('system',
                    '【调度任务草稿本（跨 run 保留，可更新）】\n'
                    + str(item['notepad'])[:800]))
    return out


def _trigger_task(item: dict) -> None:
    """后台线程：创建任务 + Agent 执行 prompt（复用 create_task + 首条消息）。

    H3 Cron 记忆（对齐 Hermes cron memory）：
    - continuity=1 且上次有 last_summary → 任务首条 system 消息注入「上次运行摘要」，
      让 Agent 跨 run 有连续性（可说"较上次变化/已处理项不重复"）；
    - notepad（job 草稿本）一并注入，供 Agent 读取上次上下文；
    - 运行结束后把本次消息末尾（assistant 末段）摘要回写 last_summary。
    """
    def _run() -> None:
        status = 'ok'
        tid = None  # noqa: F841 任务 id（H3 摘要回写用；异常路径可能未赋值）
        try:
            from src.core import db_v12 as v12_db  # S2-M6：数据层统一

            tid = v12_db.create_task(item['title'], item.get('mode') or 'craft')
            # H3：continuity 注入（上次运行摘要 + notepad）
            try:
                for _role, _content in _continuity_messages(item):
                    v12_db.add_message(tid, _role, _content)
            except Exception:  # noqa: BLE001 记忆注入失败不影响主流程
                pass
            prov = v12_db.get_active_provider()
            if not prov:
                status = 'no_provider'
            else:
                from agent_core import Agent

                agent = Agent(tid, prov, item.get('mode') or 'craft')
                for _ev in agent.run(item['prompt'] or item['title']):
                    pass  # 消费 SSE 事件流（输出已落库，含 M5 摘要）
        except Exception as exc:  # noqa: BLE001 调度边界统一兜底
            status = f'error:{type(exc).__name__}'
        try:
            from .core.db import get_conn as _gc
            # H3：运行后回写本次摘要（取任务消息中最近 assistant 回复尾部）
            try:
                _rows = _gc().execute(
                    'SELECT content FROM messages WHERE task_id=? AND role=?'
                    ' ORDER BY id DESC LIMIT 1', (tid, 'assistant')).fetchall()
                _sum = (_rows[0]['content'] or '') if _rows else ''
                if _sum:
                    ScheduleManager().set_last_summary(item['id'],
                                                       _sum[:800] + ('…' if len(_sum) > 800 else ''))
            except Exception:  # noqa: BLE001
                pass
            _gc().execute(
                'UPDATE task_schedule SET last_status=?, updated_at=? WHERE id=?',
                (status[:80], datetime.now().strftime(_TS_FMT), item['id']))
            _gc().commit()
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_run, daemon=True).start()


# ---------------- 后台守护线程 ----------------

def start_scheduler() -> threading.Thread:
    """启动后台扫描线程（幂等）。返回线程对象。"""
    manager = ScheduleManager()
    stop_evt = threading.Event()

    def _loop() -> None:
        while not stop_evt.is_set():
            try:
                manager.tick()
            except Exception:  # noqa: BLE001 调度循环永不因单次异常退出
                pass
            stop_evt.wait(_TICK_INTERVAL_S)

    th = threading.Thread(target=_loop, name='ea-scheduler', daemon=True)
    th.start()
    return th
