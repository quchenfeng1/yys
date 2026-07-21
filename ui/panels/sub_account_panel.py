"""
小号配置面板（v3.2 — 小号配置管理）

点击「小号设置 → 小号配置」，显示所有小号列表及详细配置。
支持：增删改小号、模拟器配置、识别覆盖、组队角色、副本任务。

数据结构：accounts.yaml — sub_accounts 列表
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QSizePolicy,
    QFormLayout, QLineEdit, QComboBox, QSpinBox,
    QDoubleSpinBox, QCheckBox, QGroupBox, QMessageBox,
)

from core.config_manager import ConfigManager
import yaml
from pathlib import Path

BTN_ADD = """QPushButton{background:#1A73E8;color:white;font-weight:bold;border:none;border-radius:6px;padding:6px 16px;}QPushButton:hover{background:#1557B0;}"""
BTN_SAVE = """QPushButton{background:#34A853;color:white;font-weight:bold;border:none;border-radius:6px;padding:8px 20px;}QPushButton:hover{background:#2E7D32;}"""
BTN_DEL = """QPushButton{background:transparent;color:#EA4335;border:1px solid #EA4335;border-radius:4px;padding:4px 10px;}QPushButton:hover{background:#FDECEA;}"""


class SubAccountCard(QFrame):
    """单个小号的摘要卡片"""
    clicked = pyqtSignal(str)

    def __init__(self, account_data: dict, parent=None):
        super().__init__(parent)
        self.account_id = account_data.get("account_id", "")
        self.setObjectName("sub_card")
        self.setStyleSheet("QFrame#sub_card{background:#FFF;border:1px solid #E8ECF0;border-radius:8px;padding:8px;}QFrame#sub_card:hover{border-color:#1A73E8;}")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(50)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)

        enabled = account_data.get("enabled", False)
        icon = "O" if enabled else "X"
        info = QLabel(f"{icon} {account_data.get('nickname', self.account_id)} ({self.account_id})")
        info.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        layout.addWidget(info, stretch=1)

        server = QLabel(f"服务器: {account_data.get('server', '-')}")
        server.setStyleSheet("color: #80868B; font-size: 11px;")
        layout.addWidget(server)

        role = account_data.get("teaming", {}).get("role", "guest")
        role_lbl = QLabel(f"组队: {'发车' if role == 'host' else '乘客'}")
        role_lbl.setStyleSheet("color: #5F6368; font-size: 11px;")
        layout.addWidget(role_lbl)

    def mousePressEvent(self, ev):
        self.clicked.emit(self.account_id)


class SubAccountConfigPanel(QWidget):
    """小号配置面板：列表 + 详细配置表单"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = ConfigManager()
        self._accounts: list[dict] = []
        self._selected_id: str = ""
        self._cards: dict[str, SubAccountCard] = {}
        self._init_ui()
        self._load_accounts()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("小号配置")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        header.addWidget(title)
        header.addStretch()
        add_btn = QPushButton("+ 添加小号")
        add_btn.setStyleSheet(BTN_ADD)
        add_btn.clicked.connect(self._on_add)
        header.addWidget(add_btn)
        layout.addLayout(header)

        self._card_scroll = QScrollArea()
        self._card_scroll.setWidgetResizable(True)
        self._card_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self._card_container = QWidget()
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(4)
        self._card_layout.addStretch()
        self._card_scroll.setWidget(self._card_container)
        layout.addWidget(self._card_scroll, stretch=1)

        self._cfg_scroll = QScrollArea()
        self._cfg_scroll.setWidgetResizable(True)
        self._cfg_scroll.setStyleSheet("QScrollArea{border:1px solid #E8ECF0;border-radius:8px;background:#FAFBFC;}")
        self._cfg_form = QWidget()
        self._cfg_layout = QVBoxLayout(self._cfg_form)
        self._cfg_layout.setContentsMargins(14, 10, 14, 10)
        self._cfg_scroll.setWidget(self._cfg_form)
        self._cfg_placeholder = QLabel("  点击上方小号卡片查看/编辑配置")
        self._cfg_placeholder.setStyleSheet("color:#9CA3AF;font-size:13px;padding:20px;")
        self._cfg_layout.addWidget(self._cfg_placeholder)
        layout.addWidget(self._cfg_scroll, stretch=2)

    def _load_accounts(self):
        self._accounts = self._config.get("sub_accounts", []) or []
        if not isinstance(self._accounts, list):
            self._accounts = []
        self._rebuild_cards()

    def _rebuild_cards(self):
        while self._card_layout.count() > 1:
            w = self._card_layout.takeAt(0)
            if w and w.widget():
                w.widget().deleteLater()
        self._cards.clear()
        for acct in self._accounts:
            card = SubAccountCard(acct)
            card.clicked.connect(self._on_card_clicked)
            self._card_layout.insertWidget(self._card_layout.count() - 1, card)
            self._cards[acct.get("account_id", "")] = card

    def _on_card_clicked(self, account_id: str):
        self._selected_id = account_id
        self._show_detail(account_id)

    def _show_detail(self, account_id: str):
        acct = next((a for a in self._accounts if a.get("account_id") == account_id), None)
        if not acct:
            return
        while self._cfg_layout.count():
            w = self._cfg_layout.takeAt(0)
            if w and w.widget():
                w.widget().deleteLater()

        emu = acct.get("emulator", {})
        rec = acct.get("recognize", {})
        team = acct.get("teaming", {})

        g1 = QGroupBox("模拟器配置")
        f1 = QFormLayout(g1)
        emu_type = QComboBox(); emu_type.addItems(["mumu", "ldplayer", "nox"])
        emu_type.setCurrentText(emu.get("type", "mumu"))
        f1.addRow("类型:", emu_type)
        emu_port = QSpinBox(); emu_port.setRange(1024, 65535); emu_port.setValue(emu.get("adb_port", 16416))
        f1.addRow("ADB端口:", emu_port)
        emu_path = QLineEdit(); emu_path.setText(emu.get("custom_path", "")); emu_path.setPlaceholderText("留空=自动")
        f1.addRow("路径:", emu_path)
        self._cfg_layout.addWidget(g1)

        g2 = QGroupBox("游戏配置")
        f2 = QFormLayout(g2)
        nick = QLineEdit(); nick.setText(acct.get("nickname", ""))
        f2.addRow("昵称:", nick)
        server = QLineEdit(); server.setText(acct.get("server", ""))
        f2.addRow("服务器:", server)
        enabled_cb = QCheckBox("启用此小号"); enabled_cb.setChecked(acct.get("enabled", False))
        f2.addRow("", enabled_cb)
        self._cfg_layout.addWidget(g2)

        g3 = QGroupBox("识别配置（覆盖全局）")
        f3 = QFormLayout(g3)
        rec_th = QDoubleSpinBox(); rec_th.setRange(0.5, 1.0); rec_th.setSingleStep(0.05)
        rec_th.setValue(rec.get("threshold", 0.80))
        f3.addRow("阈值:", rec_th)
        rec_gray = QCheckBox("灰度匹配"); rec_gray.setChecked(rec.get("grayscale", True))
        f3.addRow("", rec_gray)
        self._cfg_layout.addWidget(g3)

        g4 = QGroupBox("组队配置")
        f4 = QFormLayout(g4)
        team_role = QComboBox(); team_role.addItems(["guest", "host"])
        team_role.setCurrentText(team.get("role", "guest"))
        f4.addRow("角色 (host=发车, guest=乘客):", team_role)
        self._cfg_layout.addWidget(g4)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.setStyleSheet(BTN_SAVE)
        save_btn.clicked.connect(lambda: self._on_save(account_id,
            emu_type.currentText(), emu_port.value(), emu_path.text(),
            nick.text(), server.text(), enabled_cb.isChecked(),
            rec_th.value(), rec_gray.isChecked(), team_role.currentText()))
        btn_row.addWidget(save_btn)
        del_btn = QPushButton("删除")
        del_btn.setStyleSheet(BTN_DEL)
        del_btn.clicked.connect(lambda: self._on_delete(account_id))
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        self._cfg_layout.addLayout(btn_row)
        self._cfg_layout.addStretch()

    def _on_save(self, account_id, emu_type, emu_port, emu_path,
                 nick, server, enabled, rec_th, rec_gray, team_role):
        acct = next((a for a in self._accounts if a.get("account_id") == account_id), None)
        if not acct:
            return
        acct["nickname"] = nick
        acct["server"] = server
        acct["enabled"] = enabled
        acct["emulator"] = {"type": emu_type, "adb_port": emu_port,
                            "device_id": f"127.0.0.1:{emu_port}", "custom_path": emu_path}
        acct["recognize"] = {"threshold": rec_th, "grayscale": rec_gray}
        if "teaming" not in acct:
            acct["teaming"] = {}
        acct["teaming"]["role"] = team_role
        self._save_to_file()
        self._rebuild_cards()
        QMessageBox.information(self, "已保存", f"小号 {nick} 配置已保存")

    def _on_add(self):
        existing = {a.get("account_id", "") for a in self._accounts}
        i = 1
        while f"sub{i}" in existing:
            i += 1
        new_id = f"sub{i}"
        new_acct = {
            "account_id": new_id, "role": "sub", "nickname": f"小号{i}",
            "server": "", "enabled": False,
            "emulator": {"type": "mumu", "adb_port": 16384 + i * 32,
                         "device_id": f"127.0.0.1:{16384 + i * 32}", "custom_path": ""},
            "recognize": {"threshold": 0.80, "grayscale": True},
            "teaming": {"role": "guest"},
            "dungeon_tasks": [],
        }
        self._accounts.append(new_acct)
        self._save_to_file()
        self._rebuild_cards()
        self._on_card_clicked(new_id)

    def _on_delete(self, account_id):
        reply = QMessageBox.question(self, "确认删除",
            f"确定要删除小号 {account_id} 吗？", QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._accounts = [a for a in self._accounts if a.get("account_id") != account_id]
        self._save_to_file()
        self._selected_id = ""
        self._rebuild_cards()
        while self._cfg_layout.count():
            w = self._cfg_layout.takeAt(0)
            if w and w.widget():
                w.widget().deleteLater()
        self._cfg_layout.addWidget(self._cfg_placeholder)

    def _save_to_file(self):
        cfg_path = Path(__file__).parent.parent.parent / "config" / "accounts.yaml"
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        data["sub_accounts"] = self._accounts
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        self._config.reload()
