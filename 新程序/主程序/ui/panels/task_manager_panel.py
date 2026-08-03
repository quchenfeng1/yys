"""
UI 子面板：TaskManagerPanel 任务文件管理（13-任务文件管理）。

按《13-任务文件管理》说明书：
- 左侧：任务库列表（扫描 tasks/ 的元数据）
- 操作：新建任务 / 删除（重命名 .deleted）/ 打开编辑 / 导入导出配置备份
- 右侧：选中任务的详情（元数据 + uses_* 声明 + 文件路径）
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QListWidget, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

CATEGORIES = ["daily", "permanent", "event", "special"]

_TASK_TYPE_LABELS = {
    "event_task": "非战斗任务",
    "battle": "战斗任务",
    "generic": "通用任务（不单独执行）",
    "trigger": "触发任务（特殊条件触发）",
}


class TaskManagerPanel(QWidget):
    """任务文件管理面板（列表 + 详情 + 新建/删除/打开/导入导出）"""

    def __init__(self, param_bridge: Any = None, parent=None):
        super().__init__(parent)
        self._param_bridge = param_bridge
        self._current_name: str = ""
        self._current_is_generic: bool = False
        self._detail_labels: dict[str, QLabel] = {}
        self._detail_images: list[dict] = []

        layout = QHBoxLayout(self)

        # ── 左侧任务库 + 通用模块 ─────────────────────────
        left = QVBoxLayout()
        left.addWidget(QLabel("🎮 游戏任务"))
        self.task_list = QListWidget()
        self.task_list.currentItemChanged.connect(self._on_task_selected)
        left.addWidget(self.task_list)
        left.addWidget(QLabel("🧩 通用模块（不单独执行，被任务引用）"))
        self.generic_list = QListWidget()
        self.generic_list.currentItemChanged.connect(self._on_generic_selected)
        left.addWidget(self.generic_list)

        btn_layout = QHBoxLayout()
        btn_new = QPushButton("新建")
        btn_new.clicked.connect(self._new_task)
        btn_del = QPushButton("删除")
        btn_del.clicked.connect(self._delete_task)
        btn_open = QPushButton("打开编辑")
        btn_open.clicked.connect(self._open_file)
        btn_export = QPushButton("导出")
        btn_export.clicked.connect(self._export_config)
        btn_import = QPushButton("导入")
        btn_import.clicked.connect(self._import_config)
        for b in (btn_new, btn_del, btn_open, btn_export, btn_import):
            btn_layout.addWidget(b)
        left.addLayout(btn_layout)

        # ── 右侧详情 ──────────────────────────────────────
        right = QVBoxLayout()
        right.addWidget(QLabel("任务详情"))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        container = QWidget()
        self.detail_layout = QVBoxLayout(container)
        self.scroll.setWidget(container)
        right.addWidget(self.scroll, 1)

        layout.addLayout(left, 1)
        layout.addLayout(right, 2)

        # 初始提示
        self._placeholder = QLabel("（从左侧选择任务查看详情）")
        self._placeholder.setStyleSheet("color:#888;")
        self.detail_layout.addWidget(self._placeholder)

    # ── 数据加载 ─────────────────────────────────────────────

    def load_tasks(self, metas: list) -> None:
        """加载任务元数据列表（dict 或 str 兼容，由 MainWindow 调用）"""
        self.task_list.blockSignals(True)
        self.task_list.clear()
        for m in metas:
            if isinstance(m, dict):
                name = m.get("name", "")
                display = m.get("display_name", "") or name
                category = m.get("category", "")
                label = f"{display}  [{category}]"
            else:
                name = str(m)
                display = name
                label = name
            self.task_list.addItem(label)
            item = self.task_list.item(self.task_list.count() - 1)
            item.setData(Qt.UserRole, name)
        self.task_list.blockSignals(False)
        if self.task_list.count() > 0:
            self.task_list.setCurrentRow(0)

    def load_generic(self, metas: list) -> None:
        """加载通用模块元数据列表（common，供其他游戏任务引用）"""
        self.generic_list.blockSignals(True)
        self.generic_list.clear()
        for m in metas:
            if isinstance(m, dict):
                name = m.get("name", "")
                display = m.get("display_name", "") or name
                label = f"{display}  [common]"
            else:
                name = str(m)
                label = name
            self.generic_list.addItem(label)
            item = self.generic_list.item(self.generic_list.count() - 1)
            item.setData(Qt.UserRole, name)
        self.generic_list.blockSignals(False)

    def _on_generic_selected(self, current, previous) -> None:
        """选中通用模块 → 显示详情（标注通用·不单独执行）"""
        if current is None:
            return
        name = current.data(Qt.UserRole)
        if not name:
            return
        self._current_name = name
        self._current_is_generic = True
        detail = self._get_detail(name)
        detail.setdefault("is_generic", True)
        detail.setdefault("category", "common")
        self._render_detail(detail)

    def _refresh(self) -> None:
        """重新拉取任务库 + 通用模块元数据并刷新列表"""
        bridge = self._param_bridge
        if not bridge or not hasattr(bridge, 'task'):
            return
        try:
            metas = bridge.task.get_task_metas()
            self.load_tasks(metas)
        except Exception:
            pass
        try:
            gmetas = bridge.task.get_generic_modules()
            self.load_generic(gmetas)
        except Exception:
            pass

    # ── 详情渲染 ─────────────────────────────────────────────

    def _on_task_selected(self, current, previous) -> None:
        if current is None:
            return
        name = current.data(Qt.UserRole)
        if not name:
            return
        self._current_name = name
        self._current_is_generic = False
        detail = self._get_detail(name)
        self._render_detail(detail)

    def _get_detail(self, name: str) -> dict[str, Any]:
        bridge = self._param_bridge
        if bridge and hasattr(bridge, 'task') and hasattr(bridge.task, 'get_task_detail'):
            try:
                return bridge.task.get_task_detail(name)
            except Exception:
                pass
        return {"name": name, "display_name": name}

    def _render_detail(self, detail: dict[str, Any]) -> None:
        # 清空详情区
        while self.detail_layout.count():
            item = self.detail_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._detail_labels.clear()

        name = detail.get("name", "")
        display = detail.get("display_name", "") or name
        is_generic = self._current_is_generic or detail.get("is_generic")

        title = QLabel(f"📋 {display}")
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        self.detail_layout.addWidget(title)

        g = QGroupBox("元数据")
        form = QFormLayout(g)
        task_type = detail.get("task_type", "")
        type_label = _TASK_TYPE_LABELS.get(task_type, task_type)
        if is_generic:
            type_label = "通用模块（不单独执行，被任务引用）"
        rows = [
            ("文件名:", name),
            ("显示名:", display),
            ("分类:", "通用模块（common）" if is_generic else detail.get("category", "")),
            ("任务类型:", type_label),
            ("描述:", detail.get("description", "")),
            ("战斗任务:", "是" if detail.get("uses_battle") else "否"),
            ("阵容配置:", "是" if detail.get("uses_team") else "否"),
            ("御魂配置:", "是" if detail.get("uses_soul") else "否"),
            ("体力检查:", "是" if detail.get("uses_stamina") else "否"),
            ("每轮循环:", str(detail.get("loop_count", 1))),
            ("超时(秒):", str(detail.get("timeout", 300))),
        ]
        for label, value in rows:
            vl = QLabel(str(value))
            vl.setWordWrap(True)
            form.addRow(label, vl)
            self._detail_labels[label] = vl
        self.detail_layout.addWidget(g)

        # ── 任务图片区（core/asset_catalog.py 约定）──
        from core.asset_catalog import AssetCatalog
        catalog = AssetCatalog(Path(__file__).resolve().parents[2] / "assets")
        if is_generic:
            imgs = catalog.list_shared_images()
            folder = catalog.shared_dir()
            pic_title = "通用共享图片（tasks/_shared/）"
        else:
            imgs = catalog.list_task_images(name)
            folder = catalog.task_dir(name)
            pic_title = f"任务图片（tasks/{name}/）"
        self._detail_images = imgs

        g2 = QGroupBox(pic_title)
        gv = QVBoxLayout(g2)
        img_list = QListWidget()
        img_list.currentRowChanged.connect(self._on_detail_image_selected)
        # 固定高度：避免详情滚动区内再嵌套长列表滚动条
        img_list.setFixedHeight(110)
        for img in imgs:
            img_list.addItem(img["name"])
        gv.addWidget(img_list)
        self._detail_img_preview = QLabel("（选择图片预览）")
        self._detail_img_preview.setAlignment(Qt.AlignCenter)
        self._detail_img_preview.setStyleSheet(
            "border:1px solid #555; background:#222; color:#888;")
        self._detail_img_preview.setFixedHeight(120)
        gv.addWidget(self._detail_img_preview)
        self._detail_img_info = QLabel(f"共 {len(imgs)} 张 · 目录 {folder}")
        self._detail_img_info.setWordWrap(True)
        self._detail_img_info.setStyleSheet("color:#aaa;")
        gv.addWidget(self._detail_img_info)
        btn_open = QPushButton("📂 打开图片文件夹")
        btn_open.clicked.connect(lambda: self._open_detail_folder(folder))
        gv.addWidget(btn_open)
        self.detail_layout.addWidget(g2)

        self.detail_layout.addStretch()

    def _on_detail_image_selected(self, row: int) -> None:
        """详情图片区：选中 → 预览 + 引用路径"""
        if row < 0 or row >= len(self._detail_images):
            return
        img = self._detail_images[row]
        if hasattr(self, "_detail_img_preview"):
            pix = QPixmap(img["abs"])
            if not pix.isNull():
                self._detail_img_preview.setPixmap(pix.scaled(
                    self._detail_img_preview.size(),
                    Qt.KeepAspectRatio, Qt.SmoothTransformation))
        if hasattr(self, "_detail_img_info"):
            self._detail_img_info.setText(
                f"引用路径: {img['rel']}\n文件: {img['abs']}")

    def _open_detail_folder(self, folder) -> None:
        """打开任务图片文件夹（不存在则自动创建，系统文件管理器）"""
        import os
        from core.asset_catalog import open_in_file_manager
        ok = open_in_file_manager(folder, create=True)
        if not ok:
            QMessageBox.warning(
                self, "打开失败",
                f"无法打开目录：{os.path.relpath(folder)}\n（目录不存在或系统无文件管理器）")

    # ── 操作（经 TaskBridge → TaskManager） ─────────────────

    def _new_task(self) -> None:
        bridge = self._param_bridge
        if not bridge or not hasattr(bridge, 'task'):
            return
        # 任务类型（core/task_template.py）：非战斗/战斗/通用/触发
        from core.task_template import TASK_TYPES, TASK_TYPE_LABELS
        type_items = [f"{TASK_TYPE_LABELS[t]}（{t}）" for t in TASK_TYPES]
        type_label, ok0 = QInputDialog.getItem(self, "新建任务", "任务类型:",
                                               type_items, 0, False)
        if not ok0:
            return
        task_type = TASK_TYPES[type_items.index(type_label)]

        name, ok = QInputDialog.getText(self, "新建任务", "任务文件名（英文，不含 .py）:")
        if not ok or not name.strip():
            return
        display, ok2 = QInputDialog.getText(self, "新建任务", "显示名（可留空）:")
        if not ok2:
            return
        # 通用任务固定放 common/（不单独执行）；其余选择分类
        if task_type == "generic":
            category = "common"
        else:
            category, ok3 = QInputDialog.getItem(self, "新建任务", "分类:",
                                                 CATEGORIES, 0, False)
            if not ok3:
                return
        try:
            bridge.task.new_task(category, name.strip(), display.strip(), task_type=task_type)
            self._refresh()
        except Exception as e:
            QMessageBox.warning(self, "新建失败", str(e))

    def _delete_task(self) -> None:
        bridge = self._param_bridge
        if not bridge or not hasattr(bridge, 'task'):
            return
        if not self._current_name:
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"删除任务「{self._current_name}」？\n（重命名为 .deleted 保留内容，可恢复）",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                bridge.task.delete_task(self._current_name)
                self._refresh()
            except Exception as e:
                QMessageBox.warning(self, "删除失败", str(e))

    def _open_file(self) -> None:
        bridge = self._param_bridge
        if not bridge or not hasattr(bridge, 'task'):
            return
        if not self._current_name:
            return
        try:
            bridge.task.open_file(self._current_name)
        except Exception as e:
            QMessageBox.warning(self, "打开失败", str(e))

    # ── 配置备份导入导出（06-配置管理中心） ─────────────────

    def _export_config(self) -> None:
        bridge = self._param_bridge
        if not bridge or not hasattr(bridge, 'config'):
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出配置备份",
                                              "yys_config_backup.zip", "ZIP (*.zip)")
        if not path:
            return
        try:
            bridge.config.export_config(path)
            QMessageBox.information(self, "导出成功", f"已导出到 {path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _import_config(self) -> None:
        bridge = self._param_bridge
        if not bridge or not hasattr(bridge, 'config'):
            return
        path, _ = QFileDialog.getOpenFileName(self, "导入配置备份", "", "ZIP (*.zip)")
        if not path:
            return
        reply = QMessageBox.question(
            self, "确认导入",
            "导入将覆盖现有配置，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            bridge.config.import_config(path)
            QMessageBox.information(self, "导入成功", "配置已恢复")
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))
