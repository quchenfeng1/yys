"""
11-用户界面模块 — 多选下拉框（QComboBox + 复选框项）。

用于从固定列表多选（如组队小号从「小号管理」选择）：
- 下拉展开后每个选项带复选框，可多选
- 收起时输入框显示已选条目（逗号分隔）
- 数据与显示分离：set_items 传入 (data, label)，selected_data() 返回选中的 data
"""
from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import QComboBox


class MultiSelectCombo(QComboBox):
    """下拉多选：选项带复选框，收起时显示已选摘要。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data_items: dict[Any, QStandardItem] = {}
        self._data_labels: dict[Any, str] = {}

        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self.view().pressed.connect(self._toggle)

        # editable + 只读输入框：仅用于展示"已选摘要"
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText("未选择")
        self.lineEdit().setStyleSheet("background: transparent;")

    # ── 数据填充 ─────────────────────────────────────────

    def set_items(self, items: list[tuple[Any, str]]) -> None:
        """填充选项。items: [(data, label), ...]"""
        self._model.clear()
        self._data_items.clear()
        self._data_labels.clear()
        for data, label in items:
            item = QStandardItem(label)
            item.setData(data, Qt.UserRole)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self._model.appendRow(item)
            self._data_items[data] = item
            self._data_labels[data] = label
        self._refresh_text()

    def has_items(self) -> bool:
        """是否已有可选条目"""
        return self._model.rowCount() > 0

    # ── 选中态 ───────────────────────────────────────────

    def selected_data(self) -> list[Any]:
        """返回当前选中的 data 列表（保持添加顺序）"""
        out = []
        for data, item in self._data_items.items():
            if item.checkState() == Qt.Checked:
                out.append(data)
        return out

    def set_selected(self, selected: list[Any]) -> None:
        """回显勾选（仅勾选存在于选项中的 data）"""
        sel = set(selected)
        for data, item in self._data_items.items():
            item.setCheckState(Qt.Checked if data in sel else Qt.Unchecked)
        self._refresh_text()

    def select_all(self) -> None:
        """全部勾选"""
        for item in self._data_items.values():
            item.setCheckState(Qt.Checked)
        self._refresh_text()

    def clear_selection(self) -> None:
        """全部取消勾选"""
        for item in self._data_items.values():
            item.setCheckState(Qt.Unchecked)
        self._refresh_text()

    # ── 交互 ─────────────────────────────────────────────

    def _toggle(self, index) -> None:
        item = self._model.itemFromIndex(index)
        if item is None:
            return
        new_state = (Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
        item.setCheckState(new_state)
        self._refresh_text()
        # 保持下拉展开，便于连续多选；点下拉外部可关闭
        self.showPopup()

    def showPopup(self) -> None:
        """弹出前恢复摘要；Qt 可能异步激活当前项覆盖输入框文本 → 延迟再恢复"""
        self._refresh_text()
        super().showPopup()
        QTimer.singleShot(0, self._refresh_text)

    def hidePopup(self) -> None:
        """关闭后恢复摘要，避免收起时只显示最后点击的单个选项"""
        super().hidePopup()
        QTimer.singleShot(0, self._refresh_text)

    def _refresh_text(self) -> None:
        checked = self.selected_data()
        if not checked:
            self.lineEdit().setText("")
            return
        labels = [self._data_labels.get(d, str(d)) for d in checked]
        self.lineEdit().setText(", ".join(labels))
