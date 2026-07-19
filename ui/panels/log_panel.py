"""
内置终端 + 日志面板（11-UI模块 右侧面板）

右侧面板采用 QTabWidget 双标签布局：
  - 「日志」标签：结构化日志流，支持级别/模块筛选，清除/导出
  - 「终端」标签：内置只读终端，捕获 Python stdout/stderr 输出，
    替代外部 PowerShell 黑窗口，所有 print/异常信息在此展示

设计要点：
  - 终端只读不可编辑，用户无法输入命令
  - stdout/stderr 通过 OutputRedirector 实时重定向
  - 终端输出带 ANSI 颜色标记：[INFO]=绿 [WARNING]=黄 [ERROR]=红
  - 日志和终端共用事件总线的 log_record 事件
"""

import sys
from datetime import datetime

from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor, QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPlainTextEdit, QComboBox, QPushButton, QLabel,
    QFileDialog, QSizePolicy,
)

from core.event_bus import event_bus, Events


# ==================== 1. stdout/stderr 重定向器 ====================

class OutputRedirector(QObject):
    """捕获 Python stdout/stderr，通过信号发送到终端面板。

    替代外部 PowerShell 黑窗口。所有 print()、异常 traceback
    都会被捕获并实时显示在内置终端中。
    """

    output_received = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # pythonw.exe 下 sys.stdout/stderr 可能为 None
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr

    def write(self, text: str):
        """被 sys.stdout/stderr.write() 调用的入口。"""
        if text and text.strip():
            self.output_received.emit(text)
        # 写回原始 stdout（如果存在）
        if self._original_stdout is not None:
            self._original_stdout.write(text)

    def flush(self):
        if self._original_stdout is not None:
            self._original_stdout.flush()

    def install(self):
        """安装重定向——替换 sys.stdout 和 sys.stderr。"""
        sys.stdout = self
        sys.stderr = self

    def uninstall(self):
        """卸载重定向——恢复原始 stdout/stderr。"""
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr


# ==================== 2. 内置终端面板（只读） ====================

class TerminalWidget(QWidget):
    """内置只读终端。捕获 stdout/stderr 并实时显示。

    替代外部命令行黑窗口。用户不可编辑，不可输入命令。
    输出根据级别自动着色。
    """

    # 日志级别对应的颜色
    LEVEL_COLORS = {
        "DEBUG": QColor("#888888"),      # 灰
        "INFO": QColor("#4CAF50"),       # 绿
        "WARNING": QColor("#FF9800"),    # 橙
        "ERROR": QColor("#F44336"),      # 红
        "CRITICAL": QColor("#9C27B0"),   # 紫
        "STEP": QColor("#2196F3"),       # 蓝
        "BATTLE": QColor("#00BCD4"),     # 青
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._redirector: OutputRedirector = None
        self._max_lines = 10000  # 最多保留行数
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # 顶部信息栏
        info_bar = QHBoxLayout()
        self._status_label = QLabel("终端就绪 — 实时输出（只读）")
        self._status_label.setStyleSheet("color: #888; font-size: 11px;")
        info_bar.addWidget(self._status_label)
        info_bar.addStretch()
        self._clear_btn = QPushButton("清屏")
        self._clear_btn.setFixedSize(50, 22)
        self._clear_btn.clicked.connect(self._clear)
        info_bar.addWidget(self._clear_btn)
        layout.addLayout(info_bar)

        # 终端文本区（只读）
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setUndoRedoEnabled(False)
        self._text.setFont(QFont("Consolas", 10))
        self._text.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1E1E1E;
                color: #D4D4D4;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        self._text.setMaximumBlockCount(self._max_lines)
        layout.addWidget(self._text)

    def install_redirector(self):
        """安装 stdout/stderr 重定向器。"""
        self._redirector = OutputRedirector()
        self._redirector.output_received.connect(self._append_terminal)
        self._redirector.install()
        self._append_terminal("[系统] 终端重定向已安装 — 替代外部命令行窗口\n")

    def uninstall_redirector(self):
        """卸载重定向器（程序退出时调用）。"""
        if self._redirector:
            self._redirector.uninstall()

    def _append_terminal(self, text: str):
        """追加文本到终端，自动着色。"""
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.End)

        fmt = QTextCharFormat()
        text_upper = text.upper()

        # 根据内容自动着色
        for level, color in self.LEVEL_COLORS.items():
            if f"[{level}" in text_upper or f" {level} " in text_upper:
                fmt.setForeground(color)
                break
        else:
            fmt.setForeground(QColor("#D4D4D4"))  # 默认白

        cursor.insertText(text, fmt)
        self._text.setTextCursor(cursor)
        self._text.ensureCursorVisible()

    def _clear(self):
        self._text.clear()
        self._append_terminal("[系统] 屏幕已清除\n")

    def append_message(self, level: str, message: str, timestamp: str = ""):
        """程序方式追加一条消息（供外部调用）。"""
        time_str = timestamp or datetime.now().strftime("%H:%M:%S")
        self._append_terminal(f"[{time_str}] [{level}] {message}\n")


# ==================== 3. 日志面板（结构化日志流） ====================

class LogStreamWidget(QWidget):
    """结构化日志流。订阅事件总线，实时追加日志条目。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._max_lines = 10000
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # 筛选栏
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("级别:"))
        self._level_filter = QComboBox()
        self._level_filter.addItems(["全部", "INFO", "WARNING", "ERROR", "DEBUG"])
        filter_bar.addWidget(self._level_filter)

        filter_bar.addWidget(QLabel("模块:"))
        self._module_filter = QComboBox()
        self._module_filter.addItems(["全部"])
        filter_bar.addWidget(self._module_filter)
        filter_bar.addStretch()

        self._clear_btn = QPushButton("清除")
        self._clear_btn.setFixedSize(50, 22)
        self._clear_btn.clicked.connect(self._clear)
        filter_bar.addWidget(self._clear_btn)

        self._export_btn = QPushButton("导出")
        self._export_btn.setFixedSize(50, 22)
        self._export_btn.clicked.connect(self._on_export)
        filter_bar.addWidget(self._export_btn)
        layout.addLayout(filter_bar)

        # 日志文本区
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setUndoRedoEnabled(False)
        self._text.setFont(QFont("Consolas", 9))
        self._text.setStyleSheet("""
            QPlainTextEdit {
                background-color: #FAFAFA;
                color: #333;
                border: 1px solid #CCC;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        self._text.setMaximumBlockCount(self._max_lines)
        layout.addWidget(self._text)

    def start(self):
        """订阅日志事件。"""
        event_bus.subscribe(Events.LOG_RECORD, self._on_log)

    def _on_log(self, **kwargs):
        """接收日志事件，追加到文本框。"""
        level = kwargs.get("level", "INFO")
        message = kwargs.get("message", "")
        timestamp = kwargs.get("timestamp", "")
        module = kwargs.get("module", "")
        task = kwargs.get("task", "")
        step = kwargs.get("step", "")

        # 级别筛选
        filter_level = self._level_filter.currentText()
        if filter_level != "全部" and level != filter_level:
            return

        # 格式化
        prefix = f"[{module}]" if module else ""
        task_info = f"[{task}/{step}]" if task else ""
        time_str = timestamp[:19].replace("T", " ") if timestamp else datetime.now().strftime("%H:%M:%S")
        line = f"[{time_str}] [{level}] {prefix}{task_info} {message}"

        self._text.appendPlainText(line)

    def _clear(self):
        self._text.clear()

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", f"logs_export_{datetime.now():%Y%m%d_%H%M%S}.txt",
            "文本文件 (*.txt);;所有文件 (*)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._text.toPlainText())


# ==================== 4. 日志+终端 组合面板 ====================

class LogPanel(QWidget):
    """右侧组合面板：日志 + 内置终端。

    采用 QTabWidget 双标签布局：
      [ 日志 ] [ 终端 ]
    ┌─────────────────────┐
    │                     │
    │   根据标签切换内容    │
    │                     │
    └─────────────────────┘

    日志标签：结构化日志流（级别筛选 + 模块筛选 + 清除 + 导出）
    终端标签：只读内置终端（捕获 stdout/stderr，替代外部黑窗口）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._terminal = None  # type: TerminalWidget
        self._log_stream = None  # type: LogStreamWidget
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #CCC;
                border-radius: 4px;
            }
            QTabBar::tab {
                padding: 6px 16px;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                font-weight: bold;
                border-bottom: 2px solid #2196F3;
            }
        """)

        # 日志标签
        self._log_stream = LogStreamWidget()
        self._tabs.addTab(self._log_stream, "📋 日志")

        # 终端标签
        self._terminal = TerminalWidget()
        self._tabs.addTab(self._terminal, "🖥 终端")

        layout.addWidget(self._tabs)

    def start(self):
        """启动：订阅日志事件 + 安装终端重定向。"""
        self._log_stream.start()
        self._terminal.install_redirector()

    def shutdown(self):
        """关闭：卸载终端重定向。"""
        self._terminal.uninstall_redirector()

    @property
    def terminal(self) -> TerminalWidget:
        return self._terminal

    @property
    def log_stream(self) -> LogStreamWidget:
        return self._log_stream

    def switch_to_terminal(self):
        """切换到终端标签。"""
        self._tabs.setCurrentIndex(1)

    def switch_to_log(self):
        """切换到日志标签。"""
        self._tabs.setCurrentIndex(0)
