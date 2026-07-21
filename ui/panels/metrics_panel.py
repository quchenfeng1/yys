"""
运行指标面板（12-日志监控中心 UI）

展示各任务的执行统计：次数/成功率/平均耗时/最后执行。
数据来源：Monitor.get_all_metrics()
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QPushButton,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor


class MetricsPanel(QWidget):
    """运行指标展示面板。"""

    def __init__(self, monitor, parent=None):
        super().__init__(parent)
        self._monitor = monitor
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._build()

    def _build(self):
        ly = QVBoxLayout(self)
        ly.setContentsMargins(16, 12, 16, 12)
        ly.setSpacing(10)

        # 标题行
        hdr = QHBoxLayout()
        title = QLabel("📊 运行指标")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        title.setStyleSheet("color:#1A1A2E;")
        hdr.addWidget(title)
        hdr.addStretch()

        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.clicked.connect(self._refresh)
        refresh_btn.setStyleSheet("""
            QPushButton{background:#E3F0FF;color:#1A73E8;border:none;
            border-radius:6px;padding:6px 16px;}
            QPushButton:hover{background:#1A73E8;color:white;}
        """)
        hdr.addWidget(refresh_btn)
        ly.addLayout(hdr)

        # 汇总统计
        self._summary = QLabel("加载中...")
        self._summary.setStyleSheet("color:#5F6368;font-size:13px;padding:4px 0;")
        ly.addWidget(self._summary)

        # 指标表格
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels([
            "任务名", "执行次数", "成功", "失败", "成功率", "平均耗时", "最后执行"
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("""
            QTableWidget{background:#FFFFFF;border:1px solid #E8ECF0;border-radius:8px;
            gridline-color:#F1F3F4;}
            QHeaderView::section{background:#F8F9FA;padding:6px;border:none;
            font-weight:bold;color:#5F6368;}
        """)
        ly.addWidget(self._table)

        self._refresh()
        self._timer.start(5000)  # 每 5 秒自动刷新

    def _refresh(self):
        metrics = self._monitor.get_all_metrics() if self._monitor else {}
        if not metrics:
            self._summary.setText("暂无运行数据")
            self._table.setRowCount(0)
            return

        total_runs = sum(m.get("total_runs", 0) for m in metrics.values())
        total_success = sum(m.get("success_runs", 0) for m in metrics.values())
        overall_rate = round(total_success / total_runs * 100, 1) if total_runs > 0 else 0
        self._summary.setText(
            f"总计 {len(metrics)} 个任务 | {total_runs} 次执行 | "
            f"整体成功率 {overall_rate}%"
        )

        self._table.setRowCount(len(metrics))
        for row, (name, m) in enumerate(sorted(metrics.items())):
            self._table.setItem(row, 0, QTableWidgetItem(name))
            self._table.setItem(row, 1, QTableWidgetItem(str(m.get("total_runs", 0))))
            
            succ = QTableWidgetItem(str(m.get("success_runs", 0)))
            succ.setForeground(QColor("#34A853"))
            self._table.setItem(row, 2, succ)
            
            fail = QTableWidgetItem(str(m.get("fail_runs", 0)))
            if m.get("fail_runs", 0) > 0:
                fail.setForeground(QColor("#EA4335"))
            self._table.setItem(row, 3, fail)

            rate = QTableWidgetItem(f"{m.get('success_rate', 0)}%")
            rate_val = m.get("success_rate", 0)
            if rate_val >= 90:
                rate.setForeground(QColor("#34A853"))
            elif rate_val >= 70:
                rate.setForeground(QColor("#F9AB00"))
            else:
                rate.setForeground(QColor("#EA4335"))
            self._table.setItem(row, 4, rate)

            avg = m.get("avg_duration", 0)
            self._table.setItem(row, 5, QTableWidgetItem(f"{avg:.1f}s" if avg else "—"))

            last = m.get("last_run_time", "")
            if last and len(last) > 16:
                last = last[11:19]  # 只显示 HH:MM:SS
            self._table.setItem(row, 6, QTableWidgetItem(last or "—"))
