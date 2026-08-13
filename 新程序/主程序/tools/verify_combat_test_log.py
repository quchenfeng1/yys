"""combat_test 五阶段链路日志验证（临时，验证后可删除）"""
import sys, os, tempfile, threading
from pathlib import Path

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

import numpy as np
import cv2

from core.event_bus import get_global_bus
from core.events import Events
from core.anti_detect import AntiDetect
from core.recognizer import Recognizer
from core.executor import Executor
from tasks.base.task_context import TaskContext

# 通用模块引用的模板（合成素材）
NEEDED = {
    "common/scene/home": (180, 100),
    "common/soul/shirin_entry": (150, 60),
    "common/soul/team_config_tab": (150, 60),
    "common/soul/group_btn": (120, 50),
    "common/soul/change_soul_btn": (140, 60),
    "common/ui/back_btn": (120, 60),
    "common/battle/unlock_btn": (140, 60),
    "common/battle/lock_btn": (140, 60),
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


def main():
    tmp = tempfile.mkdtemp(prefix="combat_test_assets_")
    templates = generate(tmp)
    conn = MockConnection(templates)

    rec = Recognizer(asset_dir=tmp, connection=conn, screenshot_ttl=0.05, result_cache_ttl=0.01)
    ad = AntiDetect(min_interval=0.001, max_interval=0.002,
                    action_jitter=False, random_fail_rate=0)
    ex = Executor(recognizer=rec, anti_detect=ad, connection=conn, dry_run=False)

    def _on_log(**kw):
        print(f"  [{kw.get('level', 'info'):7s}] {kw.get('message', '')}")
    get_global_bus().subscribe(Events.LOG_RECORD, _on_log)

    from games.yys.tasks.special.combat_test import build_graph
    state: dict = {}
    ctx = TaskContext(
        task_id="combat_test", task_name="combat_test",
        task_config={"loop_count": 3, "floor": 10},
        executor=ex, recognizer=rec, stop_event=threading.Event(),
        state=state,
        progress_saver=lambda tid, c, t: state.setdefault(tid, {}).update(
            {"completed": c, "total": t, "updated": ""}),
    )
    g = build_graph(ctx)
    result = g.run(ctx)
    print(f"\n最终 TaskResult: status={result.status} · {result.reason}")
    print(f"实际点击次数: {len(conn.clicks)} · 断点进度: {state}")


if __name__ == "__main__":
    main()
