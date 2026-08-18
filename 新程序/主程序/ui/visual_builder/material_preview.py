"""17-可视化构建模块：素材管理页（2026-08-15，替换失效老素材管理）。

左侧三分之一 = 三种素材选择区（场景识别素材 / 操作识别素材 / OCR识别素材），
右侧 = 展示区：
  - 顶部：素材参数（名称/类型/阈值/红框位置/信号/黄框/mode/排除数）
  - 上方：特征 tabs——有几个蓝框就显示几个 tab
    · 场景识别素材：每个蓝框（marker）一个 tab
    · 操作识别素材：单个「整体特征」tab
    · OCR识别素材：单个「OCR特征」tab
  - 左侧：排除素材 tab——图标条目级 exclusions；场景素材跟随特征 tab
    切换显示对应蓝框（marker）的 exclusions

顶部按钮：📂 打开素材（资源管理器）· 🔄 刷新 · 🗑 删除（场景走删除回调；
图标/OCR 删除条目 json + 特征图 + 排除素材图）。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (QCheckBox, QFormLayout, QGroupBox, QHBoxLayout,
                             QLabel, QLineEdit, QListWidget, QMessageBox,
                             QPushButton, QScrollArea, QStackedWidget,
                             QTabWidget, QVBoxLayout, QWidget)

from core.cv_io import imread as _cv_imread

# 遮罩外像素的合成底色（BGR）：与预览页深色背景一致的灰蓝
_ALPHA_BG = (46, 50, 58)

_KIND_NAMES = {"scene": "场景识别素材", "element": "操作识别素材",
               "ocr": "OCR识别素材"}


def _fmt_region(reg) -> str:
    """红框位置四元组 → 可读文本（相对坐标，保留 3 位小数）"""
    try:
        vals = [float(v) for v in reg]
    except Exception:
        return str(reg)
    if len(vals) == 4:
        x, y, w, h = vals
        return f"x={x:.3f}  y={y:.3f}  宽={w:.3f}  高={h:.3f}"
    return ", ".join(f"{v:.3f}" for v in vals)


def _ndarray_to_pixmap(img) -> QPixmap:
    """BGR ndarray → 原尺寸 QPixmap（不缩放）"""
    if img is None or not getattr(img, "size", 0):
        return QPixmap()
    rgb = img[:, :, ::-1].copy() if img.ndim == 3 else img
    h, w = rgb.shape[:2]
    qimg = QImage(rgb.data, w, h, rgb.strides[0],
                  QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


class ZoomImageView(QScrollArea):
    """可滚轮缩放、拖拽平移的图片查看器（2026-08-15）。

    - 滚轮：以鼠标位置为锚点缩放（0.05×~8× 原图）
    - 按住左键拖动：平移查看
    - 双击：复位到适配尺寸
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("QScrollArea{background:#222;border:1px solid #555;}")
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("background:#222;")
        self.setWidget(self._label)
        self._orig = QPixmap()
        self._fit_scale = 1.0
        self._scale = 1.0
        self._max_w = 360
        self._max_h = 260
        self._drag_pos = None

    # ── 图片 ──
    def set_image(self, img=None, max_w: int = 360, max_h: int = 260) -> None:
        self._max_w, self._max_h = max_w, max_h
        if img is None:
            self._orig = QPixmap()
            self._label.clear()
            return
        self._orig = (_ndarray_to_pixmap(img) if isinstance(img, np.ndarray)
                      else QPixmap(img))
        self._fit_scale = max(0.05, min(8.0, self._calc_fit()))
        self._scale = self._fit_scale
        self._apply()

    def _calc_fit(self) -> float:
        if self._orig.isNull():
            return 1.0
        w, h = self._orig.width(), self._orig.height()
        if w <= 0 or h <= 0:
            return 1.0
        return min(self._max_w / w, self._max_h / h)

    def _apply(self) -> None:
        if self._orig.isNull():
            self._label.clear()
            return
        w = max(1, int(self._orig.width() * self._scale))
        h = max(1, int(self._orig.height() * self._scale))
        self._label.setPixmap(
            self._orig.scaled(w, h, Qt.KeepAspectRatio,
                              Qt.SmoothTransformation))
        self._label.resize(self._label.pixmap().size())

    # ── 缩放/平移 ──
    def wheelEvent(self, e) -> None:
        factor = 1.15 if e.angleDelta().y() > 0 else 1.0 / 1.15
        self.zoom_at(e.pos(), factor)
        e.accept()

    def zoom_at(self, pos, factor: float) -> None:
        """以 pos（视口内坐标）为锚点缩放 factor 倍"""
        if self._orig.isNull():
            return
        new = max(0.05, min(8.0, self._scale * factor))
        if abs(new - self._scale) < 1e-9:
            return
        hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
        lw, lh = self._label.width() or 1, self._label.height() or 1
        xr = (hb.value() + pos.x()) / lw
        yr = (vb.value() + pos.y()) / lh
        self._scale = new
        self._apply()
        hb.setValue(int(xr * self._label.width() - pos.x()))
        vb.setValue(int(yr * self._label.height() - pos.y()))

    def reset_zoom(self) -> None:
        self._scale = self._fit_scale
        self._apply()

    def scale(self) -> float:
        return self._scale

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.pos()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        if self._drag_pos is not None and e.buttons() & Qt.LeftButton:
            d = e.pos() - self._drag_pos
            hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
            hb.setValue(hb.value() - d.x())
            vb.setValue(vb.value() - d.y())
            self._drag_pos = e.pos()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        self._drag_pos = None
        self.unsetCursor()
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e) -> None:
        self.reset_zoom()
        super().mouseDoubleClickEvent(e)


class MaterialPreviewWidget(QWidget):
    """素材预览：左三分之一三种素材选择区 + 右侧属性/特征/排除素材展示区"""

    def __init__(self, assets_dir: str = "", scenes_provider=None,
                 elements_provider=None, ocr_provider=None,
                 scene_loader=None, open_callback=None,
                 delete_callback=None, scene_save_callback=None,
                 parent=None):
        super().__init__(parent)
        self._assets_dir = Path(assets_dir) if assets_dir else Path(".")
        self._scenes_provider = scenes_provider
        self._elements_provider = elements_provider
        self._ocr_provider = ocr_provider
        self._scene_loader = scene_loader
        self._open_callback = open_callback
        self._delete_callback = delete_callback
        self._scene_save_callback = scene_save_callback  # 保存场景修改（触发素材开关/信号）
        # 删除结果通知（可被测试替换，避免模态弹窗阻塞）
        self._notify = lambda title, text: QMessageBox.information(
            self, title, text)

        # 当前选中素材
        self._cur_kind: str = ""
        self._cur_key: str = ""
        self._cur_data: dict | None = None
        # 场景特征 tab → marker 索引映射（排除素材联动）
        self._feature_markers: list[tuple[dict, Path]] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # ── 左三分之一：三种素材选择区 ──────────────────
        left = QVBoxLayout()
        top_bar = QHBoxLayout()
        self._open_btn = QPushButton("📂 打开素材")
        self._open_btn.setToolTip("在资源管理器中打开素材库目录")
        self._open_btn.clicked.connect(self._open_folder)
        self._refresh_btn = QPushButton("🔄 刷新")
        self._refresh_btn.setToolTip("重新扫描素材列表")
        self._refresh_btn.clicked.connect(self.refresh)
        self._del_btn = QPushButton("🗑 删除")
        self._del_btn.setToolTip("删除当前选中的素材（需确认）")
        self._del_btn.clicked.connect(self._on_delete)
        top_bar.addWidget(self._open_btn)
        top_bar.addWidget(self._refresh_btn)
        top_bar.addWidget(self._del_btn)
        top_bar.addStretch(1)
        left.addLayout(top_bar)

        self._left_tabs = QTabWidget()
        self._lists: dict[str, QListWidget] = {}
        for kind, title in (("scene", "🧭 场景识别素材"),
                            ("element", "🎯 操作识别素材"),
                            ("ocr", "🔤 OCR识别素材")):
            lst = QListWidget()
            lst.currentItemChanged.connect(
                lambda cur, _prev, k=kind: self._on_list_changed(k, cur))
            self._lists[kind] = lst
            self._left_tabs.addTab(lst, title)
        left.addWidget(self._left_tabs, 1)
        root.addLayout(left, 1)

        # ── 右三分之二：展示区 ──────────────────────────
        right = QVBoxLayout()
        self._stack = QStackedWidget()
        # 页0：空提示
        self._empty_label = QLabel("👈 在左侧选择素材查看详情")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet("color:#8a94a6;font-size:14px;")
        self._stack.addWidget(self._empty_label)
        # 页1：展示区
        viewer = QWidget()
        v_lay = QVBoxLayout(viewer)
        v_lay.setContentsMargins(0, 0, 0, 0)
        v_lay.setSpacing(4)

        # 顶部：素材参数 + 整体预览图
        props_box = QGroupBox("📋 素材参数")
        props_lay = QHBoxLayout(props_box)
        self._props_form = QFormLayout()
        self._props_form.setLabelAlignment(Qt.AlignRight)
        props_lay.addLayout(self._props_form, 1)
        self._overview_view = ZoomImageView()
        self._overview_view.setMinimumSize(140, 120)
        self._overview_view.setMaximumSize(220, 160)
        self._overview_view.setToolTip("滚轮缩放 · 拖动平移 · 双击复位")
        props_lay.addWidget(self._overview_view, 0)
        v_lay.addWidget(props_box)

        # 中部：左=排除素材 tab；右上方=特征 tabs
        mid = QHBoxLayout()
        # 左侧：排除素材 tab
        self._excl_tabs = QTabWidget()
        self._excl_page = QWidget()
        excl_lay = QVBoxLayout(self._excl_page)
        excl_lay.setContentsMargins(4, 4, 4, 4)
        self._excl_scroll = QScrollArea()
        self._excl_scroll.setWidgetResizable(True)
        self._excl_container = QWidget()
        self._excl_form = QVBoxLayout(self._excl_container)
        self._excl_form.setSpacing(6)
        self._excl_form.addStretch(1)
        self._excl_scroll.setWidget(self._excl_container)
        excl_lay.addWidget(self._excl_scroll)
        self._excl_tabs.addTab(self._excl_page, "🚫 排除素材")
        self._excl_tabs.setMinimumWidth(200)
        mid.addWidget(self._excl_tabs, 1)
        # 上方：特征 tabs（每蓝框一个 tab）
        self._feature_tabs = QTabWidget()
        self._feature_tabs.currentChanged.connect(self._on_feature_changed)
        mid.addWidget(self._feature_tabs, 2)
        v_lay.addLayout(mid, 1)

        self._stack.addWidget(viewer)
        right.addWidget(self._stack, 1)
        root.addLayout(right, 2)

        self.refresh()

    # ── 素材列表 ─────────────────────────────────────────
    def refresh(self) -> None:
        """重新扫描三种素材并刷新列表（保持当前选择）"""
        sel: dict[str, str] = {}
        for kind, lst in self._lists.items():
            it = lst.currentItem()
            if it is not None:
                sel[kind] = it.data(Qt.UserRole) or ""
        self._rebuild_list("scene")
        self._rebuild_list("element")
        self._rebuild_list("ocr")
        # 恢复选择
        for kind, lst in self._lists.items():
            key = sel.get(kind, "")
            if key and lst.count():
                for i in range(lst.count()):
                    if lst.item(i).data(Qt.UserRole) == key:
                        lst.setCurrentRow(i)
                        break
        # 无选择时自动选第一个（三 tab 里第一个非空）
        if self._cur_kind not in self._lists or not self._lists[self._cur_kind].currentItem():
            for kind in ("scene", "element", "ocr"):
                if self._lists[kind].count():
                    self._lists[kind].setCurrentRow(0)
                    break

    def _rebuild_list(self, kind: str) -> None:
        lst = self._lists[kind]
        lst.blockSignals(True)
        lst.clear()
        if kind == "scene":
            items = []
            if self._scenes_provider is not None:
                try:
                    items = list(self._scenes_provider() or [])
                except Exception:
                    items = []
            for it in items:
                if isinstance(it, dict):
                    sid, name = it.get("id", ""), it.get("name", "")
                else:
                    sid, name = str(it), str(it)
                if not sid:
                    continue
                lst.addItem(name or sid)
                lst.item(lst.count() - 1).setData(Qt.UserRole, sid)
        else:
            items = []
            prov = (self._elements_provider if kind == "element"
                    else self._ocr_provider)
            if prov is not None:
                try:
                    items = list(prov() or [])
                except Exception:
                    items = []
            for rel in items:
                if not rel:
                    continue
                lst.addItem(Path(str(rel)).stem)
                lst.item(lst.count() - 1).setData(Qt.UserRole, str(rel))
        lst.blockSignals(False)

    def _on_list_changed(self, kind: str, cur) -> None:
        if cur is None:
            return
        self._show_material(kind, cur.data(Qt.UserRole) or "")

    # ── 删除素材 ─────────────────────────────────────────
    def _confirm_delete(self, kind: str, key: str, name: str) -> bool:
        """删除确认弹窗（测试可替换）"""
        kind_name = _KIND_NAMES.get(kind, kind)
        extra = ("（删除后各任务中引用该场景的节点将无法识别）"
                 if kind == "scene"
                 else "（将同时删除该条目的特征图与排除素材图）")
        ret = QMessageBox.question(
            self, "删除素材",
            f"确定删除{kind_name}「{name}」吗？\n{extra}")
        return ret == QMessageBox.Yes

    def _delete_entry_files(self, key: str, data: dict) -> str:
        """删除图标/OCR 条目文件：json + 特征图 + 排除素材图。返回错误文本（空=成功）"""
        json_path = self._assets_dir / key
        try:
            if json_path.exists():
                json_path.unlink()
        except Exception as e:
            return f"条目文件删除失败: {e}"
        pngs = [data.get("image") or ""]
        pngs += [ex.get("image", "") for ex in data.get("exclusions", []) or []
                 if isinstance(ex, dict)]
        for png in pngs:
            if not png:
                continue
            p = self._png_of(json_path, png)
            if p is None:
                continue
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        return ""

    def _on_delete(self) -> None:
        """🗑 删除当前选中的素材（确认后执行）"""
        kind, key = self._cur_kind, self._cur_key
        data = self._cur_data
        if not key or data is None:
            self._notify("删除素材", "请先在左侧选择要删除的素材")
            return
        name = data.get("name") or Path(str(key)).stem
        if not self._confirm_delete(kind, key, name):
            return
        errors: list[str] = []
        # 外部库级删除（场景必须；图标/OCR 可选清理任务引用）
        if self._delete_callback is not None:
            try:
                ok, msg = self._delete_callback(kind, key, data)
            except Exception as e:
                ok, msg = False, str(e)
            if kind == "scene":
                if not ok:
                    self._notify("删除失败", f"场景「{name}」删除失败：{msg or '未知错误'}")
                    self.refresh()
                    return
            elif not ok and msg:
                errors.append(msg)
        # 图标/OCR：删除条目文件
        if kind in ("element", "ocr"):
            err = self._delete_entry_files(key, data)
            if err:
                errors.append(err)
        self.refresh()
        if errors:
            self._notify("删除完成", f"素材「{name}」已删除，但：{'；'.join(errors)}")
        else:
            self._notify("删除完成", f"素材「{name}」已删除")

    # ── 打开素材库 ───────────────────────────────────────
    def _open_folder(self) -> None:
        if self._open_callback is not None:
            try:
                self._open_callback(str(self._assets_dir))
                return
            except Exception as e:
                QMessageBox.warning(self, "打开失败", str(e))
                return
        d = self._assets_dir
        if not d.exists():
            QMessageBox.information(self, "素材库", f"素材库目录不存在：\n{d}")
            return
        try:
            os.startfile(str(d))
        except Exception as e:
            QMessageBox.warning(self, "打开失败", str(e))

    # ── 素材数据加载 ─────────────────────────────────────
    def _load_material(self, kind: str, key: str) -> dict | None:
        if kind == "scene":
            return self._load_scene(key)
        p = self._assets_dir / key
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception:
            return None

    def _load_scene(self, sid: str) -> dict | None:
        if self._scene_loader is not None:
            try:
                d = self._scene_loader(sid)
                if d:
                    return d
            except Exception:
                pass
        p = self._assets_dir / "scenes" / f"{sid}.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8")) or {}
            except Exception:
                return None
        return None

    def _png_of(self, json_path: Path, image: str) -> Path | None:
        """按 image 文件名定位 PNG：条目同目录 → 各素材子目录 → 全局搜索"""
        if not image:
            return None
        if Path(image).is_absolute():
            p = Path(image)
            return p if p.exists() else None
        cands = [json_path.parent / image]
        for sub in ("scenes", "icons", "ocr"):
            cands.append(self._assets_dir / sub / image)
        cands.append(self._assets_dir / image)
        for c in cands:
            if c.exists():
                return c
        try:
            for p in self._assets_dir.rglob(image):
                if p.exists():
                    return p
        except Exception:
            pass
        return None

    def _read_rgb(self, path: Path | None):
        """读素材 PNG 并把 alpha 合成到暗底：只显示遮罩覆盖的区域。

        示教保存的素材 PNG 是 RGBA（alpha=蓝框内画笔涂出的遮罩，
        裁剪矩形=蓝框 bounding box）。若用普通彩色读图，alpha 被丢弃，
        看到的是整个蓝框矩形区域而不是遮罩形状——这里用 alpha 合成，
        遮罩外的像素显示为暗底，直观呈现真正参与匹配的遮罩。
        """
        if path is None:
            return None
        img = _cv_imread(str(path), cv2.IMREAD_UNCHANGED)
        if img is None:
            return None
        if img.ndim == 3 and img.shape[2] == 4:
            bgr = img[:, :, :3].astype(np.float32)
            a = img[:, :, 3:4].astype(np.float32) / 255.0
            bg = np.full((1, 1, 3), _ALPHA_BG, np.float32)
            return (bgr * a + bg * (1.0 - a)).astype(np.uint8)
        return img

    # ── 展示区刷新 ───────────────────────────────────────
    def _show_material(self, kind: str, key: str) -> None:
        data = self._load_material(kind, key)
        self._cur_kind = kind
        self._cur_key = key
        self._cur_data = data
        if data is None:
            self._stack.setCurrentIndex(0)
            self._empty_label.setText(
                f"⚠ 素材「{Path(str(key)).stem}」加载失败（文件缺失或格式错误）")
            return
        self._stack.setCurrentIndex(1)
        self._rebuild_props(kind, key, data)
        self._rebuild_features(kind, key, data)
        self._rebuild_exclusions()

    def _rebuild_props(self, kind: str, key: str, data: dict) -> None:
        form = self._props_form
        # 旧控件引用置空（deleteLater 后 getattr 会拿到已删对象）
        for _attr in ("_trigger_check", "_trigger_signal_edit",
                      "_trigger_save_btn"):
            setattr(self, _attr, None)
        while form.rowCount():
            form.removeRow(0)
        name = data.get("name") or Path(str(key)).stem

        def add(label: str, value: str) -> None:
            form.addRow(label, QLabel(value))

        add("名称:", name)
        add("类型:", _KIND_NAMES.get(kind, kind))
        if kind == "scene":
            signal = data.get("signal") or ""
            # 🔔 触发素材开关 + 信号名编辑（2026-08-16：可更改是否为触发素材）
            trigger_row = QWidget()
            trl = QHBoxLayout(trigger_row)
            trl.setContentsMargins(0, 0, 0, 0)
            trl.setSpacing(6)
            self._trigger_check = QCheckBox("🔔 触发素材")
            self._trigger_check.setChecked(bool(signal))
            self._trigger_check.setToolTip(
                "勾选 = 该场景作为触发素材，场景出现时激活所有绑定其信号的任务")
            self._trigger_check.toggled.connect(self._on_trigger_toggled)
            trl.addWidget(self._trigger_check)
            self._trigger_signal_edit = QLineEdit(signal)
            self._trigger_signal_edit.setPlaceholderText("信号名（留空=场景名）")
            self._trigger_signal_edit.setEnabled(bool(signal))
            self._trigger_signal_edit.setMaximumWidth(160)
            self._trigger_signal_edit.setToolTip(
                "信号名：图内任务信号触发器节点引用；见「信号管理」面板")
            trl.addWidget(self._trigger_signal_edit)
            self._trigger_save_btn = QPushButton("💾 保存修改")
            self._trigger_save_btn.setToolTip("保存触发素材开关与信号名到场景素材")
            self._trigger_save_btn.clicked.connect(self._on_save_trigger)
            trl.addWidget(self._trigger_save_btn)
            trl.addStretch(1)
            form.addRow("触发素材:", trigger_row)
            acc = data.get("accuracy")
            if acc is not None:
                add("特征值:", str(acc))
            n_regions = len(data.get("regions", []) or [])
            n_markers = sum(len(r.get("markers", []) or [])
                            for r in data.get("regions", []) or [])
            add("红框数:", str(n_regions))
            add("蓝框数:", str(n_markers))
            n_excl = sum(len(m.get("exclusions", []) or [])
                         for r in data.get("regions", []) or []
                         for m in r.get("markers", []) or [])
            add("排除素材数:", str(n_excl))
        else:
            region = data.get("region")
            if region:
                add("红框位置:", _fmt_region(region))
            thr = data.get("threshold")
            if thr is not None:
                add("匹配阈值:", f"{float(thr):.2f}")
            mode = data.get("mode")
            if mode:
                add("点击方式:", "随机点击素材" if mode == "region_click"
                    else str(mode))
            ocr_box = data.get("ocr_box")
            if ocr_box and len(ocr_box) == 4:
                dx, dy, w, h = (int(v) for v in ocr_box)
                add("文字框(黄框):", f"偏移({dx},{dy}) 尺寸 {w}×{h}px")
            n_excl = len(data.get("exclusions", []) or [])
            if kind == "element":
                add("排除素材数:", str(n_excl))
        created = data.get("created_at")
        if created:
            try:
                ts = time.strftime("%Y-%m-%d %H:%M:%S",
                                   time.localtime(int(created) / 1000))
                add("创建时间:", ts)
            except Exception:
                pass

        # 整体预览图
        img = None
        if kind == "scene":
            for r in data.get("regions", []) or []:
                for m in r.get("markers", []) or []:
                    for t in m.get("templates", []) or []:
                        p = self._png_of(self._assets_dir / "scenes",
                                         t.get("template", ""))
                        img = self._read_rgb(p)
                        if img is not None:
                            break
                    if img is not None:
                        break
                if img is not None:
                    break
        else:
            json_path = self._assets_dir / key
            p = self._png_of(json_path, data.get("image", ""))
            img = self._read_rgb(p)
        self._overview_view.set_image(img, 200, 150)

    # ── 触发素材编辑（2026-08-16）────────────────────────
    def _on_trigger_toggled(self, checked: bool) -> None:
        """触发素材开关：开 → 启用信号名输入框"""
        edit = getattr(self, "_trigger_signal_edit", None)
        if edit is not None:
            edit.setEnabled(checked)
            if checked and not edit.text().strip():
                edit.setPlaceholderText("信号名（留空=场景名）")

    def _on_save_trigger(self) -> None:
        """保存触发素材设置：开关/信号名 → 场景 json（走 scene_save_callback）"""
        check = getattr(self, "_trigger_check", None)
        edit = getattr(self, "_trigger_signal_edit", None)
        if check is None or self._cur_kind != "scene" or \
                self._cur_data is None:
            return
        name = self._cur_data.get("name") or self._cur_key
        new_signal = edit.text().strip() if check.isChecked() else ""
        if check.isChecked() and not new_signal:
            new_signal = self._cur_key  # 留空 = 场景名
        if self._scene_save_callback is None:
            self._notify("保存修改", "未配置场景保存接口，无法保存")
            return
        scene = dict(self._cur_data)
        scene["signal"] = new_signal
        try:
            ok = self._scene_save_callback(scene)
            if ok is False:
                self._notify("保存失败", f"场景「{name}」触发素材设置保存失败")
                return
        except Exception as e:
            self._notify("保存失败", f"场景「{name}」保存异常: {e}")
            return
        # 刷新数据与属性区
        self._cur_data = self._load_scene(self._cur_key) or scene
        self._rebuild_props("scene", self._cur_key, self._cur_data)
        self.refresh()
        state = ("已设为触发素材（信号: " + new_signal + "）"
                 if new_signal else "已取消触发素材")
        self._notify("保存修改", f"场景「{name}」{state}")

    def _rebuild_features(self, kind: str, key: str, data: dict) -> None:
        tabs = self._feature_tabs
        tabs.blockSignals(True)
        tabs.clear()
        self._feature_markers = []
        json_dir = self._assets_dir / key if kind != "scene" \
            else self._assets_dir / "scenes"
        if kind == "scene":
            mi = 0
            for r in data.get("regions", []) or []:
                for m in r.get("markers", []) or []:
                    mi += 1
                    title = m.get("name") or f"蓝框{mi}"
                    page, img = self._make_scene_marker_page(m, r)
                    tabs.addTab(page, title)
                    self._feature_markers.append((m, json_dir))
            if not self._feature_markers:
                lbl = QLabel("该场景没有蓝框（特征标识）")
                lbl.setAlignment(Qt.AlignCenter)
                tabs.addTab(lbl, "特征")
        else:
            json_path = self._assets_dir / key
            p = self._png_of(json_path, data.get("image", ""))
            img = self._read_rgb(p)
            lines = []
            region = data.get("region")
            if region:
                lines.append(f"红框位置（相对整屏）: {_fmt_region(region)}")
            thr = data.get("threshold")
            if thr is not None:
                lines.append(f"匹配阈值: {float(thr):.2f}")
            if kind == "ocr":
                ocr_box = data.get("ocr_box")
                if ocr_box and len(ocr_box) == 4:
                    dx, dy, w, h = (int(v) for v in ocr_box)
                    lines.append(f"文字框(黄框): 相对特征图偏移 "
                                 f"({dx},{dy}) 尺寸 {w}×{h}px")
                lines.append("（本素材无排除特征概念）")
                title = "OCR特征"
            else:
                mode = data.get("mode")
                if mode == "region_click":
                    lines.append("点击方式: 随机点击素材（红框内随机点）")
                elif mode:
                    lines.append(f"点击方式: {mode}")
                ocr_box = data.get("ocr_box")
                if ocr_box and len(ocr_box) == 4:
                    dx, dy, w, h = (int(v) for v in ocr_box)
                    lines.append(f"文字框(黄框): 相对特征图偏移 "
                                 f"({dx},{dy}) 尺寸 {w}×{h}px")
                n_excl = len(data.get("exclusions", []) or [])
                lines.append(f"排除素材: {n_excl} 个（见左侧「排除素材」tab）")
                title = "整体特征"
            tabs.addTab(self._make_feature_page(img, lines), title)
        tabs.blockSignals(False)
        if tabs.count():
            tabs.setCurrentIndex(0)

    def _make_scene_marker_page(self, marker: dict, region: dict):
        img = None
        for t in marker.get("templates", []) or []:
            p = self._png_of(self._assets_dir / "scenes",
                             t.get("template", ""))
            img = self._read_rgb(p)
            if img is not None:
                break
        lines = []
        lines.append(f"所属红框: {region.get('name') or '未命名'}")
        reg = marker.get("region")
        if reg:
            lines.append(f"蓝框位置（相对整屏）: {_fmt_region(reg)}")
        thr = marker.get("threshold")
        if thr is not None:
            lines.append(f"匹配阈值: {float(thr):.2f}")
        n_tpl = len(marker.get("templates", []) or [])
        lines.append(f"特征块: {n_tpl} 块（连通域拆分）")
        n_excl = len(marker.get("exclusions", []) or [])
        lines.append(f"排除素材: {n_excl} 个（见左侧「排除素材」tab）")
        return self._make_feature_page(img, lines), img

    def _make_feature_page(self, img, lines: list[str]) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 4, 4, 4)
        if img is not None:
            view = ZoomImageView()
            view.set_image(img, 460, 340)
            view.setToolTip("滚轮缩放 · 拖动平移 · 双击复位")
            lay.addWidget(view, 1)
        else:
            miss = QLabel("（特征图缺失）")
            miss.setAlignment(Qt.AlignCenter)
            miss.setStyleSheet("color:#8a94a6;")
            lay.addWidget(miss, 1)
        if lines:
            text = QLabel("\n".join(lines))
            text.setWordWrap(True)
            text.setStyleSheet("color:#c8d0dc;font-size:11px;")
            lay.addWidget(text, 0)
        return page

    # ── 排除素材（左列）──────────────────────────────────
    def _on_feature_changed(self, idx: int) -> None:
        if idx < 0:
            return
        self._rebuild_exclusions()

    def _rebuild_exclusions(self) -> None:
        while self._excl_form.count():
            item = self._excl_form.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        data = self._cur_data
        if data is None:
            self._excl_form.addWidget(QLabel("（未选择素材）"))
            self._excl_form.addStretch(1)
            return
        kind = self._cur_kind
        if kind == "ocr":
            lbl = QLabel("OCR识别素材暂无排除素材概念。")
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color:#8a94a6;")
            self._excl_form.addWidget(lbl)
            self._excl_form.addStretch(1)
            return
        if kind == "element":
            json_dir = (self._assets_dir / self._cur_key).parent
            excls = data.get("exclusions", []) or []
            self._fill_exclusions(excls, json_dir, f"「{data.get('name') or ''}」")
            return
        # 场景：跟随当前特征 tab（蓝框）
        idx = self._feature_tabs.currentIndex()
        if 0 <= idx < len(self._feature_markers):
            marker, json_dir = self._feature_markers[idx]
            excls = marker.get("exclusions", []) or []
            title = marker.get("name") or f"蓝框{idx + 1}"
            self._fill_exclusions(excls, json_dir, f"蓝框「{title}」")
        else:
            self._excl_form.addWidget(QLabel("（该场景没有蓝框）"))
            self._excl_form.addStretch(1)

    def _fill_exclusions(self, excls: list, json_dir: Path,
                         owner: str) -> None:
        if not excls:
            lbl = QLabel(f"{owner}暂无排除素材。\n\n"
                         f"可在「排除示教」Tab 中为图标素材标注排除特征；\n"
                         f"场景蓝框的排除素材同样在此展示。")
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color:#8a94a6;")
            self._excl_form.addWidget(lbl)
            self._excl_form.addStretch(1)
            return
        title = QLabel(f"{owner}的排除素材（{len(excls)} 个）:")
        title.setStyleSheet("font-weight:bold;")
        self._excl_form.addWidget(title)
        for ex in excls:
            if not isinstance(ex, dict):
                continue
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            p = self._png_of(json_dir, ex.get("image", ""))
            img = self._read_rgb(p)
            if img is not None:
                pic = ZoomImageView()
                pic.setMinimumSize(96, 96)
                pic.setMaximumSize(150, 150)
                pic.set_image(img, 96, 96)
                pic.setToolTip("滚轮缩放 · 拖动平移 · 双击复位")
                rl.addWidget(pic, 0)
            lines = [f"特征图: {ex.get('image', '')}"]
            reg = ex.get("region")
            if reg:
                lines.append(f"搜索区域(相对图标框): {_fmt_region(reg)}")
            else:
                lines.append("搜索区域: 整个图标框")
            thr = ex.get("threshold")
            lines.append(f"阈值: {float(thr) if thr is not None else 0.85:.2f}")
            text = QLabel("\n".join(lines))
            text.setWordWrap(True)
            text.setStyleSheet("color:#c8d0dc;font-size:11px;")
            rl.addWidget(text, 1)
            self._excl_form.addWidget(row)
        self._excl_form.addStretch(1)
