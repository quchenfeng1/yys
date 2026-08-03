"""trigger 特殊条件触发全链路临时验证（验证后可删除）"""
import time, sys, os
from datetime import datetime
# 将主程序根目录加入 sys.path（脚本位于 tools/ 下）
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)
from core.event_bus import EventBus
from core.scheduler import Scheduler, RepeatConfig, TaskConfig, ScheduleStatus
from core.trigger_watcher import TriggerWatcher


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
        name="trig_test", display_name="触发测试", category="special", priority=5,
        repeat=RepeatConfig(type="trigger", trigger_templates=["trigger/red_dot"]),
    )
    s._tasks["trig_test"] = cfg
    s.load_state()

    # ① 初始无 next_run（未触发 → 已失效区「待触发」置顶，不进未开始）
    nrt = s._calc_initial_next_run(cfg)
    assert nrt is None, f"got {nrt}"
    assert "trig_test" not in s._next_run
    up = [x["name"] for x in s.get_upcoming()]
    assert "trig_test" not in up, f"未触发不应在未开始区: {up}"
    inv = s.get_invalid_tasks()
    entry = [x for x in inv if x["name"] == "trig_test"]
    assert entry and entry[0]["status"] == "待触发", f"got {entry}"
    assert inv[0]["name"] == "trig_test", f"trigger 应置顶: {inv}"
    print("① PASS 初始无 next_run → 已失效区「待触发」并置顶")

    # ② 手动触发 → 入队
    s.update_next_run("trig_test", datetime.now(s._timezone))
    names = [t.name for t in s.build_schedule(publish=False)]
    assert "trig_test" in names, f"got {names}"
    print("② PASS 手动触发 update_next_run(now) → 到期入队")

    # ③ mark_done → COMPLETED + 清空
    s.mark_done("trig_test", True)
    assert s.task_status.get("trig_test") == ScheduleStatus.COMPLETED
    assert "trig_test" not in s._next_run
    print("③ PASS mark_done → COMPLETED + 清空 next_run")

    # ④ 已失效标注（执行完 → 等待下次触发，仍置顶）
    inv = s.get_invalid_tasks()
    entry = [x for x in inv if x["name"] == "trig_test"]
    assert entry and entry[0]["status"] == "等待下次触发", f"got {entry}"
    assert entry[0]["detail"] == "外部触发后重新激活", f"got {entry}"
    assert inv[0]["name"] == "trig_test", f"trigger 应置顶: {inv}"
    print("④ PASS 已失效区标注 [等待下次触发] · 外部触发后重新激活（置顶）")

    # ⑤ 事件触发
    bus.publish("trigger_detected", source="trigger_watcher", task_name="trig_test")
    time.sleep(0.8)
    names = [t.name for t in s.build_schedule(publish=False)]
    assert "trig_test" in names, f"got {names}"
    print("⑤ PASS trigger_detected 事件 → 置为到期入队")

    # ⑥ TriggerWatcher 命中
    s.mark_done("trig_test", True)

    class FakeRec:
        def match_any(self, names):
            return [("trigger/red_dot", object())]

    tw = TriggerWatcher(recognizer=FakeRec(), event_bus=bus, interval=0.3)
    tw.start([("trig_test", ["trigger/red_dot"])])
    time.sleep(1.0)
    tw.stop()
    time.sleep(0.5)
    names = [t.name for t in s.build_schedule(publish=False)]
    assert "trig_test" in names, f"got {names}"
    print("⑥ PASS TriggerWatcher 识图命中 → 自动触发入队")

    # ⑦ 无任务不启动线程
    tw2 = TriggerWatcher(recognizer=FakeRec(), event_bus=bus)
    tw2.start([])
    assert not tw2.is_running()
    print("⑦ PASS 无触发任务 → 监控线程不启动")

    print("\n🎉 trigger 全链路验证 7/7 通过")


if __name__ == "__main__":
    main()
