"""
11-用户界面模块 — 游戏任务面板

职责：
  显示游戏任务列表 + 任务配置表单（重复规则/优先级/阵容等）
  支持批量编辑、活动日历导入、运行时进度展示与重置
"""

from __future__ import annotations

from typing import Optional, Any
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QPushButton, QLabel, QCheckBox, QComboBox, QSpinBox,
    QTimeEdit, QDateEdit, QLineEdit, QFrame, QSplitter,
    QMessageBox, QFileDialog, QMenu,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer


class ClickableRow(QFrame):
    """可点击的任务行组件"""
    clicked = pyqtSignal(object)

    def __init__(self, task_module: Any, parent=None):
        super().__init__(parent)
        self.task_module = task_module
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        # 分类图标 + 类型 + 显示名 + 描述
        layout = QHBoxLayout(self)
        self._label = QLabel(f"{task_module.category} {task_module.display_name}")
        layout.addWidget(self._label)

    def mousePressEvent(self, event):
        self.clicked.emit(self.task_module)
        super().mousePressEvent(event)


class GameTaskPanel(QWidget):
    """游戏任务面板（列表上半 + 配置表单下半）"""

    def __init__(self, param_bridge, scheduler, task_registry, task_manager, parent=None):
        super().__init__(parent)
        self._bridge = param_bridge
        self._scheduler = scheduler
        self._registry = task_registry
        self._task_manager = task_manager
        self._current_task = None
        self._batch_mode = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Vertical)

        # ── 上半：任务列表 ──
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        # 工具栏
        toolbar = QHBoxLayout()
        self._batch_btn = QPushButton("📝 批量编辑")
        self._batch_btn.clicked.connect(self._toggle_batch_mode)
        self._calendar_btn = QPushButton("📅 导入活动日历")
        self._calendar_btn.clicked.connect(self._import_calendar)
        toolbar.addWidget(self._batch_btn)
        toolbar.addWidget(self._calendar_btn)
        toolbar.addStretch()
        top_layout.addLayout(toolbar)
        # 任务列表（可滚动）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._task_list = QWidget()
        self._task_layout = QVBoxLayout(self._task_list)
        scroll.setWidget(self._task_list)
        top_layout.addWidget(scroll)
        splitter.addWidget(top_widget)

        # ── 下半：配置表单 ──
        self._form = QWidget()
        self._form_layout = QVBoxLayout(self._form)
        self._form.setVisible(False)
        splitter.addWidget(self._form)

        layout.addWidget(splitter)
        self._populate_task_list()

    def _populate_task_list(self):
        """填充任务列表"""
        import tasks.registry
        for task in self._registry.get_all():
            row = ClickableRow(task)
            row.clicked.connect(self._on_task_clicked)
            self._task_layout.addWidget(row)

    def _on_task_clicked(self, task_module):
        self._current_task = task_module
        self._show_config_form(task_module)
        self._form.setVisible(True)

    def _show_config_form(self, task):
        """显示任务配置表单"""
        from PyQt5.QtWidgets import QFormLayout
        # 清空旧表单
        while self._form_layout.count():
            item = self._form_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        form = QFormLayout()
        self._enabled_cb = QCheckBox("启用此任务")
        form.addRow(self._enabled_cb)

        self._priority_spin = QSpinBox()
        self._priority_spin.setRange(1, 99)
        self._priority_spin.setValue(getattr(task, 'priority', 10))
        form.addRow("优先级:", self._priority_spin)

        self._repeat_combo = QComboBox()
        self._repeat_combo.addItems(["once", "daily", "weekly", "monthly",
                                      "interval_days", "interval_hours"])
        form.addRow("重复规则:", self._repeat_combo)

        self._time_edit = QTimeEdit()
        form.addRow("开始时间:", self._time_edit)

        self._save_btn = QPushButton("💾 保存配置")
        self._save_btn.clicked.connect(self._save_config)
        form.addRow(self._save_btn)

        self._form_layout.addLayout(form)

    def _save_config(self):
        """保存任务配置"""
        if not self._current_task:
            return
        cfg = {
            "enabled": self._enabled_cb.isChecked(),
            "priority": self._priority_spin.value(),
            "repeat": self._repeat_combo.currentText(),
            "at_time": self._time_edit.time().toString("HH:mm"),
        }
        self._scheduler.update_next_run(self._current_task.name, cfg)
        self._scheduler.build_schedule()

    def _toggle_batch_mode(self):
        """切换批量编辑模式"""
        self._batch_mode = not self._batch_mode
        self._batch_btn.setText("✅ 批量编辑" if self._batch_mode else "📝 批量编辑")

    def _import_calendar(self):
        """导入活动日历文件"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择活动日历文件", "", "JSON/YAML (*.json *.yaml)")
        if path:
            try:
                import json, yaml
                with open(path, encoding="utf-8") as f:
                    if path.endswith(".yaml"):
                        events = yaml.safe_load(f)
                    else:
                        events = json.load(f)
                self._scheduler.import_calendar(events)
                QMessageBox.information(self, "导入成功", f"已导入 {len(events)} 个活动")
            except Exception as e:
                QMessageBox.warning(self, "导入失败", str(e))

    def refresh(self):
        """刷新任务列表（外部事件触发）"""
        self._populate_task_list()
