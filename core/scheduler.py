"""
调度引擎主入口（05-定时模块）

纯调度引擎——根据 RepeatRule 和 next_run_time 决定"何时执行哪个任务"。
不管运行控制（那归 RunController）。

核心机制：
  - 双重判据：now >= next_run_time AND (无 window 或在 window 内)
  - 失败不推进：mark_done(success=False) 不推进 next_run_time
  - 持久化：每次状态变更立即写盘，重启恢复

对应解耦文档：模块说明/05-定时模块.md
"""

from datetime import datetime, timedelta, date
from typing import Optional

from core.event_bus import event_bus, Events
from core.repeat_rule import RepeatRule
from core.task_state import TaskStateStore, TaskState
from core.logger import get_logger

logger = get_logger("scheduler")


class Scheduler:
    """时间调度引擎。纯调度，不管运行控制。"""

    def __init__(self, config, state_manager):
        self._config = config
        self._state_manager = state_manager
        self._store = TaskStateStore()
        self._tasks: dict[str, dict] = {}  # task_name → {repeat, priority, enabled, ...}
        self._last_daily_reset: Optional[date] = None  # 上次每日重置日期

    # ==================== 状态持久化 ====================

    def load_state(self):
        """启动时从 task_state.json 恢复执行记录。"""
        self._store.load()

    def save_state(self):
        """原子写盘。"""
        self._store.save()

    # ==================== 任务注册 ====================

    def register_task(self, name: str, repeat: RepeatRule, priority: int = 10,
                      category: str = "", enabled: bool = True, **kwargs):
        """注册任务到调度器。"""
        self._tasks[name] = {
            "repeat": repeat,
            "priority": priority,
            "category": category,
            "enabled": enabled,
            **kwargs,
        }
        # 初始化 next_run_time
        st = self._store.get(name)
        if st is None or st.next_run_time is None:
            if repeat.type != "expire_at":
                initial = repeat.get_initial_next_run()
                self._store.set_next_run(name, initial)

    def get_task_repeat(self, task_name: str) -> Optional[RepeatRule]:
        t = self._tasks.get(task_name)
        return t["repeat"] if t else None

    # ==================== 从配置加载 ====================

    def load_tasks_from_config(self):
        """从 tasks.yaml 加载所有任务并注册到调度器。

        应在启动时调用，在 load_state() 之前。
        """
        tasks_cfg = self._config.get_tasks_config()
        if not tasks_cfg:
            return

        logger.info("从 tasks.yaml 加载任务配置...")
        count = 0
        categories = tasks_cfg.get("default_order", ["daily", "permanent", "special", "event"])
        for cat in categories:
            task_list = tasks_cfg.get(cat, [])
            for t_cfg in task_list:
                name = t_cfg.get("name")
                if not name:
                    continue
                repeat_raw = t_cfg.get("repeat", {})
                repeat = RepeatRule(
                    type=repeat_raw.get("type", "daily"),
                    time_start=repeat_raw.get("time_start") or repeat_raw.get("at_time"),
                    time_end=repeat_raw.get("time_end"),
                    weekdays=repeat_raw.get("weekdays"),
                    days=repeat_raw.get("days"),
                    hours=repeat_raw.get("hours"),
                    at=repeat_raw.get("at"),
                    window=repeat_raw.get("window"),
                    max_daily=repeat_raw.get("max_daily"),
                    max_total=repeat_raw.get("max_total"),
                    cooldown=repeat_raw.get("cooldown"),
                )
                self.register_task(
                    name=name,
                    repeat=repeat,
                    priority=t_cfg.get("priority", 10),
                    category=cat,
                    enabled=t_cfg.get("enabled", False),
                    team_id=t_cfg.get("team_id", ""),
                )
                count += 1
        logger.info(f"已加载 {count} 个任务到调度器")

    # ==================== 每日重置 ====================

    def check_daily_reset(self):
        """检查是否需要每日重置（跨天时重置 today_count）。"""
        today = date.today()
        if self._last_daily_reset != today:
            self._store.reset_daily_counters()
            self._last_daily_reset = today
            self._store.save()
            event_bus.publish(Events.DAILY_RESET, date=today.isoformat())
            logger.info(f"每日重置已执行: {today}")

    def import_calendar(self, events: list[dict]) -> int:
        """导入游戏活动日历，自动更新任务 active_range / window。"""
        updated = 0
        for ev in events:
            name = ev.get("name", "")
            if not name:
                continue
            existing = self._tasks.get(name)
            if existing:
                existing["active_range"] = [ev.get("start"), ev.get("end")]
                existing["window"] = ev.get("window")
                updated += 1
            else:
                repeat = RepeatRule(type="special",
                    window={"date_start": ev.get("start"), "date_end": ev.get("end")})
                self.register_task(name=name, repeat=repeat, priority=8,
                    category="special", enabled=True)
                updated += 1
        self._store.save()
        logger.info(f"活动日历导入完成: {updated} 个任务")
        return updated

    # ==================== 日程表 ====================

    def build_schedule(self, date=None) -> list[dict]:
        """扫描启用任务 → 过滤 → 排序 → 生成可执行队列。"""
        self.check_daily_reset()  # 先检查跨天重置

        now = datetime.now()
        candidates = []

        for name, task in self._tasks.items():
            if not task["enabled"]:
                continue
            if self.is_due(name, now) and self.check_times_limit(name):
                candidates.append({
                    "name": name,
                    "priority": task["priority"],
                    "category": task.get("category", ""),
                    "next_run": self.get_next_run_time(name),
                })

        # 按 priority 升序 → 同优先级按默认顺序（daily > permanent > special > event）
        order = {"daily": 0, "permanent": 1, "special": 2, "event": 3}
        candidates.sort(key=lambda t: (t["priority"], order.get(t["category"], 99)))

        # 发布日程更新事件（UI 订阅后展示任务队列）
        event_bus.publish(Events.SCHEDULE_UPDATED, queue=[
            {
                "task": c["name"],
                "priority": c["priority"],
                "next_run": c["next_run"].isoformat() if c["next_run"] else None,
                "category": c["category"],
            }
            for c in candidates
        ])
        return candidates

    def get_next_task(self) -> Optional[str]:
        """获取当前应执行的下一个任务名。"""
        schedule = self.build_schedule()
        if schedule:
            self._state_manager.set_state("schedule_queue", [s["name"] for s in schedule])
            return schedule[0]["name"]
        return None

    # ==================== 判断 ====================

    def is_due(self, task_name: str, now: datetime = None) -> bool:
        """双重判据：now >= next_run_time AND (无 window 或在 window 内)。"""
        if now is None:
            now = datetime.now()
        task = self._tasks.get(task_name)
        if not task:
            return False

        next_run = self.get_next_run_time(task_name)
        if next_run is None:
            # once 类型完成后 next_run 为 None = 已完成，不再调度
            repeat = task["repeat"]
            if repeat.type == "once":
                return False
            return True  # 其他类型无 next_run_time = 立即执行
        if now < next_run:
            return False

        # 检查时间/日期范围约束
        repeat = task["repeat"]
        # daily/weekly: 每日时间范围
        if repeat.type in ("daily", "weekly"):
            ts = getattr(repeat, 'time_start', '') or '00:00'
            te = getattr(repeat, 'time_end', '') or '23:59'
            ts = ts.zfill(5) if len(ts) < 5 else ts
            te = te.zfill(5) if len(te) < 5 else te
            now_time = now.strftime("%H:%M")
            if not (ts <= now_time <= te):
                return False
        # special: 仅日期范围（活动限定）
        if repeat.type == "special" and repeat.window:
            w = repeat.window
            today = now.strftime("%Y-%m-%d")
            ds = w.get("date_start", "")
            de = w.get("date_end", "")
            if ds and today < ds: return False
            if de and today > de: return False
        # legacy: window 中仍有 time_start/time_end
        if repeat.window and repeat.type not in ("special",):
            w = repeat.window
            ts = (w.get("time_start", "") or "00:00")
            te = (w.get("time_end", "") or "23:59")
            ts = ts.zfill(5) if len(ts) < 5 else ts
            te = te.zfill(5) if len(te) < 5 else te
            if not (ts <= now.strftime("%H:%M") <= te):
                return False
        return True

    def check_times_limit(self, task_name: str) -> bool:
        """是否未达次数上限。"""
        task = self._tasks.get(task_name)
        if not task:
            return False
        st = self._store.get_or_create(task_name)
        repeat = task["repeat"]

        if repeat.max_daily and st.today_count >= repeat.max_daily:
            return False
        if repeat.max_total and st.success_count >= repeat.max_total:
            return False
        return True

    # ==================== 推进 ====================

    def mark_done(self, task_name: str, success: bool = True):
        """标记完成：success=True 按 RepeatRule 推进 next_run_time；
        False 则添加 5 分钟冷却防止无限重试。"""
        task = self._tasks.get(task_name)
        if not task:
            return

        now = datetime.now()
        repeat = task["repeat"]
        st = self._store.get_or_create(task_name)

        st.last_run_time = now.isoformat()
        st.last_success = success

        if success:
            st.today_count += 1
            st.success_count += 1
            st.fail_streak = 0
            next_run = repeat.calc_next_run(now, success=True)
            self._store.set_next_run(task_name, next_run)
        else:
            # 失败：添加递增冷却时间，防止无限重试
            st.fail_streak = getattr(st, 'fail_streak', 0) + 1
            cooldown_minutes = min(st.fail_streak * 5, 60)  # 最多冷却 60 分钟
            next_retry = now + timedelta(minutes=cooldown_minutes)
            self._store.set_next_run(task_name, next_retry)
            logger.warning(
                f"任务 {task_name} 失败 (连续 {st.fail_streak} 次)，"
                f"{cooldown_minutes} 分钟后重试")

        self._store.save()

    def update_next_run(self, task_name: str, next_run_time: datetime):
        """手动设置 next_run_time（UI 修改/跳过本次时调用）。"""
        self._store.set_next_run(task_name, next_run_time)
        self._store.save()
        event_bus.publish(Events.SCHEDULE_UPDATED, task=task_name)

    def report_expire(self, task_name: str, expire_at: datetime):
        """任务上报外部失效时间（结界卡等）。"""
        st = self._store.get_or_create(task_name)
        st.expire_at = expire_at.isoformat()
        self._store.set_next_run(task_name, expire_at)
        self._store.save()

    # ==================== 查询 ====================

    def get_next_run_time(self, task_name: str) -> Optional[datetime]:
        """读取 next_run_time。"""
        st = self._store.get(task_name)
        if st and st.next_run_time:
            return datetime.fromisoformat(st.next_run_time)
        return None

    def get_task_state(self, task_name: str) -> Optional[TaskState]:
        return self._store.get(task_name)

    def get_task_status(self, task_name: str) -> str:
        """任务状态：待执行 / 等待中 / 已完成 / 已跳过。"""
        task = self._tasks.get(task_name)
        if not task or not task["enabled"]:
            return "disabled"
        if not self.check_times_limit(task_name):
            return "limit_reached"

        now = datetime.now()
        next_run = self.get_next_run_time(task_name)
        if next_run and now < next_run:
            return "waiting"
        if self.is_due(task_name, now):
            return "due"
        return "waiting"

    def get_all_tasks(self) -> list[dict]:
        """获取所有已注册任务（供 UI 展示），包含完整字段。"""
        result = []
        for name, task in self._tasks.items():
            st = self._store.get(name)
            result.append({
                "name": name,
                "category": task.get("category", ""),
                "priority": task.get("priority", 10),
                "enabled": task["enabled"],
                "repeat_type": task["repeat"].type if task.get("repeat") else "",
                "repeat": task["repeat"].to_dict() if task["repeat"] else None,
                "next_run": self.get_next_run_time(name),
                "status": self.get_task_status(name),
                "team_id": task.get("team_id", ""),
                "today_count": st.today_count if st else 0,
                "success_count": st.success_count if st else 0,
            })
        return result

    # ==================== 重置 ====================

    def reset_daily_counters(self):
        """每日 00:00 重置 today_count=0。"""
        self._store.reset_daily_counters()
        self._store.save()
        event_bus.publish(Events.DAILY_RESET)
