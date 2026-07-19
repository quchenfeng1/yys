"""
通用配置传参（10-传参模块 子模块）

UI 配置控件 ↔ 配置模块。
"""


class ConfigBridge:
    """通用配置传参。"""

    def __init__(self, config_manager):
        self._config = config_manager

    def bind_lineedit(self, widget, config_key: str):
        """单行输入 ↔ 配置。"""
        widget.setText(str(self._config.get(config_key, "")))
        widget.textChanged.connect(lambda v: self._config.set(config_key, v))

    def bind_spinbox(self, widget, config_key: str, min_val=0, max_val=99999):
        """数字输入 ↔ 配置。"""
        widget.setRange(min_val, max_val)
        widget.setValue(int(self._config.get(config_key, 0)))
        widget.valueChanged.connect(lambda v: self._config.set(config_key, v))

    def bind_checkbox(self, widget, config_key: str):
        """复选框 ↔ 配置。"""
        widget.setChecked(self._config.get(config_key, False))
        widget.toggled.connect(lambda v: self._config.set(config_key, v))

    def bind_combobox(self, widget, config_key: str, options: list):
        """下拉框 ↔ 配置。"""
        widget.addItems(options)
        current = self._config.get(config_key, options[0] if options else "")
        if current in options:
            widget.setCurrentText(current)
        widget.currentTextChanged.connect(lambda v: self._config.set(config_key, v))
