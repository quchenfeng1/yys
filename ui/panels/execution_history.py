"""
11-用户界面模块 — 执行历史面板

职责：
  按任务名+日期筛选，展示单任务执行明细
  数据来源：12-日志监控中心.query_task_history()
"""

from __future__ import annotations

from typing import Any
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QComboBox, QDateEdit,
    QPushButton, QLabel,
)
from PyQt5.QtCore import Qt, QDate


class ExecutionHistoryPanel(QWidget):
    """执行历史面板：按任务名+日期查看执行记录"""

    def __init__(self, monitor, task_registry, parent=None):
        super().__init__(parent)
        self._monitor = monitor
        self._registry = task_registry
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── 筛选区 ──
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("任务:"))
        self._task_combo = QComboBox()
        self._task_combo.setMinimumWidth(200)
        filter_layout.addWidget(self._task_combo)
        filter_layout.addWidget(QLabel("日期:"))
        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDate(QDate.currentDate())
        filter_layout.addWidget(self._date_edit)
        self._query_btn = QPushButton("查询")
        self._query_btn.clicked.connect(self._query_history)
        filter_layout.addWidget(self._query_btn)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # ── 结果表格 ──
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["时间", "结果", "耗时(秒)", "完成/总轮次", "详情"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table)

        # 填充任务列表
        self._populate_task_combo()

    def _populate_task_combo(self):
        """填充任务名下拉框"""
        self._task_combo.clear()
        self._task_combo.addItem("全部任务", None)
        if self._registry:
            for task in self._registry.get_all():
                self._task_combo.addItem(task.display_name, task.name)

    def _query_history(self):
        """查询执行历史"""
        task_name = self._task_combo.currentData()
        date_str = self._date_edit.date().toString("yyyy-MM-dd")
        # 从 monitor 查询历史
        records = []
        if self._monitor:
            records = self._monitor.query_task_history(task_name, date_str)
        self._table.setRowCount(len(records))
        for row, rec in enumerate(records):
            self._table.setItem(row, 0, QTableWidgetItem(str(rec.get("time", ""))))
            self._table.setItem(row, 1, QTableWidgetItem(rec.get("result", "")))
            self._table.setItem(row, 2, QTableWidgetItem(str(rec.get("duration", ""))))
            self._table.setItem(row, 3, QTableWidgetItem(
                f"{rec.get('completed', 0)}/{rec.get('total', 0)}"))
            self._table.setItem(row, 4, QTableWidgetItem(rec.get("detail", "")))

    def refresh(self):
        """刷新面板"""
        self._populate_task_combo()
