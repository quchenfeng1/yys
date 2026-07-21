"""
运行报告查看器（12-日志监控中心 UI）

展示 Monitor 生成的每日/每周运行报告（Markdown 渲染）。
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel, QComboBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont


class ReportViewer(QWidget):
    """运行报告查看器。"""

    def __init__(self, monitor, parent=None):
        super().__init__(parent)
        self._monitor = monitor
        self._build()

    def _build(self):
        ly = QVBoxLayout(self)
        ly.setContentsMargins(16, 12, 16, 12)
        ly.setSpacing(10)

        # 标题行
        hdr = QHBoxLayout()
        title = QLabel("📄 运行报告")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        title.setStyleSheet("color:#1A1A2E;")
        hdr.addWidget(title)
        hdr.addStretch()

        self._type_combo = QComboBox()
        self._type_combo.addItems(["日报", "周报"])
        hdr.addWidget(QLabel("类型:"))
        hdr.addWidget(self._type_combo)

        gen_btn = QPushButton("生成报告")
        gen_btn.clicked.connect(self._generate)
        gen_btn.setStyleSheet("""
            QPushButton{background:#E3F0FF;color:#1A73E8;border:none;
            border-radius:6px;padding:6px 16px;}
            QPushButton:hover{background:#1A73E8;color:white;}
        """)
        hdr.addWidget(gen_btn)

        export_btn = QPushButton("导出")
        export_btn.clicked.connect(self._export)
        export_btn.setStyleSheet("""
            QPushButton{background:#F1F3F4;color:#5F6368;border:1px solid #DADCE0;
            border-radius:6px;padding:6px 16px;}
            QPushButton:hover{background:#E8ECF0;}
        """)
        hdr.addWidget(export_btn)
        ly.addLayout(hdr)

        # 报告内容区
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setStyleSheet("""
            QTextEdit{background:#FFFFFF;border:1px solid #E8ECF0;border-radius:8px;
            font-family:Microsoft YaHei;font-size:13px;padding:12px;}
        """)
        self._text.setPlaceholderText("点击「生成报告」查看运行总结")
        ly.addWidget(self._text)

        self._last_report = ""

    def _generate(self):
        report_type = self._type_combo.currentText()
        try:
            if report_type == "日报":
                report = self._monitor.generate_daily_report()
            else:
                report = self._monitor.generate_weekly_report()
            self._last_report = report
            self._text.setMarkdown(report if report else "暂无数据生成报告")
        except Exception as e:
            self._text.setPlainText(f"生成报告失败: {e}")

    def _export(self):
        if not self._last_report:
            return
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "导出报告", "运行报告.md", "Markdown (*.md)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._last_report)
