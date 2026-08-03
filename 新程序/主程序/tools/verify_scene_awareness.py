"""场景感知（Scene Awareness）验证：current_scene 状态维护 + scene_updated 事件 + 步骤 scene_probe。

链路（说明书 04 §4.9 + 14 §3.4 + 07）：
  任务步骤声明 scene_probe → TaskGraph 步骤前调 executor.probe_scene
    → 命中场景 → 发布 scene_updated(scene=X)
    → 07-state_manager 订阅 → set_current_scene → current_scene + last_known_scene
    → 11-UI 订阅 scene_updated → 状态栏显示（此处验证事件与状态）
"""
import sys, os, tempfile, threading, time
from pathlib import Path

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

import numpy as np
import cv2

from core.event_bus import EventBus
from core.events import Events
from core.anti_detect import AntiDetect
from core.recognizer import Recognizer
from core.executor import Executor
from core.state_manager import StateManager
from core.state_schema import StateKeys
from tasks.base.task_context import TaskContext
from tasks.base.task_step import TaskStep, StepResult
from tasks.base.task_graph import TaskGraph

NEEDED = {
    "common/scene/home": (180, 100),
    "common/scene/battle": (180, 100),
}


def _make_template(name, size, seed):
    w, h = size
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (255, 255, 255), 2)
    return img


def _generate(target_dir):
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

    def click(self, x, y): pass
    def swipe(self, *a, **k): pass
    def echo(self): return True
    def is_connected(self): return True
    def switch_device(self, dev_id): return True


def main():
    print("── [A] probe_scene / detect_scene 命中发布 scene_updated ──")
    bus = EventBus()
    tmp = tempfile.mkdtemp(prefix="scene_aware_assets_")
    templates = _generate(tmp)
    conn = MockConnection(templates)
    rec = Recognizer(asset_dir=tmp, connection=conn, screenshot_ttl=0.05, result_cache_ttl=0.01)
    ad = AntiDetect()
    ex = Executor(recognizer=rec, anti_detect=ad, connection=conn, dry_run=False, event_bus=bus)

    received = []
    bus.subscribe(Events.SCENE_UPDATED, lambda **kw: received.append(kw.get("scene", "")))

    scene = ex.probe_scene(["common/scene/home", "common/scene/battle"])
    assert scene == "common/scene/home", f"应命中主界面: {scene}"
    time.sleep(0.5)  # EventBus 异步
    assert received == ["common/scene/home"], f"应发布一次 scene_updated: {received}"
    print("① PASS probe_scene 命中 → 发布 scene_updated")

    # 去重：再次探测同场景不重复发布
    ex.probe_scene(["common/scene/home"])
    time.sleep(0.5)
    assert len(received) == 1, f"场景未变化不应重复发布: {received}"
    print("② PASS 场景未变化去重（不重复发布）")

    # detect_scene 命中也发布
    scene2 = ex.detect_scene(["common/scene/battle"], timeout=0)
    assert scene2 == "common/scene/battle", f"应命中战斗: {scene2}"
    time.sleep(0.5)
    assert received == ["common/scene/home", "common/scene/battle"], f"got {received}"
    print("③ PASS detect_scene 命中 → 发布 scene_updated")

    # probe_scene 未命中 → 不发布 scene_unknown（静默）
    unknown = []
    bus.subscribe(Events.SCENE_UNKNOWN, lambda **kw: unknown.append(kw))
    ex.probe_scene(["common/scene/login"])  # 不存在
    time.sleep(0.5)
    assert not unknown, f"probe_scene 未命中不应发布 scene_unknown: {unknown}"
    print("④ PASS probe_scene 未命中静默（不发布 scene_unknown）")

    print("\n── [B] 07-state_manager 订阅 scene_updated 维护 current_scene ──")
    sm = StateManager(event_bus=bus)
    bus.publish(Events.SCENE_UPDATED, source="executor", scene="common/scene/home")
    bus.publish(Events.SCENE_UPDATED, source="executor", scene="common/scene/battle")
    time.sleep(0.5)  # EventBus 异步
    assert sm.get_current_scene() == "common/scene/battle", f"got {sm.get_current_scene()}"
    assert sm.get_last_known_scene() == "common/scene/battle", f"got {sm.get_last_known_scene()}"
    assert sm.get(StateKeys.CURRENT_SCENE) == "common/scene/battle"
    print("⑤ PASS state_manager 订阅 scene_updated → current_scene/last_known_scene 自动维护")

    print("\n── [C] 任务步骤 scene_probe 自动感知（TaskGraph 集成）──")

    class StepA(TaskStep):
        is_generic = False
        timeout = 10
        scene_probe = ["common/scene/home"]

        def execute(self, context=None):
            return StepResult.success("A")

    class StepB(TaskStep):
        is_generic = False
        timeout = 10
        # 未声明 scene_probe → 不感知

        def execute(self, context=None):
            return StepResult.success("B")

    g = TaskGraph()
    g.add_step("a", StepA())
    g.add_step("b", StepB())
    g.set_entry("a")
    g.add_edge("a", "b")

    sm2 = StateManager(event_bus=bus)  # 再订阅一个（同一总线）
    ctx = TaskContext(task_id="scene_test", task_name="scene_test",
                      executor=ex, recognizer=rec, stop_event=threading.Event())
    result = g.run(ctx)
    assert result.status.value == "success", f"got {result.status}"
    time.sleep(0.5)
    # StepA 步骤前探测命中主界面 → state 更新
    assert sm2.get_current_scene() == "common/scene/home", \
        f"scene_probe 应感知主界面: {sm2.get_current_scene()}"
    print(f"⑥ PASS 步骤 scene_probe 自动感知（TaskGraph 集成），步骤执行 {result.status}")

    print("\n🎉 场景感知验证 6/6 通过")


if __name__ == "__main__":
    main()
