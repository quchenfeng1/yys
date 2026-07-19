"""
图片配置面板（v2.3 新增 — 可视化图片管理）

左侧：分区列表（主界面/探索/召唤/商城/战斗/阴阳寮/活动/通用/阵容）
右侧：图片列表（缩略图+名称+备注+尺寸），支持添加/删除/编辑备注/预览

从菜单树点击「图片配置」→ 二级菜单选分区 → 中间面板显示图片列表。
"""

from pathlib import Path

from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QFont, QPixmap, QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QFileDialog, QSizePolicy,
    QMessageBox, QDialog, QFormLayout, QLineEdit, QComboBox,
    QScrollArea,
)

from core.image_manager import ImageManager, SCENE_SECTIONS, SECTION_DIRS

# ==================== 样式 ====================

PANEL_STYLE = """
    QListWidget {
        background: #FFFFFF; border: 1px solid #E8ECF0;
        border-radius: 8px; padding: 4px;
    }
    QListWidget::item {
        padding: 8px; border-bottom: 1px solid #F0F0F0;
        border-radius: 4px;
    }
    QListWidget::item:hover { background: #F5F8FF; }
    QListWidget::item:selected { background: #E3F0FF; color: #1A73E8; }
"""

BTN_ADD = """
    QPushButton {
        background: #1A73E8; color: white; font-weight: bold;
        border: none; border-radius: 6px; padding: 6px 16px;
    }
    QPushButton:hover { background: #1557B0; }
"""

BTN_DEL = """
    QPushButton {
        background: #EA4335; color: white; font-weight: bold;
        border: none; border-radius: 6px; padding: 6px 16px;
    }
    QPushButton:hover { background: #C5221F; }
"""

BTN_EDIT = """
    QPushButton {
        background: #F9AB00; color: white; font-weight: bold;
        border: none; border-radius: 6px; padding: 6px 16px;
    }
    QPushButton:hover { background: #E8A000; }
"""


# ==================== 备注编辑对话框 ====================

class NoteEditDialog(QDialog):
    """编辑图片备注和分区。"""

    def __init__(self, current_note: str, current_section: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑图片信息")
        self.setMinimumWidth(400)
        layout = QFormLayout(self)
        self._note_edit = QLineEdit(current_note)
        self._note_edit.setPlaceholderText("输入图片用途说明...")
        layout.addRow("备注:", self._note_edit)
        self._section_combo = QComboBox()
        for s in SECTION_DIRS:
            self._section_combo.addItem(f"{SCENE_SECTIONS[s]['icon']} {s}", s)
        idx = self._section_combo.findData(current_section)
        if idx >= 0:
            self._section_combo.setCurrentIndex(idx)
        layout.addRow("移动到:", self._section_combo)
        btns = QHBoxLayout()
        ok = QPushButton("保存"); ok.clicked.connect(self.accept)
        cancel = QPushButton("取消"); cancel.clicked.connect(self.reject)
        btns.addStretch(); btns.addWidget(ok); btns.addWidget(cancel)
        layout.addRow(btns)

    def get_result(self) -> tuple:
        return self._note_edit.text(), self._section_combo.currentData()


# ==================== 预览对话框 ====================

class PreviewDialog(QDialog):
    """图片真实尺寸预览。"""

    def __init__(self, image_path: str, title: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"预览: {title}")
        layout = QVBoxLayout(self)
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            lbl = QLabel()
            lbl.setPixmap(pixmap)
            lbl.setAlignment(Qt.AlignCenter)
            scroll = QScrollArea()
            scroll.setWidget(lbl)
            scroll.setWidgetResizable(False)
            layout.addWidget(scroll)
            self.resize(min(pixmap.width() + 40, 1000), min(pixmap.height() + 60, 800))
        else:
            layout.addWidget(QLabel("无法加载图片"))


# ==================== 图片列表面板 ====================

class ImageListPanel(QWidget):
    """某个分区的图片列表。"""

    image_added = pyqtSignal()
    image_deleted = pyqtSignal()

    def __init__(self, image_mgr: ImageManager, parent=None):
        super().__init__(parent)
        self._mgr = image_mgr
        self._current_section = "主界面"
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        # 顶部信息栏
        top = QHBoxLayout()
        self._title_label = QLabel()
        self._title_label.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        top.addWidget(self._title_label)
        top.addStretch()

        self._count_label = QLabel()
        self._count_label.setStyleSheet("color: #80868B; font-size: 12px;")
        top.addWidget(self._count_label)
        layout.addLayout(top)

        # 操作按钮行
        btn_row = QHBoxLayout()
        self._add_btn = QPushButton("＋ 添加图片")
        self._add_btn.setStyleSheet(BTN_ADD)
        self._add_btn.clicked.connect(self._on_add)
        btn_row.addWidget(self._add_btn)

        self._edit_btn = QPushButton("✎ 编辑备注")
        self._edit_btn.setStyleSheet(BTN_EDIT)
        self._edit_btn.clicked.connect(self._on_edit)
        btn_row.addWidget(self._edit_btn)

        self._preview_btn = QPushButton("🔍 预览")
        self._preview_btn.setStyleSheet("""
            QPushButton { background: #34A853; color: white; font-weight: bold;
            border: none; border-radius: 6px; padding: 6px 16px; }
            QPushButton:hover { background: #2E7D32; }
        """)
        self._preview_btn.clicked.connect(self._on_preview)
        btn_row.addWidget(self._preview_btn)

        self._delete_btn = QPushButton("✕ 删除")
        self._delete_btn.setStyleSheet(BTN_DEL)
        self._delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._delete_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 图片列表
        self._list = QListWidget()
        self._list.setStyleSheet(PANEL_STYLE)
        self._list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._list.setMinimumHeight(100)
        self._list.setIconSize(QSize(48, 48))
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.itemDoubleClicked.connect(self._on_preview)
        layout.addWidget(self._list, stretch=1)

        # 底部提示
        hint = QLabel("提示：双击图片预览 | 选中后点「编辑备注」修改说明 | 点「删除」移除图片")
        hint.setStyleSheet("color: #9CA3AF; font-size: 11px; padding: 4px;")
        layout.addWidget(hint)

    def show_section(self, section: str):
        """切换到指定分区。"""
        self._current_section = section
        info = SCENE_SECTIONS.get(section, {})
        self._title_label.setText(f"{info.get('icon', '')} {section}")
        self._refresh_list()

    def _refresh_list(self):
        """刷新图片列表。"""
        try:
            self._list.clear()
        except Exception:
            pass  # 列表清空失败不阻塞
        try:
            images = self._mgr.get_images(self._current_section)
        except Exception:
            images = []
        self._count_label.setText(f"共 {len(images)} 张")

        if not images:
            empty = QListWidgetItem("（此分区暂无图片，点击「＋ 添加图片」导入）")
            empty.setFlags(empty.flags() & ~Qt.ItemIsSelectable)
            empty.setForeground(QColor("#BDC1C6"))
            self._list.addItem(empty)
            return

        for entry in images:
            text = f"{entry.name}"
            if entry.note:
                text += f"  —  {entry.note}"
            if entry.size != (0, 0):
                text += f"  [{entry.size[0]}×{entry.size[1]}]"

            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, entry.name)

            # 尝试加载缩略图
            try:
                path = entry.filepath or str(Path(self._mgr._assets_dir) / entry.section / entry.name)
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    item.setIcon(pixmap.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            except Exception:
                pass

            self._list.addItem(item)

    def _on_add(self):
        """添加图片。"""
        try:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "选择图片", "", "PNG 图片 (*.png);;所有文件 (*)"
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开文件对话框失败: {e}")
            return
        if not paths:
            return

        for p in paths:
            try:
                name = Path(p).name
                entry = self._mgr.add_image(p, self._current_section, note="")
                if entry:
                    self._refresh_list()
                else:
                    QMessageBox.warning(self, "导入失败", f"无法导入 {name}")
            except Exception as e:
                QMessageBox.critical(self, "导入失败", f"导入 {Path(p).name} 时出错:\n{e}")

    def _on_edit(self):
        """编辑选中图片的备注。"""
        try:
            item = self._list.currentItem()
            if not item or not item.data(Qt.UserRole):
                return
            filename = item.data(Qt.UserRole)
            entry = self._mgr.find(filename)
            if not entry:
                return
            dlg = NoteEditDialog(entry.note, entry.section, self)
            if dlg.exec_() == QDialog.Accepted:
                new_note, new_section = dlg.get_result()
                if new_section != entry.section:
                    src = Path(self._mgr._assets_dir) / entry.section / filename
                    dst = Path(self._mgr._assets_dir) / new_section / filename
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if src.exists():
                        src.rename(dst)
                        entry.filepath = str(dst)
                        entry.section = new_section
                self._mgr.update_note(filename, new_note)
                self._refresh_list()
        except Exception as e:
            QMessageBox.critical(self, "编辑失败", f"操作出错:\n{e}")

    def _on_preview(self):
        """预览选中图片（真实尺寸）。"""
        try:
            item = self._list.currentItem()
            if not item or not item.data(Qt.UserRole):
                return
            filename = item.data(Qt.UserRole)
            path = self._mgr.get_image_path(filename, self._current_section)
            if path:
                PreviewDialog(path, filename, self).exec_()
        except Exception as e:
            QMessageBox.critical(self, "预览失败", f"无法预览:\n{e}")

    def _on_delete(self):
        """删除选中图片。"""
        try:
            item = self._list.currentItem()
            if not item or not item.data(Qt.UserRole):
                return
            filename = item.data(Qt.UserRole)
            reply = QMessageBox.question(self, "确认删除", f"确定要删除 {filename} 吗？",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self._mgr.delete_image(filename)
                self._refresh_list()
        except Exception as e:
            QMessageBox.critical(self, "删除失败", f"操作出错:\n{e}")


# ==================== 主面板（v2.5 简化：分区由菜单树管理）====================

class ImageManagerPanel(QWidget):
    """图片配置面板。分区由左侧菜单树切换，中间只显示图片列表。"""

    def __init__(self, image_mgr: ImageManager, parent=None):
        super().__init__(parent)
        self._mgr = image_mgr
        self._image_list = ImageListPanel(self._mgr)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._image_list)

    def show_section(self, section: str):
        """切换到指定分区。"""
        self._image_list.show_section(section)

    def refresh(self):
        self._image_list._refresh_list()
