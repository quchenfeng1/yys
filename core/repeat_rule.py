"""
RepeatRule 执行规则（05-定时模块 子模块）

定义所有任务的时间执行规则及 next_run_time 推进逻辑。
七种类型：once / daily / weekly / monthly / interval_days / interval_hours / expire_at

对应解耦文档：模块说明/05-定时模块.md
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class RepeatRule:
    """任务执行规则。每个任务必须配置。

    七种类型：
      once            — 单次执行，指定时刻后执行一次，标记完成不再调度
      daily           — 每日 at_time 执行
      weekly          — 每周指定 weekdays 的 at_time 执行
      monthly         — 每月指定 month_days 的 at_time 执行
      interval_days   — 隔 N 天 at_time 执行
      interval_hours  — 隔 N 小时执行
      expire_at       — 依赖外部失效时间，任务上报 report_expire()
    """
    type: str                                    # daily/weekly/monthly_start/interval_days/interval_hours/once/expire_at/special
    at_time: Optional[str] = None                # "HH:MM"（daily/weekly/interval_days 用）— 已废弃，用 time_start
    time_start: Optional[str] = None             # "HH:MM" 每日/每周的开始时间
    time_end: Optional[str] = None               # "HH:MM" 每日/每周的结束时间
    weekdays: Optional[list[int]] = None          # [1,3,5]（1=周一...7=周日）
    month_days: Optional[list[int]] = None        # 已废弃，用 monthly_start
    days: Optional[int] = None                   # interval_days：隔 N 天
    hours: Optional[float] = None                # interval_hours：隔 N 小时
    at: Optional[str] = None                     # once：完整 ISO 时间 "2026-08-01T10:00:00"
    times: int = 1                               # 已废弃，用 execution_rule
    window: Optional[dict] = None                # special: {date_start?, date_end?}
    max_daily: Optional[int] = None              # 每日上限
    max_total: Optional[int] = None              # 总次数上限
    cooldown: Optional[int] = None               # 两次执行最小间隔（秒）

    def validate(self) -> list[str]:
        """校验规则合法性，返回错误信息列表。"""
        errors = []
        valid_types = {"daily","weekly","monthly_start","interval_days","interval_hours","once","expire_at","special"}
        if self.type not in valid_types:
            errors.append(f"无效的 repeat.type: {self.type}，应为 {valid_types}")
        if self.type in ("daily", "weekly", "interval_days") and not self.time_start:
            errors.append(f"{self.type} 类型必须指定 time_start")
        if self.type == "weekly" and not self.weekdays:
            errors.append("weekly 类型必须指定 weekdays")
        if self.type == "interval_days" and not self.days:
            errors.append("interval_days 类型必须指定 days")
        if self.type == "interval_hours" and not self.hours:
            errors.append("interval_hours 类型必须指定 hours")
        if self.type == "once" and not self.at:
            errors.append("once 类型必须指定 at (ISO 时间)")
        return errors

    def calc_next_run(self, now: datetime, success: bool = True) -> Optional[datetime]:
        """计算下一次执行时间。

        Args:
            now: 当前时间
            success: 是否成功。失败时不推进，返回 now（允许重试）

        Returns:
            下一次执行时间，once 成功返回 None（不再调度）
        """
        if not success:
            return now  # 失败不推进

        if self.type == "once":
            return None  # 标记完成

        if self.type == "daily":
            return self._next_daily(now)
        if self.type == "weekly":
            return self._next_weekly(now)
        if self.type == "monthly_start":
            return self._next_monthly_start(now)
        if self.type == "interval_days":
            return self._next_interval_days(now)
        if self.type == "interval_hours":
            return now + timedelta(hours=self.hours or 1)
        if self.type == "expire_at":
            return now  # 不自动推进，等任务上报

        return now

    def get_initial_next_run(self, now: datetime = None) -> datetime:
        """获取首次 next_run_time（注册时调用）。"""
        if now is None:
            now = datetime.now()
        if self.type == "once":
            return datetime.fromisoformat(self.at) if self.at else now
        return self._parse_time_today(now, self.at_time or "00:00")

    # ==================== 内部计算 ====================

    def _next_daily(self, now: datetime) -> datetime:
        target = self._parse_time_today(now, self.time_start or self.at_time or "00:00")
        if target <= now:
            target += timedelta(days=1)
        return target

    def _next_weekly(self, now: datetime) -> datetime:
        t_str = self.time_start or self.at_time or "00:00"
        target_time = self._parse_time_today(now, t_str)
        current_wday = now.isoweekday()
        weekdays = sorted(self.weekdays or [1])
        for wd in weekdays:
            if wd >= current_wday:
                days_ahead = wd - current_wday
                candidate = target_time + timedelta(days=days_ahead)
                if candidate > now:
                    return candidate
        days_ahead = 7 - current_wday + weekdays[0]
        return target_time + timedelta(days=days_ahead)

    def _next_monthly(self, now: datetime) -> datetime:
        target_time = self._parse_time(now, self.at_time or "00:00")
        month_days = sorted(self.month_days or [1])
        # 简化：下月第一个匹配日
        current_day = now.day
        for md in month_days:
            if md > current_day:
                try:
                    return now.replace(day=md, hour=target_time.hour, minute=target_time.minute, second=0)
                except ValueError:
                    continue
        # 下月
        import calendar
        next_month = now.month + 1
        next_year = now.year
        if next_month > 12:
            next_month = 1
            next_year += 1
        last_day = calendar.monthrange(next_year, next_month)[1]
        target_day = min(month_days[0], last_day)
        return datetime(next_year, next_month, target_day, target_time.hour, target_time.minute, 0)

    def _next_interval_days(self, now: datetime) -> datetime:
        target = self._parse_time_today(now, self.time_start or self.at_time or "00:00")
        days = self.days or 1
        if target <= now:
            target += timedelta(days=1)
        return target + timedelta(days=days - 1)

    def get_initial_next_run(self, now: datetime = None) -> datetime:
        """获取首次 next_run_time（注册时调用）。"""
        if now is None:
            now = datetime.now()
        if self.type == "once":
            if self.at:
                try:
                    at_clean = self.at.replace(" ", "T").replace("/", "-")
                    return datetime.fromisoformat(at_clean)
                except (ValueError, TypeError):
                    pass
            return now
        if self.type == "monthly_start":
            return self._next_monthly_start(now)
        if self.type == "special":
            return now  # 活动限定：立即
        return self._parse_time_today(now, self.time_start or self.at_time or "00:00")

    def _next_monthly_start(self, now: datetime) -> datetime:
        """每月1号 00:00。"""
        if now.month == 12:
            return now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def _parse_time_today(now: datetime, time_str: str) -> datetime:
        h, m = map(int, time_str.split(":"))
        return now.replace(hour=h, minute=m, second=0, microsecond=0)

    # ==================== 序列化 ====================

    def to_dict(self) -> dict:
        d = {"type": self.type}
        if self.time_start: d["time_start"] = self.time_start
        if self.time_end: d["time_end"] = self.time_end
        if self.weekdays: d["weekdays"] = self.weekdays
        if self.days: d["days"] = self.days
        if self.hours: d["hours"] = self.hours
        if self.at: d["at"] = self.at
        if self.window: d["window"] = self.window
        if self.max_daily: d["max_daily"] = self.max_daily
        if self.max_total: d["max_total"] = self.max_total
        if self.cooldown: d["cooldown"] = self.cooldown
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RepeatRule":
        return cls(
            type=d.get("type", "daily"),
            time_start=d.get("time_start") or d.get("at_time"),
            time_end=d.get("time_end"),
            weekdays=d.get("weekdays"),
            month_days=d.get("month_days"),
            days=d.get("days"),
            hours=d.get("hours"),
            at=d.get("at"),
            times=d.get("times", 1),
            window=d.get("window"),
            max_daily=d.get("max_daily"),
            max_total=d.get("max_total"),
            cooldown=d.get("cooldown"),
        )
