"""
05-时间调度模块

RepeatRule 重复规则（dataclass + helper）。
对应设计书 §5.2 RepeatConfig / §5.3 RepeatRule 方法定义。

支持 10 种重复类型:
- once: 单次执行（calc_next_run 返回 datetime.max）
- daily: 每天固定 time_start
- weekly: 每周固定 weekday
- monthly_start: 每月指定日（默认 1 号）
- interval_days: 每 N 天
- interval_hours: 每 N 小时
- expire_at: 已弃用（UI 已移除，代码保留兼容旧配置：每 1 小时执行到指定日期 23:59:59 截止）
- special: 已弃用（等同 daily，日历导入兼容；window 不参与调度，旧配置回退 daily）
- on_enter: 每次运行启动后执行一次（load_state 时重置 next_run=now，执行后本轮完成）
- trigger: 特殊条件触发（无时间推进，无初始 next_run；由外部触发——TriggerWatcher 识图命中/手动 update_next_run——置为到期；执行后本轮完成）

所有时间基于 UTC+8（TZ_UTC8）。
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any

TZ_UTC8: tzinfo = timezone(timedelta(hours=8), "UTC+8")


@dataclass
class RepeatRule:
    """
    重复规则（§5.2 RepeatConfig 对应实现）。

    字段说明:
      type: 规则类型
      interval: interval_days=N / interval_hours=N
      time: 每日执行时间 "HH:MM"（daily/weekly 等使用）
      weekdays: weekly 类型专属，每周几执行（0=周一）
      expire_date: expire_at 类型专属到期日期 "YYYY-MM-DD"
      monthly_day: monthly_start 专属，每月几号（1~28）
    """
    type: str = "daily"
    interval: int = 1
    time: str = "06:00"
    time_end: str = ""  # 每日结束时间 "HH:MM"（可选，用于窗口判断）
    weekdays: list[int] | None = None
    expire_date: str = ""
    monthly_day: int = 1

    def __post_init__(self):
        if self.weekdays is None:
            self.weekdays = []

    # ── 初始计算（§5.3 get_initial_next_run）────────────────

    def get_initial_next_run(self, from_time: datetime | None = None) -> datetime:
        """
        首次注册时计算初始 next_run_time（宽容解析）。

        窗口修正（§3.1 三重判据补充）：
        - 若当前时刻已达到 time_start 且未超过 time_end（若有），
          则直接返回当前时刻（立即可执行）——避免配置在窗口内时
          被错误推到明天/下周。
        - 否则取下一个有效时间点。
        """
        now = (from_time or datetime.now(TZ_UTC8)).astimezone(TZ_UTC8)

        # 窗口内 → 立即可执行
        if self.type in ("daily", "monthly_start", "special"):
            if self._initial_now_ok(now):
                return now
        elif self.type == "weekly":
            if (not self.weekdays or now.weekday() in self.weekdays) and self._initial_now_ok(now):
                return now

        if self.type in ("on_enter", "once"):
            return now

        elif self.type == "trigger":
            # 触发式任务：不产生初始 next_run（等待外部触发），
            # 返回 datetime.max 表示"不按时间调度"（由 Scheduler 层拦截为 None）
            return datetime.max.replace(tzinfo=TZ_UTC8)

        elif self.type == "daily":
            return self._next_daily(now)

        elif self.type == "weekly":
            return self._next_weekly(now)

        elif self.type == "monthly_start":
            return self._next_monthly(now)

        elif self.type == "interval_days":
            return now + timedelta(days=self.interval)

        elif self.type == "interval_hours":
            return now + timedelta(hours=self.interval)

        elif self.type == "expire_at":
            if self.expire_date:
                expire = datetime.strptime(f"{self.expire_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
                expire = expire.replace(tzinfo=TZ_UTC8)
                if now > expire:
                    return datetime.max.replace(tzinfo=TZ_UTC8)
            return now

        # special / fallback
        return self._next_daily(now)

    def _initial_now_ok(self, now: datetime) -> bool:
        """
        当前时刻是否已在可执行窗口内。

        - 未到 time_start → False（应等到 time_start）
        - 已过 time_end（若配置）→ False（今日窗口已过，推明天）
        - 其余（含无 time_end 且已过 time_start）→ True（立即可执行）
        """
        parts = self.time.split(":")
        h = int(parts[0]) if parts else 6
        m = int(parts[1]) if len(parts) > 1 else 0
        cur = now.hour * 60 + now.minute
        if cur < h * 60 + m:
            return False
        if self.time_end:
            parts2 = self.time_end.split(":")
            h2 = int(parts2[0]) if parts2 else 0
            m2 = int(parts2[1]) if len(parts2) > 1 else 0
            if cur > h2 * 60 + m2:
                return False
        return True

    # ── 推进计算（§5.3 calc_next_run）──────────────────────

    def calc_next_run(self, last_run: datetime) -> datetime:
        """
        执行成功后计算下一次执行时间（§5.3 calc_next_run）。

        严格推进：计算结果必须大于 last_run。
        daily 若已过 time_end → 次日 time_start
        weekly 若已过本周匹配日 → 下周
        interval 跨越窗口边界时自动调整
        """
        if self.type in ("on_enter", "once"):
            return datetime.max.replace(tzinfo=TZ_UTC8)

        elif self.type == "trigger":
            # 触发式任务：执行后不推进时间（由 Scheduler 标记 completed + 清空 next_run）
            return datetime.max.replace(tzinfo=TZ_UTC8)

        elif self.type == "daily":
            # _next_daily 内部保证结果 > last_run（时间相等/已过 → 次日）
            return self._next_daily(last_run)

        elif self.type == "weekly":
            return self._next_weekly(last_run + timedelta(days=1))

        elif self.type == "monthly_start":
            return self._next_monthly(last_run + timedelta(days=1))

        elif self.type == "interval_days":
            return self._ensure_future(last_run + timedelta(days=self.interval))

        elif self.type == "interval_hours":
            return self._ensure_future(last_run + timedelta(hours=self.interval))

        elif self.type == "expire_at":
            if self.expire_date:
                expire = datetime.strptime(f"{self.expire_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
                expire = expire.replace(tzinfo=TZ_UTC8)
                if last_run >= expire:
                    return datetime.max.replace(tzinfo=TZ_UTC8)
            return self._ensure_future(last_run + timedelta(hours=1))

        # special
        return self._next_daily(last_run)

    # ── 过期判断（§5.3 is_expired）────────────────────────

    def is_expired(self, now: datetime | None = None) -> bool:
        """检查任务是否已过期（once 或 expire_at 到期）"""
        now = (now or datetime.now(TZ_UTC8)).astimezone(TZ_UTC8)
        if self.type == "once":
            return True
        if self.type == "trigger":
            return False  # 触发式任务不过期，等待外部触发
        if self.type == "expire_at" and self.expire_date:
            expire = datetime.strptime(f"{self.expire_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
            expire = expire.replace(tzinfo=TZ_UTC8)
            return now >= expire
        return False

    # ── 内部辅助 ──────────────────────────────────────────

    def _next_daily(self, from_time: datetime) -> datetime:
        """计算下一个 daily 时间点"""
        from_time = from_time.astimezone(TZ_UTC8)
        parts = self.time.split(":")
        h = int(parts[0]) if parts else 6
        m = int(parts[1]) if len(parts) > 1 else 0
        target = from_time.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= from_time:
            target += timedelta(days=1)
        return target

    def _next_weekly(self, from_time: datetime) -> datetime:
        """计算下一个 weekly 时间点"""
        from_time = from_time.astimezone(TZ_UTC8)
        target = self._next_daily(from_time)
        if self.weekdays:
            while target.weekday() not in self.weekdays:
                target += timedelta(days=1)
        return target

    def _next_monthly(self, from_time: datetime) -> datetime:
        """计算下一个 monthly_start 时间点"""
        from_time = from_time.astimezone(TZ_UTC8)
        day = min(self.monthly_day, 28)  # 安全处理
        target = from_time.replace(day=day, hour=6, minute=0, second=0, microsecond=0)
        if target <= from_time:
            # 推进到下个月
            month = from_time.month + 1
            year = from_time.year
            if month > 12:
                month = 1
                year += 1
            target = from_time.replace(year=year, month=month, day=day,
                                       hour=6, minute=0, second=0, microsecond=0)
        return target

    @staticmethod
    def _ensure_future(dt: datetime) -> datetime:
        """确保结果 > now（避免推进后仍过期）"""
        now = datetime.now(TZ_UTC8)
        if dt <= now:
            dt = now + timedelta(hours=1)
        return dt
