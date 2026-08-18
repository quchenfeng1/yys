"""trigger 触发语义验证（2026-08-16 改写：老任务文件已删除，只保留调度层语义）。"""
import sys, os, time
from pathlib import Path

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from core.event_bus import EventBus
from core.scheduler import Scheduler, RepeatConfig, TaskConfig
from core.trigger_watcher import TriggerWatcher


class FakeStore:
    def __init__(self):
        self.data = {}
    def load(self): pass
    def save(self, data): self.data = data
    def get(self, name): return self.data.get(name)
    def get_or_create(self, name): return self.data.setdefault(name, {})
    def update(self, name, **kw): self.data.setdefault(name, {}).update(kw)


def test_trigger_semantics():
    print("\n── trigger 触发语义 ──")
    bus = EventBus()
    s = Scheduler(event_bus=bus, store=FakeStore())
    # 手动触发任务：无 trigger_templates
    s._tasks["manual_trigger_test"] = TaskConfig(
        name="manual_trigger_test", category="special",
        repeat=RepeatConfig(type="trigger"),
    )
    # 识图触发任务：有 trigger_templates
    s._tasks["image_trigger_test"] = TaskConfig(
        name="image_trigger_test", category="special",
        repeat=RepeatConfig(type="trigger",
                            trigger_templates=["trigger/image_entry_a", "trigger/image_entry_b"]),
    )
    s.load_state()

    # ① 初始均无 next_run（等待触发）→ 统一归入已失效区「待触发」并置顶
    assert "manual_trigger_test" not in s._next_run
    assert "image_trigger_test" not in s._next_run
    up = [x["name"] for x in s.get_upcoming()]
    assert "manual_trigger_test" not in up and "image_trigger_test" not in up, \
        f"未触发不应在未开始区: {up}"
    inv = s.get_invalid_tasks()
    statuses = {x["name"]: x["status"] for x in inv}
    assert statuses.get("manual_trigger_test") == "待触发", f"got {statuses}"
    assert statuses.get("image_trigger_test") == "待触发", f"got {statuses}"
    assert set(x["name"] for x in inv[:2]) == {"manual_trigger_test", "image_trigger_test"}, \
        f"trigger 应置顶: {inv}"
    print("① PASS 两个 trigger 初始无 next_run → 已失效区「待触发」并置顶")

    # ② TriggerWatcher 只收集识图任务（有 trigger_templates）——
    #    模拟 run_controller.start_trigger_watcher 的过滤：无模板=仅手动触发，不监控
    class FakeRec:
        def match_any(self, names):
            return []
    tw = TriggerWatcher(recognizer=FakeRec(), event_bus=bus, interval=0.2)
    # 多对多索引：{模板路径: [任务,...]}（模拟 run_controller 构建）
    tpl_tasks: dict[str, list[str]] = {}
    for c in s.get_all_tasks():
        if c.repeat and c.repeat.type == 'trigger' and c.repeat.trigger_templates:
            for t in c.repeat.trigger_templates:
                tpl_tasks.setdefault(t, []).append(c.name)
    tw.start(tpl_tasks)
    assert "trigger/image_entry_a" in tw._tpl_tasks, \
        f"应监控识图模板: {tw._tpl_tasks.keys()}"
    assert tw._tpl_tasks["trigger/image_entry_a"] == ["image_trigger_test"]
    task_names = {n for names in tw._tpl_tasks.values() for n in names}
    assert "manual_trigger_test" not in task_names, "手动触发任务不应被监控"
    print("② PASS TriggerWatcher 只监控识图任务（image_trigger_test）")
    tw.stop()

    # ③ 手动触发：update_next_run(now) → 入队
    import datetime
    s.update_next_run("manual_trigger_test", datetime.datetime.now(s._timezone))
    names = [t.name for t in s.build_schedule(publish=False)]
    assert "manual_trigger_test" in names, f"手动触发应入队: {names}"
    print("③ PASS 手动触发 update_next_run(now) → 到期入队")

    # ④ TRIGGER_DETECTED 事件 → 识图任务入队
    bus.publish("trigger_detected", source="trigger_watcher", task_name="image_trigger_test")
    time.sleep(0.6)
    names = [t.name for t in s.build_schedule(publish=False)]
    assert "image_trigger_test" in names, f"识图触发应入队: {names}"
    print("④ PASS TRIGGER_DETECTED 事件 → 识图任务入队")


def main():
    test_trigger_semantics()
    print("\n🎉 trigger 特殊任务语义验证 4/4 通过")


if __name__ == "__main__":
    main()
