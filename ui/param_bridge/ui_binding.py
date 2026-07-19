"""
UI 数据绑定层（10-传参模块 子模块）

实现控件与配置数据的双向同步。
"""

from PyQt5.QtWidgets import QCheckBox, QSpinBox, QLabel, QLineEdit


class UIBinding:
    """UI 控件 ↔ 配置/状态 双向绑定。"""

    def __init__(self, config_manager, state_manager, scheduler):
        self._config = config_manager
        self._state_mgr = state_manager
        self._scheduler = scheduler

    def bind_checkbox(self, checkbox: QCheckBox, config_key: str):
        """复选框 ↔ 配置 bool 值。"""
        checkbox.setChecked(self._config.get(config_key, False))
        checkbox.toggled.connect(lambda v: self._config.set(config_key, v))

    def bind_spinbox(self, spinbox: QSpinBox, config_key: str,
                     min_val: int = None, max_val: int = None):
        """数字输入框 ↔ 配置 int 值。"""
        if min_val is not None:
            spinbox.setMinimum(min_val)
        if max_val is not None:
            spinbox.setMaximum(max_val)
        spinbox.setValue(int(self._config.get(config_key, 0)))
        spinbox.valueChanged.connect(lambda v: self._config.set(config_key, v))

    def bind_lineedit(self, widget: QLineEdit, config_key: str):
        """单行输入 ↔ 配置。"""
        widget.setText(str(self._config.get(config_key, "")))
        widget.textChanged.connect(lambda v: self._config.set(config_key, v))

    def bind_label(self, label: QLabel, state_key: str):
        """标签 ↔ 状态管理器（只读，自动刷新）。"""
        label.setText(str(self._state_mgr.get_state(state_key, "")))
        self._state_mgr.subscribe(state_key, lambda new, old: label.setText(str(new)))
