"""验证：示教保存为场景端到端（截图按钮手动模式 → 保存走回调入库，2026-08-15）。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)
import ui.visual_builder.teach_console as tc
from ui.visual_builder.teach_console import TeachConsole

# 1) 假弹窗（避免模态阻塞）
class _FakeSceneDialog:
    Accepted = 1
    def __init__(self, parent=None):
        self.name_edit = _F("场景名")
        self.signal_edit = _F("场景信号")
        self.accuracy_spin = _F(2)
    def exec_(self):
        return 1  # Accepted

class _F:
    def __init__(self, v):
        self.v = v
    def text(self):
        return self.v
    def value(self):
        return self.v


def test_save_scene_via_callback():
    tc._SceneDialog = _FakeSceneDialog

    tmp = Path(tempfile.mkdtemp(prefix="teach_scene_"))
    saved: dict = {}

    def scene_cb(scene, node_id):
        saved["scene"] = scene
        saved["node"] = node_id

    console = TeachConsole(assets_dir=str(tmp),
                           scene_commit_callback=scene_cb)
    console._ask_name = lambda title, prompt, default: default  # 跳过命名弹窗
    # 手动截图模式（📷 截图按钮行为：capture 回调 + 设置 manual_mode）
    img = np.full((200, 300, 3), 127, dtype=np.uint8)
    cv2.rectangle(img, (40, 40), (80, 80), (0, 0, 255), -1)
    console._capture_callback = lambda: img
    console._on_capture()
    assert console._manual_mode is True, "截图后应进入手动示教模式"

    # 红框 + 蓝框 + 遮罩（直接注入遮罩，跳过真实画笔）
    console._add_red_region(0.1, 0.1, 0.6, 0.6)
    console._add_blue_marker(0.15, 0.15, 0.2, 0.2)
    key = console._regions[0]["markers"][0]["mask_key"]
    console._canvas.set_active_mask(key)
    mask = console._canvas._masks.setdefault(
        key, np.zeros((200, 300), dtype=np.uint8))
    mask[50:90, 50:90] = 255   # 遮罩块（画布图像 200x300）
    console._canvas.update()
    console._teach_node = "node123"

    console._save_scene()
    scene = saved.get("scene")
    print("saved scene:", scene)
    assert scene is not None, "保存场景未走回调（bug：manual_mode 未生效）"
    assert scene["id"] == "场景名"
    assert scene["signal"] == "场景信号"
    assert scene["accuracy"] == 2
    assert saved["node"] == "node123"
    assert scene["regions"] and scene["regions"][0]["markers"], \
        "场景应有 红框+蓝框特征组"
    print("  ✅ 手动截图 → 保存为场景 → 回调入库（含信号/特征值/特征组）")


def test_save_region_as_element_undo_and_preserve():
    """红框右键保存图标素材 + 撤回 + 保存场景不清空画面（2026-08-15）"""
    import json
    tmp = Path(tempfile.mkdtemp(prefix="teach_v2_"))
    saved: dict = {}
    console = TeachConsole(assets_dir=str(tmp),
                           element_commit_callback=lambda rel, rs, nid: (
                               saved.update(rel=rel, region=rs, node=nid)))
    console.set_task_name("mytask")
    console._ask_name = lambda t, p, d: d
    console._manual_mode = True
    img = np.full((200, 300, 3), 127, dtype=np.uint8)
    console._last_image = img
    console._canvas.set_image(img)

    # 红框 + 蓝框 + 遮罩
    console._add_red_region(0.1, 0.1, 0.5, 0.5)
    console._add_blue_marker(0.15, 0.15, 0.25, 0.25)
    region = console._regions[0]
    key = region["markers"][0]["mask_key"]
    console._canvas.set_active_mask(key)
    console._canvas._masks[key] = np.zeros((200, 300), np.uint8)
    console._canvas._masks[key][60:85, 60:85] = 255

    # 1) 红框右键 → 保存图标素材（区域+图标合并）
    console._save_region_as_element(region["box_id"])
    rel = saved.get("rel")
    assert rel and rel.endswith(".json"), f"未保存条目: {saved}"
    entry = json.loads((tmp / rel).read_text(encoding="utf-8"))
    assert entry["region"] == [0.1, 0.1, 0.5, 0.5], entry
    assert (tmp / rel).parent.joinpath(entry["image"]).exists(), "PNG 未生成"
    print("  ✅ 红框右键保存图标素材（区域+遮罩 PNG）")

    # 2) 撤回：删框 → 撤回恢复红框/蓝框/遮罩
    console._delete_box(region["box_id"])
    assert console._regions == []
    console._undo()
    assert len(console._regions) == 1 and console._regions[0]["markers"], \
        "撤回未恢复红/蓝框"
    assert console._canvas.get_mask(key).any(), "撤回未恢复遮罩"
    print("  ✅ 撤回：删除的框与遮罩完整恢复")

    # 3) 保存场景后画面不清空（红框/蓝框/遮罩保留，可继续操作）
    class _D:
        Accepted = 1
        class E:
            def text(self): return "场景A"
            def value(self): return 2
        name_edit = E(); signal_edit = E(); accuracy_spin = E()
        def exec_(self): return 1
    tc._SceneDialog = lambda parent=None: _D()
    scene_saved = {}
    console._scene_commit_callback = lambda sc, nid: scene_saved.update(scene=sc)
    console._save_scene()
    assert scene_saved.get("scene") is not None, "场景未保存"
    assert len(console._regions) == 1 and console._regions[0]["markers"], \
        "保存场景后选框被清空"
    assert console._canvas.get_mask(key).any(), "保存场景后遮罩被清空"
    assert console._manual_mode is True, "保存场景后应仍为手动模式"
    print("  ✅ 保存场景后画面标注保留（可继续保存图标素材）")

    # 4) 结束示教回调
    ended = {}
    console._end_teach_callback = lambda: ended.update(called=True)
    console._end_teach()
    assert ended.get("called") and console._manual_mode is False
    print("  ✅ 结束示教（合并跳过/停止）回调生效")


def test_save_icon_entry_chinese_path():
    """中文目录路径下保存图标素材（2026-08-15 修复：cv2.imwrite 中文路径失败）"""
    import json
    tmp = Path(tempfile.mkdtemp(prefix="teach_cn_")) / "新程序" / "主程序"
    assets = tmp / "assets"
    saved: dict = {}
    console = TeachConsole(assets_dir=str(assets),
                           element_commit_callback=lambda rel, rs, nid: (
                               saved.update(rel=rel)))
    console.set_task_name("mytask")
    console._ask_name = lambda t, p, d: "中文图标"
    console._manual_mode = True
    img = np.full((200, 300, 3), 127, dtype=np.uint8)
    console._last_image = img
    console._canvas.set_image(img)
    console._add_red_region(0.1, 0.1, 0.5, 0.5)
    region = console._regions[0]
    console._save_region_as_element(region["box_id"])
    rel = saved.get("rel")
    assert rel, "中文路径下保存失败（cv2.imwrite 中文路径 bug）"
    entry = json.loads((assets / rel).read_text(encoding="utf-8"))
    assert (assets / rel).parent.joinpath(entry["image"]).exists(), "PNG 未写入"
    print("  ✅ 中文目录路径下图标素材保存成功（json + PNG 均落盘）")


def test_save_scene_non_manual_still_saves():
    """非手动模式（如点过结束示教后）保存场景也必须入库（2026-08-15 修复）"""
    import json
    tmp = Path(tempfile.mkdtemp(prefix="teach_nm_"))
    saved: dict = {}
    console = TeachConsole(assets_dir=str(tmp),
                           scene_commit_callback=lambda sc, nid: (
                               saved.update(scene=sc, node=nid)))
    console._ask_name = lambda t, p, d: d
    console._manual_mode = False   # ← 关键：非手动模式也必须走回调入库
    img = np.full((200, 300, 3), 127, dtype=np.uint8)
    console._last_image = img
    console._canvas.set_image(img)
    console._add_red_region(0.1, 0.1, 0.5, 0.5)
    console._add_blue_marker(0.15, 0.15, 0.25, 0.25)
    region = console._regions[0]
    key = region["markers"][0]["mask_key"]
    console._canvas.set_active_mask(key)
    console._canvas._masks[key] = np.zeros((200, 300), np.uint8)
    console._canvas._masks[key][60:85, 60:85] = 255

    class _D:
        Accepted = 1
        class E:
            def text(self): return "非手动场景"
            def value(self): return 0
        name_edit = E(); signal_edit = E(); accuracy_spin = E()
        def exec_(self): return 1
    tc._SceneDialog = lambda parent=None: _D()
    console._save_scene()
    scene = saved.get("scene")
    assert scene is not None, "非手动模式保存场景丢失（事件无人处理 bug）"
    assert scene["id"] == "非手动场景" and scene["regions"]
    print("  ✅ 非手动模式保存场景也走回调入库（不再静默丢失）")


if __name__ == "__main__":
    test_save_scene_via_callback()
    test_save_region_as_element_undo_and_preserve()
    test_save_icon_entry_chinese_path()
    test_save_scene_non_manual_still_saves()
    print("\n🎉 verify_teach_save_scene 全部通过")
