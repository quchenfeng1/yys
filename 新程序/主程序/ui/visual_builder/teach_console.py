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
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QRadioButton, QVBoxLayout, QWidget)

from core.event_bus import get_global_bus
from core.events import Events
from ui.visual_builder.screen_canvas import ScreenCanvas


class TeachConsole(QWidget):
    """示教控制台（脚本图片指示器）"""

    def __init__(self, event_bus=None, store=None, assets_dir="", ocr=None,
                 parent=None):
        super().__init__(parent)
        self._bus = event_bus or get_global_bus()
        self._store = store
        self._assets_dir = Path(assets_dir) if assets_dir else Path(".")
        self._ocr = ocr  # OcrLocator（复用现有 PaddleOCR，未装时降级）
        self._task_name = ""
        self._unknown_count = 0
        self._scene_name = ""
        self._judgements: list[dict] = []
        self._pending_points: list[tuple] = []
        self._mode = "point"

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
        for rb in (self._rb_point, self._rb_scene, self._rb_ocr):
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
        self._logic_combo = QComboBox()
        self._logic_combo.addItems(["and", "or"])
        self._logic_combo.setToolTip("场景判定逻辑：全部满足/任一满足")
        self._input_row.addWidget(self._scene_name_input)
        self._input_row.addWidget(self._point_label_input)
        self._input_row.addWidget(self._ocr_label_input)
        self._input_row.addWidget(self._logic_combo)
        lay.addLayout(self._input_row)

        # 操作按钮
        btn_row = QHBoxLayout()
        self._region_btn = QPushButton("⇱ 框选区域")
        self._region_btn.setCheckable(True)
        self._region_btn.toggled.connect(self._on_region_toggle)
        self._add_judge_btn = QPushButton("＋ 判定原语(裁剪)")
        self._add_judge_btn.clicked.connect(self._capture_region_as_judgement)
        self._submit_btn = QPushButton("✔ 提交指示")
        self._submit_btn.clicked.connect(self._submit)
        self._skip_btn = QPushButton("⏭ 跳过")
        self._skip_btn.clicked.connect(self._skip)
        self._stop_btn = QPushButton("⏹ 停止")
        self._stop_btn.clicked.connect(self._stop)
        for b in (self._region_btn, self._add_judge_btn, self._submit_btn,
                  self._skip_btn, self._stop_btn):
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
        lay.addWidget(self._canvas, 1)

        # 订阅未知画面
        self._bus.subscribe(Events.VISUAL_UNKNOWN, self._on_unknown)

        self._update_inputs_visibility()

    # ── 未知画面接收 ─────────────────────────────────────
    def _on_unknown(self, **kw) -> None:
        path = kw.get("screenshot_path", "")
        self._task_name = kw.get("task", "")
        self._unknown_count = kw.get("count", 0)
        if path and Path(path).exists():
            img = cv2.imread(str(path))
            self._canvas.set_image(img)
        else:
            self._canvas.set_image(None)
        self._canvas.clear_overlays()
        self._scene_name = ""
        self._judgements = []
        self._pending_points = []
        self._region_btn.setChecked(False)
        self._status.setText(f"⚠ 未知画面 #{self._unknown_count} — 请指示怎么办")
        self._hint.setText(f"任务「{self._task_name}」遇到不认识画面"
                           f"（{kw.get('info', {}).get('type', '?')}），请在截图上指示")

    # ── 模式切换 ─────────────────────────────────────────
    def _on_mode_changed(self) -> None:
        self._update_inputs_visibility()

    def _update_inputs_visibility(self) -> None:
        scene = self._rb_scene.isChecked()
        point = self._rb_point.isChecked()
        ocr = self._rb_ocr.isChecked()
        self._scene_name_input.setVisible(scene)
        self._logic_combo.setVisible(scene)
        self._point_label_input.setVisible(point)
        self._ocr_label_input.setVisible(ocr)
        self._mode = "scene" if scene else ("ocr" if ocr else "point")
        # 标注场景需要框选 → 自动开框选
        self._region_btn.setVisible(scene or ocr)
        self._add_judge_btn.setVisible(scene)
        if scene or ocr:
            self._region_btn.setChecked(True)
            self._canvas.set_region_mode(True)

    def _on_region_toggle(self, checked: bool) -> None:
        self._canvas.set_region_mode(checked)

    # ── 画布交互 ─────────────────────────────────────────
    def _on_canvas_point(self, x: float, y: float) -> None:
        if not self._canvas.has_image():
            return
        if self._mode == "point":
            label = self._point_label_input.text().strip()
            if not label:
                label = f"pt{len(self._pending_points) + 1}"
            self._pending_points.append((x, y, label))
            self._canvas.add_point(x, y, label)
            self._point_label_input.clear()

    def _on_canvas_region(self, x: float, y: float, w: float, h: float) -> None:
        if not self._canvas.has_image():
            return
        if self._mode == "scene":
            # 框选 → 先暂存，等用户点【判定原语】时裁剪
            self._last_region = (x, y, w, h)
            self._canvas.add_rect(x, y, w, h, f"区域{len(self._judgements) + 1}")
        elif self._mode == "ocr":
            label = self._ocr_label_input.text().strip() or f"ocr_{len(self._judgements) + 1}"
            region = {"id": label, "label": label,
                      "region": [x, y, w, h], "mode": "relative"}
            self._canvas.add_rect(x, y, w, h, label)
            # 实时识别预览（OCR 引擎可用时）
            preview = self._ocr_preview(x, y, w, h)
            self._status.setText(f"OCR区域「{label}」已提交 · 识别: {preview}")
            self._bus.publish(Events.VISUAL_ACTION_RECEIVED,
                              action="add_ocr_region", region=region,
                              task=self._task_name)

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
        rel_dir = f"visual/{self._task_name}"
        out_dir = self._assets_dir / rel_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{name}_{int(time.time() * 1000)}.png"
        cv2.imwrite(str(out_dir / fname), crop)
        return f"{rel_dir}/{fname}"

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
            scene_name = self._scene_name_input.text().strip() or "未命名场景"
            scene_id = scene_name
            scene = {
                "id": scene_id,
                "name": scene_name,
                "judgements": list(self._judgements),
                "logic": self._logic_combo.currentText(),
            }
            self._bus.publish(Events.VISUAL_ACTION_RECEIVED,
                              action="add_scene", scene=scene,
                              task=self._task_name)
            self._status.setText(f"✔ 场景「{scene_name}」已提交，继续…")
            self._canvas.clear_overlays()
            self._judgements = []
        elif self._mode == "point":
            if not self._pending_points:
                self._hint.setText("请先在截图上点击目标位置")
                return
            for x, y, label in self._pending_points:
                point = {"id": label, "label": label, "x": x, "y": y,
                         "mode": "relative"}
                self._bus.publish(Events.VISUAL_ACTION_RECEIVED,
                                  action="add_point", point=point,
                                  task=self._task_name)
            self._status.setText(f"✔ 已提交 {len(self._pending_points)} 个点击点，继续…")
            self._pending_points = []

    def _skip(self) -> None:
        self._bus.publish(Events.VISUAL_ACTION_RECEIVED, action="skip",
                          task=self._task_name)
        self._canvas.set_image(None)
        self._status.setText("⏭ 已跳过该画面，继续…")

    def _stop(self) -> None:
        self._bus.publish(Events.VISUAL_ACTION_RECEIVED, action="stop",
                          task=self._task_name)
        self._status.setText("⏹ 已停止示教")

    # ── 外部注入 ─────────────────────────────────────────
    def set_screenshot(self, img) -> None:
        """外部注入当前截图（供裁剪）"""
        self._last_image = img
