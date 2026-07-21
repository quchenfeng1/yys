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

    def bind_timeedit(self, widget, config_key: str):
        """时间编辑器 ↔ 配置（格式 HH:mm）。"""
        from PyQt5.QtCore import QTime
        val = self._config.get(config_key, "08:00")
        widget.setTime(QTime.fromString(val, "HH:mm"))
        widget.timeChanged.connect(
            lambda t: self._config.set(config_key, t.toString("HH:mm"))
        )

    # ==================== 配置管理操作 ====================

    def export_config(self) -> str | None:
        """导出配置到 zip 文件，返回路径。"""
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(None, "导出配置", "config_backup.zip", "ZIP (*.zip)")
        if path:
            self._config.export_config(path)
            return path
        return None

    def import_config(self) -> str | None:
        """从 zip 文件导入配置，返回路径。"""
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getOpenFileName(None, "导入配置", "", "ZIP (*.zip)")
        if path:
            reply = QMessageBox.question(None, "确认导入",
                f"将从备份恢复配置，当前配置将被覆盖。继续？",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self._config.import_config(path)
                self._config.reload()
                return path
        return None

    def reload_config(self):
        """热重载配置。"""
        self._config.reload()

    def validate_config(self) -> list[str]:
        """校验配置，返回错误列表。"""
        return self._config.validate()
