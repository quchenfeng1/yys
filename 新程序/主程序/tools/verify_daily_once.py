"""daily 积压天数当天不重复执行 验证（临时，验证后可保留）"""
import sys, os
from datetime import datetime, timedelta
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from core.event_bus import EventBus
from core.scheduler import Scheduler, RepeatConfig, TaskConfig, ScheduleStatus


class FakeStore:
    def __init__(self):
        self.data = {}
    def load(self): pass
    def save(self, data): self.data = data
    def get(self, name): return self.data.get(name)
    def get_or_create(self, name): return self.data.setdefault(name, {})
    def update(self, name, **kw): self.data.setdefault(name, {}).update(kw)


def main():
    bus = EventBus()
    s = Scheduler(event_bus=bus, store=FakeStore())

    cfg = TaskConfig(
        name="daily_test", display_name="日常测试", category="daily",
        repeat=RepeatConfig(type="daily", value=1),
        time_start="06:00", time_end="23:59",
    )
    s._tasks["daily_test"] = cfg
    s.load_state()
    now = datetime.now(s._timezone)

    # 模拟积压：next_run 停在 2 天前 06:00（08-01，今天 08-03）
    s._next_run["daily_test"] = (now - timedelta(days=2)).replace(
        hour=6, minute=0, second=0, microsecond=0)

    # ① 修复前问题复现检查：is_due 应为 True（积压到期）
    assert s.is_due("daily_test"), "积压的 next_run 应到期"
    print("① PASS 积压 next_run 到期（等待补执行）")

    # ② mark_done 一次 → next_run 必须跳到未来（跳过积压天数）
    s.mark_done("daily_test", True)
    nrt = s._next_run.get("daily_test")
    assert nrt is not None and nrt > now, f"推进后应在未来: {nrt} vs now {now}"
    print(f"② PASS 执行一次后 next_run={nrt.strftime('%m-%d %H:%M')} > now（跳过积压天数）")

    # ③ 推进后当天不再到期（当天只执行一次）
    assert not s.is_due("daily_test"), "推进到未来后不应再到期"
    due = [t.name for t in s.build_schedule(publish=False)]
    assert "daily_test" not in due, f"当天不应再入队: {due}"
    print("③ PASS 推进后当天不再到期/入队（当天仅执行一次）")

    # ④ 队列只应入队一次（填充线程不会再次拾取）
    assert s._today_count.get("daily_test") == 1, s._today_count
    print("④ PASS today_count=1（当天只执行一次）")

    print("\n🎉 daily 积压修复验证 4/4 通过")


if __name__ == "__main__":
    main()
