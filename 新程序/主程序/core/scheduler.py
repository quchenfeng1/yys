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
from datetime import datetime, timedelta, timezone, tzinfo
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
    type: str = "daily"  # once/daily/weekly/monthly_start/interval_days/interval_hours/on_enter/trigger（special/expire_at 已从 UI 移除，代码保留兼容旧配置）
    value: int | None = None  # interval_days=N / interval_hours=N
    weekday: int | None = None  # weekly 专属 0=周一~6=周日（旧字段，单值）
    weekdays: list[int] | None = None  # weekly 专属多选（新）：每周几执行，如 [2,5]=周三、周六
    window: dict | None = None  # 日历导入兼容（活动日历 window→active_range 映射），调度不读取
    expire_at: str | None = None  # 兼容旧配置（expire_at 已弃用）：到期日期，到期后不再调度
    loop_count: int | None = None  # 战斗循环次数（周期任务=周期内总轮次）
    monthly_day: int = 1  # monthly_start 专属
    total_count: int | None = None  # 活动循环次数：循环体循环次数上限（每轮循环成功 +1，达到→失效，None=不限）
    trigger_templates: list[str] | None = None  # trigger 专属：触发模板识别列表（02-TriggerWatcher 监控）
    trigger_max_count: int | None = None  # 旧字段（已废弃）：触发上限统一走 max_daily，仅作兼容读取


@dataclass
class TaskConfig:
    """任务配置（§5.2 TaskConfig，从 tasks.yaml 加载）"""
    name: str
    display_name: str = ""
    enabled: bool = True
    category: str = "daily"  # daily/permanent/event/special
    priority: int = 10  # 1~99，越小越优先
    repeat: RepeatConfig | None = None
    execution_mode: str = "daily"  # 执行模式：daily=按天执行一次 / per_slot=每时间段各执行一次（设计书 §5.2）
    max_daily: int | None = None  # 周期触发次数：活动周期内任务被触发的次数上限（达到→失效，None=不限）
    max_fail_streak: int = 10
    active_range: list[str] | None = None  # ["2026-07-20", "2026-08-20"]
    time_start: str | None = None  # "08:00"（单时段；与 time_slots 互斥）
    time_end: str | None = None  # "23:00"（单时段；与 time_slots 互斥）
    time_slots: list[list[str]] | None = None  # 多时段 [["10:00","12:00"],["12:00","14:00"]]，2+ 时段时优先
    team_id: str | None = None
    floor: int | None = None
    total_count: int | None = None  # 活动循环次数：循环体循环次数上限（每轮循环成功 +1，达到→失效）
    # ── 任务图片映射（§5.2）：{逻辑名: 素材路径} ──────────
    # 任务代码引用逻辑名（如 click_image("btn.start")），
    # 运行时经 Executor.set_asset_aliases 解析为素材路径；未配置时逻辑名即素材名
    images: dict | None = None
    # ── 组队配置（§3.10 组队协调）：大号带小号刷副本 ──────
    # 格式: {"group": "组队分组"} 或 {"sub_ids": ["sub1", "sub2"]}
    # 或 {"sub_ids": [...]}（主号带队；轮数复用 repeat.loop_count / 顶层 loop_count）
    teaming: dict | None = None
    # ── 战斗配置（UI「战斗配置」Tab 保存，透传给执行层）──
    soul_setup: dict | None = None      # 御魂套装 {group, team, position}
    lock_team: bool = False             # 战前准备：锁定队伍
    change_team: bool = False           # 战前准备：更换队伍
    stamina_required: int | None = None # 体力门槛（0=不检查）


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
        self._event_bus = event_bus or get_global_bus()
        self._bus = self._event_bus  # 兼容别名
        self._config = config
        self._state_manager = state_manager
        self._state_mgr = self._state_manager  # 兼容别名
        self._store = store

        # 线程安全（§2.3）
        self._lock = threading.Lock()

        # §2.3 内部属性
        self._tasks: dict[str, TaskConfig] = {}       # 任务名 → TaskConfig
        self._next_run: dict[str, datetime] = {}      # 任务名 → 下次执行时间
        self._defer_reasons: dict[str, str] = {}      # 任务名 → 异常推迟原因（UI 标注）
        self._today_count: dict[str, int] = {}        # 任务名 → 周期触发累计次数（mark_done 成功 +1，达到 max_daily→失效，不按天重置）
        self._total_count: dict[str, int] = {}        # 任务名 → 活动循环累计次数（record_cycle 每轮循环 +1，达到 total_count→失效）
        self._timezone: tzinfo = TZ_UTC8              # 默认 UTC+8

        # 运行时状态（§2.2 对外暴露）
        self.schedule_queue: list[TaskInfo] = []       # 对外只读的快照
        self.task_status: dict[str, ScheduleStatus] = {}  # 任务名 → 当前调度状态

        # 到期日志去重（build_schedule 结果变化时才打印，避免刷屏）
        self._last_due_names: tuple[str, ...] | None = None

        # 配置变更 → 热重载任务（保存后立即生效）
        self._bus.subscribe(Events.CONFIG_CHANGED, self._on_config_changed)
        # 触发式任务：02-TriggerWatcher 识别命中触发模板 → 置为到期（§3.1 trigger 例外）
        self._bus.subscribe(Events.TRIGGER_DETECTED, self._on_trigger_detected)

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
            # 每轮循环：repeat.loop_count 优先，顶层 loop_count 兜底（UI 表单保存到顶层）
            _rep_loop = (repeat_raw.get('loop_count') if isinstance(repeat_raw, dict)
                         else getattr(repeat_raw, 'loop_count', None))
            _top_loop = getattr(raw, 'loop_count', None)
            repeat = RepeatConfig(
                type=repeat_raw.get('type', 'daily') if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'type', 'daily'),
                value=repeat_raw.get('value') if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'value', None),
                weekday=repeat_raw.get('weekday') if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'weekday', None),
                weekdays=repeat_raw.get('weekdays') if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'weekdays', None),
                window=repeat_raw.get('window') if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'window', None),
                expire_at=repeat_raw.get('expire_at') if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'expire_at', None),
                loop_count=_rep_loop if _rep_loop is not None else _top_loop,
                monthly_day=repeat_raw.get('monthly_day', 1) if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'monthly_day', 1),
                total_count=repeat_raw.get('total_count') if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'total_count', None),
                trigger_templates=repeat_raw.get('trigger_templates') if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'trigger_templates', None),
                trigger_max_count=repeat_raw.get('trigger_max_count') if isinstance(repeat_raw, dict) else getattr(repeat_raw, 'trigger_max_count', None),
            )

            # 执行模式：execution_mode（daily/per_slot），兼容旧 execution_rule
            execution_mode = getattr(raw, 'execution_mode', None)
            if execution_mode not in ('daily', 'per_slot'):
                # 旧字段迁移：execution_rule count>1 → per_slot，否则 daily
                _er = getattr(raw, 'execution_rule', None) or {}
                _er_val = (_er.get('value') if isinstance(_er, dict)
                           else getattr(_er, 'value', None)) or 1
                execution_mode = 'per_slot' if _er_val > 1 else 'daily'

            config = TaskConfig(
                name=name,
                display_name=getattr(raw, 'display_name', '') or name,
                enabled=enabled,
                category=getattr(raw, 'category', 'daily'),
                priority=getattr(raw, 'priority', 10),
                repeat=repeat,
                execution_mode=execution_mode,
                max_daily=getattr(raw, 'max_daily', None),
                max_fail_streak=getattr(raw, 'max_fail_streak', 10),
                active_range=getattr(raw, 'active_range', None),
                time_start=getattr(raw, 'time_start', None),
                time_end=getattr(raw, 'time_end', None),
                time_slots=getattr(raw, 'time_slots', None),
                team_id=getattr(raw, 'team_id', None),
                floor=getattr(raw, 'floor', None),
                total_count=getattr(raw, 'total_count', None),
                images=getattr(raw, 'images', None),
                teaming=getattr(raw, 'teaming', None),
                soul_setup=getattr(raw, 'soul_setup', None),
                lock_team=bool(getattr(raw, 'lock_team', False)),
                change_team=bool(getattr(raw, 'change_team', False)),
                stamina_required=getattr(raw, 'stamina_required', None),
            )

            with self._lock:
                self._tasks[name] = config
                # 从持久化恢复或计算初始 next_run_time（§5.4 异常恢复④）
                # trigger 类型：不设置初始 next_run（等待外部触发）
                if self._store and name not in self._next_run:
                    stored = self._store.get(name)
                    if stored and stored.get('next_run_time'):
                        try:
                            self._next_run[name] = self._ensure_tz(
                                datetime.fromisoformat(stored['next_run_time']))
                        except (ValueError, TypeError):
                            nrt = self._calc_initial_next_run(config)
                            if nrt is not None:
                                self._next_run[name] = nrt
                    else:
                        nrt = self._calc_initial_next_run(config)
                        if nrt is not None:
                            self._next_run[name] = nrt
                elif name not in self._next_run:
                    nrt = self._calc_initial_next_run(config)
                    if nrt is not None:
                        self._next_run[name] = nrt

                # today_count 从持久化恢复
                if self._store:
                    stored = self._store.get(name)
                    if stored and 'today_count' in stored:
                        self._today_count[name] = stored['today_count']
                    else:
                        self._today_count.setdefault(name, 0)
                else:
                    self._today_count.setdefault(name, 0)

    def reload_from_config(self, changed_task: str | None = None) -> None:
        """
        热重载任务配置（保存后立即生效）。

        清空并重新从 tasks.yaml 加载全部任务 → 恢复仍在任务的
        运行时状态（next_run/today_count/total_count）→ 新任务
        计算初始 next_run → 清理已删除任务的状态 → 原子写盘。

        Args:
            changed_task: 本次被保存/修改的任务名。仅对该任务执行
                提前评估（窗口内且今日未执行 → 提前到当前时刻），
                避免保存一个任务时把其他窗口内任务也全部提前。
        """
        with self._lock:
            self._tasks.clear()
        self.load_tasks_from_config()  # 内部自行持锁

        with self._lock:
            # 清理已删除/禁用的任务状态
            for key in (self._next_run, self._today_count, self._total_count,
                        self.task_status):
                for name in list(key):
                    if name not in self._tasks:
                        key.pop(name, None)
            # 新任务：计算初始 next_run（trigger 类型不设置，等待外部触发）
            now = datetime.now(self._timezone)
            for name, cfg in self._tasks.items():
                if name not in self._next_run:
                    nrt = self._calc_initial_next_run(cfg)
                    if nrt is not None:
                        self._next_run[name] = nrt
                self._today_count.setdefault(name, 0)
                self._total_count.setdefault(name, 0)

            # 提前评估：仅对本次变更的任务生效
            # （当前在可执行窗口内、今日未执行、next_run 在未来
            #   → 提前到当前时刻，保存配置后立即执行）
            targets = [changed_task] if changed_task else []
            for name in targets:
                cfg = self._tasks.get(name)
                if cfg is None:
                    continue
                nrt = self._next_run.get(name)
                if (nrt is not None and nrt > now
                        and self._today_count.get(name, 0) == 0
                        and self._now_in_window(cfg, now)):
                    self._next_run[name] = now
                    self.task_status[name] = ScheduleStatus.WAITING
        self.save_state()

    def _now_in_window(self, config: TaskConfig, now: datetime) -> bool:
        """
        当前时刻是否在任务的每日时间窗口内（§3.1 ②）。

        多时段（time_slots）：当前时间落在任一时段内即视为在窗口内。
        单时段（time_start/time_end）：向后兼容的原有判断。
        """
        # 多时段优先
        if config.time_slots:
            current_time = now.strftime("%H:%M")
            for s, e in config.time_slots:
                if s and current_time < s:
                    continue
                if e and current_time > e:
                    continue
                return True
            return False
        # 单时段（向后兼容）
        if config.time_start or config.time_end:
            current_time = now.strftime("%H:%M")
            if config.time_start and current_time < config.time_start:
                return False
            if config.time_end and current_time > config.time_end:
                return False
        return True

    def _dt_in_any_slot(self, config: TaskConfig, dt: datetime) -> bool:
        """dt 时刻是否落在任一执行时段内（时段内间隔推进判断用）。"""
        slots = config.time_slots
        if not slots:
            return False
        current_time = dt.strftime("%H:%M")
        for s, e in slots:
            if s and current_time < s:
                continue
            if e and current_time > e:
                continue
            return True
        return False

    def _next_slot_time(self, config: TaskConfig, after: datetime) -> datetime | None:
        """
        返回 after 之后的下一个时段起点（多时段 time_slots）。

        - 今天还有未过的时段起点 → 返回该起点
        - 今天所有时段起点均已过 → 次日第一个时段起点
        - 无 time_slots → None（调用方回退到 RepeatRule）
        """
        slots = config.time_slots
        if not slots:
            return None
        for s, _e in slots:
            try:
                sh, sm = map(int, s.split(":"))
            except (ValueError, AttributeError):
                continue
            start_dt = after.replace(hour=sh, minute=sm, second=0, microsecond=0)
            if start_dt > after:
                return start_dt
        # 全部已过 → 次日第一个时段
        try:
            sh, sm = map(int, slots[0][0].split(":"))
        except (ValueError, AttributeError):
            return None
        return (after + timedelta(days=1)).replace(hour=sh, minute=sm, second=0, microsecond=0)

    def _next_day_first_slot(self, config: TaskConfig, after: datetime) -> datetime | None:
        """
        返回次日第一个时段起点（多时段 time_slots 的 daily 模式）。
        无 time_slots → None（调用方回退到 RepeatRule daily 推进）。
        """
        slots = config.time_slots
        if not slots:
            return None
        try:
            sh, sm = map(int, slots[0][0].split(":"))
        except (ValueError, AttributeError):
            sh, sm = 6, 0
        return (after + timedelta(days=1)).replace(hour=sh, minute=sm, second=0, microsecond=0)

    def _on_config_changed(self, source: str = "", task_name: str | None = None, **kw) -> None:
        """tasks 配置变更 → 热重载（保存立即生效，§3.2 补充）"""
        if source and source not in ("tasks", "reload"):
            return
        try:
            self.reload_from_config(changed_task=task_name)
            # 通知 UI 刷新日程
            self._bus.publish(Events.SCHEDULE_UPDATED, source="scheduler",
                              queue=[t.name for t in self.build_schedule()])
        except Exception:
            pass

    def _on_trigger_detected(self, task_name: str = "", source: str = "", **kw) -> None:
        """触发式任务识别命中 → 置 next_run=now（立即到期入队，§3.1 trigger 例外）。

        调用方：02-TriggerWatcher 识别到触发模板后发布 TRIGGER_DETECTED。
        本方法内部调 update_next_run(name, now) 复用既有入队链路。
        """
        if not task_name:
            return
        config = self._tasks.get(task_name)
        if not config or not config.enabled:
            return
        if config.repeat and config.repeat.type != 'trigger':
            return  # 仅对触发式任务生效
        self._log("info", f"[05-调度] 触发命中(trigger_detected): {task_name} → 置为到期入队", task=task_name)
        self.update_next_run(task_name, datetime.now(self._timezone))
        self.task_status[task_name] = ScheduleStatus.WAITING
        # 通知 UI 刷新队列（build_schedule 会拾取该任务）
        try:
            self._bus.publish(Events.SCHEDULE_UPDATED, source="scheduler",
                              queue=[t.name for t in self.build_schedule(publish=False)])
        except Exception:
            pass

    def _log(self, level: str, message: str, task: str = "") -> None:
        """模块级日志：发布 LOG_RECORD（UI 日志面板可见），兜底 print"""
        try:
            self._bus.publish(Events.LOG_RECORD, source="scheduler", level=level,
                              message=message, task=task)
        except Exception:
            print(f"[{level}] {message}")

    @staticmethod
    def _ensure_tz(dt: datetime, tz: tzinfo = TZ_UTC8) -> datetime:
        """规范化时区：naive datetime → 附加默认时区（UTC+8）。

        防御持久化/外部传入的 naive 时间（如 UI 手动设置 next_run 时用
        datetime.now()），避免与 aware 的 now 比较时抛
        TypeError: can't compare offset-naive and offset-aware datetimes。
        """
        if dt is None:
            return dt
        if dt.tzinfo is None:
            return dt.replace(tzinfo=tz)
        return dt

    @staticmethod
    def _resolve_weekdays(repeat: RepeatConfig) -> list[int]:
        """weekly 匹配日列表：优先 weekdays（多选），回退 weekday（单值）。"""
        if repeat and repeat.weekdays:
            return list(repeat.weekdays)
        if repeat and repeat.weekday is not None:
            return [repeat.weekday]
        return []

    def _calc_initial_next_run(self, config: TaskConfig) -> datetime | None:
        """计算初始 next_run_time（支持多时段 time_slots）。

        trigger 类型返回 None（不设置 next_run，等待外部触发）。
        """
        now = datetime.now(self._timezone)
        # trigger：无时间调度，不产生初始 next_run
        if config.repeat and config.repeat.type == 'trigger':
            return None
        # 多时段：当前在某时段内 → 立即执行；否则 → 下一时段起点
        if config.time_slots:
            if self._now_in_window(config, now):
                return now
            nxt = self._next_slot_time(config, now)
            if nxt:
                return nxt
        if config.repeat:
            rule = RepeatRule(
                type=config.repeat.type,
                interval=config.repeat.value or 1,
                time=config.time_start or "06:00",
                time_end=config.time_end or "",
                weekdays=self._resolve_weekdays(config.repeat),
                expire_date=config.repeat.expire_at or "",
                monthly_day=config.repeat.monthly_day,
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

            # 恢复 next_run_time（naive 自动附加时区，防御历史脏数据）
            nrt = st.get('next_run_time')
            if nrt:
                try:
                    self._next_run[name] = self._ensure_tz(
                        datetime.fromisoformat(nrt))
                except (ValueError, TypeError):
                    pass

            # 恢复周期触发累计次数
            tc = st.get('today_count', 0)
            self._today_count[name] = tc

            # 恢复活动循环累计次数
            self._total_count[name] = st.get('total_count', 0)

        # on_enter 启动任务：每次启动重置 next_run=now（设计书 §5.3）
        # 使「每次运行启动后执行一次」在本轮运行重新激活
        _start_now = datetime.now(self._timezone)
        for _n, _cfg in self._tasks.items():
            if _cfg.repeat and _cfg.repeat.type == 'on_enter':
                self._next_run[_n] = _start_now
                self.task_status[_n] = ScheduleStatus.WAITING

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
                "today_count": self._today_count.get(name, 0),  # 周期触发累计次数
                "total_count": self._total_count.get(name, 0),  # 活动循环累计次数
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

    def build_schedule(self, publish: bool = True) -> list[TaskInfo]:
        """
        生成日程表（§3.2 + §5.3）。

        流程：
        ① 获取 _lock
        ②   遍历所有启用任务
        ③   对每个任务：is_due() + check_times_limit()
        ④   过滤 → 按 priority 升序 → 同优先级按 category 排序
        ⑤ 释放 _lock
        ⑥ 发布 SCHEDULE_UPDATED 事件（已无锁；publish=False 时跳过，供只读查询）
        ⑦ 返回排序后的 TaskInfo 列表

        Args:
            publish: 是否发布 SCHEDULE_UPDATED 事件。UI 定时只读查询时传 False，
                     避免事件回环（查询 → 刷新 → 查询）。
        """
        with self._lock:
            now = datetime.now(self._timezone)
            result: list[TaskInfo] = []

            for name, config in self._tasks.items():
                if not config.enabled:
                    continue

                # 状态过滤（§3.2）：skipped 直接跳过；
                # completed 且 next_run 已被清空（on_enter 本轮已完成 / total_count 达上限）
                # → 跳过，防止反复入队。max_daily 满但 next_run 已推进 → 走 is_due 次日恢复
                task_status = self.task_status.get(name)
                if task_status == ScheduleStatus.SKIPPED:
                    continue
                if task_status == ScheduleStatus.COMPLETED and name not in self._next_run:
                    continue

                # 三重判据 + 次数上限
                if not self.is_due(name, now):
                    # 过期未执行（已错过今日窗口/有效期）→ 自动推进下一次
                    self._advance_stale_task(name, config, now)
                    status = self.task_status.get(name, ScheduleStatus.WAITING)
                elif (config.total_count is not None
                      and self._total_count.get(name, 0) >= config.total_count):
                    # 活动循环次数已达上限 → 永久完成（失效区）
                    status = ScheduleStatus.COMPLETED
                elif not self._check_times_limit(name):
                    # 周期触发次数已达上限 → 永久完成（失效区）
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
            # 到期日志去重：结果变化时才打印（避免填充线程每轮刷屏）
            due_names = tuple(sorted(t.name for t in result))
            if due_names != self._last_due_names:
                self._last_due_names = due_names or None
                if result:
                    self._log("info",
                              f"[05-调度] 到期任务 {len(result)} 个: "
                              f"{', '.join(t.name for t in result)}")

        # 已无锁时发布事件
        if publish:
            self._bus.publish(Events.SCHEDULE_UPDATED, source="scheduler",
                              queue=[t.name for t in result])

        self.schedule_queue = result
        return result

    def get_due_tasks(self) -> list[dict[str, Any]]:
        """
        待执行任务列表（due，已到期等待执行）。

        供 UI 队列面板「待执行」区域展示。
        纯调度查询：不依赖启动/运行状态，任何时刻都可调用；
        内部走 build_schedule(publish=False)，会顺带推进过期任务、
        更新 task_status（即自动整理调度队列）。
        """
        result = self.build_schedule(publish=False)
        return [
            {
                "name": t.name,
                "next_run": t.next_run.strftime("%m-%d %H:%M") if t.next_run else "",
                "priority": t.priority,
            }
            for t in result
        ]

    def get_next_task(self) -> str | None:
        """获取下一个到期任务名（§5.3 + §5.4）"""
        schedule = self.build_schedule()
        return schedule[0].name if schedule else None

    def get_upcoming(self) -> list[dict[str, Any]]:
        """
        未开始任务列表（waiting，未到 next_run_time）。
        供 UI 队列面板「未开始」区域展示。
        已失效任务（活动期结束/次数用尽/到期）不进入此处，归入「已失效」区。
        """
        with self._lock:
            now = datetime.now(self._timezone)
            today_str = now.strftime("%Y-%m-%d")
            result: list[dict[str, Any]] = []
            for name, cfg in self._tasks.items():
                if not cfg.enabled:
                    continue
                # 已失效（过期）任务不进入未开始
                if self._invalid_reason(cfg, now, today_str):
                    continue
                status = self.task_status.get(name, ScheduleStatus.WAITING)
                nrt = self._next_run.get(name)
                if status == ScheduleStatus.WAITING and (nrt is None or nrt > now):
                    result.append({
                        "name": name,
                        "next_run": nrt.strftime("%m-%d %H:%M") if nrt else "",
                        "reason": self._defer_reasons.get(name, ""),
                    })
            result.sort(key=lambda x: x["next_run"] or "9999")
            return result

    def get_invalid_tasks(self) -> list[dict[str, Any]]:
        """
        已失效任务列表（已过期，供 UI 队列面板「已失效」区域）。

        失效原因（满足其一）：
          - 累计次数达上限（total_count 用尽）
          - 活动有效期已结束（active_range 过期）
          - 到期日已过（repeat.type=expire_at）
          - next_run 已被清空（调度器标记永久完成）
        """
        with self._lock:
            now = datetime.now(self._timezone)
            today_str = now.strftime("%Y-%m-%d")
            result: list[dict[str, Any]] = []
            for name, cfg in self._tasks.items():
                if not cfg.enabled:
                    continue
                reason = self._invalid_reason(cfg, now, today_str)
                if reason:
                    result.append({
                        "name": name,
                        "status": reason,  # 已过期/本轮已完成/待触发/等待下次触发
                        "detail": self._invalid_detail(cfg),
                    })
            # trigger 相关（待触发 / 等待下次触发）置顶
            result.sort(key=lambda x: (
                0 if x["status"] in ("待触发", "等待下次触发") else 1, x["name"]))
            return result

    def _invalid_reason(self, config: TaskConfig, now: datetime, today_str: str) -> str | None:
        """返回任务的失效原因（已过期），否则 None。调用方需持有 _lock。"""
        name = config.name
        # ① 活动循环次数达上限（循环体循环用尽）
        if (config.total_count is not None
                and self._total_count.get(name, 0) >= config.total_count):
            return "已过期"
        # ①b 周期触发次数达上限（触发用尽）
        if (config.max_daily is not None
                and self._today_count.get(name, 0) >= config.max_daily):
            return "已过期"
        # ② 活动有效期已结束
        if config.active_range and len(config.active_range) > 1:
            end_date = config.active_range[1]
            if end_date and today_str > end_date:
                return "已过期"
        # ③ expire_at 到期日已过
        if (config.repeat and config.repeat.type == "expire_at"
                and config.repeat.expire_at and today_str > config.repeat.expire_at):
            return "已过期"
        # ④ trigger 任务：无 next_run = 等待触发（未触发 或 已执行完，统一归入已失效）
        if (config.repeat and config.repeat.type == 'trigger'
                and name not in self._next_run):
            if self.task_status.get(name) == ScheduleStatus.COMPLETED:
                # 达周期触发上限 → 单独状态（触发按钮失效）
                if "已达周期上限" in (self._defer_reasons.get(name) or ""):
                    return "已达上限"
                return "等待下次触发"
            return "待触发"
        # ⑤ next_run 已被清空（调度器标记永久完成 / on_enter 本轮完成）
        if (self.task_status.get(name) == ScheduleStatus.COMPLETED
                and name not in self._next_run):
            if config.repeat and config.repeat.type == 'on_enter':
                return "本轮已完成"
            return "已过期"
        # ⑥ 熔断（SKIPPED）→ 异常熔断，归入已失效区（UI 标注）
        if self.task_status.get(name) == ScheduleStatus.SKIPPED:
            return "异常熔断"
        return None

    def _invalid_detail(self, config: TaskConfig) -> str:
        """失效任务的说明文字。调用方需持有 _lock。"""
        name = config.name
        if self.task_status.get(name) == ScheduleStatus.SKIPPED:
            return self._defer_reasons.get(name, "连续失败熔断，需手动重置")
        if config.repeat and config.repeat.type == 'trigger':
            if "已达周期上限" in (self._defer_reasons.get(name) or ""):
                return self._defer_reasons.get(name)
            if self.task_status.get(name) == ScheduleStatus.COMPLETED:
                return "外部触发后重新激活"
            return "等待外部触发（按钮/识图）"
        if config.repeat and config.repeat.type == 'on_enter':
            return "下次启动执行"
        if config.repeat and config.repeat.type == 'trigger':
            if self.task_status.get(name) == ScheduleStatus.COMPLETED:
                return "外部触发后重新激活"
            return "等待外部触发（按钮/识图）"
        if config.total_count is not None:
            return f"累计 {self._total_count.get(name, 0)}/{config.total_count} 次已完成"
        if config.active_range and len(config.active_range) > 1:
            return f"活动期 {config.active_range[0]}~{config.active_range[1]} 已结束"
        if (config.repeat and config.repeat.type == "expire_at"
                and config.repeat.expire_at):
            return f"到期日 {config.repeat.expire_at} 已过"
        return "任务已结束"

    def get_all_tasks(self) -> list[TaskConfig]:
        """获取所有已注册任务的 TaskConfig（§5.3）"""
        return list(self._tasks.values())

    def get_config(self, task_name: str) -> TaskConfig | None:
        """查询单个任务的 TaskConfig（供执行层注入 task_config）"""
        with self._lock:
            return self._tasks.get(task_name)

    @property
    def next_run_time(self) -> dict[str, datetime]:
        """各任务的下次执行时间映射表（§2.2 只读对外）"""
        return dict(self._next_run)

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
        if now < self._ensure_tz(nrt):
            return False

        config = self._tasks.get(task_name)
        if not config:
            return False

        # ② 每日时间窗口（单时段 time_start/time_end 或多时段 time_slots）
        if not self._now_in_window(config, now):
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
        """检查任务是否未达周期触发次数上限（§5.3）

        周期触发次数 = 活动周期内任务被触发的次数上限（不按天重置），
        达到后任务进入失效区。
        """
        config = self._tasks.get(task_name)
        if not config or config.max_daily is None:
            return True
        return self._today_count.get(task_name, 0) < config.max_daily

    def _advance_stale_task(self, task_name: str, config: TaskConfig, now: datetime) -> None:
        """
        过期未执行自动推进（§3.3 补充）。

        当 next_run_time 已到期、但当前已错过每日时间窗口（超过 time_end）
        或活动有效期已结束 → 自动推进 next_run_time 到下一个有效时点：
          daily      → 次日 time_start
          weekly     → 下周匹配 weekday
          interval_days / interval_hours → N 天/小时后
        保证推进结果 > now（避免 nrt 滞后多日仍不过期）。

        没有该逻辑时，过期任务会永远停留在 WAITING 状态（is_due 因窗口已过
        返回 False，但无人推进 next_run_time）。
        """
        nrt = self._next_run.get(task_name)
        if nrt is None or self._ensure_tz(nrt) > now:
            return  # 未到时间，正常等待

        # 当前是否仍在每日时间窗口内（单时段或多时段）
        if self._now_in_window(config, now):
            return  # 窗口内 → 正常到期执行

        # 活动有效期已结束 → 永久完成
        if config.active_range:
            today_str = now.strftime("%Y-%m-%d")
            end_date = config.active_range[1] if len(config.active_range) > 1 else None
            if end_date and today_str > end_date:
                self.task_status[task_name] = ScheduleStatus.COMPLETED
                self._next_run.pop(task_name, None)
                return

        # 多时段：窗口外 → 推进到下一个时段起点
        if config.time_slots:
            nxt = self._next_slot_time(config, now)
            if nxt:
                self._next_run[task_name] = nxt
                self.task_status[task_name] = ScheduleStatus.WAITING
                return

        # 按重复规则推进到下一有效时点
        if config.repeat:
            rule = RepeatRule(
                type=config.repeat.type,
                interval=config.repeat.value or 1,
                time=config.time_start or "06:00",
                weekdays=self._resolve_weekdays(config.repeat),
                expire_date=config.repeat.expire_at or "",
                monthly_day=config.repeat.monthly_day,
            )
            sentinel = datetime.max.replace(tzinfo=self._timezone)
            next_time = rule.calc_next_run(nrt)
            # 确保推进到 now 之后（防止 nrt 滞后多日）
            for _ in range(10):
                if next_time == sentinel or next_time == datetime.max or next_time > now:
                    break
                next_time = rule.calc_next_run(next_time)
            if next_time == sentinel or next_time == datetime.max:
                self.task_status[task_name] = ScheduleStatus.COMPLETED
                self._next_run.pop(task_name, None)
            else:
                self._next_run[task_name] = next_time
                self.task_status[task_name] = ScheduleStatus.WAITING

    # 内部别名
    _check_times_limit = check_times_limit

    # ── 执行反馈（§3.3 + §5.3）──────────────────────────────

    def mark_done(self, task_name: str, success: bool, interrupted: bool = False) -> None:
        """
        标记任务完成（§3.3 + §5.4）。

        success=True:
          fail_streak 归零 → 按 RepeatRule.type 推进 next_run_time → today_count += 1

        success=False + interrupted=False（异常失败）:
          fail_streak += 1 → 超阈值则熔断 skipped → 否则递增冷却（不推进原时间）
          并在 _defer_reasons 记录标注（UI 展示"异常推迟"）

        success=False + interrupted=True（系统停止中断）:
          不算任务失败（fail_streak 归零）→ next_run 直接置为当前时间
          （下次启动立即到期重跑，不冷却）
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
                # 成功执行 → 清除异常推迟标注
                self._defer_reasons.pop(task_name, None)

                next_count = self._today_count.get(task_name, 0) + 1  # 周期触发累计 +1
                self._today_count[task_name] = next_count

                now = datetime.now(self._timezone)

                # 周期触发次数上限（max_daily）：达到 → 永久完成（失效区，不按天恢复）
                trigger_limit_ok = (config.max_daily is None) or (next_count < config.max_daily)
                # 活动循环次数上限（total_count）：由 record_cycle 每轮循环累计，此处仅检查
                cycle_limit_ok = (config.total_count is None
                                  or self._total_count.get(task_name, 0) < config.total_count)

                # ── 推进 next_run_time（设计书 §3.3 execution_mode）──
                repeat_type = config.repeat.type if config.repeat else 'daily'

                if not trigger_limit_ok or not cycle_limit_ok:
                    # 达触发/循环上限 → 永久完成（进入失效区，不再调度）
                    self.task_status[task_name] = ScheduleStatus.COMPLETED
                    self._next_run.pop(task_name, None)
                    _tl = config.max_daily if config.max_daily is not None else "-"
                    _cl = config.total_count if config.total_count is not None else "-"
                    self._defer_reasons[task_name] = (
                        f"已达周期上限（触发 {self._today_count.get(task_name, 0)}/{_tl} 次 · "
                        f"循环 {self._total_count.get(task_name, 0)}/{_cl} 轮）")
                elif repeat_type == 'on_enter':
                    # 启动任务：本轮完成，清空 next_run（下次启动 load_state 重置激活）
                    self.task_status[task_name] = ScheduleStatus.COMPLETED
                    self._next_run.pop(task_name, None)
                elif repeat_type == 'trigger':
                    # 触发式任务：本轮完成，清空 next_run（等待外部再次触发，load_state 不自动激活）
                    self.task_status[task_name] = ScheduleStatus.COMPLETED
                    self._next_run.pop(task_name, None)
                elif config.time_slots:
                    # 多时段：固定"每时段各执行一次"（execution_mode 已移除）；
                    # 配时段内间隔（interval_hours）时按间隔推进
                    # 时段内间隔：interval_hours 类型 → 每 value 小时在时段内推进
                    interval_h = None
                    if config.repeat and config.repeat.type == 'interval_hours':
                        interval_h = (config.repeat.value or 1)
                    if interval_h:
                        # 时段内按间隔推进：当前 + N 小时；仍在时段内 → 该时刻，
                        # 否则 → 下一时段起点（今日无剩余 → 次日首个）
                        cand = now + timedelta(hours=interval_h)
                        if self._dt_in_any_slot(config, cand):
                            self._next_run[task_name] = cand
                            self.task_status[task_name] = ScheduleStatus.WAITING
                        else:
                            slot_next = self._next_slot_time(config, cand)
                            if slot_next is not None:
                                self._next_run[task_name] = slot_next
                                self.task_status[task_name] = ScheduleStatus.WAITING
                            else:
                                nxt = self._next_day_first_slot(config, now)
                                if nxt is None:
                                    nxt = now + timedelta(days=1)
                                self._next_run[task_name] = nxt
                                self.task_status[task_name] = ScheduleStatus.WAITING
                    else:
                        # 无间隔：每时段各执行一次 → 下一时段起点（今日无剩余 → 次日首个）
                        slot_next = self._next_slot_time(config, now)
                        if slot_next is not None:
                            self._next_run[task_name] = slot_next
                            self.task_status[task_name] = ScheduleStatus.WAITING
                        else:
                            self._next_run.pop(task_name, None)
                            self.task_status[task_name] = ScheduleStatus.COMPLETED
                else:
                    # 单时段（无 time_slots）：按 RepeatRule 推进（daily/per_slot 每天一次）
                    if config.repeat:
                        rule = RepeatRule(
                            type=config.repeat.type,
                            interval=config.repeat.value or 1,
                            time=config.time_start or "06:00",
                            weekdays=self._resolve_weekdays(config.repeat),
                            expire_date=config.repeat.expire_at or "",
                            monthly_day=config.repeat.monthly_day,
                        )
                        last_run = self._ensure_tz(self._next_run.get(task_name) or now)
                        next_time = rule.calc_next_run(last_run)
                        # once 类型或已过期 → 标记 completed
                        sentinel = datetime.max.replace(tzinfo=self._timezone)
                        # ★ 确保推进到 now 之后（防止 next_run 积压多天后当天反复执行）：
                        #   例如 next_run 停在 08-01，今天 08-03 才运行，+1 天仍是过去
                        #   → 继续推进跳过积压天数，当天只执行一次
                        for _ in range(10):
                            if next_time == sentinel or next_time == datetime.max or next_time > now:
                                break
                            next_time = rule.calc_next_run(next_time)
                        if next_time == sentinel or next_time == datetime.max:
                            self.task_status[task_name] = ScheduleStatus.COMPLETED
                            self._next_run.pop(task_name, None)
                        else:
                            self._next_run[task_name] = next_time
                            self.task_status[task_name] = ScheduleStatus.WAITING
                    else:
                        # 无 repeat 配置 → 默认 daily（确保未来）
                        self._next_run[task_name] = now + timedelta(days=1)
                        self.task_status[task_name] = ScheduleStatus.WAITING

            else:
                if interrupted:
                    # 系统停止中断：不算任务失败 → 立即按当前时间到期
                    # （重新启动后立即执行，不进入冷却；fail_streak 归零）
                    if self._store:
                        stored = self._store.get(task_name) or {}
                        stored.pop('fail_streak', None)
                        stored.pop('skip_reason', None)
                        self._store.update(task_name, fail_streak=0, skip_reason='')
                    self._defer_reasons.pop(task_name, None)
                    self._next_run[task_name] = datetime.now(self._timezone)
                    self.task_status[task_name] = ScheduleStatus.WAITING
                else:
                    # 异常失败：递增 fail_streak
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
                        self._defer_reasons[task_name] = (
                            f"异常熔断（连续失败 {fail_streak} 次，需手动重置）")
                        self._bus.publish(Events.TASK_SKIPPED, source="scheduler",
                                         task_name=task_name, reason="连续失败熔断",
                                         fail_streak=fail_streak, max_fail_streak=max_fail)
                    else:
                        # 递增冷却：fail_streak × 5min ≤ 60min（不推进原 next_run_time）
                        cool_seconds = min(fail_streak * 300, 3600)
                        next_time = datetime.now(self._timezone) + timedelta(seconds=cool_seconds)
                        self._next_run[task_name] = next_time
                        self.task_status[task_name] = ScheduleStatus.WAITING
                        # 异常推迟标注（UI 队列「未开始」区显示）
                        self._defer_reasons[task_name] = (
                            f"异常推迟（连续失败 {fail_streak} 次，"
                            f"约 {cool_seconds // 60} 分钟后重试）")

        # 持锁外持久化 + 发布事件
        _st = self.task_status.get(task_name, ScheduleStatus.WAITING)
        _nrt = self._next_run.get(task_name)
        if _nrt:
            _nrt_s = _nrt.strftime("%m-%d %H:%M")
        else:
            _rtype = (config.repeat.type if config.repeat else '')
            if _rtype == 'on_enter':
                _nrt_s = "无(下次启动执行)"
            elif _rtype == 'trigger':
                _nrt_s = "无(等待外部触发)"
            else:
                _nrt_s = "无"
        self._log("info",
                  f"[05-调度] mark_done({task_name}, success={success}) "
                  f"→ 状态: {_st.value} · 下次执行: {_nrt_s}",
                  task=task_name)
        self.save_state()
        self._bus.publish(Events.SCHEDULE_UPDATED, source="scheduler",
                         task=task_name, success=success)

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
                nrt = self._calc_initial_next_run(config)
                if nrt is not None:
                    self._next_run[task_name] = nrt
        if self._store:
            self._store.update(task_name, fail_streak=0, skip_reason='')
        self.save_state()

    # ── 活动循环次数上报（§5.3 补充）────────────────────────

    def record_cycle(self, task_name: str, n: int = 1) -> bool:
        """
        活动循环次数上报：循环体每完成一轮循环调用一次。

        累计 _total_count（活动循环累计）→ 达到 total_count（活动循环次数上限）
        → 标记永久完成（失效区），返回 True；否则 False。

        调用方：执行层 BattleLoop 每场/每轮循环结束（run_controller._on_task_progress）。
        """
        with self._lock:
            config = self._tasks.get(task_name)
            if not config or config.total_count is None:
                return False
            cur = self._total_count.get(task_name, 0) + int(n)
            self._total_count[task_name] = cur
            if cur >= config.total_count:
                # 活动循环次数达上限 → 永久完成（失效区）
                self.task_status[task_name] = ScheduleStatus.COMPLETED
                self._next_run.pop(task_name, None)
                self._defer_reasons[task_name] = (
                    f"已达周期上限（触发 {self._today_count.get(task_name, 0)}/"
                    f"{config.max_daily if config.max_daily is not None else '-'} 次 · "
                    f"循环 {cur}/{config.total_count} 轮）")
                self._log("info",
                          f"[05-调度] 活动循环次数达上限: {task_name} "
                          f"累计 {cur}/{config.total_count} 轮 → 任务失效",
                          task=task_name)
                self.save_state()
                self._bus.publish(Events.SCHEDULE_UPDATED, source="scheduler",
                                 task=task_name)
                return True
        return False

    def get_cycle_progress(self, task_name: str) -> tuple[int, int | None]:
        """查询任务活动循环进度：(已累计循环次数, 活动循环次数上限)。

        供 UI 显示「累计循环次数 x/y」。上限为 None → 不限。
        """
        with self._lock:
            config = self._tasks.get(task_name)
            limit = config.total_count if config is not None else None
            return self._total_count.get(task_name, 0), limit

    def get_trigger_progress(self, task_name: str) -> tuple[int, int | None]:
        """查询任务周期触发进度：(已累计触发次数, 周期触发次数上限)。

        供 UI 显示「已触发 x/y 次」。上限为 None → 不限。
        """
        with self._lock:
            config = self._tasks.get(task_name)
            limit = config.max_daily if config is not None else None
            return self._today_count.get(task_name, 0), limit

    # ── 手动设置（§5.3）─────────────────────────────────────

    def update_next_run(self, task_name: str, next_run_time: datetime) -> None:
        """手动设置 next_run_time（trigger 任务触发入口：识图命中/手动⚡触发）。

        trigger 任务带周期触发次数（max_daily）时：
        已达上限 → 拦截触发并标记失效（下次触发条件不再生效，进入失效区、
        触发按钮失效；周期累计不按天恢复）。
        """
        with self._lock:
            config = self._tasks.get(task_name)
            # 周期触发次数：统一用 max_daily（UI「周期触发次数」），
            # 兼容旧 trigger_max_count 字段
            limit = None
            if config is not None:
                if config.max_daily is not None:
                    limit = config.max_daily
                elif config.repeat and config.repeat.trigger_max_count is not None:
                    limit = config.repeat.trigger_max_count
            if (config and config.repeat and config.repeat.type == 'trigger'
                    and limit is not None):
                if self._today_count.get(task_name, 0) >= limit:
                    # 已达周期触发上限 → 拦截触发，标记失效
                    self.task_status[task_name] = ScheduleStatus.COMPLETED
                    self._next_run.pop(task_name, None)
                    self._defer_reasons[task_name] = (
                        f"已达周期上限（已触发 "
                        f"{self._today_count.get(task_name, 0)}/{limit} 次，任务失效）")
                    self._log("warning",
                              f"[05-调度] 触发被拦截: {task_name} 已达周期上限"
                              f"({limit} 次)，不再触发", task=task_name)
                    self.save_state()
                    self._bus.publish(Events.SCHEDULE_UPDATED, source="scheduler",
                                     task=task_name)
                    return
            # 规范化时区：UI/外部可能传入 naive（datetime.now()），统一附加 UTC+8
            self._next_run[task_name] = self._ensure_tz(next_run_time)
        self.save_state()
        self._log("info",
                  f"[05-调度] 手动/触发设置 next_run: {task_name} → "
                  f"{next_run_time.strftime('%m-%d %H:%M:%S')}",
                  task=task_name)

    # ── 活动日历导入（§3.5 + §5.3）─────────────────────────

    def import_calendar(self, events: list[CalendarEvent | dict]) -> tuple[int, int]:
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
                # 统一支持 dict 和 CalendarEvent 对象
                if isinstance(evt, dict):
                    name = evt.get('name', '')
                    evt_start = evt.get('start', '')
                    evt_end = evt.get('end', '')
                    evt_window = evt.get('window')
                    evt_type = evt.get('type', 'special')
                    evt_display = evt.get('display_name', name)
                else:
                    name = evt.name
                    evt_start = evt.start
                    evt_end = evt.end
                    evt_window = evt.window
                    evt_type = evt.type
                    evt_display = evt.display_name or name

                if not name:
                    continue

                if name in self._tasks:
                    # 更新现有任务的 active_range / window
                    config = self._tasks[name]
                    config.active_range = [evt_start, evt_end]
                    if evt_window:
                        if config.repeat:
                            config.repeat.window = evt_window
                    updated += 1
                else:
                    # 新建 special 类型任务
                    repeat = RepeatConfig(
                        type=evt_type,
                        window=evt_window,
                    )
                    config = TaskConfig(
                        name=name,
                        display_name=evt_display,
                        category='event',
                        repeat=repeat,
                        active_range=[evt_start, evt_end] if evt_start else None,
                    )
                    self._tasks[name] = config
                    nrt = self._calc_initial_next_run(config)
                    if nrt is not None:
                        self._next_run[name] = nrt
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



