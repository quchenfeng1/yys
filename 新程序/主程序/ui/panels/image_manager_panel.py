"""
UI 子面板：ImageManagerPanel 素材管理（11 说明书 §3.4 + core/asset_catalog.py 约定）。

按目录语义，素材分两类：
  - 🧭 识图素材 → assets/scene/（脚本可以识别的背景/场景模板）
  - 🎮 控制素材 → assets/tasks/_shared/（需要点击的按钮/控件模板）

每张图片带元数据（标签 / 描述 / 文件名），存储于 assets/manifest.json：
  - 添加图片时必须选择至少 1 个标签才能加入
  - 文件名可自定义（默认用原文件名）
  - 素材管理面板可统一管理标签（新增/删除）并按标签筛选查找

布局：左侧 Tab（识图素材/控制素材）+ 图片列表 + 标签筛选；右侧预览。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from core.asset_catalog import AssetCatalog
from core.asset_meta import AssetMetaStore

_ALL_TAG = "🏷 全部标签"


class AddAssetDialog(QDialog):
    """添加图片弹窗：文件名 / 描述 / 标签（至少 1 个）"""

    def __init__(self, parent=None, tags: list[str] | None = None,
                 default_name: str = "", is_scene: bool = False):
        super().__init__(parent)
        self.setWindowTitle("➕ 添加图片（设置标签）")
        self.setMinimumWidth(420)
        self._is_scene = is_scene

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # 源文件
        src_row = QHBoxLayout()
        self.ed_source = QLineEdit()
        self.ed_source.setReadOnly(True)
        self.ed_source.setPlaceholderText("选择源图片文件…")
        btn_src = QPushButton("选择文件")
        btn_src.clicked.connect(self._pick_source)
        src_row.addWidget(self.ed_source, 1)
        src_row.addWidget(btn_src)
        form.addRow("源文件 *:", src_row)

        # 文件名（默认原文件名）
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("保存文件名（留空用原文件名）")
        if default_name:
            self.ed_name.setText(default_name)
        form.addRow("文件名:", self.ed_name)

        # 描述
        self.ed_desc = QLineEdit()
        self.ed_desc.setPlaceholderText("如：主界面式神录按钮 / 悬赏弹窗…")
        form.addRow("描述:", self.ed_desc)

        # 识图信号（仅识图素材 scene/）
        if is_scene:
            self.ed_signal = QLineEdit()
            self.ed_signal.setPlaceholderText(
                "识别信号名，如：主界面（任务代码 if 识图 == '主界面'）")
            form.addRow("信号名:", self.ed_signal)

        # 标签（多选下拉，至少 1 个；新增标签请到「标签管理」）
        from ui.widgets.multi_select_combo import MultiSelectCombo
        self.tag_combo = MultiSelectCombo()
        self.tag_combo.set_items([(t, t) for t in (tags or [])])
        form.addRow("标签 *:", self.tag_combo)

        layout.addLayout(form)

        # 按钮
        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_ok = QPushButton("保存")
        btn_ok.clicked.connect(self._on_ok)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        layout.addLayout(btns)

    def _pick_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.tiff)")
        if path:
            self.ed_source.setText(path)
            if not self.ed_name.text().strip():
                self.ed_name.setText(Path(path).name)

    def _on_ok(self) -> None:
        if not self.ed_source.text().strip():
            QMessageBox.warning(self, "提示", "请先选择源图片文件。")
            return
        if not self.selected_tags():
            QMessageBox.warning(self, "提示", "请至少选择 1 个标签。")
            return
        self.accept()

    # ── 取值 ─────────────────────────────────────────────

    def source_path(self) -> str:
        return self.ed_source.text().strip()

    def file_name(self) -> str:
        name = self.ed_name.text().strip()
        return name if name else Path(self.source_path()).name

    def description(self) -> str:
        return self.ed_desc.text().strip()

    def selected_tags(self) -> list[str]:
        """多选下拉中选中的标签"""
        return list(self.tag_combo.selected_data())

    def signal_name(self) -> str:
        """识图素材的信号名（仅识图素材；控制素材返回空）"""
        if self._is_scene:
            return self.ed_signal.text().strip()
        return ""


class TagManagerDialog(QDialog):
    """标签管理：查看全部标签，可新增 / 删除"""

    def __init__(self, parent=None, meta: AssetMetaStore | None = None):
        super().__init__(parent)
        self.setWindowTitle("🏷 标签管理")
        self.setMinimumWidth(360)
        self._meta = meta

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("全部标签（点击选中可删除）:"))
        self.tag_list = QListWidget()
        self._reload_tags()
        layout.addWidget(self.tag_list, 1)

        new_row = QHBoxLayout()
        self.ed_new = QLineEdit()
        self.ed_new.setPlaceholderText("新增标签（如：挑战按钮）")
        btn_add = QPushButton("添加")
        btn_add.clicked.connect(self._add_tag)
        new_row.addWidget(self.ed_new, 1)
        new_row.addWidget(btn_add)
        layout.addLayout(new_row)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self._remove_tag)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        btns.addWidget(btn_del)
        btns.addWidget(btn_close)
        layout.addLayout(btns)

    def _reload_tags(self) -> None:
        self.tag_list.clear()
        for tag in (self._meta.get_all_tags() if self._meta else []):
            self.tag_list.addItem(tag)

    def _add_tag(self) -> None:
        tag = self.ed_new.text().strip()
        if not tag:
            return
        if self._meta:
            self._meta.add_tag(tag)
            self._reload_tags()
        self.ed_new.clear()

    def _remove_tag(self) -> None:
        item = self.tag_list.currentItem()
        if not item:
            return
        tag = item.text()
        if self._meta:
            self._meta.remove_tag(tag)
            self._reload_tags()


class ImageManagerPanel(QWidget):
    """素材管理面板（识图素材 scene/ + 控制素材 tasks/_shared/）"""

    def __init__(self, param_bridge=None, parent=None):
        super().__init__(parent)
        self._bridge = param_bridge
        from core.game_profile import current_game_assets
        self._assets_dir = current_game_assets()
        self._catalog = AssetCatalog(self._assets_dir)
        self._meta = AssetMetaStore(self._assets_dir)
        self._tag_filter: str = _ALL_TAG  # 当前标签筛选（全部/某标签）

        layout = QHBoxLayout(self)

        # ── 左：Tab（识图素材 / 控制素材）+ 图片列表 ──────
        left = QVBoxLayout()

        # 标签筛选 + 标签管理
        filter_row = QHBoxLayout()
        self.tag_combo = QComboBox()
        self.tag_combo.currentTextChanged.connect(self._on_tag_filter_changed)
        filter_row.addWidget(QLabel("按标签:"))
        filter_row.addWidget(self.tag_combo, 1)
        btn_tag_mgr = QPushButton("🏷 标签管理")
        btn_tag_mgr.clicked.connect(self._open_tag_manager)
        filter_row.addWidget(btn_tag_mgr)
        left.addLayout(filter_row)

        self.tabs = QTabWidget()
        self.scene_list = QListWidget()      # 🧭 识图素材（scene/）
        self.control_list = QListWidget()    # 🎮 控制素材（tasks/_shared/）
        self.scene_list.currentRowChanged.connect(
            lambda row: self._on_image_selected("scene", row))
        self.control_list.currentRowChanged.connect(
            lambda row: self._on_image_selected("shared", row))
        self.tabs.addTab(self.scene_list, "🧭 识图素材")
        self.tabs.addTab(self.control_list, "🎮 控制素材")
        self.tabs.currentChanged.connect(lambda _i: self._on_tab_changed())
        left.addWidget(self.tabs, 1)

        # 操作按钮
        btn_layout = QHBoxLayout()
        btn_add = QPushButton("➕ 添加图片")
        btn_add.clicked.connect(self._add_images)
        btn_del = QPushButton("🗑 删除")
        btn_del.clicked.connect(self._delete_image)
        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.clicked.connect(self._refresh)
        btn_open = QPushButton("📂 打开文件夹")
        btn_open.clicked.connect(self._open_folder)
        for b in (btn_add, btn_del, btn_refresh, btn_open):
            btn_layout.addWidget(b)
        left.addLayout(btn_layout)
        layout.addLayout(left, 2)

        # ── 右：预览 ──────────────────────────────────────
        right = QVBoxLayout()
        right.addWidget(QLabel("预览"))
        self.preview_label = QLabel("（选择图片预览）")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("border:1px solid #555; background:#222; color:#888;")
        self.preview_label.setMinimumSize(300, 400)
        right.addWidget(self.preview_label, 1)
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color:#aaa;")
        right.addWidget(self.info_label, 0)
        layout.addLayout(right, 2)

        self._refresh()

    # ── 当前 Tab 对应目录/列表 ───────────────────────────

    def _current_key(self) -> str:
        """当前 Tab 对应 key（scene=识图素材 / shared=控制素材）"""
        return "scene" if self.tabs.currentIndex() == 0 else "shared"

    def _current_list(self) -> QListWidget:
        """当前 Tab 的图片列表控件"""
        return self.scene_list if self._current_key() == "scene" else self.control_list

    def _current_dir(self) -> Path:
        """当前 Tab 对应目录"""
        if self._current_key() == "scene":
            return self._catalog.ensure_scene_dir()
        return self._catalog.ensure_shared_dir()

    def _on_tab_changed(self) -> None:
        """切换 Tab → 重置预览信息"""
        self.preview_label.setText("（选择图片预览）")
        self.info_label.setText(f"目录: {self._current_dir()}")

    # ── 标签筛选 ─────────────────────────────────────────

    def _reload_tag_combo(self) -> None:
        """重建标签筛选下拉（全部 + 各标签），以内部状态 _tag_filter 为准"""
        self.tag_combo.blockSignals(True)
        current = self._tag_filter
        self.tag_combo.clear()
        self.tag_combo.addItem(_ALL_TAG)
        for tag in self._meta.get_all_tags():
            self.tag_combo.addItem(tag)
        idx = self.tag_combo.findText(current)
        self.tag_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.tag_combo.blockSignals(False)
        # 当前标签已被删除 → 回退全部
        if current != _ALL_TAG and self.tag_combo.currentText() != current:
            self._tag_filter = _ALL_TAG
            self.tag_combo.setCurrentIndex(0)

    def _on_tag_filter_changed(self, text: str) -> None:
        self._tag_filter = text or _ALL_TAG
        self._refresh()

    def _open_tag_manager(self) -> None:
        dlg = TagManagerDialog(self, meta=self._meta)
        dlg.exec_()
        self._reload_tag_combo()
        self._refresh()

    # ── 列表刷新 ─────────────────────────────────────────

    def _list_display(self, img: dict) -> str:
        """构造列表项文本：文件名 + 描述 + 标签"""
        meta = self._meta.get_image_meta(img["rel"]) or {}
        tags = meta.get("tags") or []
        desc = meta.get("description") or ""
        tag_txt = ",".join(tags) if tags else "（无标签）"
        if desc:
            return f"{img['name']}  |  {desc}  |  🏷 {tag_txt}"
        return f"{img['name']}  |  🏷 {tag_txt}"

    def _refresh(self) -> None:
        """刷新两个 Tab 的图片列表（按标签筛选）+ 重置预览"""
        self._reload_tag_combo()
        filter_tag = None if self._tag_filter == _ALL_TAG else self._tag_filter

        def fill(lst: QListWidget, folder: Path, show_signal: bool = False) -> None:
            lst.blockSignals(True)
            lst.clear()
            for img in self._catalog._list_images(folder):
                if filter_tag is not None:
                    meta = self._meta.get_image_meta(img["rel"]) or {}
                    if filter_tag not in (meta.get("tags") or []):
                        continue
                text = self._list_display(img)
                if show_signal:
                    sig = self._meta.get_signal(img["rel"])
                    if sig:
                        text += f"  ⚡{sig}"
                lst.addItem(text)
            lst.blockSignals(False)

        fill(self.scene_list, self._catalog.ensure_scene_dir(), show_signal=True)
        fill(self.control_list, self._catalog.ensure_shared_dir())
        self.preview_label.setText("（选择图片预览）")
        self.info_label.setText(f"目录: {self._current_dir()}")

    # 兼容旧接口（外部可能调用 _reload_locations）
    def _reload_locations(self) -> None:
        self._refresh()

    # ── 图片操作 ──────────────────────────────────────────

    def _on_image_selected(self, key: str, row: int) -> None:
        """选中图片 → 预览 + 显示元数据"""
        if row < 0:
            return
        folder = (self._catalog.ensure_scene_dir() if key == "scene"
                  else self._catalog.ensure_shared_dir())
        images = self._catalog._list_images(folder)
        if row >= len(images):
            return
        img = images[row]
        pix = QPixmap(img["abs"])
        if not pix.isNull():
            self.preview_label.setPixmap(pix.scaled(
                self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.preview_label.setText("（无法预览）")
        meta = self._meta.get_image_meta(img["rel"]) or {}
        tags = ",".join(meta.get("tags") or []) or "（无标签）"
        desc = meta.get("description") or "（无描述）"
        fname = meta.get("file_name") or img["name"]
        self.info_label.setText(
            f"文件: {img['abs']}\n引用路径: {img['rel']}\n"
            f"文件名: {fname}\n描述: {desc}\n标签: {tags}")

    def _add_images(self) -> None:
        """添加图片：直接弹窗（选文件 + 文件名/描述/标签/信号名，至少 1 个标签）→ 保存到当前目录"""
        is_scene = self._current_key() == "scene"
        dlg = AddAssetDialog(self, tags=self._meta.get_all_tags(), is_scene=is_scene)
        if dlg.exec_() != QDialog.Accepted:
            return
        src = Path(dlg.source_path())
        file_name = dlg.file_name()
        dst = self._current_dir() / file_name
        try:
            shutil.copy(src, dst)
        except Exception as e:
            QMessageBox.warning(self, "复制失败", f"{src.name}: {e}")
            return
        # 写入元数据（相对 assets/ 路径；识图素材带信号名）
        rel = str(dst.relative_to(self._assets_dir)).replace("\\", "/")
        self._meta.set_image_meta(rel, dlg.selected_tags(),
                                  dlg.description(), file_name,
                                  signal=dlg.signal_name())
        self._reload_tag_combo()
        self._refresh()

    def _delete_image(self) -> None:
        """删除当前 Tab 中选中的图片（同步删除元数据）"""
        row = self._current_list().currentRow()
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
        self._meta.remove_image_meta(img["rel"])
        self._reload_tag_combo()
        self._refresh()

    def _open_folder(self) -> None:
        """用系统文件管理器打开当前 Tab 对应文件夹（不存在则自动创建）"""
        import os
        from core.asset_catalog import open_in_file_manager
        folder = self._current_dir()
        ok = open_in_file_manager(folder, create=True)
        if not ok:
            QMessageBox.warning(
                self, "打开失败",
                f"无法打开目录：{os.path.relpath(folder)}\n（目录不存在或系统无文件管理器）")
