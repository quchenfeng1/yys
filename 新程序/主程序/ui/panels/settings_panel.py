"""
UI 子面板：SettingsPanel 设置面板。

将原「配置」(ConfigPanel) 与「UI 设置」(UISettingsPanel) 合并为
菜单「⚙️ 设置」下的两个 Tab：
  - Tab1「⚙️ 全局配置」：原 ConfigPanel（global.yaml 可编辑表单）
  - Tab2「🎨 界面设置」：原 UISettingsPanel（主题/日志/字体/面板显隐）
"""
from __future__ import annotations

from typing import Any

from PyQt5.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from ui.panels.config_panel import ConfigPanel
from ui.panels.ui_settings_panel import UISettingsPanel


class SettingsPanel(QWidget):
    """设置面板：全局配置 + 界面设置 两个 Tab"""

    def __init__(self, param_bridge: Any = None, parent=None):
        super().__init__(parent)
        self._param_bridge = param_bridge

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.config_panel = ConfigPanel(param_bridge=param_bridge)
        self.ui_panel = UISettingsPanel()
        self.tabs.addTab(self.config_panel, "⚙️ 全局配置")
        self.tabs.addTab(self.ui_panel, "🎨 界面设置")
        layout.addWidget(self.tabs)
