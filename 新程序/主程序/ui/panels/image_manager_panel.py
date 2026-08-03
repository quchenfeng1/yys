"""
UI 子面板：ImageManagerPanel 任务图片管理（11 说明书 §3.4 + core/asset_catalog.py 约定）。

左侧：图片位置（识图文件夹 / 通用共享 / 各游戏任务专属文件夹）
中间：该位置的图片列表（文件名 + 相对引用路径 + 大小）
右侧：图片预览
底部：添加图片 / 删除 / 刷新 / 打开文件夹
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QFileDialog, QGridLayout, QHBoxLayout, QLabel, QListWidget,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from core.asset_catalog import AssetCatalog


class ImageManagerPanel(QWidget):
    """素材管理面板（任务图片关联）"""

    def __init__(self, param_bridge=None, parent=None):
        super().__init__(parent)
        self._bridge = param_bridge
        self._assets_dir = Path(__file__).resolve().parents[2] / "assets"
        self._catalog = AssetCatalog(self._assets_dir)

        # 数据源：位置 key（scene/shared/任务名） → 显示 label
        self._task_items: dict[str, str] = {}

        layout = QHBoxLayout(self)

        # ── 左：位置列表 ──────────────────────────────────
        left = QVBoxLayout()
        left.addWidget(QLabel("图片位置"))
        self.location_list = QListWidget()
        self.location_list.currentTextChanged.connect(self._on_location_selected)
        left.addWidget(self.location_list)
        layout.addLayout(left, 1)

        # ── 中：图片列表 ──────────────────────────────────
        mid = QVBoxLayout()
        mid.addWidget(QLabel("图片（选择查看预览与引用路径）"))
        self.image_list = QListWidget()
        self.image_list.currentTextChanged.connect(self._on_image_selected)
        mid.addWidget(self.image_list)

        btn_layout = QGridLayout()
        btn_add = QPushButton("➕ 添加图片")
        btn_add.clicked.connect(self._add_images)
        btn_del = QPushButton("🗑 删除")
        btn_del.clicked.connect(self._delete_image)
        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.clicked.connect(self._refresh)
        btn_open = QPushButton("📂 打开文件夹")
        btn_open.clicked.connect(self._open_folder)
        btn_layout.addWidget(btn_add, 0, 0)
        btn_layout.addWidget(btn_del, 0, 1)
        btn_layout.addWidget(btn_refresh, 1, 0)
        btn_layout.addWidget(btn_open, 1, 1)
        mid.addLayout(btn_layout)
        layout.addLayout(mid, 2)

        # ── 右：预览 ──────────────────────────────────────
        right = QVBoxLayout()
        right.addWidget(QLabel("预览"))
        self.preview_label = QLabel("（选择图片预览）")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("border:1px solid #555; background:#222; color:#888;")
        self.preview_label.setMinimumSize(280, 360)
        right.addWidget(self.preview_label, 1)
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color:#aaa;")
        right.addWidget(self.info_label, 0)
        layout.addLayout(right, 2)

        self._reload_locations()

    # ── 位置加载 ──────────────────────────────────────────

    def _reload_locations(self) -> None:
        """重建左侧位置列表：识图 / 共享 / 各游戏任务"""
        self.location_list.blockSignals(True)
        self.location_list.clear()
        self._task_items.clear()

        self._task_items["scene"] = "🧭 识图文件夹（scene/）"
        self._task_items["shared"] = "🔗 通用共享（tasks/_shared/）"
        for _label in self._task_items.values():
            self.location_list.addItem(_label)

        # 游戏任务（从 TaskBridge 获取元数据）
        metas = []
        if self._bridge and hasattr(self._bridge, 'task'):
            try:
                metas = self._bridge.task.get_task_metas()
            except Exception:
                metas = []
        for m in metas:
            name = m.get("name", "")
            if not name:
                continue
            display = m.get("display_name", "") or name
            self._task_items[name] = f"📁 {display}（{name}）"
            self.location_list.addItem(self._task_items[name])

        self.location_list.blockSignals(False)
        if self.location_list.count():
            self.location_list.setCurrentRow(0)
        self._refresh()

    # ── 选中响应 ──────────────────────────────────────────

    def _current_key(self) -> str:
        """当前选中的位置 key（scene/shared/任务名）"""
        item = self.location_list.currentItem()
        text = item.text() if item else ""
        for key, label in self._task_items.items():
            if label == text:
                return key
        return ""

    def _current_dir(self) -> Path:
        key = self._current_key()
        if key == "scene":
            return self._catalog.ensure_scene_dir()
        if key == "shared":
            return self._catalog.ensure_shared_dir()
        if key:
            return self._catalog.ensure_task_dir(key)
        return self._assets_dir

    def _on_location_selected(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        """刷新当前位置的图片列表"""
        self.image_list.blockSignals(True)
        self.image_list.clear()
        folder = self._current_dir()
        for img in self._catalog._list_images(folder):
            self.image_list.addItem(f"{img['name']}  ({img['size'] // 1024}KB)")
        self.image_list.blockSignals(False)
        self.preview_label.setText("（选择图片预览）")
        self.info_label.setText(f"目录: {folder}")

    # ── 图片操作 ──────────────────────────────────────────

    def _on_image_selected(self) -> None:
        """选中图片 → 预览 + 显示引用路径"""
        row = self.image_list.currentRow()
        folder = self._current_dir()
        images = self._catalog._list_images(folder)
        if row < 0 or row >= len(images):
            return
        img = images[row]
        pix = QPixmap(img["abs"])
        if not pix.isNull():
            self.preview_label.setPixmap(pix.scaled(
                self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.preview_label.setText("（无法预览）")
        self.info_label.setText(
            f"文件: {img['abs']}\n引用路径: {img['rel']}")

    def _add_images(self) -> None:
        """添加图片：文件对话框多选 → 复制到当前任务图片文件夹"""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.tiff)")
        if not paths:
            return
        folder = self._current_dir()
        copied = 0
        for p in paths:
            src = Path(p)
            dst = folder / src.name
            try:
                shutil.copy(src, dst)
                copied += 1
            except Exception as e:
                QMessageBox.warning(self, "复制失败", f"{src.name}: {e}")
        if copied:
            self._refresh()

    def _delete_image(self) -> None:
        """删除当前选中的图片"""
        row = self.image_list.currentRow()
        folder = self._current_dir()
        images = self._catalog._list_images(folder)
        if row < 0 or row >= len(images):
            return
        img = images[row]
        reply = QMessageBox.question(
            self, "确认删除", f"删除图片「{img['rel']}」？")
        if reply != QMessageBox.Yes:
            return
        try:
            Path(img["abs"]).unlink()
        except Exception as e:
            QMessageBox.warning(self, "删除失败", str(e))
        self._refresh()

    def _open_folder(self) -> None:
        """用系统文件管理器打开当前图片文件夹（不存在则自动创建）"""
        import os
        from core.asset_catalog import open_in_file_manager
        folder = self._current_dir()
        ok = open_in_file_manager(folder, create=True)
        if not ok:
            QMessageBox.warning(
                self, "打开失败",
                f"无法打开目录：{os.path.relpath(folder)}\n（目录不存在或系统无文件管理器）")
