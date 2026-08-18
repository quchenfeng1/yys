"""验证：随机点击素材（只有红框）+ 素材保存验证 + 点击器/拖拽器适配（2026-08-15）。

覆盖：
1. 红框内无蓝框 → 保存为随机点击素材（mode=region_click，红框内随机点）
2. 红框内有蓝框但蓝框无遮罩 → 拒绝保存操作识别素材（提示）
3. 红框+蓝框+遮罩 → 正常操作识别素材（无 mode）
4. 保存为场景识别素材验证：无红框 / 红框无蓝框 / 蓝框无遮罩 均拒绝并提示
5. 点击器遇随机点击素材 → 不识别，红框内随机点击（多次采样全在红框内）
6. 拖拽器遇随机点击素材 → 红框内随机点作为拖拽起点
7. 拖拽器遇正常素材 → 遮罩内随机点作为起点；未命中 → not_found
8. 拖拽器未设置素材 → 屏幕中心起滑（旧行为不变）
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import cv2
import numpy as np
from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)
import ui.visual_builder.teach_console as tc
from ui.visual_builder.teach_console import TeachConsole
from visual.nodes import GraphContext, _exec_clicker, _exec_dragger


class _F:
    def __init__(self, v):
        self.v = v
    def text(self):
        return self.v
    def value(self):
        return self.v


class _FakeSceneDialog:
    Accepted = 1
    def __init__(self, parent=None):
        self.name_edit = _F("场景名")
        self.signal_edit = _F("场景信号")
        self.accuracy_spin = _F(2)
    def exec_(self):
        return 1


def _make_console(tmp: Path, img=None):
    saved: dict = {}
    console = TeachConsole(
        assets_dir=str(tmp),
        element_commit_callback=lambda rel, rs, nid: saved.update(
            rel=rel, region=rs, node=nid),
        scene_commit_callback=lambda sc, nid: saved.update(scene=sc),
    )
    console._ask_name = lambda title, prompt, default: default
    console._manual_mode = True
    img = img if img is not None else np.full((200, 300, 3), 127, np.uint8)
    console._last_image = img
    console._canvas.set_image(img)
    return console, saved


# ── 1. 只有红框 → 随机点击素材 ──────────────────────────────
def test_region_only_saves_region_click():
    tmp = Path(tempfile.mkdtemp(prefix="rc_save_"))
    console, saved = _make_console(tmp)
    console._add_red_region(0.1, 0.1, 0.5, 0.5)
    region = console._regions[0]
    console._save_region_as_element(region["box_id"])
    rel = saved.get("rel", "")
    assert rel, "随机点击素材未保存"
    entry = json.loads((tmp / rel).read_text(encoding="utf-8"))
    assert entry["mode"] == "region_click", entry
    assert entry["region"] == [0.1, 0.1, 0.5, 0.5], entry
    assert (tmp / rel).parent.joinpath(entry["image"]).exists(), "PNG 未生成"
    print("  ✅ 只有红框 → 随机点击素材条目（mode=region_click + 区域 + 预览图）")


# ── 2. 有蓝框无遮罩 → 拒绝 ────────────────────────────────
def test_blue_without_mask_rejected():
    tmp = Path(tempfile.mkdtemp(prefix="rc_bad_"))
    console, saved = _make_console(tmp)
    console._add_red_region(0.1, 0.1, 0.5, 0.5)
    console._add_blue_marker(0.15, 0.15, 0.25, 0.25)
    region = console._regions[0]
    console._save_region_as_element(region["box_id"])
    assert "rel" not in saved, "有蓝框无遮罩不应保存成功"
    assert "没有遮罩" in console._hint.text(), console._hint.text()
    print("  ✅ 红框内有蓝框但无遮罩 → 拒绝保存并提示")


# ── 3. 红框+蓝框+遮罩 → 正常素材（无 mode）────────────────
def test_normal_element_no_mode():
    tmp = Path(tempfile.mkdtemp(prefix="rc_norm_"))
    console, saved = _make_console(tmp)
    console._add_red_region(0.1, 0.1, 0.5, 0.5)
    console._add_blue_marker(0.15, 0.15, 0.25, 0.25)
    region = console._regions[0]
    key = region["markers"][0]["mask_key"]
    console._canvas.set_active_mask(key)
    console._canvas._masks[key] = np.zeros((200, 300), np.uint8)
    console._canvas._masks[key][60:85, 60:85] = 255
    console._save_region_as_element(region["box_id"])
    rel = saved.get("rel", "")
    assert rel, "正常素材未保存"
    entry = json.loads((tmp / rel).read_text(encoding="utf-8"))
    assert not entry.get("mode"), entry
    print("  ✅ 红框+蓝框+遮罩 → 正常操作识别素材（无 mode）")


# ── 4. 场景保存验证 ────────────────────────────────────────
def test_scene_save_validation():
    tc._SceneDialog = _FakeSceneDialog
    # 4a 无红框
    tmp = Path(tempfile.mkdtemp(prefix="rc_sv1_"))
    console, saved = _make_console(tmp)
    console._save_scene()
    assert "scene" not in saved
    assert "红框" in console._hint.text(), console._hint.text()
    # 4b 红框无蓝框
    tmp2 = Path(tempfile.mkdtemp(prefix="rc_sv2_"))
    console2, saved2 = _make_console(tmp2)
    console2._add_red_region(0.1, 0.1, 0.5, 0.5)
    console2._save_scene()
    assert "scene" not in saved2
    assert "没有蓝框" in console2._hint.text(), console2._hint.text()
    # 4c 蓝框无遮罩
    tmp3 = Path(tempfile.mkdtemp(prefix="rc_sv3_"))
    console3, saved3 = _make_console(tmp3)
    console3._add_red_region(0.1, 0.1, 0.5, 0.5)
    console3._add_blue_marker(0.15, 0.15, 0.25, 0.25)
    console3._save_scene()
    assert "scene" not in saved3
    assert "没有遮罩" in console3._hint.text(), console3._hint.text()
    # 4d 齐备 → 通过
    tmp4 = Path(tempfile.mkdtemp(prefix="rc_sv4_"))
    console4, saved4 = _make_console(tmp4)
    console4._add_red_region(0.1, 0.1, 0.5, 0.5)
    console4._add_blue_marker(0.15, 0.15, 0.25, 0.25)
    key = console4._regions[0]["markers"][0]["mask_key"]
    console4._canvas.set_active_mask(key)
    console4._canvas._masks[key] = np.zeros((200, 300), np.uint8)
    console4._canvas._masks[key][60:85, 60:85] = 255
    console4._save_scene()
    assert saved4.get("scene") is not None, "齐备场景未保存"
    print("  ✅ 场景识别素材验证：无红框/红框无蓝框/蓝框无遮罩 拒绝，齐备通过")


# ── 5. 点击器遇随机点击素材 ───────────────────────────────
class _Ex:
    def __init__(self, screen):
        self.clicks = []
        self.swipes = []
        self._recognizer = None
        self._screen = screen

    def click_position(self, x, y):
        self.clicks.append((int(x), int(y)))

    def swipe(self, x1, y1, x2, y2, duration=0.6):
        self.swipes.append((int(x1), int(y1), int(x2), int(y2), duration))


def _make_ctx(tmp: Path, screen, executor, entry) -> GraphContext:
    ctx = GraphContext(task={}, assets_dir=str(tmp), screen_size=(300, 200))
    ctx.executor = executor
    ctx._screenshot = screen
    return ctx


def _write_entry(tmp: Path, name: str, entry: dict,
                 mask: np.ndarray | None) -> str:
    d = tmp / "visual" / "t1" / "icons"
    d.mkdir(parents=True, exist_ok=True)
    if mask is not None:
        cv2.imencode(".png", mask)[1].tofile(str(d / f"{name}.png"))
    (d / f"{name}.json").write_text(json.dumps(entry, ensure_ascii=False),
                                    encoding="utf-8")
    return f"visual/t1/icons/{name}.json"


def test_clicker_region_click():
    tmp = Path(tempfile.mkdtemp(prefix="rc_clk_"))
    screen = np.full((200, 300, 3), 127, np.uint8)
    rel = _write_entry(tmp, "rand", {
        "id": "rand", "name": "rand", "image": "rand.png",
        "region": [0.1, 0.1, 0.3, 0.3], "threshold": 0.85,
        "mode": "region_click"}, None)
    ex = _Ex(screen)
    ctx = _make_ctx(tmp, screen, ex, rel)
    r = _exec_clicker({"params": {"template": rel}}, ctx)
    assert r.goto == "out" and r.status == "ok", r
    assert r.data.get("mode") == "region_click", r.data
    px, py = r.data["point"]
    # 红框 = x∈[30,120), y∈[20,80)（int(浮点×分辨率) 有 ±1px 取整误差）
    assert 29 <= px <= 120 and 19 <= py <= 80, (px, py)
    assert ex.clicks and ex.clicks[0] == (px, py)
    # 采样 50 次全部落在红框内
    for _ in range(50):
        rr = _exec_clicker({"params": {"template": rel}}, ctx)
        x, y = rr.data["point"]
        assert 29 <= x <= 120 and 19 <= y <= 80, (x, y)
    print("  ✅ 点击器遇随机点击素材：红框内随机点击（50 次采样全在框内）")


# ── 6/7/8. 拖拽器 ─────────────────────────────────────────
def test_dragger_region_click_start():
    tmp = Path(tempfile.mkdtemp(prefix="rc_drg_"))
    screen = np.full((200, 300, 3), 127, np.uint8)
    rel = _write_entry(tmp, "rand2", {
        "id": "rand2", "name": "rand2", "image": "rand2.png",
        "region": [0.1, 0.1, 0.3, 0.3], "threshold": 0.85,
        "mode": "region_click"}, None)
    ex = _Ex(screen)
    ctx = _make_ctx(tmp, screen, ex, rel)
    r = _exec_dragger({"params": {"template": rel, "direction": "up",
                                  "distance": 0.5, "duration_ms": 600}}, ctx)
    assert r.goto == "out" and r.status == "ok", r
    sx, sy = r.data["start"]
    ex_, ey = r.data["end"]
    assert 29 <= sx <= 120 and 19 <= sy <= 80, (sx, sy)
    assert ex_ == sx and ey == sy - 100, (ex_, ey)  # 0.5×200=100
    assert ex.swipes and ex.swipes[0][:2] == (sx, sy)
    print("  ✅ 拖拽器遇随机点击素材：红框内随机点起滑，终点=起点+位移")


def test_dragger_normal_material_and_miss():
    tmp = Path(tempfile.mkdtemp(prefix="rc_drg2_"))
    screen = np.full((200, 300, 3), 127, np.uint8)
    screen[40:100, 50:110] = (255, 0, 0)   # 蓝块匹配区
    # 正常素材：60x60 蓝块 + alpha 遮罩
    mask = np.zeros((60, 60, 4), np.uint8)
    mask[..., 0] = 255
    mask[..., 3] = 255
    rel = _write_entry(tmp, "icon", {
        "id": "icon", "name": "icon", "image": "icon.png",
        "region": None, "threshold": 0.85}, mask)
    ex = _Ex(screen)
    ctx = _make_ctx(tmp, screen, ex, rel)
    r = _exec_dragger({"params": {"template": rel, "direction": "left",
                                  "distance": 0.5, "duration_ms": 300}}, ctx)
    assert r.goto == "out" and r.status == "ok", r
    sx, sy = r.data["start"]
    assert 50 <= sx <= 109 and 40 <= sy <= 99, (sx, sy)  # 遮罩内
    assert ex.swipes[0][:2] == (sx, sy)
    # 未命中：屏幕无蓝块
    screen2 = np.full((200, 300, 3), 127, np.uint8)
    ex2 = _Ex(screen2)
    ctx2 = _make_ctx(tmp, screen2, ex2, rel)
    r2 = _exec_dragger({"params": {"template": rel, "direction": "down",
                                   "distance": 0.5, "duration_ms": 300}}, ctx2)
    assert r2.goto == "not_found", r2
    assert not ex2.swipes, "未命中不应滑动"
    print("  ✅ 拖拽器遇正常素材：遮罩内随机点起滑；未命中 → not_found 不滑动")


def test_dragger_no_template_old_behavior():
    tmp = Path(tempfile.mkdtemp(prefix="rc_drg3_"))
    screen = np.full((200, 300, 3), 127, np.uint8)
    ex = _Ex(screen)
    ctx = _make_ctx(tmp, screen, ex, None)
    r = _exec_dragger({"params": {"direction": "up", "distance": 0.5,
                                  "duration_ms": 600}}, ctx)
    assert r.goto == "out" and r.status == "ok" and not r.data, r
    assert ex.swipes[0][:2] == (150, 100), ex.swipes  # 屏幕中心
    print("  ✅ 拖拽器未设置素材：屏幕中心起滑（旧行为不变）")


if __name__ == "__main__":
    test_region_only_saves_region_click()
    test_blue_without_mask_rejected()
    test_normal_element_no_mode()
    test_scene_save_validation()
    test_clicker_region_click()
    test_dragger_region_click_start()
    test_dragger_normal_material_and_miss()
    test_dragger_no_template_old_behavior()
    print("\n🎉 verify_visual_region_click 全部通过")
