"""
阵容编辑器（11-用户界面模块）

可视化编辑阵容预设：名称 / 式神列表 / 御魂配置。
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QPushButton, QScrollArea, QFrame,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont


class TeamEditor(QWidget):
    """阵容预设编辑器。"""

    team_changed = pyqtSignal(str, dict)  # team_id, team_data

    def __init__(self, team_data: dict = None, parent=None):
        super().__init__(parent)
        self._data = team_data or {"id": "", "name": "新阵容", "members": []}
        self._build()
        self._load()

    def _build(self):
        ly = QVBoxLayout(self)
        ly.setContentsMargins(0, 0, 0, 0)
        ly.setSpacing(8)

        # 阵容名称
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("阵容名:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("输入阵容名称...")
        self._name_edit.textChanged.connect(self._on_name_changed)
        name_row.addWidget(self._name_edit)
        ly.addLayout(name_row)

        # 成员列表
        members_label = QLabel("式神成员（最多 6 人）")
        members_label.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        members_label.setStyleSheet("color:#5F6368;")
        ly.addWidget(members_label)

        self._members_area = QScrollArea()
        self._members_area.setWidgetResizable(True)
        self._members_area.setMaximumHeight(200)
        self._members_area.setStyleSheet("QScrollArea{border:1px solid #E8ECF0;border-radius:6px;}")
        self._members_widget = QWidget()
        self._members_layout = QVBoxLayout(self._members_widget)
        self._members_layout.setContentsMargins(4, 4, 4, 4)
        self._members_layout.setSpacing(4)
        self._members_area.setWidget(self._members_widget)
        ly.addWidget(self._members_area)

        # 添加成员按钮
        add_btn = QPushButton("+ 添加式神")
        add_btn.setStyleSheet("""
            QPushButton{background:#E3F0FF;color:#1A73E8;border:none;
            border-radius:6px;padding:6px 12px;font-size:12px;}
            QPushButton:hover{background:#1A73E8;color:white;}
        """)
        add_btn.clicked.connect(self._add_member)
        ly.addWidget(add_btn)

    def _load(self):
        self._name_edit.setText(self._data.get("name", ""))
        # 重建成员行
        for m in self._data.get("members", []):
            self._add_member_row(m.get("name", ""), m.get("soul", ""))

    def _add_member(self):
        self._add_member_row("", "")
        self._emit_change()

    def _add_member_row(self, name: str = "", soul: str = ""):
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 2, 0, 2)
        rl.setSpacing(6)

        name_edit = QLineEdit(name)
        name_edit.setPlaceholderText("式神名")
        name_edit.setFixedWidth(100)
        name_edit.textChanged.connect(self._emit_change)
        rl.addWidget(name_edit)

        soul_combo = QComboBox()
        soul_combo.addItems(["", "破势", "针女", "招财", "地藏", "镜姬", "火灵", "蚌精", "薙魂", "魅妖"])
        if soul:
            idx = soul_combo.findText(soul)
            if idx >= 0:
                soul_combo.setCurrentIndex(idx)
        soul_combo.currentTextChanged.connect(self._emit_change)
        rl.addWidget(soul_combo)

        rl.addStretch()

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(24, 24)
        del_btn.setStyleSheet("""
            QPushButton{background:transparent;color:#EA4335;border:none;
            border-radius:12px;font-size:12px;}
            QPushButton:hover{background:#FCE8E6;}
        """)
        del_btn.clicked.connect(lambda: self._remove_row(row))
        rl.addWidget(del_btn)

        self._members_layout.addWidget(row)

    def _remove_row(self, row: QWidget):
        self._members_layout.removeWidget(row)
        row.deleteLater()
        self._emit_change()

    def _on_name_changed(self, text: str):
        self._data["name"] = text
        self._emit_change()

    def _emit_change(self):
        members = []
        for i in range(self._members_layout.count()):
            w = self._members_layout.itemAt(i).widget()
            if w:
                edits = w.findChildren(QLineEdit)
                combos = w.findChildren(QComboBox)
                if edits and combos:
                    members.append({
                        "name": edits[0].text(),
                        "soul": combos[0].currentText(),
                    })
        self._data["members"] = members
        self._data["name"] = self._name_edit.text()
        self.team_changed.emit(self._data.get("id", ""), dict(self._data))

    def get_team(self) -> dict:
        return dict(self._data)
