"""
05-时间调度模块

RepeatRule 重复规则（dataclass + helper）。
对应设计书 §5.2 RepeatConfig / §5.3 RepeatRule 方法定义。

支持 8 种重复类型:
- once: 单次执行（calc_next_run 返回 datetime.max）
- daily: 每天固定 time_start
- weekly: 每周固定 weekday
- monthly_start: 每月指定日（默认 1 号）
- interval_days: 每 N 天
- interval_hours: 每 N 小时
- expire_at: 执行到指定日期后不再调度
- special: 特殊规则（同 daily，受 window.date 限制）

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
        若当前已过当日 time_start，则取下一个有效时间点。
        """
        now = (from_time or datetime.now(TZ_UTC8)).astimezone(TZ_UTC8)

        if self.type == "once":
            return now

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

    # ── 推进计算（§5.3 calc_next_run）──────────────────────

    def calc_next_run(self, last_run: datetime) -> datetime:
        """
        执行成功后计算下一次执行时间（§5.3 calc_next_run）。

        严格推进：计算结果必须大于 last_run。
        daily 若已过 time_end → 次日 time_start
        weekly 若已过本周匹配日 → 下周
        interval 跨越窗口边界时自动调整
        """
        if self.type == "once":
            return datetime.max.replace(tzinfo=TZ_UTC8)

        elif self.type == "daily":
            return self._next_daily(last_run + timedelta(days=1))

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
        return self._next_daily(last_run + timedelta(days=1))

    # ── 过期判断（§5.3 is_expired）────────────────────────

    def is_expired(self, now: datetime | None = None) -> bool:
        """检查任务是否已过期（once 或 expire_at 到期）"""
        now = (now or datetime.now(TZ_UTC8)).astimezone(TZ_UTC8)
        if self.type == "once":
            return True
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
