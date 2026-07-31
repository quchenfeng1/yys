"""
UI 子面板：LogPanel 日志+终端双标签。
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget,
)


class LogPanel(QWidget):
    """日志面板（日志+终端双标签）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()

        # 日志标签
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(10000)
        self.tabs.addTab(self.log_view, "日志")

        # 终端标签
        self.terminal_view = QPlainTextEdit()
        self.terminal_view.setReadOnly(True)
        self.terminal_view.setMaximumBlockCount(5000)
        self.tabs.addTab(self.terminal_view, "终端")

        layout.addWidget(self.tabs)

    def append_log(self, message: str | None = None, **kw: str) -> None:
        """
        追加日志（兼容 **kw 和 str 两种调用方式）。

        支持 MainWindow 的调用方式:
          append_log(**kw)  — kw 含 level/message/key
          append_log(message="xxx") — 关键字
          append_log("xxx") — 位置参数
        """
        if message is None:
            message = kw.get("message") or kw.get("key", "")
        if not message:
            return
        level = kw.get("level", "INFO")
        formatted = f"[{level}] {message}" if level else message
        self.log_view.appendPlainText(formatted)
        # 自动滚动到底部
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def append_terminal(self, text: str) -> None:
        """追加终端输出"""
        self.terminal_view.appendPlainText(text)
