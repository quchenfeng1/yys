"""
UI 子面板：ExecutionHistoryPanel 执行历史。
"""
from __future__ import annotations

from PyQt5.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget


class ExecutionHistoryPanel(QWidget):
    """执行历史面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["时间", "任务", "状态", "耗时", "错误"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        layout.addWidget(self.table)

    def add_record(self, time: str, task: str, status: str, duration: str, error: str = "") -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(time))
        self.table.setItem(row, 1, QTableWidgetItem(task))
        self.table.setItem(row, 2, QTableWidgetItem(status))
        self.table.setItem(row, 3, QTableWidgetItem(duration))
        self.table.setItem(row, 4, QTableWidgetItem(error))
        self.table.scrollToBottom()
