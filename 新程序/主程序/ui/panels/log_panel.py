"""
UI 子面板：LogPanel 日志+终端双标签（§3.3）。

日志标签：结构化日志流（级别筛选 / 清除 / 导出）；
终端标签：只读显示 stdout/stderr。
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

# 日志级别顺序（供筛选）
_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class LogPanel(QWidget):
    """日志面板（日志+终端双标签）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # ── 日志工具栏（§3.3 级别筛选/清除/导出） ─────────
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("级别:"))
        self.level_combo = QComboBox()
        self.level_combo.addItem("全部", "")
        for lv in _LEVELS:
            self.level_combo.addItem(lv, lv)
        self.level_combo.setCurrentIndex(0)
        self.level_combo.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self.level_combo)

        btn_clear = QPushButton("🗑 清除")
        btn_clear.clicked.connect(self.clear_log)
        btn_export = QPushButton("💾 导出")
        btn_export.clicked.connect(self.export_log)
        toolbar.addWidget(btn_clear)
        toolbar.addWidget(btn_export)
        toolbar.addStretch()
        layout.addLayout(toolbar)

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

        # 原始日志缓存（(level, text)，供筛选/导出）
        self._log_cache: list[tuple[str, str]] = []

    # ── 日志追加 ─────────────────────────────────────────

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
        # 缓存原始记录（供筛选/导出）
        self._log_cache.append((str(level), str(message)))
        # 当前筛选级别：不匹配则不显示
        sel = self.level_combo.currentData() if hasattr(self, 'level_combo') else ""
        if sel and level != sel:
            return
        formatted = f"[{level}] {message}" if level else message
        self.log_view.appendPlainText(formatted)
        # 自动滚动到底部
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def append_terminal(self, text: str) -> None:
        """追加终端输出"""
        self.terminal_view.appendPlainText(text)

    # ── §3.3 级别筛选 / 清除 / 导出 ───────────────────────

    def _apply_filter(self) -> None:
        """按当前筛选级别重建日志视图"""
        sel = self.level_combo.currentData() if hasattr(self, 'level_combo') else ""
        self.log_view.clear()
        for level, text in self._log_cache:
            if sel and level != sel:
                continue
            self.log_view.appendPlainText(f"[{level}] {text}" if level else text)
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_log(self) -> None:
        """清除日志（视图 + 缓存）"""
        self.log_view.clear()
        self._log_cache.clear()

    def export_log(self) -> None:
        """导出日志到文本文件"""
        path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", "yys_log.txt", "文本文件 (*.txt);;所有文件 (*)")
        if not path:
            return
        lines = []
        for level, text in self._log_cache:
            lines.append(f"[{level}] {text}" if level else text)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "导出失败", str(e))
