"""
17-可视化构建模块：示教控制台（P1，TeachConsole）。

脚本图片指示器：展示未知画面截图 → 接收用户指示（标注场景/指示点击/OCR区域/
跳过/停止）→ 发布 VISUAL_ACTION_RECEIVED 恢复执行。

模式：
- 标注场景：输入场景名 → 框选判定区域（自动裁剪模板入库）→ 完成场景
- 指示点击：点击截图 → 记录点击点（相对坐标）
- OCR区域：输入标签 → 框选文字区域
- 跳过 / 停止
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel,
                             QLineEdit, QPushButton, QRadioButton, QSpinBox,
                             QVBoxLayout, QWidget)

from core.event_bus import get_global_bus
from core.events import Events
from ui.visual_builder.screen_canvas import ScreenCanvas

# 未知画面类型 → 锁定的示教模式（节点触发时只能用对应模式）
_MODE_BY_TYPE = {
    "scene_new": "scene",
    "scene": "scene",
    "element_new": "element",
    "element": "element",
}
_MODE_LABEL = {"scene": "场景判定", "element": "识图器", "ocr": "OCR", "point": "点击"}


class TeachConsole(QWidget):
    """示教控制台（脚本图片指示器）"""

    def __init__(self, event_bus=None, store=None, assets_dir="", ocr=None,
                 scene_commit_callback=None, element_commit_callback=None,
                 parent=None):
        super().__init__(parent)
        self._bus = event_bus or get_global_bus()
        self._store = store
        self._assets_dir = Path(assets_dir) if assets_dir else Path(".")
        self._ocr = ocr  # OcrLocator（复用现有 PaddleOCR，未装时降级）
        self._scene_commit_callback = scene_commit_callback  # (scene, node_id) -> None
        self._element_commit_callback = element_commit_callback  # (template, region, node_id) -> None
        self._task_name = ""
        self._unknown_count = 0
        self._scene_name = ""
        self._judgements: list[dict] = []
        self._pending_points: list[dict] = []
        self._mode = "point"
        self._teach_node = ""  # 当前示教目标节点 id（未设置识图节点触发时）
        self._manual_mode = False  # True=手动示教（走回调）；False=阻断示教（走事件）
        self._element_region = None  # 识图元素示教：搜索区域 (x,y,w,h) 相对
        # 场景示教：红框(识别区域) + 蓝框(整体标识) + 遮罩
        self._regions: list[dict] = []       # [{name, region, markers:[{name, region, mask_key}]}]
        self._current_region: dict | None = None
        self._current_marker: dict | None = None
        self._accuracy = 0                   # 场景判断精度（0=全部命中）
        self._pending_frame: str | None = None  # 待处理的框选类型
        self._mask_seq = 0                   # 蓝框遮罩 key 序号（改名不受影响）
        self._locked_mode: str | None = None  # 锁定示教模式（节点触发时，禁用其他模式）

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        # 标题 / 状态
        self._status = QLabel("示教控制台（等待未知画面…）")
        self._status.setStyleSheet("font-weight:bold;")
        lay.addWidget(self._status)

        # 模式选择
        mode_row = QHBoxLayout()
        self._rb_point = QRadioButton("指示点击")
        self._rb_point.setChecked(True)
        self._rb_scene = QRadioButton("标注场景")
        self._rb_ocr = QRadioButton("OCR区域")
        self._rb_element = QRadioButton("识图元素")
        for rb in (self._rb_point, self._rb_scene, self._rb_ocr,
                   self._rb_element):
            rb.toggled.connect(self._on_mode_changed)
            mode_row.addWidget(rb)
        mode_row.addStretch(1)
        lay.addLayout(mode_row)

        # 标注输入区
        self._input_row = QHBoxLayout()
        self._scene_name_input = QLineEdit()
        self._scene_name_input.setPlaceholderText("场景名（如 主界面）")
        self._point_label_input = QLineEdit()
        self._point_label_input.setPlaceholderText("点击点标签（如 btn.start）")
        self._ocr_label_input = QLineEdit()
        self._ocr_label_input.setPlaceholderText("OCR区域标签（如 体力）")
        self._element_name_input = QLineEdit()
        self._element_name_input.setPlaceholderText("元素名（如 btn.confirm）")
        self._accuracy_label = QLabel("精度")
        self._accuracy_spin = QSpinBox()
        self._accuracy_spin.setRange(0, 99)
        self._accuracy_spin.setValue(0)
        self._accuracy_spin.setToolTip("场景判断精度：需命中 N 个蓝框标识才通过（0=全部命中）")
        self._accuracy_spin.valueChanged.connect(self._on_accuracy)
        self._input_row.addWidget(self._scene_name_input)
        self._input_row.addWidget(self._point_label_input)
        self._input_row.addWidget(self._ocr_label_input)
        self._input_row.addWidget(self._element_name_input)
        self._input_row.addWidget(self._accuracy_label)
        self._input_row.addWidget(self._accuracy_spin)
        lay.addLayout(self._input_row)

        # 操作按钮
        btn_row = QHBoxLayout()
        self._click_region_btn = QPushButton("⇱ 框选点击区域")
        self._click_region_btn.setCheckable(True)
        self._click_region_btn.toggled.connect(self._on_click_region_toggle)
        self._red_btn = QPushButton("＋红框(识别)")
        self._red_btn.setCheckable(True)
        self._red_btn.toggled.connect(self._on_red_toggle)
        self._blue_btn = QPushButton("＋蓝框(标识)")
        self._blue_btn.setCheckable(True)
        self._blue_btn.toggled.connect(self._on_blue_toggle)
        self._region_btn = QPushButton("⇱ 框选区域")
        self._region_btn.setCheckable(True)
        self._region_btn.toggled.connect(self._on_region_toggle)
        self._brush_btn = QPushButton("🖌 画笔")
        self._brush_btn.setCheckable(True)
        self._brush_btn.toggled.connect(self._on_brush_toggle)
        self._brush_size_spin = QSpinBox()
        self._brush_size_spin.setRange(1, 60)
        self._brush_size_spin.setValue(10)
        self._brush_size_spin.setToolTip("画笔大小（像素）")
        self._brush_size_spin.valueChanged.connect(self._on_brush_size)
        self._submit_btn = QPushButton("✔ 提交指示")
        self._submit_btn.clicked.connect(self._submit)
        self._skip_btn = QPushButton("⏭ 跳过")
        self._skip_btn.clicked.connect(self._skip)
        self._stop_btn = QPushButton("⏹ 停止")
        self._stop_btn.clicked.connect(self._stop)
        for b in (self._click_region_btn, self._red_btn, self._blue_btn,
                  self._region_btn, self._brush_btn, self._brush_size_spin,
                  self._submit_btn, self._skip_btn, self._stop_btn):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        # 提示
        self._hint = QLabel("提示：标注场景=先框选区域再点【判定原语(裁剪)】；"
                            "指示点击=直接点截图；完成后点【提交指示】")
        self._hint.setStyleSheet("color:#8a94a6;font-size:11px;")
        self._hint.setWordWrap(True)
        lay.addWidget(self._hint)

        # 截图画布
        self._canvas = ScreenCanvas()
        self._canvas.point_clicked.connect(self._on_canvas_point)
        self._canvas.region_selected.connect(self._on_canvas_region)
        self._canvas.box_deleted.connect(self._on_box_deleted)
        self._canvas.box_rename_requested.connect(self._on_box_rename_requested)
        lay.addWidget(self._canvas, 1)

        # 订阅未知画面
        self._bus.subscribe(Events.VISUAL_UNKNOWN, self._on_unknown)

        self._update_inputs_visibility()

    # ── 未知画面接收 ─────────────────────────────────────
    def _on_unknown(self, **kw) -> None:
        path = kw.get("screenshot_path", "")
        self._task_name = kw.get("task", "")
        self._unknown_count = kw.get("count", 0)
        info = kw.get("info") or {}
        self._teach_node = info.get("node", "")
        info_type = info.get("type", "")
        if path and Path(path).exists():
            img = cv2.imread(str(path))
            self._canvas.set_image(img)
        else:
            self._canvas.set_image(None)
        self._canvas.clear_overlays()
        self._canvas.clear_all_masks()
        self._scene_name = ""
        self._judgements = []
        self._pending_points = []
        self._regions = []
        self._current_region = None
        self._current_marker = None
        self._pending_frame = None
        self._element_region = None
        self._reset_frame_buttons()
        # 锁定示教模式：该节点只能用自己的示教页面（禁用其他模式切换）
        lock_mode = _MODE_BY_TYPE.get(info_type)
        self._lock_mode(lock_mode)
        # 未设置的图像识别节点 → 直接进入对应示教模式
        if lock_mode == "scene":
            self._rb_scene.setChecked(True)
        elif lock_mode == "element":
            self._rb_element.setChecked(True)
        self._status.setText(f"⚠ 未知画面 #{self._unknown_count} — 请指示怎么办")
        if lock_mode:
            self._hint.setText(f"任务「{self._task_name}」遇到不认识画面"
                               f"（{info_type}），当前为「{_MODE_LABEL.get(lock_mode, '')}」"
                               f"节点示教，模式已锁定")
        else:
            self._hint.setText(f"任务「{self._task_name}」遇到不认识画面"
                               f"（{info_type}），请在截图上指示")

    # ── 模式切换 ─────────────────────────────────────────
    def _lock_mode(self, mode: str | None) -> None:
        """锁定示教模式：mode 非 None 时禁用其他模式切换按钮"""
        self._locked_mode = mode
        locked = mode is not None
        for rb in (self._rb_point, self._rb_scene, self._rb_ocr, self._rb_element):
            rb.setEnabled(not locked)

    def _unlock_mode(self) -> None:
        self._lock_mode(None)

    def _on_mode_changed(self) -> None:
        self._reset_frame_buttons()
        self._update_inputs_visibility()

    def _reset_frame_buttons(self) -> None:
        """取消所有框选/画笔按钮选中态（避免互斥混乱）"""
        self._pending_frame = None
        for b in (self._click_region_btn, self._red_btn, self._blue_btn,
                  self._region_btn):
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        self._brush_btn.blockSignals(True)
        self._brush_btn.setChecked(False)
        self._brush_btn.blockSignals(False)
        self._canvas.set_region_mode(False)
        self._canvas.set_brush_mode(False)

    def _update_inputs_visibility(self) -> None:
        scene = self._rb_scene.isChecked()
        point = self._rb_point.isChecked()
        ocr = self._rb_ocr.isChecked()
        element = self._rb_element.isChecked()
        self._scene_name_input.setVisible(scene)
        self._accuracy_label.setVisible(scene)
        self._accuracy_spin.setVisible(scene)
        self._point_label_input.setVisible(point)
        self._ocr_label_input.setVisible(ocr)
        self._element_name_input.setVisible(element)
        if element:
            self._mode = "element"
        elif scene:
            self._mode = "scene"
        elif ocr:
            self._mode = "ocr"
        else:
            self._mode = "point"
        # 各模式专属按钮显隐
        self._click_region_btn.setVisible(point)
        self._red_btn.setVisible(scene)
        self._blue_btn.setVisible(scene)
        self._region_btn.setVisible(ocr or element)
        self._brush_btn.setVisible(scene or element)
        self._brush_size_spin.setVisible(scene or element)
        if scene:
            self._hint.setText("标注场景：点【＋红框】框识别区域(命名) → 点【＋蓝框】"
                               "框整体标识(命名) → 开【画笔】涂图标 → 【提交】。"
                               "一个红框内可有多个蓝框，每个蓝框的遮罩为一个整体。")
        elif element:
            self._hint.setText("识图元素：可先【框选区域】限定搜索范围（红线），"
                               "再开【画笔】涂出要识别的图标，最后【提交】。")
        elif ocr:
            self._hint.setText("OCR区域：【框选区域】框文字范围(红色)并命名，自动识别文字。")
        else:
            self._hint.setText("指示点击：直接点截图=固定点击；或点【框选点击区域】框范围="
                               "区域内随机点击；完成后【提交】。")

    def _on_accuracy(self, v: int) -> None:
        self._accuracy = max(0, int(v))

    def _begin_frame(self, kind: str) -> None:
        """进入框选模式，记录本次框选用途"""
        self._pending_frame = kind
        self._canvas.set_region_mode(True)
        self._canvas.set_brush_mode(False)
        self._brush_btn.blockSignals(True)
        self._brush_btn.setChecked(False)
        self._brush_btn.blockSignals(False)

    def _on_click_region_toggle(self, checked: bool) -> None:
        if checked:
            self._begin_frame("click_region")

    def _on_red_toggle(self, checked: bool) -> None:
        if checked:
            self._begin_frame("red")

    def _on_blue_toggle(self, checked: bool) -> None:
        if checked:
            if not self._current_region:
                self._blue_btn.setChecked(False)
                self._hint.setText("请先点【＋红框】框一个识别区域，再框蓝框")
                return
            self._begin_frame("blue")

    def _on_region_toggle(self, checked: bool) -> None:
        if checked:
            kind = "element" if self._mode == "element" else "ocr"
            self._begin_frame(kind)

    def _on_brush_toggle(self, checked: bool) -> None:
        self._canvas.set_brush_mode(checked)
        if checked:
            for b in (self._click_region_btn, self._red_btn, self._blue_btn,
                      self._region_btn):
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
            self._pending_frame = None

    def _on_brush_size(self, v: int) -> None:
        self._canvas.set_brush_size(v)

    # ── 画布交互 ─────────────────────────────────────────
    def _on_canvas_point(self, x: float, y: float) -> None:
        if not self._canvas.has_image():
            return
        if self._mode == "point":
            label = self._point_label_input.text().strip()
            if not label:
                label = f"pt{len(self._pending_points) + 1}"
            self._pending_points.append({"id": label, "label": label,
                                         "x": x, "y": y, "mode": "relative"})
            self._canvas.add_point(x, y, label)
            self._point_label_input.clear()

    def _on_canvas_region(self, x: float, y: float, w: float, h: float) -> None:
        if not self._canvas.has_image():
            return
        kind = self._pending_frame
        self._pending_frame = None
        self._reset_frame_buttons()
        if kind == "red":
            self._add_red_region(x, y, w, h)
        elif kind == "blue":
            self._add_blue_marker(x, y, w, h)
        elif kind == "click_region":
            self._add_click_region(x, y, w, h)
        elif kind == "ocr":
            self._add_ocr_region(x, y, w, h)
        elif kind == "element":
            self._set_element_region(x, y, w, h)

    # ── 红框(识别区域) / 蓝框(整体标识) ──────────────────
    def _ask_name(self, title: str, prompt: str, default: str) -> str:
        name, ok = QInputDialog.getText(self, title, prompt, text=default)
        if not ok or not name.strip():
            return default
        return name.strip()

    def _add_red_region(self, x: float, y: float, w: float, h: float) -> None:
        default = f"红{len(self._regions) + 1}区"
        name = self._ask_name("识别区域名", "红色识别区域名（搜索范围）：", default)
        region = {"name": name, "region": [x, y, w, h], "markers": []}
        region["box_id"] = self._canvas.add_region(x, y, w, h, name, ref=region)
        self._regions.append(region)
        self._current_region = region
        self._current_marker = None
        self._status.setText(f"✔ 红框「{name}」已添加；可继续＋蓝框或＋红框")

    def _add_blue_marker(self, x: float, y: float, w: float, h: float) -> None:
        region = self._current_region
        if region is None:
            self._hint.setText("请先点【＋红框】框一个识别区域，再框蓝框")
            return
        default = f"蓝{len(region['markers']) + 1}区"
        name = self._ask_name("标识名", "蓝色标识名（框内遮罩为一个整体）：", default)
        self._mask_seq += 1
        key = f"m{self._mask_seq}"
        marker = {"name": name, "region": [x, y, w, h], "mask_key": key}
        marker["box_id"] = self._canvas.add_marker(x, y, w, h, name, ref=marker)
        region["markers"].append(marker)
        self._current_marker = marker
        self._canvas.set_active_mask(key)
        self._status.setText(f"✔ 蓝框「{name}」已加入「{region['name']}」；开【画笔】涂图标")

    # ── 选框删除 / 改名 ──────────────────────────────────
    def _on_box_deleted(self, box_id: str) -> None:
        """画布删除选框 → 同步从 _regions 移除对应红框/蓝框"""
        for region in self._regions:
            if region.get("box_id") == box_id:
                self._regions.remove(region)
                if self._current_region is region:
                    self._current_region = None
                    self._current_marker = None
                self._status.setText("✔ 已删除识别区域")
                return
            for marker in region.get("markers", []):
                if marker.get("box_id") == box_id:
                    region["markers"].remove(marker)
                    if self._current_marker is marker:
                        self._current_marker = None
                    self._status.setText("✔ 已删除标识")
                    return

    def _on_box_rename_requested(self, box_id: str) -> None:
        """双击选框 → 弹窗改名，同步 ref 与画布显示"""
        for region in self._regions:
            if region.get("box_id") == box_id:
                name, ok = QInputDialog.getText(
                    self, "识别区域名", "区域名：", text=region.get("name", ""))
                if ok and name.strip():
                    region["name"] = name.strip()
                    self._canvas.rename_box(box_id, name.strip())
                return
            for marker in region.get("markers", []):
                if marker.get("box_id") == box_id:
                    name, ok = QInputDialog.getText(
                        self, "标识名", "标识名：", text=marker.get("name", ""))
                    if ok and name.strip():
                        marker["name"] = name.strip()
                        self._canvas.rename_box(box_id, name.strip())
                    return

    def _add_click_region(self, x: float, y: float, w: float, h: float) -> None:
        label = self._point_label_input.text().strip() or \
            f"area{len(self._pending_points) + 1}"
        self._pending_points.append({"id": label, "label": label,
                                     "region": [x, y, w, h],
                                     "kind": "region", "mode": "relative"})
        self._canvas.add_region(x, y, w, h, f"点击区:{label}")
        self._point_label_input.clear()
        self._status.setText(f"✔ 点击区域「{label}」已记录（区域内随机点击）")

    def _add_ocr_region(self, x: float, y: float, w: float, h: float) -> None:
        label = self._ocr_label_input.text().strip() or \
            f"ocr_{len(self._judgements) + 1}"
        region = {"id": label, "label": label,
                  "region": [x, y, w, h], "mode": "relative"}
        self._canvas.add_region(x, y, w, h, label)  # 红框
        preview = self._ocr_preview(x, y, w, h)
        self._status.setText(f"OCR区域「{label}」已提交 · 识别: {preview}")
        self._bus.publish(Events.VISUAL_ACTION_RECEIVED,
                          action="add_ocr_region", region=region,
                          task=self._task_name)

    def _set_element_region(self, x: float, y: float, w: float, h: float) -> None:
        # 识图元素：框选 → 搜索区域（红线），限制图标搜索范围
        self._element_region = (x, y, w, h)
        self._canvas.add_region(x, y, w, h, "搜索区域")
        self._status.setText("✔ 搜索区域已框选；可开【画笔】涂出图标，或直接【提交】")

    def _capture_region_as_judgement(self) -> None:
        """把最近框选区域裁剪为模板，作为场景判定原语"""
        if not getattr(self, "_last_region", None) or not self._canvas.has_image():
            self._hint.setText("请先在截图上框选一个区域，再点【判定原语(裁剪)】")
            return
        x, y, w, h = self._last_region
        scene_name = self._scene_name_input.text().strip() or "scene"
        # 裁剪当前截图区域 → 保存模板
        idx = len(self._judgements) + 1
        rel = self._save_template_crop(x, y, w, h, f"{scene_name}_{idx}")
        self._judgements.append({
            "primitive": "template",
            "template": rel,
            "region": [x, y, w, h],
            "threshold": 0.85,
        })
        self._status.setText(f"✔ 判定原语 #{idx} 已裁剪: {rel}")
        self._last_region = None

    def _save_template_crop(self, x: float, y: float, w: float, h: float,
                            name: str) -> str:
        """裁剪截图区域保存到任务素材目录，返回相对 assets 根路径"""
        img = self._canvas_current_image()
        if img is None:
            return ""
        H, W = img.shape[:2]
        x0, y0 = int(x * W), int(y * H)
        w0, h0 = max(1, int(w * W)), max(1, int(h * H))
        crop = img[y0:y0 + h0, x0:x0 + w0]
        rel_dir = f"visual/{self._task_name}".rstrip("/") or "visual"
        out_dir = self._assets_dir / rel_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{name}_{int(time.time() * 1000)}.png"
        cv2.imwrite(str(out_dir / fname), crop)
        return f"{rel_dir}/{fname}"

    def _save_element_template(self) -> str:
        """用画笔遮罩裁剪图标 → 保存带 alpha 的 RGBA PNG，返回相对 assets 根路径"""
        img = self._canvas_current_image()
        mask = self._canvas.get_mask()
        if img is None or mask is None or not mask.any():
            return ""
        ys, xs = np.nonzero(mask)
        H, W = img.shape[:2]
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(W - 1, x1), min(H - 1, y1)
        if x1 < x0 or y1 < y0:
            return ""
        crop = img[y0:y1 + 1, x0:x1 + 1]
        crop_mask = mask[y0:y1 + 1, x0:x1 + 1]
        rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
        rgba[:, :, 3] = crop_mask
        rel_dir = f"visual/{self._task_name}".rstrip("/") or "visual"
        out_dir = self._assets_dir / rel_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = f"element_{int(time.time() * 1000)}.png"
        cv2.imwrite(str(out_dir / fname), rgba)
        return f"{rel_dir}/{fname}"

    def _save_marker_template(self, mask: np.ndarray, prefix: str) -> str:
        """裁剪蓝框遮罩 → 保存带 alpha 的 RGBA PNG（遮罩块为一个整体图案）。

        兼容保留：整体裁剪一张图。新逻辑请用 _save_marker_templates（连通域拆分）。
        """
        img = self._canvas_current_image()
        if img is None or mask is None or not mask.any():
            return ""
        ys, xs = np.nonzero(mask)
        H, W = img.shape[:2]
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(W - 1, x1), min(H - 1, y1)
        if x1 < x0 or y1 < y0:
            return ""
        crop = img[y0:y1 + 1, x0:x1 + 1]
        crop_mask = mask[y0:y1 + 1, x0:x1 + 1]
        rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
        rgba[:, :, 3] = crop_mask
        rel_dir = f"visual/{self._task_name}".rstrip("/") or "visual"
        out_dir = self._assets_dir / rel_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in str(prefix) if c.isalnum() or c in "_-.") or "marker"
        fname = f"{safe}_{int(time.time() * 1000)}.png"
        cv2.imwrite(str(out_dir / fname), rgba)
        return f"{rel_dir}/{fname}"

    def _save_marker_templates(self, mask: np.ndarray, prefix: str) -> list[dict]:
        """蓝框遮罩按连通域拆成多个独立图标块，每块裁剪独立 RGBA 模板。

        返回 [{template, dx, dy}]，dx/dy = 该块相对第一块左上角的像素偏移，
        供整体匹配时校验「每个图标都找到且相对位置对应」。
        """
        img = self._canvas_current_image()
        if img is None or mask is None or not mask.any():
            return []
        H, W = img.shape[:2]
        n, labels, stats, _ = cv2.connectedComponentsWithStats(
            mask.astype(np.uint8), 8)
        rel_dir = f"visual/{self._task_name}".rstrip("/") or "visual"
        out_dir = self._assets_dir / rel_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in str(prefix) if c.isalnum() or c in "_-.") or "block"
        out: list[dict] = []
        base: tuple[int, int] | None = None
        for i in range(1, n):  # 跳过背景(0)
            bx, by, bw, bh, area = stats[i]
            if area < 6:  # 忽略噪点
                continue
            x0, y0 = int(bx), int(by)
            x1, y1 = int(bx + bw - 1), int(by + bh - 1)
            crop = img[y0:y1 + 1, x0:x1 + 1]
            cm = (labels[y0:y1 + 1, x0:x1 + 1] == i).astype(np.uint8) * 255
            rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
            rgba[:, :, 3] = cm
            fname = f"{safe}_{i}_{int(time.time() * 1000)}.png"
            cv2.imwrite(str(out_dir / fname), rgba)
            if base is None:
                base = (x0, y0)
            out.append({"template": f"{rel_dir}/{fname}",
                        "dx": x0 - base[0], "dy": y0 - base[1]})
        return out

    def _canvas_current_image(self):
        """从画布取回当前图像（用于裁剪）——由外部注入或从缓存读取"""
        img = getattr(self, "_last_image", None)
        return img

    def _ocr_preview(self, x: float, y: float, w: float, h: float) -> str:
        """OCR 区域实时识别预览（OcrLocator 未就绪时降级提示）"""
        if self._ocr is None or not getattr(self._ocr, "is_ready", False):
            return "OCR 引擎未就绪（安装 PaddleOCR 后自动识别）"
        img = self._canvas_current_image()
        if img is None:
            return "无截图可识别"
        H, W = img.shape[:2]
        x0, y0 = int(x * W), int(y * H)
        w0, h0 = max(1, int(w * W)), max(1, int(h * H))
        crop = img[y0:y0 + h0, x0:x0 + w0]
        if crop.size == 0:
            return "区域无效"
        try:
            results = self._ocr.recognize(crop)
            texts = [r.text for r in results]
            return "｜".join(texts) if texts else "（未识别到文字）"
        except Exception as e:
            return f"（识别失败: {e}）"

    # ── 提交 / 跳过 / 停止 ───────────────────────────────
    def _submit(self) -> None:
        if self._mode == "scene":
            self._submit_scene()
        elif self._mode == "element":
            self._submit_element()
        elif self._mode == "point":
            self._submit_point()

    def _submit_scene(self) -> None:
        """场景：遍历 红框→蓝框→遮罩 裁剪模板，生成 regions/markers 结构"""
        scene_name = self._scene_name_input.text().strip() or "未命名场景"
        regions_out: list[dict] = []
        for region in self._regions:
            markers_out: list[dict] = []
            for marker in region.get("markers", []):
                mask = self._canvas.get_mask(marker.get("mask_key", ""))
                templates = self._save_marker_templates(
                    mask, f"{scene_name}_{marker.get('name', 'm')}")
                if templates:
                    markers_out.append({"name": marker.get("name", ""),
                                        "templates": templates,
                                        "region": marker.get("region"),
                                        "threshold": 0.85})
            if markers_out:
                regions_out.append({"name": region.get("name", ""),
                                    "region": region.get("region"),
                                    "markers": markers_out})
        if not regions_out:
            self._hint.setText("请先框红框 + 蓝框并用画笔涂出图标，再【提交】")
            return
        scene = {"id": scene_name, "name": scene_name,
                 "accuracy": int(self._accuracy or 0),
                 "regions": regions_out}
        if self._manual_mode and self._scene_commit_callback is not None:
            self._scene_commit_callback(scene, self._teach_node)
            self._status.setText(f"✔ 识别素材「{scene_name}」已保存并绑定节点")
        else:
            self._bus.publish(Events.VISUAL_ACTION_RECEIVED,
                              action="add_scene", scene=scene,
                              task=self._task_name, node=self._teach_node)
            self._status.setText(f"✔ 场景「{scene_name}」已提交，继续…")
        self._canvas.clear_overlays()
        self._canvas.clear_all_masks()
        self._regions = []
        self._current_region = None
        self._current_marker = None
        self._unlock_mode()

    def _submit_element(self) -> None:
        rel = self._save_element_template()
        if not rel:
            self._hint.setText("请先用【画笔】涂出要识别的图标，再点【提交】")
            return
        name = self._element_name_input.text().strip() or "element"
        region = None
        if self._element_region:
            region = ",".join(f"{v:.4f}" for v in self._element_region)
        if self._manual_mode and self._element_commit_callback is not None:
            self._element_commit_callback(rel, region, self._teach_node)
            self._status.setText(f"✔ 识图元素「{name}」已保存并绑定节点")
        else:
            self._bus.publish(Events.VISUAL_ACTION_RECEIVED,
                              action="add_element", template=rel, name=name,
                              region=region,
                              task=self._task_name, node=self._teach_node)
            self._status.setText(f"✔ 识图元素「{name}」已提交，继续…")
        self._canvas.clear_mask()
        self._canvas.clear_overlays()
        self._element_region = None
        self._unlock_mode()

    def _submit_point(self) -> None:
        if not self._pending_points:
            self._hint.setText("请先在截图上点击目标位置，或框选点击区域")
            return
        for point in self._pending_points:
            self._bus.publish(Events.VISUAL_ACTION_RECEIVED,
                              action="add_point", point=point,
                              task=self._task_name)
        self._status.setText(f"✔ 已提交 {len(self._pending_points)} 个点击目标，继续…")
        self._canvas.clear_overlays()
        self._pending_points = []
        self._unlock_mode()

    def _skip(self) -> None:
        self._bus.publish(Events.VISUAL_ACTION_RECEIVED, action="skip",
                          task=self._task_name)
        self._canvas.set_image(None)
        self._unlock_mode()
        self._status.setText("⏭ 已跳过该画面，继续…")

    def _stop(self) -> None:
        self._bus.publish(Events.VISUAL_ACTION_RECEIVED, action="stop",
                          task=self._task_name)
        self._unlock_mode()
        self._status.setText("⏹ 已停止示教")

    # ── 外部注入 ─────────────────────────────────────────
    def set_screenshot(self, img) -> None:
        """外部注入当前截图（供裁剪）"""
        self._last_image = img

    def start_manual_teach(self, img, node_id: str = "") -> None:
        """手动示教：注入一张截图 → 进入「标注场景」模式 → 目标节点 node_id"""
        self._manual_mode = True
        self._teach_node = node_id
        self._task_name = ""
        self._unknown_count = 0
        self._last_image = img
        self._canvas.set_image(img)
        self._canvas.clear_overlays()
        self._scene_name = ""
        self._judgements = []
        self._pending_points = []
        self._regions = []
        self._current_region = None
        self._current_marker = None
        self._pending_frame = None
        self._element_region = None
        self._accuracy = 0
        self._reset_frame_buttons()
        self._lock_mode("scene")
        self._rb_scene.setChecked(True)
        if img is None:
            self._status.setText("🎓 手动示教：截图失败，请检查设备连接")
        else:
            self._status.setText("🎓 场景示教：点【＋红框】框识别区域 → 点【＋蓝框】框整体标识 → "
                                 "开【画笔】涂图标 → 【提交】")

    def start_element_teach(self, img, node_id: str = "") -> None:
        """手动示教：识图元素模式 → 框搜索区域 + 画笔涂图标 → 目标节点 node_id"""
        self._manual_mode = True
        self._teach_node = node_id
        self._task_name = ""
        self._unknown_count = 0
        self._last_image = img
        self._element_region = None
        self._canvas.set_image(img)
        self._canvas.clear_overlays()
        self._scene_name = ""
        self._judgements = []
        self._pending_points = []
        self._regions = []
        self._current_region = None
        self._current_marker = None
        self._pending_frame = None
        self._reset_frame_buttons()
        self._lock_mode("element")
        self._rb_element.setChecked(True)
        if img is None:
            self._status.setText("🎓 识图元素示教：截图失败，请检查设备连接")
        else:
            self._status.setText("🎓 识图元素示教：可先框选搜索区域，再用画笔涂出图标")
