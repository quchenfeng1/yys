"""
UI 子面板：SubAccountStatusPanel 小号状态监控。
"""
from __future__ import annotations

from PyQt5.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget


class SubAccountPanel(QWidget):
    """小号状态监控面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["账号", "状态", "区域", "在线", "备注"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        layout.addWidget(self.table)

    def update_accounts(self, accounts: list[dict]) -> None:
        """更新账号列表"""
        self.table.setRowCount(len(accounts))
        for row, acc in enumerate(accounts):
            self.table.setItem(row, 0, QTableWidgetItem(acc.get("name", "")))
            self.table.setItem(row, 1, QTableWidgetItem(acc.get("status", "unknown")))
            self.table.setItem(row, 2, QTableWidgetItem(acc.get("region", "cn")))
            self.table.setItem(row, 3, QTableWidgetItem("✅" if acc.get("online") else "❌"))
            self.table.setItem(row, 4, QTableWidgetItem(acc.get("remark", "")))
