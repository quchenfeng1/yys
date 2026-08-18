"""验证：保存为场景彻底修复（2026-08-15）。

覆盖四个曾经反复出现的"保存为场景不入库"场景：
1. 面板+示教完整链路：素材库文件、SceneStore.load、任务素材库、任务文件、
   下拉、运行时 get_scene 全部可用
2. 素材库未配置（scene_store=None）时优雅降级：任务文件内副本仍可用，
   回调返回失败原因（不再静默）
3. 纯符号场景名（safe 名为空 → md5 文件名）：save 后 load 仍能找到
4. 事件路径（TeachEngine add_scene）：同样入素材库 + 任务素材库
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np

from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)
from visual import VisualTaskStore, visual_schema as vs
from visual.nodes import GraphContext
from visual.scene_store import SceneStore
from ui.param_bridge.visual_bridge import VisualBridge
from ui.visual_builder.visual_builder_panel import VisualBuilderPanel
import ui.visual_builder.teach_console as tc_mod


def _annotate(tc, screen):
    """截图 + 红框 + 蓝框 + 遮罩（免弹窗）"""
    tc._show_image(screen)
    tc._ask_name = lambda *a, **k: a[2] if len(a) > 2 else "auto"
    tc._add_red_region(0.05, 0.05, 0.9, 0.9)
    tc._add_blue_marker(0.104, 0.148, 0.125, 0.222)
    marker = tc._regions[0]["markers"][0]
    H, W = screen.shape[:2]
    mask = np.zeros((H, W), dtype=np.uint8)
    mask[80:200, 100:220] = 255
    tc._canvas.set_all_masks({marker["mask_key"]: mask})


def _save_scene_as(tc, name, signal="sigA"):
    """免弹窗执行 _save_scene"""
    orig_dlg = tc_mod._SceneDialog

    class _AutoDlg:
        Accepted = 1

        class _NameEdit:
            def text(self):
                return name

        class _SigEdit:
            def text(self):
                return signal

        class _AccSpin:
            def value(self):
                return 1

        def __init__(self, parent=None):
            self.name_edit = self._NameEdit()
            self.signal_edit = self._SigEdit()
            self.accuracy_spin = self._AccSpin()

        def exec_(self):
            return 1

    tc_mod._SceneDialog = _AutoDlg
    try:
        tc._save_scene()
    finally:
        tc_mod._SceneDialog = orig_dlg
    return tc._status.text()


def _make_screen():
    screen = np.full((540, 960, 3), 127, dtype=np.uint8)
    cv2.rectangle(screen, (100, 80), (219, 199), (0, 0, 255), -1)
    return screen


def test_full_chain():
    """面板链路：保存 → 素材库 + 任务 + 下拉 + 运行时全部可用"""
    tmp = Path(tempfile.mkdtemp(prefix="scene_save_"))
    assets = tmp / "assets"
    store = VisualTaskStore(tmp / "vt")
    scene_store = SceneStore([tmp / "scenes"])
    bridge = VisualBridge(store=store, assets_dir=str(assets),
                          scene_store=scene_store)
    bridge.create_task("t1", "任务", "daily")
    panel = VisualBuilderPanel(visual_bridge=bridge)
    assert panel.open_visual("yys", "task", "t1", store)
    panel.resize(1000, 700)
    panel.show()
    app.processEvents()

    tc = panel._teach_console
    tc.set_task_name("t1")
    _annotate(tc, _make_screen())
    status = _save_scene_as(tc, "主界面", "main")
    print("  状态:", status)
    assert "已保存到素材库" in status, status

    # 素材库文件 + load + list
    assert (tmp / "scenes" / "主界面.json").exists()
    loaded = scene_store.load("主界面")
    assert loaded is not None and loaded["signal"] == "main"
    assert any(s["id"] == "主界面" for s in scene_store.list())
    # 任务素材库 + 任务文件
    task = store.load("t1")
    assert "主界面" in task["materials"]["scenes"]
    assert vs.find_scene(task, "主界面") is not None
    # 下拉
    sp = panel._canvas.add_node("scene_probe")
    panel._canvas.refresh_combos()
    combo = sp.get_widget("scene").get_custom_widget()
    assert [combo.itemText(i) for i in range(combo.count())] == ["主界面"]
    # 运行时可用
    ctx = GraphContext(task=task, assets_dir=assets, screen_size=(960, 540))
    ctx.scene_loader = scene_store.load
    assert ctx.get_scene("主界面") is not None
    print("  ✅ 完整链路：素材库/任务/下拉/运行时全部可用")


def test_graceful_without_store():
    """素材库未配置：任务内副本仍可用，回调提示失败原因"""
    tmp = Path(tempfile.mkdtemp(prefix="scene_nostore_"))
    store = VisualTaskStore(tmp / "vt")
    bridge = VisualBridge(store=store, assets_dir=str(tmp / "assets"),
                          scene_store=None)
    bridge.create_task("t1", "任务", "daily")
    panel = VisualBuilderPanel(visual_bridge=bridge)
    assert panel.open_visual("yys", "task", "t1", store)
    panel.resize(1000, 700)
    panel.show()
    app.processEvents()

    tc = panel._teach_console
    tc.set_task_name("t1")
    _annotate(tc, _make_screen())
    status = _save_scene_as(tc, "主界面", "main")
    print("  状态:", status)
    assert "素材库" in status, "应提示素材库写入失败"
    task = store.load("t1")
    assert "主界面" in task["materials"]["scenes"]
    assert vs.find_scene(task, "主界面") is not None, "任务内副本应可用"
    ctx = GraphContext(task=task, assets_dir=tmp / "assets",
                       screen_size=(960, 540))
    assert ctx.get_scene("主界面") is not None, "运行时从任务副本加载"
    print("  ✅ 素材库缺失时优雅降级（任务副本兜底 + 明确提示）")


def test_symbol_scene_name():
    """纯符号场景名：safe 名为空 → md5 文件名，save 后 load 仍能找到"""
    tmp = Path(tempfile.mkdtemp(prefix="scene_sym_"))
    store = SceneStore([tmp / "scenes"])
    store.save({"id": "★★★", "name": "★★★", "signal": "s",
                "judgements": [], "logic": "and"})
    assert store.load("★★★") is not None
    assert any(s["id"] == "★★★" for s in store.list())
    print("  ✅ 纯符号场景名可存可取（md5 文件名兼容）")


def test_event_path():
    """事件路径（TeachEngine.add_scene）：入素材库 + 任务素材库"""
    from visual.teach_engine import TeachEngine
    tmp = Path(tempfile.mkdtemp(prefix="scene_evt_"))
    store = VisualTaskStore(tmp / "vt")
    task = store.create("t1", "任务", "daily")
    scene_store = SceneStore([tmp / "scenes"])
    eng = TeachEngine(event_bus=None, store=store, assets_dir=str(tmp),
                      scene_store=scene_store)
    eng._task = task
    eng._pending = {"info": {}, "event": __import__("threading").Event()}
    eng._on_action_received(action="add_scene",
                            scene={"id": "战斗界面", "name": "战斗界面",
                                   "signal": "battle", "judgements": [],
                                   "logic": "and", "regions": [],
                                   "accuracy": 0})
    assert scene_store.load("战斗界面") is not None
    assert "战斗界面" in task.get("materials", {}).get("scenes", [])
    assert vs.find_scene(task, "战斗界面") is not None
    print("  ✅ 事件路径同样入素材库 + 任务素材库")


if __name__ == "__main__":
    test_full_chain()
    test_graceful_without_store()
    test_symbol_scene_name()
    test_event_path()
    print("\n🎉 verify_visual_scene_save 全部通过")
