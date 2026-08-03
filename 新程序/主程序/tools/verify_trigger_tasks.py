"""两个 trigger 特殊任务验证（临时）：手动触发 / 识图触发"""
import sys, os, tempfile, threading, time
from pathlib import Path

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

import numpy as np
import cv2

from core.event_bus import EventBus, get_global_bus
from core.events import Events
from core.anti_detect import AntiDetect
from core.recognizer import Recognizer
from core.executor import Executor
from core.scheduler import Scheduler, RepeatConfig, TaskConfig
from core.trigger_watcher import TriggerWatcher
from tasks.base.task_context import TaskContext

NEEDED = {
    "common/ui/test_button": (140, 60),
    "common/scene/confirm": (140, 60),
    "trigger/image_entry_a": (160, 80),
    "trigger/image_entry_b": (160, 80),
}


def _make_template(name, size, seed):
    w, h = size
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (255, 255, 255), 2)
    return img


def generate(target_dir):
    templates = {}
    for name, size in NEEDED.items():
        img = _make_template(name, size, sum(ord(c) for c in name))
        templates[name] = img
        p = Path(target_dir) / f"{name}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(p), img)
    return templates


class MockConnection:
    SCREEN_W, SCREEN_H = 1080, 1920

    def __init__(self, templates):
        self.templates = templates
        self.clicks = []
        self._screen = None

    def _build_screen(self):
        screen = np.full((self.SCREEN_H, self.SCREEN_W, 3), 30, dtype=np.uint8)
        y = 60
        for name, tpl in self.templates.items():
            h, w = tpl.shape[:2]
            if y + h > self.SCREEN_H:
                break
            screen[y:y + h, 100:100 + w] = tpl
            y += h + 40
        return screen

    def screenshot(self, use_cache=False):
        if self._screen is None or not use_cache:
            self._screen = self._build_screen()
        return self._screen.copy()

    def click(self, x, y):
        self.clicks.append((int(x), int(y)))

    def swipe(self, x1, y1, x2, y2, duration=None):
        pass

    def echo(self): return True
    def is_connected(self): return True
    def switch_device(self, dev_id): return True
    def input_text(self, text): pass
    def input_key(self, key): pass


def _run_task(name, mod_name):
    tmp = tempfile.mkdtemp(prefix="trig_assets_")
    templates = generate(tmp)
    conn = MockConnection(templates)
    rec = Recognizer(asset_dir=tmp, connection=conn, screenshot_ttl=0.05, result_cache_ttl=0.01)
    ad = AntiDetect()
    ex = Executor(recognizer=rec, anti_detect=ad, connection=conn, dry_run=False)
    ctx = TaskContext(task_id=name, task_name=name,
                      executor=ex, recognizer=rec, stop_event=threading.Event())
    import importlib
    mod = importlib.import_module(mod_name)
    result = mod.build_graph(ctx).run(ctx)
    assert result.status.value == "success", f"{name} 应为 success: {result.status}"
    print(f"  ✅ {name} 四步链路: {result.status} · {result.reason}")
    return conn


class FakeStore:
    def __init__(self):
        self.data = {}
    def load(self): pass
    def save(self, data): self.data = data
    def get(self, name): return self.data.get(name)
    def get_or_create(self, name): return self.data.setdefault(name, {})
    def update(self, name, **kw): self.data.setdefault(name, {}).update(kw)


def test_trigger_semantics():
    print("\n── [C] trigger 触发语义 ──")
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
    trigger_tasks = [
        (c.name, list(c.repeat.trigger_templates or []))
        for c in s.get_all_tasks()
        if c.repeat and c.repeat.type == 'trigger' and c.repeat.trigger_templates
    ]
    tw.start(trigger_tasks)
    assert "image_trigger_test" in tw._tasks, f"应监控识图任务: {tw._tasks.keys()}"
    assert "manual_trigger_test" not in tw._tasks, "手动触发任务不应被监控"
    print("② PASS TriggerWatcher 只监控识图任务（image_trigger_test）")
    tw.stop()

    # ③ 手动触发：update_next_run(now) → 入队
    s.update_next_run("manual_trigger_test", s._timezone.localize(None) if hasattr(s._timezone, 'localize') else __import__('datetime').datetime.now(s._timezone))
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
    print("── [A] 手动触发测试任务 ──")
    _run_task("manual_trigger_test", "tasks.special.manual_trigger_test")
    print("── [B] 识图触发测试任务 ──")
    _run_task("image_trigger_test", "tasks.special.image_trigger_test")
    test_trigger_semantics()
    print("\n🎉 两个 trigger 特殊任务验证 4/4 通过")


if __name__ == "__main__":
    main()
