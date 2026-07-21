"""
执行规则编辑器（11-用户界面模块）

可视化编辑任务的 RepeatRule：类型 / 间隔 / 次数 / 时段。
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QSpinBox, QTimeEdit, QCheckBox, QGroupBox,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

REPEAT_TYPES = {
    "interval": "固定间隔",
    "daily": "每日定时",
    "cron": "Cron 表达式",
    "once": "仅一次",
    "loop": "持续循环",
    "countdown": "倒计时触发",
    "manual": "手动触发",
    "event_driven": "事件驱动",
}


class RepeatEditor(QWidget):
    """执行规则编辑器 — 可视化配置 RepeatRule。"""

    rule_changed = pyqtSignal(dict)   # 发出完整规则 dict

    def __init__(self, rule: dict = None, parent=None):
        super().__init__(parent)
        self._rule = rule or {"type": "interval", "interval_minutes": 60}
        self._build()
        self._load()

    def _build(self):
        ly = QVBoxLayout(self)
        ly.setContentsMargins(0, 0, 0, 0)
        ly.setSpacing(6)

        # 类型选择
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("执行类型:"))
        self._type_combo = QComboBox()
        for key, label in REPEAT_TYPES.items():
            self._type_combo.addItem(label, key)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_row.addWidget(self._type_combo)
        type_row.addStretch()
        ly.addLayout(type_row)

        # 参数区（动态显隐）
        self._param_stack = QWidget()
        self._param_ly = QVBoxLayout(self._param_stack)
        self._param_ly.setContentsMargins(0, 4, 0, 0)
        self._param_ly.setSpacing(4)

        # 间隔参数
        self._interval_row = QWidget()
        il = QHBoxLayout(self._interval_row)
        il.setContentsMargins(0, 0, 0, 0)
        il.addWidget(QLabel("间隔(分):"))
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(1, 1440)
        self._interval_spin.setSuffix(" 分钟")
        self._interval_spin.valueChanged.connect(self._emit_change)
        il.addWidget(self._interval_spin)
        il.addStretch()
        self._param_ly.addWidget(self._interval_row)

        # 每日定时
        self._daily_row = QWidget()
        dl = QHBoxLayout(self._daily_row)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(QLabel("每日:"))
        self._daily_time = QTimeEdit()
        self._daily_time.setDisplayFormat("HH:mm")
        self._daily_time.timeChanged.connect(lambda: self._emit_change())
        dl.addWidget(self._daily_time)
        dl.addStretch()
        self._param_ly.addWidget(self._daily_row)

        # 次数限制
        limit_row = QHBoxLayout()
        limit_row.addWidget(QLabel("次数上限:"))
        self._max_times = QSpinBox()
        self._max_times.setRange(0, 9999)
        self._max_times.setSpecialValueText("不限")
        self._max_times.valueChanged.connect(self._emit_change)
        limit_row.addWidget(self._max_times)
        limit_row.addStretch()
        self._param_ly.addLayout(limit_row)

        ly.addWidget(self._param_stack)

        self.setStyleSheet("RepeatEditor{background:transparent;}")

    def _load(self):
        rtype = self._rule.get("type", "interval")
        idx = self._type_combo.findData(rtype)
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)
        self._interval_spin.setValue(self._rule.get("interval_minutes", 60))
        from PyQt5.QtCore import QTime
        t = self._rule.get("daily_time", "08:00")
        self._daily_time.setTime(QTime.fromString(t, "HH:mm"))
        self._max_times.setValue(self._rule.get("max_times", 0))
        self._on_type_changed()

    def _on_type_changed(self):
        rtype = self._type_combo.currentData()
        self._interval_row.setVisible(rtype in ("interval", "countdown"))
        self._daily_row.setVisible(rtype == "daily")
        self._emit_change()

    def _emit_change(self):
        rtype = self._type_combo.currentData()
        rule = {"type": rtype}
        if rtype in ("interval", "countdown"):
            rule["interval_minutes"] = self._interval_spin.value()
        if rtype == "daily":
            rule["daily_time"] = self._daily_time.time().toString("HH:mm")
        if self._max_times.value() > 0:
            rule["max_times"] = self._max_times.value()
        self._rule = rule
        self.rule_changed.emit(rule)

    def get_rule(self) -> dict:
        return dict(self._rule)
