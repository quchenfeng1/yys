"""
异常截图查看器（12-日志监控中心 UI）

浏览 logs/snapshots/ 目录下的异常截图和上下文。
"""

import os
from pathlib import Path
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QSplitter, QTextEdit,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QPixmap

PROJECT_ROOT = Path(__file__).parent.parent.parent  # d:\yys


class SnapshotViewer(QWidget):
    """异常截图查看器。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._snapshot_dir = PROJECT_ROOT / "logs" / "snapshots"
        self._build()
        self._load_list()

    def _build(self):
        ly = QHBoxLayout(self)
        ly.setContentsMargins(16, 12, 16, 12)
        ly.setSpacing(12)

        # 左侧：截图列表
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)

        title = QLabel("📸 异常截图")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        title.setStyleSheet("color:#1A1A2E;")
        ll.addWidget(title)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_select)
        self._list.setStyleSheet("""
            QListWidget{background:#FFFFFF;border:1px solid #E8ECF0;border-radius:8px;}
            QListWidget::item{padding:8px;border-bottom:1px solid #F1F3F4;}
            QListWidget::item:selected{background:#E3F0FF;color:#1A73E8;}
            QListWidget::item:hover{background:#F8F9FA;}
        """)
        ll.addWidget(self._list)

        refresh_btn = QPushButton("🔄 刷新列表")
        refresh_btn.clicked.connect(self._load_list)
        refresh_btn.setStyleSheet("""
            QPushButton{background:#E3F0FF;color:#1A73E8;border:none;
            border-radius:6px;padding:6px 16px;}
            QPushButton:hover{background:#1A73E8;color:white;}
        """)
        ll.addWidget(refresh_btn)

        ly.addWidget(left, stretch=1)

        # 右侧：预览 + 上下文
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        self._img_label = QLabel("选择截图查看")
        self._img_label.setAlignment(Qt.AlignCenter)
        self._img_label.setMinimumHeight(300)
        self._img_label.setStyleSheet(
            "background:#F8F9FA;border:1px solid #E8ECF0;border-radius:8px;"
            "color:#BDC1C6;font-size:14px;"
        )
        rl.addWidget(self._img_label, stretch=2)

        ctx_label = QLabel("上下文信息")
        ctx_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        ctx_label.setStyleSheet("color:#5F6368;")
        rl.addWidget(ctx_label)

        self._ctx_text = QTextEdit()
        self._ctx_text.setReadOnly(True)
        self._ctx_text.setMaximumHeight(200)
        self._ctx_text.setStyleSheet(
            "background:#FFFFFF;border:1px solid #E8ECF0;border-radius:8px;"
            "font-family:Consolas;font-size:12px;"
        )
        rl.addWidget(self._ctx_text)

        ly.addWidget(right, stretch=2)

    def _load_list(self):
        self._list.clear()
        if not self._snapshot_dir.exists():
            self._list.addItem("（暂无截图）")
            return

        # 收集所有截图文件夹
        items = []
        for date_dir in sorted(self._snapshot_dir.iterdir(), reverse=True):
            if date_dir.is_dir():
                for png in sorted(date_dir.glob("*.png"), reverse=True):
                    ctx_file = date_dir / f"{png.stem}.json"
                    items.append((png, ctx_file, date_dir.name))

        if not items:
            self._list.addItem("（暂无截图）")
            return

        for png, ctx_file, date_str in items:
            ts = png.stem.split("_")[-1] if "_" in png.stem else ""
            label = f"{date_str}  {ts[:8] if len(ts)>=8 else ts}  {png.stem[:40]}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, {"png": str(png), "ctx": str(ctx_file)})
            self._list.addItem(item)

    def _on_select(self, row: int):
        if row < 0:
            return
        item = self._list.item(row)
        data = item.data(Qt.UserRole)
        if not data:
            return

        # 显示截图
        png_path = data["png"]
        if os.path.exists(png_path):
            pix = QPixmap(png_path)
            if not pix.isNull():
                scaled = pix.scaledToWidth(
                    self._img_label.width() - 20,
                    mode=Qt.SmoothTransformation,
                )
                self._img_label.setPixmap(scaled)
                self._img_label.setStyleSheet("")
            else:
                self._img_label.setText("无法加载图片")
        else:
            self._img_label.setText("文件不存在")

        # 显示上下文
        ctx_path = data["ctx"]
        if os.path.exists(ctx_path):
            try:
                import json
                with open(ctx_path, "r", encoding="utf-8") as f:
                    ctx = json.load(f)
                self._ctx_text.setPlainText(json.dumps(ctx, ensure_ascii=False, indent=2))
            except Exception:
                self._ctx_text.setPlainText("（无法读取上下文）")
        else:
            self._ctx_text.setPlainText("（无上下文文件）")
