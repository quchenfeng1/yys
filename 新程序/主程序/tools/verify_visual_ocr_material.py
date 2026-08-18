"""验证：OCR 识别素材全链路（2026-08-15）。

覆盖：
1. 示教：红框(搜索区域) + 蓝框(遮罩标识) + 黄框(文字位置，蓝框内) →
   右键蓝框保存 OCR 识别素材条目（ocr_box=相对遮罩裁剪的像素偏移）
2. 桥接 ocr_items() 列出条目；面板 _task_ocr_items 只出任务素材库内容
3. OCR读取执行器：蓝框遮罩匹配 → 黄框相对位置裁剪截图 → OCR 提取文字
   → 含关键词 out / 不含 miss / 遮罩未命中 miss
"""
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
from visual import VisualTaskStore, visual_schema as vs
from visual import nodes as vn
from visual.nodes import GraphContext
from ui.visual_builder.teach_console import TeachConsole
from ui.param_bridge.visual_bridge import VisualBridge


class _FakeResult:
    def __init__(self, text, score=0.99):
        self.text = text
        self.score = score


class _FakeOCR:
    is_ready = True

    def __init__(self, text="1234"):
        self._text = text
        self.crops: list = []

    def recognize(self, crop):
        self.crops.append(np.array(crop, copy=True))
        return [_FakeResult(self._text)]


class _FakeRecognizer:
    def __init__(self, screen):
        self._screen = screen

    def _get_screenshot(self):
        return self._screen


def _make_screen(mark=True):
    """200x300 屏幕：蓝框标识画在 (50,40)-(109,99)（红块），
    黄框文字区 (100,60)-(179,119)（深色块）；mark=False 时无标识。"""
    screen = np.full((200, 300, 3), 127, dtype=np.uint8)
    if mark:
        cv2.rectangle(screen, (50, 40), (109, 99), (0, 0, 255), -1)
    return screen


def _make_ctx(tmp: Path, task: dict, screen, ocr) -> GraphContext:
    ctx = GraphContext(task=task, assets_dir=tmp, screen_size=(300, 200))
    ctx.recognizer = _FakeRecognizer(screen)
    ctx.ocr = ocr
    return ctx


# ── 测试 ─────────────────────────────────────────────────
def test_teach_save_ocr_entry():
    """示教保存：红框+蓝框遮罩+黄框 → OCR 识别素材条目（ocr_box 像素偏移）"""
    import json
    tmp = Path(tempfile.mkdtemp(prefix="ocr_teach_"))
    screen = _make_screen()
    store = VisualTaskStore(tmp / "vt")
    got: dict = {}
    console = TeachConsole(event_bus=None, store=store, assets_dir=str(tmp),
                           ocr=_FakeOCR(),
                           ocr_commit_callback=lambda rel, nid: got.update(
                               rel=rel, nid=nid))
    console.set_task_name("t1")
    console._show_image(screen)
    console._ask_name = lambda *a, **k: a[2] if len(a) > 2 else "auto"  # 免弹窗

    # 红框（整图搜索区域）+ 蓝框（标识）+ 遮罩 + 黄框（文字位置，蓝框内）
    console._add_red_region(0.05, 0.05, 0.9, 0.9)
    console._add_blue_marker(0.1667, 0.2, 0.2, 0.3)   # 像素 (50,40)-(109,99)
    marker = console._regions[0]["markers"][0]
    H, W = screen.shape[:2]
    mask = np.zeros((H, W), dtype=np.uint8)
    mask[40:100, 50:110] = 255
    console._canvas.set_all_masks({marker["mask_key"]: mask})
    console._add_yellow_box(0.2, 0.275, 0.1333, 0.2)  # 像素 (60,55)-(99,94)，蓝框内

    console._save_box_as_ocr(marker["box_id"])
    rel = got.get("rel", "")
    assert rel.endswith("ocr/蓝1区.json"), rel
    entry_path = tmp / rel
    assert entry_path.exists(), f"条目不存在: {entry_path}"
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    print("  条目:", json.dumps(entry, ensure_ascii=False))
    assert entry["image"], "缺图片"
    assert entry["region"] == [0.05, 0.05, 0.9, 0.9], entry["region"]
    # 黄框像素偏移 = 黄框左上角 - 遮罩裁剪左上角（宽 0.1333×300=39 取整）
    assert entry["ocr_box"] == [10, 15, 39, 40], entry["ocr_box"]
    img_path = entry_path.parent / entry["image"]
    assert img_path.exists()
    tpl = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8),
                       cv2.IMREAD_UNCHANGED)
    assert tpl.shape[2] == 4 and tpl.shape[:2] == (60, 60)
    print("  ✅ OCR识别素材条目：区域+遮罩+黄框偏移全部正确")


def test_bridge_and_panel_items():
    """桥接 ocr_items 列出条目；面板下拉只显示任务素材库内容"""
    tmp = Path(tempfile.mkdtemp(prefix="ocr_items_"))
    (tmp / "visual" / "t1" / "ocr").mkdir(parents=True)
    (tmp / "visual" / "t1" / "ocr" / "体力数值.json").write_text(
        '{"id":"体力数值","name":"体力数值","image":"a.png"}',
        encoding="utf-8")
    (tmp / "visual" / "t1" / "ocr" / "a.png").write_bytes(
        cv2.imencode(".png", np.zeros((4, 4, 3), np.uint8))[1].tobytes())
    store = VisualTaskStore(tmp / "vt")
    bridge = VisualBridge(store=store, assets_dir=str(tmp))
    items = bridge.ocr_items()
    print("  ocr_items:", items)
    assert items == ["visual/t1/ocr/体力数值.json"]
    print("  ✅ 桥接列出 OCR 识别素材")


def test_executor_hit_keyword_out():
    """执行器：遮罩匹配 → 黄框裁剪 → OCR → 含关键词 out + 变量"""
    import json
    tmp = Path(tempfile.mkdtemp(prefix="ocr_exec_"))
    screen = _make_screen(mark=True)
    # 条目（模拟示教产物：遮罩裁剪 60x60 @ (50,40)，黄框偏移 [10,15,40,40]）
    (tmp / "visual" / "t1" / "ocr").mkdir(parents=True)
    crop = screen[40:100, 50:110].copy()
    rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = 255
    cv2.imencode(".png", rgba)[1].tofile(
        str(tmp / "visual" / "t1" / "ocr" / "a.png"))
    entry = {"id": "体力数值", "name": "体力数值", "image": "a.png",
             "region": [0.05, 0.05, 0.9, 0.9], "threshold": 0.85,
             "ocr_box": [10, 15, 40, 40], "created_at": 0}
    (tmp / "visual" / "t1" / "ocr" / "体力数值.json").write_text(
        json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    rel = "visual/t1/ocr/体力数值.json"

    store = VisualTaskStore(tmp / "vt")
    task = store.create("ocr_exec", "OCR执行", "daily")
    ocr = _FakeOCR("1234")
    ctx = _make_ctx(tmp, task, screen, ocr)

    node = vs.new_node("ocr_reader", name="读体力")
    node["params"] = {"template": rel, "keyword": "1234",
                      "output_var": "txt"}
    res = vn.dispatch(node, ctx)
    print(f"  goto={res.goto} data={res.data}")
    assert res.goto == "out", res.message
    assert ctx.vars["txt"] == "1234"
    assert len(ocr.crops) == 1
    c = ocr.crops[0]
    # 裁剪 = 黄框区域（匹配点 50,40 + 偏移 10,15 → (60,55)，40x40）
    assert c.shape[:2] == (40, 40), c.shape
    assert np.array_equal(c, screen[55:95, 60:100])
    print("  ✅ 遮罩匹配→黄框裁剪→OCR→关键词命中 out")


def test_executor_miss():
    """遮罩未命中 → miss"""
    import json
    tmp = Path(tempfile.mkdtemp(prefix="ocr_miss_"))
    screen = _make_screen(mark=False)   # 屏幕没有标识
    (tmp / "visual" / "t1" / "ocr").mkdir(parents=True)
    crop = _make_screen()[40:100, 50:110].copy()
    rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = 255
    cv2.imencode(".png", rgba)[1].tofile(
        str(tmp / "visual" / "t1" / "ocr" / "a.png"))
    entry = {"id": "体力数值", "name": "体力数值", "image": "a.png",
             "region": [0.05, 0.05, 0.9, 0.9], "threshold": 0.85,
             "ocr_box": [10, 15, 40, 40], "created_at": 0}
    (tmp / "visual" / "t1" / "ocr" / "体力数值.json").write_text(
        json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    store = VisualTaskStore(tmp / "vt")
    task = store.create("ocr_miss", "OCR未命中", "daily")
    ctx = _make_ctx(tmp, task, screen, _FakeOCR())
    node = vs.new_node("ocr_reader", name="读体力")
    node["params"] = {"template": "visual/t1/ocr/体力数值.json",
                      "keyword": "1234"}
    res = vn.dispatch(node, ctx)
    print(f"  goto={res.goto}")
    assert res.goto == "miss", res.message
    print("  ✅ 遮罩未命中→miss")


def test_context_menu_ocr_option():
    """右键菜单：红框（蓝框+黄框已画）与蓝框右键都有保存 OCR 识别素材选项"""
    import ui.visual_builder.teach_console as tc_mod

    class _FakeAction:
        def __init__(self, text):
            self.text = text
            self.triggered = _FakeAction._Sig()

        class _Sig:
            def connect(self, fn):
                pass

    class _FakeMenu:
        last = None

        def __init__(self, parent=None):
            self.texts = []
            _FakeMenu.last = self

        def addAction(self, text):
            self.texts.append(text)
            return _FakeAction(text)

        def exec_(self, *a, **k):
            pass

    tmp = Path(tempfile.mkdtemp(prefix="ocr_menu_"))
    screen = _make_screen()
    console = TeachConsole(event_bus=None, store=VisualTaskStore(tmp / "vt"),
                           assets_dir=str(tmp), ocr=_FakeOCR())
    console.set_task_name("t1")
    console._show_image(screen)
    console._ask_name = lambda *a, **k: a[2] if len(a) > 2 else "auto"
    console._add_red_region(0.05, 0.05, 0.9, 0.9)
    console._add_blue_marker(0.1667, 0.2, 0.2, 0.3)
    marker = console._regions[0]["markers"][0]
    console._add_yellow_box(0.2, 0.275, 0.1333, 0.2)
    red_id = console._regions[0]["box_id"]
    blue_id = marker["box_id"]

    orig_menu = tc_mod.QMenu
    tc_mod.QMenu = _FakeMenu
    try:
        console._on_box_context(red_id)
        red_texts = list(_FakeMenu.last.texts)
        console._on_box_context(blue_id)
        blue_texts = list(_FakeMenu.last.texts)
    finally:
        tc_mod.QMenu = orig_menu
    print("  红框右键:", red_texts)
    print("  蓝框右键:", blue_texts)
    assert any("OCR识别素材" in t for t in red_texts), "红框右键缺 OCR 选项"
    assert any("OCR识别素材" in t for t in blue_texts), "蓝框右键缺 OCR 选项"
    # 无黄框的蓝框也始终显示该选项（点击时给提示而非灰掉）
    marker2 = {"name": "蓝2区", "region": [0.5, 0.5, 0.1, 0.1], "mask_key": "m0",
               "box_id": "boxX"}
    console._regions[0]["markers"].append(marker2)
    tc_mod.QMenu = _FakeMenu
    try:
        console._on_box_context("boxX")
        no_yellow_texts = list(_FakeMenu.last.texts)
    finally:
        tc_mod.QMenu = orig_menu
    assert any("OCR识别素材" in t for t in no_yellow_texts)
    print("  ✅ 右键菜单 OCR 选项齐全（红框/蓝框/无黄框）")


if __name__ == "__main__":
    test_teach_save_ocr_entry()
    test_bridge_and_panel_items()
    test_executor_hit_keyword_out()
    test_executor_miss()
    test_context_menu_ocr_option()
    print("\n🎉 verify_visual_ocr_material 全部通过")
