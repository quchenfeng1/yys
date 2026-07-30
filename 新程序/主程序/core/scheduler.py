"""
05-时间调度模块

Scheduler 调度引擎主入口（基于任务配置的调度器）。
对应设计书 §5.1/§5.2/§5.3/§5.4/§5.5。

职责：
- 从 tasks.yaml 加载任务配置（TaskConfig）
- 按 RepeatRule 类型计算 next_run_time（三重时间过滤）
- build_schedule() / get_next_task() / mark_done()
- 递增冷却 + 双模式熔断（fail_streak / unrecoverable）
- 活动日历导入 import_calendar()
- 状态持久化（原子写盘 task_state.json）
- 惰性每日重置 check_daily_reset()

设计原则：
- 纯调度职责：只回答"哪些任务已到期"，不关心执行
- 失败不推进 next_run_time，保持到期可重试
- 原子持久化：每次状态变更立即写盘
- 线程安全：_lock 保护 _next_run / _today_count
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from core.event_bus import EventBus, get_global_bus
from core.events import Events
from core.repeat_rule import RepeatRule
from core.task_state import TaskStateStore


# ── 时区 ─────────────────────────────────────────────────────
TZ_UTC8: tzinfo = timezone(timedelta(hours=8), "UTC+8")


# ═══════════════════════════════════════════════════════════════
#  数据结构（§5.2）
# ═══════════════════════════════════════════════════════════════

@dataclass
class RepeatConfig:
    """重复规则配置（§5.2 RepeatConfig）"""
    type: str = "daily"  # once/daily/weekly/monthly_start/interval_days/interval_hours/expire_at/special
    value: int | None = None  # interval_days=N / weekly weekday
    weekday: int | None = None  # weekly 专属 0=周一~6=周日
    window: dict | None = None  # special 专属 {date, start, end}
    expire_at: str | None = None  # expire_at 专属到期日期
    loop_count: int | None = None  # 战斗循环次数
    monthly_day: int = 1  # monthly_start 专属


@dataclass
class TaskConfig:
    """任务配置（§5.2 TaskConfig，从 tasks.yaml 加载）"""
    name: str
    display_name: str = ""
    enabled: bool = True
    category: str = "daily"  # daily/permanent/event/special
    priority: int = 10  # 1~99，越小越优先
    repeat: RepeatConfig | None = None
    max_daily: int | None = None
    max_fail_streak: int = 10
    active_range: list[str] | None = None  # ["2026-07-20", "2026-08-20"]
    time_start: str | None = None  # "08:00"
    time_end: str | None = None  # "23:00"
    team_id: str | None = None
    floor: int | None = None


class ScheduleStatus(str, Enum):
    """调度状态枚举（§5.2 ScheduleStatus）"""
    DUE = "due"             # 已到期，等待执行
    WAITING = "waiting"     # 未到期
    COMPLETED = "completed" # 今日已完成（已达 max_daily）
    SKIPPED = "skipped"     # 被跳过（熔断）


@dataclass
class TaskInfo:
    """日程条目（§5.2 TaskInfo — build_schedule/schedule_queue 返回值）"""
    name: str
    priority: int = 10
    category: str = "daily"
    next_run: datetime | None = None
    status: ScheduleStatus = ScheduleStatus.WAITING


@dataclass
class CalendarEvent:
    """活动日历事件（§5.2 CalendarEvent）"""
    name: str = ""
    start: str = ""          # 开始日期 "2026-07-20"
    end: str = ""            # 结束日期 "2026-08-20"
    window: dict | None = None  # 每日时间窗口 {start: "10:00", end: "12:00"}
    type: str = "special"    # 规则类型


# ═══════════════════════════════════════════════════════════════
#  Scheduler 调度引擎
# ═══════════════════════════════════════════════════════════════

class Scheduler:
    """任务调度引擎（§5.3 方法定义）"""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        config: Any = None,
        state_manager: Any = None,
        store: TaskStateStore | None = None,
    ):
        self._bus = event_bus or get_global_bus()
        self._config = config
        self._state_mgr = state_manager
        self._store = store

        # 线程安全（§2.3）
        self._lock = threading.Lock()

        # §2.3 内部属性
        self._tasks: dict[str, TaskConfig] = {}       # 任务名 → TaskConfig
        self._next_run: dict[str, datetime] = {}      # 任务名 → 下次执行时间
        self._today_count: dict[str, int] = {}        # 任务名 → 今日已执行次数
        self._last_daily_reset: date = date.today()   # 上次每日重置日期
        self._timezone: tzinfo = TZ_UTC8              # 默认 UTC+8

        # 运行时状态（§2.2 对外暴露）
        self.schedule_queue: list[TaskInfo] = []       # 对外只读的快照
        self.task_status: dict[str, ScheduleStatus] = {}  # 任务名 → 当前调度状态

    # ── 配置加载（§5.3）──────────────────────────────────────

    def load_tasks_from_config(self) -> None:
        """从 tasks.yaml 加载任务配置并注册（§5.3 + §5.4 异常恢复③④）"""
        if not self._config:
            return

        # 读取 tasks.yaml 中的任务列表
        raw_tasks = getattr(self._config, 'tasks_config', None)
        if not raw_tasks:
            return
        tasks_list = getattr(raw_tasks, 'tasks', []) if hasattr(raw_tasks, 'tasks') else raw_tasks

        for raw in tasks_list:
            name = getattr(raw, 'name', '') or getattr(raw, 'id', '')
            if not name:
                continue
            enabled = getattr(raw, 'enabled', True)
            if not enabled:
                continue

            # 构建 RepeatConfig
            repeat_raw = getattr(raw, 'repeat', None) or {}
            repeat = RepeatConfig(
                type=repeat_raw.get('type', 'daily') if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'type', 'daily'),
                value=repeat_raw.get('value') if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'value', None),
                weekday=repeat_raw.get('weekday') if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'weekday', None),
                window=repeat_raw.get('window') if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'window', None),
                expire_at=repeat_raw.get('expire_at') if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'expire_at', None),
                loop_count=repeat_raw.get('loop_count') if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'loop_count', None),
                monthly_day=repeat_raw.get('monthly_day', 1) if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'monthly_day', 1),
            )

            config = TaskConfig(
                name=name,
                display_name=getattr(raw, 'display_name', '') or name,
                enabled=enabled,
                category=getattr(raw, 'category', 'daily'),
                priority=getattr(raw, 'priority', 10),
                repeat=repeat,
                max_daily=getattr(raw, 'max_daily', None),
                max_fail_streak=getattr(raw, 'max_fail_streak', 10),
                active_range=getattr(raw, 'active_range', None),
                time_start=getattr(raw, 'time_start', None),
                time_end=getattr(raw, 'time_end', None),
                team_id=getattr(raw, 'team_id', None),
                floor=getattr(raw, 'floor', None),
            )

            with self._lock:
                self._tasks[name] = config
                # 从持久化恢复或计算初始 next_run_time（§5.4 异常恢复④）
                if self._store and name not in self._next_run:
                    stored = self._store.get(name)
                    if stored and stored.get('next_run_time'):
                        try:
                            self._next_run[name] = datetime.fromisoformat(stored['next_run_time'])
                        except (ValueError, TypeError):
                            self._next_run[name] = self._calc_initial_next_run(config)
                    else:
                        self._next_run[name] = self._calc_initial_next_run(config)
                elif name not in self._next_run:
                    self._next_run[name] = self._calc_initial_next_run(config)

                # today_count 从持久化恢复
                if self._store:
                    stored = self._store.get(name)
                    if stored and 'today_count' in stored:
                        self._today_count[name] = stored['today_count']
                    else:
                        self._today_count.setdefault(name, 0)
                else:
                    self._today_count.setdefault(name, 0)

    def _calc_initial_next_run(self, config: TaskConfig) -> datetime:
        """计算初始 next_run_time"""
        now = datetime.now(self._timezone)
        if config.repeat:
            rule = RepeatRule(
                type=config.repeat.type,
                interval=config.repeat.value or 1,
                time=config.time_start or "06:00",
                weekdays=[config.repeat.weekday] if config.repeat.weekday is not None else [],
                expire_date=config.repeat.expire_at or "",
            )
            return rule.get_initial_next_run(now)
        return now

    # ── 状态持久化（§5.3 + §4.3）────────────────────────────

    def load_state(self) -> None:
        """
        从 task_state.json 恢复执行记录（§5.3 + §3.6 异常恢复①②⑤）。

        恢复规则：
        - 文件不存在或损坏 → 初始化空状态 → 重新计算 next_run_time
        - skip_reason="fail_streak" → 自动调用 reset_fail_streak()
        - skip_reason="unrecoverable" → 保持 skipped（必须手动重置）
        - _last_daily_reset 初始化为 date.today()（防止重启后错误跨日重置）
        """
        if not self._store:
            return

        try:
            self._store.load()
        except (FileNotFoundError, json.JSONDecodeError):
            # §3.6 异常恢复①②：文件不存在或损坏 → 初始化空状态
            return

        now = datetime.now(self._timezone)

        for name, st in self._store.data.items():
            skip_reason = st.get('skip_reason') or ''
            if skip_reason == 'fail_streak':
                # 自动恢复 fail_streak 熔断（§4.2）
                self.reset_fail_streak(name)
            elif skip_reason == 'unrecoverable':
                # 不可恢复错误熔断，保持 skipped
                self.task_status[name] = ScheduleStatus.SKIPPED

            # 恢复 next_run_time
            nrt = st.get('next_run_time')
            if nrt:
                try:
                    self._next_run[name] = datetime.fromisoformat(nrt)
                except (ValueError, TypeError):
                    pass

            # 恢复 today_count
            tc = st.get('today_count', 0)
            self._today_count[name] = tc

        # _last_daily_reset 初始化为今天（§2.3 + §5.3 load_state 说明）
        self._last_daily_reset = date.today()

    def save_state(self) -> None:
        """原子写盘 task_state.json（§5.3 + §4.3）"""
        if not self._store:
            return

        now = datetime.now(self._timezone)
        data: dict[str, dict[str, Any]] = {}
        for name in self._tasks:
            task_status = self.task_status.get(name, ScheduleStatus.WAITING)
            nrt = self._next_run.get(name)
            # 从持久化存储读取真实 fail_streak/last_done/last_status/skip_reason
            stored = self._store.get(name) if self._store else None
            real_fail_streak = (stored or {}).get('fail_streak', 0) if stored else 0
            real_last_done = (stored or {}).get('last_done', '') if stored else ''
            real_last_status = (stored or {}).get('last_status', '') if stored else ''
            real_skip_reason = (stored or {}).get('skip_reason', '') if stored else ''
            data[name] = {
                "task_name": name,
                "next_run_time": nrt.isoformat() if nrt else "",
                "today_count": self._today_count.get(name, 0),
                "fail_streak": real_fail_streak,
                "last_done": real_last_done,
                "last_status": real_last_status,
                "skip_reason": real_skip_reason,
                "updated": now.isoformat(),
            }
            # 对 SKIPPED 状态确保 skip_reason 有值
            if task_status == ScheduleStatus.SKIPPED and not data[name]["skip_reason"]:
                data[name]["skip_reason"] = 'fail_streak'

        self._store.save(data)

    # ── 调度查询（§5.3 + §3.2）───────────────────────────────

    def build_schedule(self) -> list[TaskInfo]:
        """
        生成日程表（§3.2 + §5.3）。

        流程：
        ① 获取 _lock
        ②   check_daily_reset()（持锁，避免 DAILY_RESET 与 mark_done 交错）
        ③   遍历所有启用任务
        ④   对每个任务：is_due() + check_times_limit()
        ⑤   过滤 → 按 priority 升序 → 同优先级按 category 排序
        ⑥ 释放 _lock
        ⑦ 发布 SCHEDULE_UPDATED 事件（已无锁）
        ⑧ 返回排序后的 TaskInfo 列表
        """
        with self._lock:
            self.check_daily_reset()

            now = datetime.now(self._timezone)
            result: list[TaskInfo] = []

            for name, config in self._tasks.items():
                if not config.enabled:
                    continue

                # 熔断检查
                task_status = self.task_status.get(name)
                if task_status == ScheduleStatus.SKIPPED:
                    continue

                # 三重判据
                if not self.is_due(name, now):
                    status = ScheduleStatus.WAITING
                elif not self._check_times_limit(name):
                    status = ScheduleStatus.COMPLETED
                else:
                    status = ScheduleStatus.DUE

                self.task_status[name] = status

                if status == ScheduleStatus.DUE:
                    result.append(TaskInfo(
                        name=name,
                        priority=config.priority,
                        category=config.category,
                        next_run=self._next_run.get(name),
                        status=status,
                    ))

            # 按 priority 升序（1~99，越小越优先）→ 同优先级按 category 排序
            cat_order = {"daily": 0, "permanent": 1, "event": 2, "special": 3}
            result.sort(key=lambda x: (x.priority, cat_order.get(x.category, 99)))

        # 已无锁时发布事件
        self._bus.publish(Events.SCHEDULE_UPDATED, source="scheduler",
                          queue=[t.name for t in result])

        self.schedule_queue = result
        return result

    def get_next_task(self) -> str | None:
        """获取下一个到期任务名（§5.3 + §5.4）"""
        schedule = self.build_schedule()
        return schedule[0].name if schedule else None

    def get_all_tasks(self) -> list[TaskConfig]:
        """获取所有已注册任务的 TaskConfig（§5.3）"""
        return list(self._tasks.values())

    def get_next_run_time(self, task_name: str) -> datetime | None:
        """查询任务的 next_run_time（§5.3）"""
        return self._next_run.get(task_name)

    # ── 到期判据（§3.1 + §5.3）──────────────────────────────

    def is_due(self, task_name: str, now: datetime | None = None) -> bool:
        """
        三重到期判据（§3.1）。

        任务可执行需同时满足：
        ① 时间已到：当前时间 ≥ next_run_time
        ② 在每日时间窗口内：time_start ~ time_end
        ③ 在活动有效期内：active_range
        """
        now = now or datetime.now(self._timezone)

        # ① next_run_time
        nrt = self._next_run.get(task_name)
        if nrt is None:
            return False
        if now < nrt:
            return False

        config = self._tasks.get(task_name)
        if not config:
            return False

        # ② 每日时间窗口
        if config.time_start or config.time_end:
            current_time = now.strftime("%H:%M")
            if config.time_start and current_time < config.time_start:
                return False
            if config.time_end and current_time > config.time_end:
                return False

        # ③ 活动有效期
        if config.active_range:
            today_str = now.strftime("%Y-%m-%d")
            start_date = config.active_range[0] if len(config.active_range) > 0 else None
            end_date = config.active_range[1] if len(config.active_range) > 1 else None
            if start_date and today_str < start_date:
                return False
            if end_date and today_str > end_date:
                return False

        return True

    def check_times_limit(self, task_name: str) -> bool:
        """检查任务是否未达每日次数上限（§5.3）"""
        config = self._tasks.get(task_name)
        if not config or config.max_daily is None:
            return True
        return self._today_count.get(task_name, 0) < config.max_daily

    # 内部别名
    _check_times_limit = check_times_limit

    # ── 执行反馈（§3.3 + §5.3）──────────────────────────────

    def mark_done(self, task_name: str, success: bool) -> None:
        """
        标记任务完成（§3.3 + §5.4）。

        success=True:
          fail_streak 归零 → 按 RepeatRule.type 推进 next_run_time → today_count += 1

        success=False:
          fail_streak += 1 → 超阈值则熔断 skipped → 否则递增冷却（不推进原时间）
        """
        config = self._tasks.get(task_name)
        if not config:
            return

        with self._lock:
            if success:
                # 成功：归零 fail_streak
                # 从持久化中清除 skip_reason
                if self._store:
                    stored = self._store.get(task_name) or {}
                    stored.pop('skip_reason', None)

                # 按 RepeatRule 推进 next_run_time
                if config.repeat:
                    rule = RepeatRule(
                        type=config.repeat.type,
                        interval=config.repeat.value or 1,
                        time=config.time_start or "06:00",
                        weekdays=[config.repeat.weekday] if config.repeat.weekday is not None else [],
                        expire_date=config.repeat.expire_at or "",
                    )

                    last_run = self._next_run.get(task_name) or datetime.now(self._timezone)
                    next_time = rule.calc_next_run(last_run)

                    if next_time == datetime.max:
                        # once 类型或已过期 → 标记 completed
                        self.task_status[task_name] = ScheduleStatus.COMPLETED
                        self._next_run.pop(task_name, None)
                    else:
                        self._next_run[task_name] = next_time
                        self.task_status[task_name] = ScheduleStatus.WAITING
                else:
                    # 无 repeat 配置 → 默认 daily
                    next_time = datetime.now(self._timezone) + timedelta(days=1)
                    self._next_run[task_name] = next_time

                self._today_count[task_name] = self._today_count.get(task_name, 0) + 1
                # 已达每日上限则标记 completed，否则 waiting
                if config.max_daily and self._today_count.get(task_name, 0) >= config.max_daily:
                    self.task_status[task_name] = ScheduleStatus.COMPLETED
                else:
                    self.task_status[task_name] = ScheduleStatus.WAITING

            else:
                # 失败：递增 fail_streak
                stored = self._store.get(task_name) if self._store else {}
                fail_streak = (stored or {}).get('fail_streak', 0) + 1
                if self._store:
                    self._store.update(task_name, fail_streak=fail_streak)

                max_fail = config.max_fail_streak
                if fail_streak >= max_fail:
                    # §4.2 熔断
                    self.task_status[task_name] = ScheduleStatus.SKIPPED
                    if self._store:
                        self._store.update(task_name,
                                          skip_reason='fail_streak',
                                          status='skipped')
                    self._bus.publish(Events.TASK_SKIPPED, source="scheduler",
                                     task_name=task_name, reason="连续失败熔断",
                                     fail_streak=fail_streak, max_fail_streak=max_fail)
                else:
                    # 递增冷却：fail_streak × 5min ≤ 60min（不推进原 next_run_time）
                    cool_seconds = min(fail_streak * 300, 3600)
                    next_time = datetime.now(self._timezone) + timedelta(seconds=cool_seconds)
                    self._next_run[task_name] = next_time
                    self.task_status[task_name] = ScheduleStatus.WAITING

        # 持锁外持久化 + 发布事件
        self.save_state()
        self._bus.publish(Events.SCHEDULE_UPDATED, source="scheduler",
                         task=task_name, success=success)

    # ── 每日重置（§3.4 + §5.3）──────────────────────────────

    def check_daily_reset(self) -> None:
        """
        惰性检查跨日重置（§3.4 + §5.3 check_daily_reset）。

        在 build_schedule() 持锁时调用，确保 DAILY_RESET 事件不会与 mark_done 交错。
        """
        today = date.today()
        if today > self._last_daily_reset:
            # 所有任务 today_count = 0
            for name in self._today_count:
                self._today_count[name] = 0
            self._last_daily_reset = today
            self._bus.publish(Events.DAILY_RESET, source="scheduler", date=str(today))

    def reset_daily_counters(self) -> None:
        """每日重置 today_count（§5.3，供外部直接调用）"""
        with self._lock:
            for name in self._today_count:
                self._today_count[name] = 0
            self._last_daily_reset = date.today()

    # ── 熔断恢复（§4.2 + §5.3）──────────────────────────────

    def report_expire(self, task_name: str) -> None:
        """
        报告任务到期（§5.3 report_expire）。
        expire_at 类型专用。标记为 completed，不再调度。
        """
        with self._lock:
            self.task_status[task_name] = ScheduleStatus.COMPLETED
            self._next_run.pop(task_name, None)
        self.save_state()

    def reset_fail_streak(self, task_name: str) -> None:
        """
        重置失败计数（§5.3 reset_fail_streak）。
        清除 skipped 状态，恢复调度。
        """
        with self._lock:
            if task_name in self.task_status:
                self.task_status[task_name] = ScheduleStatus.WAITING
            config = self._tasks.get(task_name)
            if config and not self._next_run.get(task_name):
                self._next_run[task_name] = self._calc_initial_next_run(config)
        if self._store:
            self._store.update(task_name, fail_streak=0, skip_reason='')
        self.save_state()

    # ── 手动设置（§5.3）─────────────────────────────────────

    def update_next_run(self, task_name: str, next_run_time: datetime) -> None:
        """手动设置 next_run_time"""
        with self._lock:
            self._next_run[task_name] = next_run_time
        self.save_state()

    # ── 活动日历导入（§3.5 + §5.3）─────────────────────────

    def import_calendar(self, events: list[dict]) -> tuple[int, int]:
        """
        导入活动日历（§3.5 + §5.3）。

        Args:
            events: CalendarEvent 列表，每项含
                name/start/end/window/type

        Returns: (更新数, 新建数)
        """
        updated = 0
        created = 0

        with self._lock:
            for evt in events:
                name = evt.get('name', '')
                if not name:
                    continue

                if name in self._tasks:
                    # 更新现有任务的 active_range / window
                    config = self._tasks[name]
                    config.active_range = [evt.get('start', ''), evt.get('end', '')]
                    if evt.get('window'):
                        if config.repeat:
                            config.repeat.window = evt['window']
                    updated += 1
                else:
                    # 新建 special 类型任务
                    repeat = RepeatConfig(
                        type=evt.get('type', 'special'),
                        window=evt.get('window'),
                    )
                    config = TaskConfig(
                        name=name,
                        display_name=evt.get('display_name', name),
                        category='event',
                        repeat=repeat,
                        active_range=[evt.get('start', ''), evt.get('end', '')] if evt.get('start') else None,
                    )
                    self._tasks[name] = config
                    self._next_run[name] = self._calc_initial_next_run(config)
                    self._today_count[name] = 0
                    created += 1

        if updated or created:
            self.save_state()
            self._bus.publish(Events.SCHEDULE_UPDATED, source="scheduler",
                             imported_updated=updated, imported_created=created)

        return (updated, created)

    # ── 工具 ──────────────────────────────────────────────────

    def clear(self) -> None:
        with self._lock:
            self._tasks.clear()
            self._next_run.clear()
            self._today_count.clear()
            self.schedule_queue.clear()
            self.task_status.clear()



