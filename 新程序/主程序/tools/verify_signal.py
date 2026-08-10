"""端到端验证：识图信号机制（scene/ 素材 → 信号名）。

验证点：
  1. AssetMetaStore.signal 字段：读写 / all_signals / get_rel_by_signal / 持久化
  2. Executor.set_signal_map + detect_scene 命中 → 发布 SCENE_SIGNAL + current_signal
  3. ensure_scene 命中 → 发布信号
  4. Executor.wait_signal API（命中/未注册/超时）
  5. run_controller.set_signal_map + trigger 信号名→素材路径解析（start_trigger_watcher 收集）
"""
import sys, os, tempfile, shutil
from pathlib import Path

import numpy as np
import cv2

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt5.QtWidgets import QApplication


def _make_template(name: str, size: tuple[int, int], seed: int) -> np.ndarray:
    w, h = size
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (255, 255, 255), 2)
    cv2.putText(img, name.split("/")[-1][:8], (6, h // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    return img


class MockConnection:
    """模拟设备：合成截图（含素材模板）+ 记录点击"""
    SCREEN_W, SCREEN_H = 1080, 1920

    def __init__(self, templates: dict[str, np.ndarray]):
        self.templates = templates
        self._screen = None
        self._positions: dict[str, tuple[int, int]] = {}

    def _build_screen(self) -> np.ndarray:
        screen = np.full((self.SCREEN_H, self.SCREEN_W, 3), 30, dtype=np.uint8)
        y = 60
        for name, tpl in self.templates.items():
            h, w = tpl.shape[:2]
            x = 100
            if y + h > self.SCREEN_H:
                break
            screen[y:y + h, x:x + w] = tpl
            self._positions[name] = (x, y)
            y += h + 40
        return screen

    def screenshot(self, use_cache: bool = False) -> np.ndarray:
        if self._screen is None or not use_cache:
            self._screen = self._build_screen()
        return self._screen.copy()

    def click(self, x, y):
        pass

    def swipe(self, *a, **k):
        pass

    def echo(self):
        return True

    def is_connected(self):
        return True


def main():
    app = QApplication(sys.argv)
    ok, fail = 0, 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"✅ {name}")
        else:
            fail += 1
            print(f"❌ {name}  {detail}")

    # ════════════ 0. 临时目录 + 素材 ════════════
    tmp = Path(tempfile.mkdtemp(prefix="signal_"))
    assets = tmp / "assets"
    (assets / "scene").mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(assets / "scene" / "主界面.png"),
                _make_template("scene/主界面", (200, 80), 11))
    cv2.imwrite(str(assets / "scene" / "战斗界面.png"),
                _make_template("scene/战斗界面", (200, 80), 12))

    # ════════════ 1. AssetMetaStore.signal ════════════
    print("\n── [1/5] AssetMetaStore 信号字段 ──")
    from core.asset_meta import AssetMetaStore
    meta = AssetMetaStore(assets)
    meta.set_image_meta("scene/主界面.png", ["主界面"], "主界面识别图", "主界面.png",
                        signal="主界面")
    meta.set_image_meta("scene/战斗界面.png", ["背景图"], "战斗界面", "战斗界面.png",
                        signal="战斗界面")
    check("get_signal 读取", meta.get_signal("scene/主界面.png") == "主界面")
    check("无 signal 的素材返回 None", meta.get_signal("scene/不存在.png") is None)
    sigs = meta.all_signals()
    check("all_signals 含两个信号（key=去扩展名识别名）",
          sigs.get("scene/主界面") == "主界面"
          and sigs.get("scene/战斗界面") == "战斗界面", str(sigs))
    check("get_rel_by_signal 反查（去扩展名）",
          meta.get_rel_by_signal("主界面") == "scene/主界面",
          str(meta.get_rel_by_signal("主界面")))
    # 持久化
    meta2 = AssetMetaStore(assets)
    check("信号持久化重载", meta2.get_signal("scene/主界面.png") == "主界面")

    # ════════════ 2. Executor 识别命中发布信号 ════════════
    print("\n── [2/5] Executor 识别命中 → SCENE_SIGNAL ──")
    from core.recognizer import Recognizer
    from core.anti_detect import AntiDetect
    from core.executor import Executor
    from core.events import Events

    templates = {}
    for p in assets.rglob("*.png"):
        templates[str(p.relative_to(assets)).replace("\\", "/").rsplit(".", 1)[0]] = cv2.imread(str(p))
    conn = MockConnection(templates)
    rec = Recognizer(asset_dir=str(assets), connection=conn,
                     screenshot_ttl=0.05, result_cache_ttl=0.01)
    ex = Executor(recognizer=rec, anti_detect=AntiDetect(), connection=conn, dry_run=False)
    ex.set_signal_map(meta.all_signals())

    signals = []
    ex._bus.subscribe(Events.SCENE_SIGNAL, lambda **kw: signals.append(kw.get("signal")))

    scene = ex.detect_scene(["scene/主界面"], timeout=2)
    check("detect_scene 命中主界面", scene == "scene/主界面", str(scene))
    import time as _t
    _t.sleep(0.5)  # 等待 EventBus 异步分发
    check("命中后发布 SCENE_SIGNAL(主界面)", "主界面" in signals, str(signals))
    check("current_signal 记录", ex.current_signal == "主界面", str(ex.current_signal))

    ok_ens = ex.ensure_scene("scene/战斗界面", timeout=2)
    check("ensure_scene 命中战斗界面", ok_ens)
    _t.sleep(0.5)
    check("ensure_scene 发布 SCENE_SIGNAL(战斗界面)", "战斗界面" in signals, str(signals))

    # ════════════ 3. Executor.wait_signal ════════════
    print("\n── [3/5] Executor.wait_signal ──")
    got = ex.wait_signal("主界面", timeout=2)
    check("wait_signal('主界面') 命中", got)
    check("wait_signal 后 current_signal=主界面", ex.current_signal == "主界面")
    got2 = ex.wait_signal("未注册信号", timeout=1)
    check("wait_signal 未注册信号 → False", not got2)
    # 素材移除后超时
    (assets / "scene" / "战斗界面.png").unlink()
    meta3 = AssetMetaStore(assets)
    meta3.remove_image_meta("scene/战斗界面.png")
    ex.set_signal_map(meta3.all_signals())
    got3 = ex.wait_signal("战斗界面", timeout=1)
    check("wait_signal 素材缺失超时 → False", not got3)

    # ════════════ 4. run_controller 信号注入 + trigger 解析 ════════════
    print("\n── [4/5] run_controller 信号 + trigger 信号名解析 ──")
    from core.run_controller import RunController
    rc = RunController(executor=ex, recognizer=rec)
    rc.set_signal_map(meta3.all_signals())
    check("set_signal_map 转发到 Executor",
          ex._signal_map.get("scene/主界面") == "主界面")
    # 模拟 trigger 任务收集（信号名 → 素材路径）
    rc._rel_by_signal = {v: k for k, v in rc._signal_map.items()}
    trigger_tasks = []
    class _Cfg:
        def __init__(self, name, tmpls):
            self.name = name
            self.repeat = type("R", (), {"type": "trigger", "trigger_templates": tmpls})()
    for cfg in [_Cfg("task_a", ["主界面"]), _Cfg("task_b", ["scene/主界面"])]:
        if cfg.repeat.type == 'trigger':
            tmpls = cfg.repeat.trigger_templates or []
            resolved = []
            for t in tmpls:
                resolved.append(rc._rel_by_signal[t] if t in rc._rel_by_signal else t)
            trigger_tasks.append((cfg.name, resolved))
    check("信号名'主界面'解析为素材路径",
          [t for _, ts in trigger_tasks for t in ts] == ["scene/主界面", "scene/主界面"],
          str(trigger_tasks))

    # ════════════ 5. 触发任务入队链路（TriggerWatcher → 事件） ════════════
    print("\n── [5/5] 触发任务信号触发链路 ──")
    from core.trigger_watcher import TriggerWatcher
    tw = TriggerWatcher(recognizer=rec, connection=conn, event_bus=ex._bus, interval=0.2)
    detected = []
    ex._bus.subscribe(Events.TRIGGER_DETECTED, lambda **kw: detected.append(kw))
    tw.start([("task_a", ["scene/主界面"])])
    import time
    time.sleep(0.6)
    tw.stop()
    check("TriggerWatcher 命中 scene/主界面 → trigger_detected",
          any(d.get("task_name") == "task_a" for d in detected), str(detected))

    shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'=' * 46}")
    print(f"🎉 识图信号机制验证 {ok}/{ok + fail} 通过")
    if fail:
        print("存在失败项，请检查。")
        sys.exit(1)


if __name__ == "__main__":
    main()
