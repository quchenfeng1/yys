"""
17-可视化构建模块：示教控制台（P1，TeachConsole，2026-08-15 简化重构）。

单一标注流程（不再区分场景/元素/点击/OCR 四种模式）：
- 📷 截图：立即从模拟器截一张图显示
- ＋红框（识别区域，搜索范围）/ ＋蓝框（标识，框内画笔遮罩为一个整体）/ ＋黄框（OCR 文字位置，需画在蓝框内）
- 🖌 画笔：涂遮罩
- ↩ 撤回：撤销上一步（框选/涂色/删除/拖动，最多 30 步）
- 💾 保存为场景：弹窗输入 场景名 / 场景信号 / 特征值；保存后画面标注保留
- 红框右键 → 保存为图标素材（识别区域 + 框内图标遮罩）/ 点击点
- 蓝框右键 → 保存为 OCR 识别素材（红框区域 + 蓝框遮罩 + 黄框相对文字位置）
- 🏁 结束示教：手动示教返回流程编排；阻断示教停止任务
- 任务运行遇未知画面：显示截图 + 标注保存后恢复执行
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                             QInputDialog, QLabel, QLineEdit, QMenu, QPushButton,
                             QSpinBox, QVBoxLayout, QWidget)

from core.event_bus import get_global_bus
from core.events import Events
from ui.visual_builder.screen_canvas import ScreenCanvas


class _SceneDialog(QDialog):
    """保存场景弹窗：场景名 / 场景信号 / 特征值"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("保存为场景")
        form = QFormLayout(self)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("如 主界面")
        self.signal_edit = QLineEdit()
        self.signal_edit.setPlaceholderText("判定成功输出的信号，默认=场景名")
        self.accuracy_spin = QSpinBox()
        self.accuracy_spin.setRange(0, 99)
        self.accuracy_spin.setValue(0)
        self.accuracy_spin.setToolTip(
            "N 个蓝框需命中 M 个(特征值)即判定识别到场景；0=全部命中")
        form.addRow("场景名", self.name_edit)
        form.addRow("场景信号", self.signal_edit)
        form.addRow("特征值", self.accuracy_spin)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)


class TeachConsole(QWidget):
    """示教控制台（截图 + 标注 + 保存为场景/标识）"""

    def __init__(self, event_bus=None, store=None, assets_dir="", ocr=None,
                 scene_commit_callback=None, element_commit_callback=None,
                 point_commit_callback=None, ocr_commit_callback=None,
                 capture_callback=None,
                 end_teach_callback=None, parent=None):
        super().__init__(parent)
        self._bus = event_bus or get_global_bus()
        self._store = store
        self._assets_dir = Path(assets_dir) if assets_dir else Path(".")
        self._ocr = ocr
        self._scene_commit_callback = scene_commit_callback  # (scene, node_id)
        self._element_commit_callback = element_commit_callback  # (template, region, node_id)
        self._point_commit_callback = point_commit_callback  # (point, node_id)
        self._ocr_commit_callback = ocr_commit_callback  # (rel, node_id)：OCR识别素材
        self._capture_callback = capture_callback  # () -> np.ndarray | None
        self._end_teach_callback = end_teach_callback  # () -> None（结束示教）
        self._task_name = ""
        self._unknown_count = 0
        self._teach_node = ""      # 目标节点 id（右键示教/未知画面触发）
        self._teach_type = ""      # 目标节点类型（提示文案用）
        self._manual_mode = False  # True=手动示教（走回调）；False=阻断示教（走事件）
        # 场景标注：红框(识别区域) + 蓝框(标识) + 遮罩
        self._regions: list[dict] = []
        self._current_region: dict | None = None
        self._pending_frame = None   # 待处理的框选类型 red/blue
        self._mask_seq = 0
        self._undo_stack: list[dict] = []   # 撤回快照（只进不退问题的解决）

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        self._status = QLabel("画面示教：点【📷 截图】从模拟器抓一帧")
        self._status.setStyleSheet("font-weight:bold;")
        lay.addWidget(self._status)

        # 工具栏
        btn_row = QHBoxLayout()
        self._capture_btn = QPushButton("📷 截图")
        self._capture_btn.clicked.connect(self._on_capture)
        self._red_btn = QPushButton("＋红框(识别)")
        self._red_btn.setCheckable(True)
        self._red_btn.toggled.connect(self._on_red_toggle)
        self._blue_btn = QPushButton("＋蓝框(标识)")
        self._blue_btn.setCheckable(True)
        self._blue_btn.toggled.connect(self._on_blue_toggle)
        self._yellow_btn = QPushButton("＋黄框(文字)")
        self._yellow_btn.setCheckable(True)
        self._yellow_btn.toggled.connect(self._on_yellow_toggle)
        self._brush_btn = QPushButton("🖌 画笔")
        self._brush_btn.setCheckable(True)
        self._brush_btn.toggled.connect(self._on_brush_toggle)
        self._erase_btn = QPushButton("🧹 橡皮")
        self._erase_btn.setCheckable(True)
        self._erase_btn.setToolTip("擦除画笔涂出的遮罩")
        self._erase_btn.toggled.connect(self._on_erase_toggle)
        self._pan_btn = QPushButton("✋ 拖动")
        self._pan_btn.setCheckable(True)
        self._pan_btn.setToolTip("按下后按住左键拖动平移画面")
        self._pan_btn.toggled.connect(self._on_pan_toggle)
        # 按下状态高亮（选中工具视觉反馈）
        _TOOL_CHECKED_QSS = (
            "QPushButton:checked {"
            " background-color:#1e6fd9; color:#ffffff;"
            " border:1px solid #0f5bb5; font-weight:bold; }")
        for _tb in (self._red_btn, self._blue_btn, self._yellow_btn,
                    self._brush_btn, self._erase_btn, self._pan_btn):
            _tb.setStyleSheet(_TOOL_CHECKED_QSS)
        self._brush_size_spin = QSpinBox()
        self._brush_size_spin.setRange(1, 60)
        self._brush_size_spin.setValue(10)
        self._brush_size_spin.setToolTip("画笔/橡皮大小（像素）")
        self._brush_size_spin.valueChanged.connect(
            lambda v: self._canvas.set_brush_size(v) if hasattr(self, "_canvas") else None)
        self._save_scene_btn = QPushButton("💾 保存为场景")
        self._save_scene_btn.clicked.connect(self._save_scene)
        self._undo_btn = QPushButton("↩ 撤回")
        self._undo_btn.setToolTip("撤销上一步操作（框选/涂色/删除/拖动）")
        self._undo_btn.clicked.connect(self._undo)
        self._end_btn = QPushButton("🏁 结束示教")
        self._end_btn.setToolTip("结束当前示教：手动示教返回流程编排；阻断示教停止任务")
        self._end_btn.clicked.connect(self._end_teach)
        for b in (self._capture_btn, self._red_btn, self._blue_btn,
                  self._yellow_btn, self._brush_btn, self._erase_btn,
                  self._pan_btn, self._brush_size_spin,
                  self._save_scene_btn,
                  self._undo_btn, self._end_btn):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self._hint = QLabel("红框=识别区域(搜索范围)；蓝框=标识(画笔涂遮罩)；"
                            "黄框=OCR文字位置(画在蓝框内)；红框右键存操作识别素材/点击点，"
                            "蓝框右键存OCR识别素材；↩ 可撤回上一步；"
                            "✋ 拖动或按住中键平移画面 · 滚轮缩放 · 双击画面复位")
        self._hint.setStyleSheet("color:#8a94a6;font-size:11px;")
        self._hint.setWordWrap(True)
        lay.addWidget(self._hint)

        self._canvas = ScreenCanvas()
        self._canvas.region_selected.connect(self._on_canvas_region)
        self._canvas.box_deleted.connect(self._on_box_deleted)
        self._canvas.box_rename_requested.connect(self._on_box_rename_requested)
        self._canvas.box_context_requested.connect(self._on_box_context)
        self._canvas.state_mutating.connect(self._snapshot)
        lay.addWidget(self._canvas, 1)

        self._bus.subscribe(Events.VISUAL_UNKNOWN, self._on_unknown)

    # ── 截图 ────────────────────────────────────────────
    def _on_capture(self) -> None:
        """📷 立即从模拟器截一张图"""
        if self._capture_callback is None:
            self._status.setText("⚠ 未配置截图接口")
            return
        try:
            img = self._capture_callback()
        except Exception as e:
            img = None
            self._status.setText(f"⚠ 截图失败: {e}")
        if img is None:
            self._status.setText("⚠ 截图失败：请检查模拟器连接")
            return
        # 手动示教模式：截图后保存场景/图标走回调（直接入库）
        self._manual_mode = True
        self._show_image(img)
        self._status.setText("✔ 已截图；红框圈识别区域 → 蓝框圈标识 → 画笔涂图标")

    def _show_image(self, img) -> None:
        self._last_image = img
        self._canvas.set_image(img)
        self._canvas.clear_overlays()
        self._canvas.clear_all_masks()
        self._regions = []
        self._current_region = None
        self._pending_frame = None
        self._mask_seq = 0
        self._reset_frame_buttons()

    # ── 外部入口（节点右键示教 / 未知画面）──────────────
    def set_task_name(self, name: str) -> None:
        """同步当前打开任务名（素材保存到 assets/visual/{task}/icons/）"""
        self._task_name = name or ""

    def begin_manual(self, img, node_id: str = "", node_type: str = "",
                     task_name: str = "") -> None:
        """手动示教：注入截图 → 标注 → 保存（走回调回填节点）"""
        self._manual_mode = True
        self._teach_node = node_id
        self._teach_type = node_type or ""
        self._task_name = task_name
        self._show_image(img)
        if img is None:
            self._status.setText("🎓 示教：截图失败，请检查设备连接后点【📷 截图】")
        elif node_type == "scene_probe":
            self._status.setText("🎓 场景判定示教：红框+蓝框+遮罩标注后点【💾 保存为场景】")
        elif node_type == "ocr_reader":
            self._status.setText("🎓 OCR读取示教：红框圈搜索区域 → 蓝框圈标识+涂遮罩 → "
                                 "黄框圈文字位置（画在蓝框内）→ 右键蓝框【保存为OCR识别素材】")
        else:
            self._status.setText("🎓 示教：标注画面后保存为场景/标识")

    # ── 未知画面接收（阻断示教流程）─────────────────────
    def _on_unknown(self, **kw) -> None:
        path = kw.get("screenshot_path", "")
        self._task_name = kw.get("task", "")
        self._unknown_count = kw.get("count", 0)
        info = kw.get("info") or {}
        self._teach_node = info.get("node", "")
        self._teach_type = info.get("type", "")
        self._manual_mode = False
        img = None
        if path and Path(path).exists():
            from core.cv_io import imread as _cv_imread
            img = _cv_imread(str(path))
        self._show_image(img)
        self._status.setText(f"⚠ 未知画面 #{self._unknown_count} — 标注后保存为场景继续")
        self._hint.setText(
            f"任务「{self._task_name}」遇到不认识画面：标注特征后【💾 保存为场景】"
            f"恢复执行；或点【🏁 结束示教】停止任务")

    # ── 撤回（解决只进不退）──────────────────────────────
    def _snapshot(self) -> None:
        """把当前标注状态推入撤回栈（框选/涂色/删除/拖动前调用）"""
        import copy
        self._undo_stack.append({
            "regions": copy.deepcopy(self._regions),
            "masks": {k: np.array(v, copy=True)
                      for k, v in self._canvas.get_all_masks().items()},
            "current_idx": (self._regions.index(self._current_region)
                            if self._current_region in self._regions else -1),
            "mask_seq": self._mask_seq,
        })
        if len(self._undo_stack) > 30:
            self._undo_stack.pop(0)

    def _undo(self) -> None:
        """撤回一步：恢复选框 + 遮罩 + 红蓝框数据"""
        if not self._undo_stack:
            self._hint.setText("没有可撤回的操作")
            return
        s = self._undo_stack.pop()
        self._canvas.clear_overlays()          # 清掉画布上的框
        self._canvas.set_all_masks(s["masks"])  # 恢复遮罩
        self._regions = s["regions"]
        self._mask_seq = s["mask_seq"]
        # 重建框（box_id 重新分配，ref 指向恢复的数据）
        for r in self._regions:
            r["box_id"] = self._canvas.add_region(*r["region"], r.get("name", ""), ref=r)
            for m in r.get("markers", []):
                m["box_id"] = self._canvas.add_marker(*m["region"], m.get("name", ""), ref=m)
                if m.get("ocr_box"):
                    m["ocr_box_id"] = self._canvas.add_yellow(
                        *m["ocr_box"], "文字", ref=m)
        self._current_region = (self._regions[s["current_idx"]]
                                if 0 <= s["current_idx"] < len(self._regions)
                                else None)
        self._status.setText("↩ 已撤回上一步")

    # ── 框选 / 画笔 ─────────────────────────────────────
    def _reset_frame_buttons(self) -> None:
        self._pending_frame = None
        for b in (self._red_btn, self._blue_btn, self._yellow_btn):
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        for b in (self._brush_btn, self._erase_btn, self._pan_btn):
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        self._canvas.set_region_mode(False)
        self._canvas.set_brush_mode(False)
        self._canvas.set_erase_mode(False)
        self._canvas.set_pan_mode(False)

    def _begin_frame(self, kind: str) -> None:
        self._pending_frame = kind
        self._canvas.set_region_mode(True)
        self._canvas.set_brush_mode(False)
        self._canvas.set_erase_mode(False)
        self._canvas.set_pan_mode(False)
        for b in (self._brush_btn, self._erase_btn, self._pan_btn):
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)

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

    def _on_yellow_toggle(self, checked: bool) -> None:
        if checked:
            if not self._current_region or not self._current_region.get("markers"):
                self._yellow_btn.setChecked(False)
                self._hint.setText("请先框蓝框（标识），再在蓝框内画黄框（文字位置）")
                return
            self._begin_frame("yellow")

    def _on_brush_toggle(self, checked: bool) -> None:
        self._canvas.set_brush_mode(checked)
        if checked:
            for b in (self._red_btn, self._blue_btn, self._yellow_btn):
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
            for b in (self._erase_btn, self._pan_btn):
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
            self._pending_frame = None

    def _on_erase_toggle(self, checked: bool) -> None:
        """🧹 橡皮：擦除当前蓝框/元素遮罩上已涂的像素"""
        self._canvas.set_erase_mode(checked)
        if checked:
            for b in (self._red_btn, self._blue_btn, self._yellow_btn):
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
            for b in (self._brush_btn, self._pan_btn):
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
            self._pending_frame = None

    def _on_pan_toggle(self, checked: bool) -> None:
        """✋ 拖动：按住左键拖动平移画面"""
        self._canvas.set_pan_mode(checked)
        if checked:
            for b in (self._red_btn, self._blue_btn, self._yellow_btn,
                      self._brush_btn, self._erase_btn):
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
            self._pending_frame = None

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
        elif kind == "yellow":
            self._add_yellow_box(x, y, w, h)

    def _ask_name(self, title: str, prompt: str, default: str) -> str:
        name, ok = QInputDialog.getText(self, title, prompt, text=default)
        if not ok or not name.strip():
            return default
        return name.strip()

    def _add_red_region(self, x: float, y: float, w: float, h: float) -> None:
        self._snapshot()
        default = f"红{len(self._regions) + 1}区"
        name = self._ask_name("识别区域名", "红色识别区域名（搜索范围）：", default)
        region = {"name": name, "region": [x, y, w, h], "markers": []}
        region["box_id"] = self._canvas.add_region(x, y, w, h, name, ref=region)
        self._regions.append(region)
        self._current_region = region
        self._status.setText(f"✔ 红框「{name}」已添加；可继续＋蓝框")

    def _add_blue_marker(self, x: float, y: float, w: float, h: float) -> None:
        region = self._current_region
        if region is None:
            self._hint.setText("请先点【＋红框】框一个识别区域，再框蓝框")
            return
        self._snapshot()
        default = f"蓝{len(region['markers']) + 1}区"
        name = self._ask_name("标识名", "蓝色标识名（框内遮罩为一个整体）：", default)
        self._mask_seq += 1
        key = f"m{self._mask_seq}"
        marker = {"name": name, "region": [x, y, w, h], "mask_key": key}
        marker["box_id"] = self._canvas.add_marker(x, y, w, h, name, ref=marker)
        region["markers"].append(marker)
        self._canvas.set_active_mask(key)
        self._status.setText(f"✔ 蓝框「{name}」已加入；开【🖌 画笔】涂图标")

    # ── 选框删除 / 改名 ──────────────────────────────────
    def _on_box_deleted(self, box_id: str) -> None:
        for region in self._regions:
            if region.get("box_id") == box_id:
                self._regions.remove(region)
                if self._current_region is region:
                    self._current_region = None
                self._status.setText("✔ 已删除识别区域")
                return
            for marker in region.get("markers", []):
                if marker.get("box_id") == box_id:
                    region["markers"].remove(marker)
                    self._status.setText("✔ 已删除标识")
                    return
                if marker.get("ocr_box_id") == box_id:
                    marker["ocr_box"] = None
                    marker["ocr_box_id"] = ""
                    self._status.setText("✔ 已删除黄框（文字位置）")
                    return

    def _on_box_rename_requested(self, box_id: str) -> None:
        for region in self._regions:
            if region.get("box_id") == box_id:
                name, ok = QInputDialog.getText(
                    self, "识别区域名", "区域名：", text=region.get("name", ""))
                if ok and name.strip():
                    self._snapshot()
                    region["name"] = name.strip()
                    self._canvas.rename_box(box_id, name.strip())
                return
            for marker in region.get("markers", []):
                if marker.get("box_id") == box_id:
                    name, ok = QInputDialog.getText(
                        self, "标识名", "标识名：", text=marker.get("name", ""))
                    if ok and name.strip():
                        self._snapshot()
                        marker["name"] = name.strip()
                        self._canvas.rename_box(box_id, name.strip())
                    return

    # ── 右键选框菜单 ─────────────────────────────────────
    def _find_marker_by_box(self, box_id: str) -> dict | None:
        for region in self._regions:
            for marker in region.get("markers", []):
                if marker.get("box_id") == box_id:
                    return marker
        return None

    def _on_box_context(self, box_id: str) -> None:
        marker = self._find_marker_by_box(box_id)
        menu = QMenu(self)
        if marker is None:
            # 红框右键：保存为操作识别素材 / 点击点 / OCR识别素材（需框内有蓝框+黄框）
            act = menu.addAction("💾 保存为操作识别素材（区域+图标）")
            act.triggered.connect(
                lambda: self._save_region_as_element(box_id))
            act_pt = menu.addAction("🎯 保存为点击点（区域中心）")
            act_pt.triggered.connect(lambda: self._save_box_as_point(box_id))
            # 红框内已有「蓝框+黄框」时可直接保存 OCR 识别素材
            ocr_marker = self._ocr_marker_in_region(box_id)
            if ocr_marker is not None:
                act_ocr = menu.addAction("🔤 保存为OCR识别素材（蓝框+黄框）")
                act_ocr.triggered.connect(
                    lambda: self._save_box_as_ocr(ocr_marker.get("box_id", "")))
        else:
            # 蓝框右键：保存为 OCR 识别素材（需框内黄框；未画时点击给提示）
            act = menu.addAction("🔤 保存为OCR识别素材（黄框=文字位置）")
            act.triggered.connect(lambda: self._save_box_as_ocr(box_id))
        act_del = menu.addAction("🗑 删除此框")
        act_del.triggered.connect(lambda: self._delete_box(box_id))
        menu.exec_(self._canvas.mapToGlobal(
            self._canvas.rect().center()))

    def _ocr_marker_in_region(self, box_id: str) -> dict | None:
        """红框内第一个「蓝框+黄框」标识（无则 None）"""
        for r in self._regions:
            if r.get("box_id") == box_id:
                for m in r.get("markers", []):
                    if m.get("ocr_box"):
                        return m
                return None
        return None

    def _delete_box(self, box_id: str) -> None:
        self._snapshot()
        self._canvas.delete_box(box_id)
        self._on_box_deleted(box_id)

    # ── 红框 → 保存为操作识别素材（识别区域 + 框内图标）──────
    def _save_region_as_element(self, box_id: str) -> None:
        """红框右键保存：操作识别素材 = 红框（搜索区域）+ 框内遮罩图标。

        - 红框内有蓝框：蓝框内必须有遮罩 → 合并遮罩为图标（正常操作识别素材）
        - 红框内没有蓝框：随机点击素材（mode=region_click，点击红框内随机点）
        - 红框内有蓝框但蓝框无遮罩：拒绝保存并提示
        """
        region = None
        for r in self._regions:
            if r.get("box_id") == box_id:
                region = r
                break
        if region is None:
            self._hint.setText("未找到该识别区域")
            return
        markers = region.get("markers", []) or []
        # 合并框内所有蓝框遮罩
        merged = None
        for marker in markers:
            m = self._canvas.get_mask(marker.get("mask_key", ""))
            if m is not None and m.any():
                merged = m.copy() if merged is None else np.maximum(merged, m)
        if markers and merged is None:
            # 有蓝框但蓝框内没有遮罩：不合法，拒绝保存
            self._hint.setText("红框内有蓝框但蓝框内没有遮罩：请先用【🖌 画笔】涂出图标，"
                               "或删除蓝框后保存为随机点击素材")
            return
        if not markers:
            # 只有红框 → 随机点击素材（点击区=整红框，无需识别）
            img = self._canvas_current_image()
            if img is None:
                self._hint.setText("请先【📷 截图】")
                return
            H, W = img.shape[:2]
            merged = np.zeros((H, W), dtype=np.uint8)
            x, y, w, h = region["region"]
            x0, y0 = max(0, int(x * W)), max(0, int(y * H))
            x1, y1 = min(W - 1, int((x + w) * W)), min(H - 1, int((y + h) * H))
            if x1 <= x0 or y1 <= y0:
                self._hint.setText("识别区域无效，请重新框选")
                return
            merged[y0:y1 + 1, x0:x1 + 1] = 255
            name = self._ask_name("保存为随机点击素材",
                                  "随机点击素材名（如 领取按钮区域）：",
                                  region.get("name", "rand"))
            rel = self._save_icon_entry(merged, name, region.get("region"),
                                        mode="region_click")
            if not rel:
                self._hint.setText("随机点击素材保存失败（图片写入错误）")
                return
            region_str = ",".join(f"{v:.4f}" for v in region.get("region", []))
            if self._element_commit_callback is not None:
                self._element_commit_callback(rel, region_str, self._teach_node)
                self._status.setText(f"✔ 随机点击素材「{name}」已保存"
                                     f"（红框内随机点击，区域：{region_str or '全图'}）")
            else:
                self._bus.publish(Events.VISUAL_ACTION_RECEIVED,
                                  action="add_element", template=rel, name=name,
                                  region=region_str, task=self._task_name,
                                  node=self._teach_node)
                self._status.setText(f"✔ 随机点击素材「{name}」已提交，继续…")
            return
        # 蓝框+遮罩齐备 → 正常操作识别素材
        name = self._ask_name("保存为操作识别素材",
                              "操作识别素材名（如 icon_attack）：",
                              region.get("name", "icon"))
        rel = self._save_icon_entry(merged, name, region.get("region"))
        if not rel:
            self._hint.setText("操作识别素材保存失败（遮罩裁剪/图片写入错误）")
            return
        region_str = ",".join(f"{v:.4f}" for v in region.get("region", []))
        if self._element_commit_callback is not None:
            self._element_commit_callback(rel, region_str, self._teach_node)
            self._status.setText(f"✔ 操作识别素材「{name}」已保存"
                                 f"（搜索区域：{region_str or '全图'}）")
        else:
            self._bus.publish(Events.VISUAL_ACTION_RECEIVED,
                              action="add_element", template=rel, name=name,
                              region=region_str, task=self._task_name,
                              node=self._teach_node)
            self._status.setText(f"✔ 操作识别素材「{name}」已提交，继续…")

    # ── 红框 → 点击点 / OCR 区域（轻量保底）──────────────
    def _save_box_as_point(self, box_id: str) -> None:
        box = self._canvas.box_of(box_id)
        if box is None:
            return
        x, y, w, h = box["region"]
        cx, cy = x + w / 2.0, y + h / 2.0
        label = self._ask_name("保存为点击点", "点击点名（如 btn.start）：",
                               box.get("name", "pt"))
        point = {"id": label, "label": label, "x": round(cx, 4),
                 "y": round(cy, 4), "mode": "relative"}
        if self._point_commit_callback is not None:
            self._point_commit_callback(point, self._teach_node)
            self._status.setText(f"✔ 点击点「{label}」已保存")
        else:
            self._bus.publish(Events.VISUAL_ACTION_RECEIVED,
                              action="add_point", point=point,
                              task=self._task_name)
            self._status.setText(f"✔ 点击点「{label}」已提交，继续…")

    def _save_box_as_ocr(self, box_id: str) -> None:
        """蓝框右键 → 保存为 OCR 识别素材（2026-08-15）。

        素材 = 红框（搜索区域）+ 蓝框遮罩（匹配标识）+ 黄框（文字位置，
        存相对遮罩裁剪的像素偏移）。蓝框遮罩匹配成功后，按偏移裁剪截图
        交给 OCR 提取文字。
        """
        marker = None
        region = None
        for r in self._regions:
            for m in r.get("markers", []):
                if m.get("box_id") == box_id:
                    marker, region = m, r
                    break
        if marker is None:
            self._hint.setText("请在蓝框上右键保存（OCR 识别素材 = 蓝框标识 + 黄框文字位置）")
            return
        ocr_box = marker.get("ocr_box")
        if not ocr_box:
            self._hint.setText("请先点【＋黄框(文字)】在该蓝框内画出要识别的文字位置")
            return
        mask = self._canvas.get_mask(marker.get("mask_key", ""))
        if mask is None or not mask.any():
            self._hint.setText("蓝框内没有遮罩：先用【🖌 画笔】涂出标识")
            return
        name = self._ask_name("保存为OCR识别素材",
                              "OCR识别素材名（如 体力数值）：",
                              marker.get("name", "ocr"))
        rel = self._save_icon_entry(mask, name, region.get("region") if region else None,
                                    ocr_box=ocr_box, sub="ocr")
        if not rel:
            self._hint.setText("OCR识别素材保存失败（遮罩裁剪/图片写入错误）")
            return
        if self._ocr_commit_callback is not None:
            self._ocr_commit_callback(rel, self._teach_node)
            self._status.setText(f"✔ OCR识别素材「{name}」已保存（蓝框标识 + 黄框文字位置）")
        else:
            self._bus.publish(Events.VISUAL_ACTION_RECEIVED,
                              action="add_ocr_element", template=rel, name=name,
                              task=self._task_name, node=self._teach_node)
            self._status.setText(f"✔ OCR识别素材「{name}」已提交，继续…")

    # ── 黄框（OCR 文字位置，需画在蓝框内）──────────────
    def _add_yellow_box(self, x: float, y: float, w: float, h: float) -> None:
        region = self._current_region
        if region is None:
            self._hint.setText("请先框蓝框（标识），再在蓝框内画黄框")
            return
        # 黄框中心必须落在某个蓝框内（取最后画的，即最上层）
        cx, cy = x + w / 2.0, y + h / 2.0
        marker = None
        for m in reversed(region.get("markers", [])):
            bx, by, bw, bh = m["region"]
            if bx <= cx <= bx + bw and by <= cy <= by + bh:
                marker = m
                break
        if marker is None:
            self._hint.setText("黄框需要画在蓝框内（先＋蓝框，再把黄框拖进蓝框范围）")
            return
        self._snapshot()
        # 旧黄框删除（一个标识只保留一个文字位置）
        if marker.get("ocr_box_id"):
            self._canvas.delete_box(marker["ocr_box_id"])
        marker["ocr_box"] = [round(v, 4) for v in (x, y, w, h)]
        marker["ocr_box_id"] = self._canvas.add_yellow(x, y, w, h, "文字", ref=marker)
        self._status.setText(f"✔ 黄框已加入蓝框「{marker.get('name', '')}」；"
                             f"右键该蓝框【保存为OCR识别素材】")

    # ── 保存为场景识别素材 ──────────────────────────────────
    def _save_scene(self) -> None:
        if not self._canvas.has_image():
            self._hint.setText("请先点【📷 截图】")
            return
        # 验证：至少一个红框；每个红框内有蓝框；每个蓝框内有遮罩
        if not self._regions:
            self._hint.setText("请先框红框（识别区域）")
            return
        bad = ""
        for region in self._regions:
            markers = region.get("markers", []) or []
            if not markers:
                bad = f"红框「{region.get('name') or '未命名'}」内没有蓝框"
                break
            for marker in markers:
                mask = self._canvas.get_mask(marker.get("mask_key", ""))
                if mask is None or not mask.any():
                    bad = (f"红框「{region.get('name') or '未命名'}」的蓝框"
                           f"「{marker.get('name') or '未命名'}」内没有遮罩")
                    break
            if bad:
                break
        if bad:
            self._hint.setText(f"{bad}：请先补齐标注，或用【🖌 画笔】涂出图标")
            return
        dlg = _SceneDialog(self)
        if dlg.exec_() != dlg.Accepted:
            return
        scene_name = dlg.name_edit.text().strip() or "未命名场景"
        signal = dlg.signal_edit.text().strip() or scene_name
        accuracy = int(dlg.accuracy_spin.value() or 0)

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
            self._hint.setText("蓝框内没有遮罩：先用【🖌 画笔】涂出图标")
            return
        scene = {"id": scene_name, "name": scene_name, "signal": signal,
                 "accuracy": accuracy, "regions": regions_out}
        if self._scene_commit_callback is not None:
            # 阻断流程已移除：只要界面回调存在就直接入库（防止事件无人处理静默丢失）；
            # 回调返回状态文本（含失败原因），不再无脑显示"已保存"
            msg = ""
            try:
                msg = self._scene_commit_callback(scene, self._teach_node) or ""
            except Exception as e:
                msg = f"⚠ 场景保存异常: {e}"
            if msg:
                self._status.setText(msg + "；画面标注已保留，可继续标注")
            else:
                self._status.setText(f"✔ 识别素材「{scene_name}」已保存并绑定节点"
                                     f"（信号: {signal}，特征值: {accuracy}）"
                                     f"；画面标注已保留，可继续保存图标素材/再保存场景")
        else:
            self._bus.publish(Events.VISUAL_ACTION_RECEIVED,
                              action="add_scene", scene=scene,
                              task=self._task_name, node=self._teach_node)
            self._status.setText(f"✔ 场景「{scene_name}」已提交，画面标注已保留，继续…")
        # 不清空画面：红框/蓝框/遮罩全部保留，便于继续标注或右键保存图标素材

    # ── 结束示教（跳过/停止合并，2026-08-15）───────────
    def _end_teach(self) -> None:
        """结束当前示教：手动示教返回流程编排页；阻断示教停止任务"""
        if not self._manual_mode:
            self._bus.publish(Events.VISUAL_ACTION_RECEIVED, action="stop",
                              task=self._task_name)
            self._status.setText("🏁 已结束示教（任务停止）")
        else:
            self._status.setText("🏁 示教已结束，返回流程编排继续编辑")
        self._manual_mode = False
        self._teach_node = ""
        if self._end_teach_callback is not None:
            try:
                self._end_teach_callback()
            except Exception:
                pass

    # ── 素材保存（复用旧实现核心）───────────────────────
    def _save_icon_entry(self, mask: np.ndarray, name: str,
                         search_region, ocr_box=None, sub: str = "icons",
                         mode: str | None = None) -> str:
        """操作识别/OCR素材条目化（2026-08-15）：与场景识别素材同规格的结构化条目。

        目录 assets/visual/{task}/{sub}/：
          {条目名}.json   主文件（name/image/region/threshold[/ocr_box][/mode]/created_at）
          {ascii}_{ts}.png 遮罩图片数据（文件名强制 ASCII：cv2.imwrite 中文路径会失败）
        ocr_box：黄框相对坐标 [x,y,w,h]（相对整图）；保存时换算成
                 相对遮罩裁剪左上角的像素偏移 [dx,dy,dw,dh]。
        mode="region_click"：随机点击素材（只有红框，点击区=整红框）。
        返回条目 json 的相对路径（加入任务素材库/节点下拉的就是它）。
        """
        import json
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
        out_dir = self._asset_out_dir(sub)
        rel_dir = (f"visual/{self._task_name}/{sub}" if self._task_name
                   else f"visual/{sub}")
        # PNG 文件名：ASCII 安全名 + 时间戳（中文会走条目 json 的 name 字段）
        ascii_id = "".join(
            c for c in str(name) if c.isascii() and (c.isalnum() or c == "_")
        ) or "icon"
        ts = int(time.time() * 1000)
        png_name = f"{ascii_id}_{ts}.png"
        from core.cv_io import imwrite as _cv_imwrite
        if not _cv_imwrite(str(out_dir / png_name), rgba):
            return ""
        # 条目 json 文件名 = 用户输入名（中文 OK；过滤路径非法字符）
        safe_json = "".join(c for c in str(name)
                            if c not in '<>:"/\\|?*').strip() or "icon"
        json_name = f"{safe_json}.json"
        entry = {
            "id": str(name).strip(),
            "name": str(name).strip(),
            "image": png_name,
            "region": [round(float(v), 4) for v in search_region]
            if search_region else None,
            "threshold": 0.85,
            "created_at": ts,
        }
        if mode:
            entry["mode"] = mode
        if ocr_box is not None and len(ocr_box) == 4:
            bx, by, bw, bh = (float(v) for v in ocr_box)
            px0 = max(0, int(bx * W))
            py0 = max(0, int(by * H))
            pw = max(1, int(bw * W))
            ph = max(1, int(bh * H))
            entry["ocr_box"] = [px0 - x0, py0 - y0, pw, ph]
        try:
            (out_dir / json_name).write_text(
                json.dumps(entry, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:
            return ""
        return f"{rel_dir}/{json_name}"

    def _canvas_current_image(self):
        return getattr(self, "_last_image", None)

    def _asset_out_dir(self, sub: str = "") -> Path:
        """示教产物目录：assets/visual/{task}/icons|scenes/"""
        rel_dir = f"visual/{self._task_name}".rstrip("/") or "visual"
        out_dir = self._assets_dir / rel_dir / sub if sub \
            else self._assets_dir / rel_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    def _save_marker_templates(self, mask: np.ndarray, prefix: str) -> list[dict]:
        """蓝框遮罩按连通域拆成多个独立图标块，每块裁剪独立 RGBA 模板。

        返回 [{template, dx, dy}]，dx/dy = 该块相对第一块左上角的像素偏移。
        """
        img = self._canvas_current_image()
        if img is None or mask is None or not mask.any():
            return []
        H, W = img.shape[:2]
        n, labels, stats, _ = cv2.connectedComponentsWithStats(
            mask.astype(np.uint8), 8)
        out_dir = self._asset_out_dir("scenes")
        rel_dir = f"visual/{self._task_name}/scenes".rstrip("/")
        safe = "".join(c for c in str(prefix) if c.isalnum() or c in "_-.") \
            or "block"
        out: list[dict] = []
        base: tuple[int, int] | None = None
        for i in range(1, n):  # 跳过背景(0)
            bx, by, bw, bh, area = stats[i]
            if area < 6:
                continue
            x0, y0 = int(bx), int(by)
            x1, y1 = int(bx + bw - 1), int(by + bh - 1)
            crop = img[y0:y1 + 1, x0:x1 + 1]
            cm = (labels[y0:y1 + 1, x0:x1 + 1] == i).astype(np.uint8) * 255
            rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
            rgba[:, :, 3] = cm
            fname = f"{safe}_{i}_{int(time.time() * 1000)}.png"
            from core.cv_io import imwrite as _cv_imwrite
            if not _cv_imwrite(str(out_dir / fname), rgba):
                continue
            if base is None:
                base = (x0, y0)
            out.append({"template": f"{rel_dir}/{fname}",
                        "dx": x0 - base[0], "dy": y0 - base[1]})
        return out

    def set_screenshot(self, img) -> None:
        """外部注入当前截图"""
        self._last_image = img
