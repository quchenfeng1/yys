"""once_test 四步链路（含触发识图任务）+ on_enter 调度语义 验证（临时）"""
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
from core.scheduler import Scheduler, RepeatConfig, TaskConfig, ScheduleStatus
from tasks.base.task_context import TaskContext

NEEDED = {
    "common/award/award_entry": (150, 60),
    "common/award/award_panel": (180, 100),
    "common/award/daily_reward_btn": (150, 60),
    "common/ui/back_btn": (120, 60),
    "common/scene/home": (180, 100),
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


class FakeStore:
    def __init__(self):
        self.data = {}
    def load(self): pass
    def save(self, data): self.data = data
    def get(self, name): return self.data.get(name)
    def get_or_create(self, name): return self.data.setdefault(name, {})
    def update(self, name, **kw): self.data.setdefault(name, {}).update(kw)


def test_task_graph():
    print("── [A] once_test 三步链路（合成素材）──")
    tmp = tempfile.mkdtemp(prefix="once_test_assets_")
    templates = generate(tmp)
    conn = MockConnection(templates)
    rec = Recognizer(asset_dir=tmp, connection=conn, screenshot_ttl=0.05, result_cache_ttl=0.01)
    ad = AntiDetect(min_interval=0.001, max_interval=0.002,
                    action_jitter=False, random_fail_rate=0)
    ex = Executor(recognizer=rec, anti_detect=ad, connection=conn, dry_run=False)

    def _on_log(**kw):
        print(f"  [{kw.get('level', 'info'):7s}] {kw.get('message', '')}")
    get_global_bus().subscribe(Events.LOG_RECORD, _on_log)

    from tasks.special.once_test import build_graph
    ctx = TaskContext(task_id="once_test", task_name="once_test",
                      executor=ex, recognizer=rec, stop_event=threading.Event())
    result = build_graph(ctx).run(ctx)
    assert result.status.value == "success", f"应为 success: {result.status}"
    print(f"  ✅ 四步执行结果: {result.status} · {result.reason}")
    return conn


def test_on_enter_semantics():
    print("\n── [B] on_enter 调度语义 ──")
    bus = EventBus()
    s = Scheduler(event_bus=bus, store=FakeStore())
    cfg = TaskConfig(
        name="once_test", display_name="单次测试", category="special",
        repeat=RepeatConfig(type="on_enter"),
    )
    s._tasks["once_test"] = cfg
    s.load_state()

    # ① load_state 后 next_run=now（每次启动激活）
    nrt = s._next_run.get("once_test")
    assert nrt is not None, "on_enter 启动应重置 next_run=now"
    print("① PASS load_state 后 on_enter 任务激活（next_run=now）")

    # ② build_schedule 应 DUE
    due = [t.name for t in s.build_schedule(publish=False)]
    assert "once_test" in due, f"应为 DUE: {due}"
    print("② PASS on_enter 任务到期入队")

    # ③ mark_done → COMPLETED + 清空 next_run
    s.mark_done("once_test", True)
    assert s.task_status.get("once_test") == ScheduleStatus.COMPLETED
    assert "once_test" not in s._next_run
    print("③ PASS mark_done → COMPLETED + 清空 next_run")

    # ④ 已失效区标注"本轮已完成"
    inv = s.get_invalid_tasks()
    entry = [x for x in inv if x["name"] == "once_test"]
    assert entry and entry[0]["status"] == "本轮已完成", f"got {entry}"
    print(f"④ PASS 已失效标注: {entry[0]['status']} · {entry[0]['detail']}")

    # ⑤ build_schedule 不再入队（状态过滤拦截）
    due = [t.name for t in s.build_schedule(publish=False)]
    assert "once_test" not in due, f"不应再次入队: {due}"
    print("⑤ PASS 执行后不再反复入队")

    # ⑥ 再次 load_state（模拟重启）→ 重新激活
    s._store.data = {}
    s.load_state()
    nrt = s._next_run.get("once_test")
    assert nrt is not None, "重启后应重新激活"
    print("⑥ PASS 重启后 on_enter 任务重新激活（每次启动执行一次）")


def test_trigger_image():
    print("\n── [C] once_test 触发识图任务（trigger_detected → 05 → 到期入队）──")
    from core.event_bus import get_global_bus
    from tasks.special.once_test import build_graph, TRIGGER_TASK

    bus = get_global_bus()
    s = Scheduler(event_bus=bus, store=FakeStore())
    s._tasks[TRIGGER_TASK] = TaskConfig(
        name=TRIGGER_TASK, category="special",
        repeat=RepeatConfig(type="trigger",
                            trigger_templates=["trigger/image_entry_a", "trigger/image_entry_b"]),
    )
    s.load_state()
    assert TRIGGER_TASK not in s._next_run, "识图任务初始无 next_run"

    # 构造 once_test 运行环境并完整执行（四步，含发布 trigger_detected）
    tmp = tempfile.mkdtemp(prefix="once_trigger_assets_")
    templates = generate(tmp)
    conn = MockConnection(templates)
    rec = Recognizer(asset_dir=tmp, connection=conn, screenshot_ttl=0.05, result_cache_ttl=0.01)
    ad = AntiDetect(min_interval=0.001, max_interval=0.002,
                    action_jitter=False, random_fail_rate=0)
    ex = Executor(recognizer=rec, anti_detect=ad, connection=conn, dry_run=False)
    ctx = TaskContext(task_id="once_test", task_name="once_test",
                      executor=ex, recognizer=rec, stop_event=threading.Event())
    result = build_graph(ctx).run(ctx)
    assert result.status.value == "success", f"once_test 应为 success: {result.status}"
    print(f"  ✅ once_test 四步执行: {result.status} · {result.reason}")

    time.sleep(0.8)  # EventBus 发布是异步的
    # 断言：识图任务被置为到期（05 订阅 trigger_detected → update_next_run(now)）→ 入队
    assert TRIGGER_TASK in s._next_run, f"识图任务应被触发: {s._next_run}"
    due = [t.name for t in s.build_schedule(publish=False)]
    assert TRIGGER_TASK in due, f"识图任务应到期入队: {due}"
    print("① PASS once_test 发布 trigger_detected → 识图任务置为到期入队")

    # 收尾：识图任务执行后回到等待触发
    s.mark_done(TRIGGER_TASK, True)
    assert TRIGGER_TASK not in s._next_run
    inv = s.get_invalid_tasks()
    entry = [x for x in inv if x["name"] == TRIGGER_TASK]
    assert entry and entry[0]["status"] == "等待下次触发", f"got {entry}"
    print("② PASS 识图任务执行后 → 已失效[等待下次触发]")


def main():
    test_task_graph()
    test_on_enter_semantics()
    test_trigger_image()
    print("\n🎉 once_test 四步链路 + on_enter 语义 + 触发识图任务验证 8/8 通过")


if __name__ == "__main__":
    main()
