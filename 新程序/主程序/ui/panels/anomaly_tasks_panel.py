"""
UI 子面板：AnomalyTasksPanel 异常任务（2026-08-16 信号体系）。

设计（v7）：
- 左：异常任务列表（未确认修复的任务，不进任何队列直到确认修复）
- 右：所选任务的异常履历（最新在上），每条带「处理」按钮 → 点击后变「已处理」
- 全部异常处理完才能点「已修复」，否则弹窗「异常未处理」
- 处理按钮：跳转到可视化构建的流程编排 Tab，打开对应任务并定位到异常节点
"""
from __future__ import annotations

from typing import Any, Callable

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)


class AnomalyTasksPanel(QWidget):
    """异常任务面板。"""

    # (task_name, node_id)：跳转可视化构建并定位异常节点
    handle_requested = pyqtSignal(str, str)

    def __init__(self,
                 abnormal_provider: Callable[[], list[str]] | None = None,
                 list_provider: Callable[[str | None], list[dict]] | None = None,
                 mark_handled_cb: Callable[[str], bool] | None = None,
                 confirm_fixed_cb: Callable[[str], bool] | None = None,
                 unresolved_cb: Callable[[str], int] | None = None,
                 parent=None):
        super().__init__(parent)
        self._abnormal_provider = abnormal_provider or (lambda: [])
        self._list_provider = list_provider or (lambda t: [])
        self._mark_handled_cb = mark_handled_cb or (lambda aid: False)
        self._confirm_fixed_cb = confirm_fixed_cb or (lambda t: False)
        self._unresolved_cb = unresolved_cb or (lambda t: 0)
        self._setup_ui()
        self.refresh()

    # ── UI ──────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        top = QHBoxLayout()
        top.addWidget(QLabel("⚠️ 异常任务"))
        top.addStretch(1)
        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.clicked.connect(self.refresh)
        top.addWidget(btn_refresh)
        layout.addLayout(top)

        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("未确认修复的任务"))
        self.task_list = QListWidget()
        self.task_list.currentItemChanged.connect(self._on_task_selected)
        ll.addWidget(self.task_list, 1)
        self.btn_fixed = QPushButton("✅ 已修复")
        self.btn_fixed.setToolTip("全部异常处理完才能确认修复")
        self.btn_fixed.clicked.connect(self._on_confirm_fixed)
        ll.addWidget(self.btn_fixed)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("异常履历（最新在上）"))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["时间", "原因", "节点", "场景信号", "状态", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        rl.addWidget(self.table, 1)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        layout.addWidget(split, 1)

        hint = QLabel("异常任务被标记后不进入任何队列，直到确认修复；"
                      "「处理」跳转到可视化构建定位异常节点。")
        hint.setStyleSheet("color:#8a94a6; font-size:12px;")
        layout.addWidget(hint)

    # ── 数据 ────────────────────────────────────────────

    def refresh(self) -> None:
        self._fill_tasks()

    def _fill_tasks(self) -> None:
        self.task_list.clear()
        for name in self._abnormal_provider():
            item = QListWidgetItem(name)
            item.setData(256, name)
            self.task_list.addItem(item)

    def _current_task(self) -> str:
        item = self.task_list.currentItem()
        return item.data(256) if item else ""

    def _fill_history(self, task_name: str) -> None:
        rows = self._list_provider(task_name)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r.get("time", ""), r.get("reason", ""),
                    r.get("node_id", ""), r.get("signal", ""),
                    "已处理" if r.get("handled") else "未处理", ""]
            for j, v in enumerate(vals[:5]):
                self.table.setItem(i, j, QTableWidgetItem(str(v)))
            btn = QPushButton("✔ 已处理" if r.get("handled") else "处理")
            btn.setEnabled(not bool(r.get("handled")))
            btn.clicked.connect(
                lambda *a, rid=r.get("id", ""), t=task_name,
                nid=r.get("node_id", ""): self._on_handle(t, rid, nid))
            self.table.setCellWidget(i, 5, btn)

    # ── 交互 ────────────────────────────────────────────

    def _on_task_selected(self, current, _prev) -> None:
        if current is None:
            self.table.setRowCount(0)
            return
        self._fill_history(current.data(256))

    def _on_handle(self, task_name: str, anomaly_id: str,
                   node_id: str) -> None:
        # 先跳转定位（用户查看/修复），再标记已处理
        if node_id:
            self.handle_requested.emit(task_name, node_id)
        if self._mark_handled_cb(anomaly_id):
            self._fill_history(task_name)

    def _on_confirm_fixed(self) -> None:
        task_name = self._current_task()
        if not task_name:
            QMessageBox.information(self, "提示", "请先选择异常任务")
            return
        if self._unresolved_cb(task_name) > 0:
            QMessageBox.warning(self, "异常未处理",
                                f"「{task_name}」还有未处理的异常，"
                                "请先处理全部异常。")
            return
        if self._confirm_fixed_cb(task_name):
            self.refresh()
