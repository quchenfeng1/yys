"""
UI 子面板：TaskManagerPanel 任务文件管理（13-任务文件管理）。

按《13-任务文件管理》说明书：
- 左侧：任务库列表（扫描 tasks/ 的元数据）
- 操作：新建任务 / 删除（重命名 .deleted）/ 打开编辑 / 导入导出配置备份
- 右侧：选中任务的详情（元数据 + uses_* 声明 + 文件路径）
"""
from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QListWidget, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

CATEGORIES = ["daily", "permanent", "event", "special"]


class TaskManagerPanel(QWidget):
    """任务文件管理面板（列表 + 详情 + 新建/删除/打开/导入导出）"""

    def __init__(self, param_bridge: Any = None, parent=None):
        super().__init__(parent)
        self._param_bridge = param_bridge
        self._current_name: str = ""
        self._detail_labels: dict[str, QLabel] = {}

        layout = QHBoxLayout(self)

        # ── 左侧任务库 ────────────────────────────────────
        left = QVBoxLayout()
        left.addWidget(QLabel("任务库"))
        self.task_list = QListWidget()
        self.task_list.currentItemChanged.connect(self._on_task_selected)
        left.addWidget(self.task_list)

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

    def _refresh(self) -> None:
        """重新拉取任务库元数据并刷新列表"""
        bridge = self._param_bridge
        if not bridge or not hasattr(bridge, 'task'):
            return
        try:
            metas = bridge.task.get_task_metas()
            self.load_tasks(metas)
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

        title = QLabel(f"📋 {display}")
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        self.detail_layout.addWidget(title)

        g = QGroupBox("元数据")
        form = QFormLayout(g)
        rows = [
            ("文件名:", name),
            ("显示名:", display),
            ("分类:", detail.get("category", "")),
            ("任务类型:", detail.get("task_type", "")),
            ("描述:", detail.get("description", "")),
            ("战斗任务:", "是" if detail.get("uses_battle") else "否"),
            ("阵容配置:", "是" if detail.get("uses_team") else "否"),
            ("御魂配置:", "是" if detail.get("uses_soul") else "否"),
            ("体力检查:", "是" if detail.get("uses_stamina") else "否"),
            ("每轮循环:", str(detail.get("loop_count", 1))),
            ("超时(秒):", str(detail.get("timeout", 300))),
        ]
        # 文件路径（如果 detail 有）
        for label, value in rows:
            vl = QLabel(str(value))
            vl.setWordWrap(True)
            form.addRow(label, vl)
            self._detail_labels[label] = vl
        self.detail_layout.addWidget(g)

        self.detail_layout.addStretch()

    # ── 操作（经 TaskBridge → TaskManager） ─────────────────

    def _new_task(self) -> None:
        bridge = self._param_bridge
        if not bridge or not hasattr(bridge, 'task'):
            return
        name, ok = QInputDialog.getText(self, "新建任务", "任务文件名（英文，不含 .py）:")
        if not ok or not name.strip():
            return
        display, ok2 = QInputDialog.getText(self, "新建任务", "显示名（可留空）:")
        if not ok2:
            return
        category, ok3 = QInputDialog.getItem(self, "新建任务", "分类:",
                                             CATEGORIES, 0, False)
        if not ok3:
            return
        try:
            bridge.task.new_task(category, name.strip(), display.strip())
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
