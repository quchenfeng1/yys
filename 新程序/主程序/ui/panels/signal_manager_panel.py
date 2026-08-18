"""
UI 子面板：SignalManagerPanel 信号管理（2026-08-16 信号体系）。

三个 Tab：
- 场景信号：场景素材附带的 signal（{场景id, 信号}）
- 触发信号：任务图内「任务信号触发器」节点设立的信号（{任务, 信号}）
- 任务信号：任务图内「任务信号输出/接收」节点使用的信号（{任务, 信号}）
  + 自定义信号（手工添加，供节点下拉候选）

数据经回调注入（VisualBridge），面板无核心依赖。
"""
from __future__ import annotations

from typing import Any, Callable

from PyQt5.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)


class SignalManagerPanel(QWidget):
    """信号管理面板。"""

    def __init__(self,
                 scene_provider: Callable[[], list[dict]] | None = None,
                 trigger_provider: Callable[[], list[dict]] | None = None,
                 task_provider: Callable[[], list[dict]] | None = None,
                 custom_provider: Callable[[], list[str]] | None = None,
                 add_custom_cb: Callable[[str], bool] | None = None,
                 remove_custom_cb: Callable[[str], bool] | None = None,
                 parent=None):
        super().__init__(parent)
        self._scene_provider = scene_provider or (lambda: [])
        self._trigger_provider = trigger_provider or (lambda: [])
        self._task_provider = task_provider or (lambda: [])
        self._custom_provider = custom_provider or (lambda: [])
        self._add_custom_cb = add_custom_cb or (lambda n: False)
        self._remove_custom_cb = remove_custom_cb or (lambda n: False)
        self._setup_ui()
        self.refresh()

    # ── UI ──────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        top = QHBoxLayout()
        top.addWidget(QLabel("🔔 信号管理"))
        top.addStretch(1)
        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.clicked.connect(self.refresh)
        top.addWidget(btn_refresh)
        layout.addLayout(top)

        self.tabs = QTabWidget()
        self.tab_scene = self._make_table(["场景 ID", "场景信号"], "scene")
        self.tab_trigger = self._make_table(["任务", "触发信号"], "trigger")
        task_tab = QWidget()
        task_lay = QVBoxLayout(task_tab)
        self.tab_task = self._make_table(["任务", "任务信号"], "task")
        task_lay.addWidget(self.tab_task, 1)
        # 自定义信号区
        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("自定义信号"))
        self.ed_custom = QLineEdit()
        self.ed_custom.setPlaceholderText("输入信号名，可被任务信号节点引用")
        btn_add = QPushButton("＋ 添加")
        btn_add.clicked.connect(self._on_add_custom)
        btn_del = QPushButton("🗑 删除选中")
        btn_del.clicked.connect(self._on_remove_custom)
        custom_row.addWidget(self.ed_custom)
        custom_row.addWidget(btn_add)
        custom_row.addWidget(btn_del)
        custom_row.addStretch(1)
        task_lay.addLayout(custom_row)
        self.list_custom = None
        from PyQt5.QtWidgets import QListWidget
        self.list_custom = QListWidget()
        task_lay.addWidget(self.list_custom, 1)

        self.tabs.addTab(self.tab_scene, "场景信号")
        self.tabs.addTab(self.tab_trigger, "触发信号")
        self.tabs.addTab(task_tab, "任务信号")
        layout.addWidget(self.tabs, 1)

        hint = QLabel("说明：场景信号由场景素材附带（素材管理可改）；触发信号/任务信号来自"
                      "可视化任务图内信号节点，自动扫描；自定义信号供节点下拉使用。")
        hint.setStyleSheet("color:#8a94a6; font-size:12px;")
        layout.addWidget(hint)

    def _make_table(self, headers: list[str], _kind: str) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setAlternatingRowColors(True)
        return table

    # ── 数据 ────────────────────────────────────────────

    def refresh(self) -> None:
        self._fill_table(self.tab_scene, self._scene_provider(),
                         lambda r: [r.get("scene_id", ""), r.get("signal", "")])
        self._fill_table(self.tab_trigger, self._trigger_provider(),
                         lambda r: [r.get("task", ""), r.get("signal", "")])
        self._fill_table(self.tab_task, self._task_provider(),
                         lambda r: [r.get("task", ""), r.get("signal", "")])
        if self.list_custom is not None:
            self.list_custom.clear()
            self.list_custom.addItems(self._custom_provider())

    @staticmethod
    def _fill_table(table: QTableWidget, rows: list[dict],
                    extract) -> None:
        table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, v in enumerate(extract(r)):
                table.setItem(i, j, QTableWidgetItem(str(v)))

    # ── 交互 ────────────────────────────────────────────

    def _on_add_custom(self) -> None:
        name = self.ed_custom.text().strip()
        if not name:
            return
        if self._add_custom_cb(name):
            self.ed_custom.clear()
            self.refresh()
        else:
            QMessageBox.warning(self, "提示", "添加失败（已存在或名称为空）")

    def _on_remove_custom(self) -> None:
        if self.list_custom is None:
            return
        item = self.list_custom.currentItem()
        if item is None:
            QMessageBox.information(self, "提示", "请先选中一个自定义信号")
            return
        if self._remove_custom_cb(item.text()):
            self.refresh()
        else:
            QMessageBox.warning(self, "提示", "删除失败")
