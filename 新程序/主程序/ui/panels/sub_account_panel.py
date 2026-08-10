"""
UI 子面板：SubAccountPanel 小号管理。

功能：
- 展示全部账号配置（账号ID/显示名/角色/设备ID/区服/状态/启用）
- 「➕ 添加小号」：弹窗填写小号信息 → 持久化到 accounts.yaml → 刷新
- 「🔄 刷新」：从 AccountBridge 重新读取账号列表
- 兼容旧版 update_accounts（sub_account_status 状态事件，仅更新状态列）
"""
from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

# 表格列定义
_COLUMNS = ["账号ID", "显示名", "角色", "设备ID", "区服", "状态", "启用"]
_COL_ROLE = 2
_COL_DEVICE = 3
_COL_REGION = 4
_COL_STATUS = 5
_COL_ENABLED = 6


class AddSubAccountDialog(QDialog):
    """添加小号弹窗"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("➕ 添加小号")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.ed_id = QLineEdit()
        self.ed_id.setPlaceholderText("如 sub2（唯一标识）")
        form.addRow("账号ID *:", self.ed_id)

        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("显示名（留空用账号ID）")
        form.addRow("显示名:", self.ed_name)

        self.ed_device = QLineEdit()
        self.ed_device.setPlaceholderText("模拟器设备ID，如 127.0.0.1:16416")
        form.addRow("设备ID:", self.ed_device)

        self.cb_region = QComboBox()
        self.cb_region.addItems(["cn", "cn_android", "ios", "jp", "tw"])
        form.addRow("区服:", self.cb_region)

        self.ed_remark = QLineEdit()
        self.ed_remark.setPlaceholderText("备注（可选）")
        form.addRow("备注:", self.ed_remark)

        self.cb_enabled = QCheckBox("启用（作为组队小号被调用）")
        self.cb_enabled.setChecked(True)
        form.addRow("", self.cb_enabled)

        layout.addLayout(form)

        # 按钮
        btns = QHBoxLayout()
        btn_ok = QPushButton("保存")
        btn_cancel = QPushButton("取消")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        layout.addLayout(btns)

    def account_id(self) -> str:
        return self.ed_id.text().strip()

    def name(self) -> str:
        return self.ed_name.text().strip()

    def device_id(self) -> str:
        return self.ed_device.text().strip()

    def region(self) -> str:
        return self.cb_region.currentText().strip()

    def remark(self) -> str:
        return self.ed_remark.text().strip()

    def enabled(self) -> bool:
        return self.cb_enabled.isChecked()


class SubAccountPanel(QWidget):
    """小号管理面板（§2.2 账号配置 + 添加小号）"""

    def __init__(self, parent=None, param_bridge: Any = None):
        super().__init__(parent)
        self._param_bridge = param_bridge
        self._row_by_id: dict[str, int] = {}  # account_id → 行号

        layout = QVBoxLayout(self)

        # 顶部工具条
        top = QHBoxLayout()
        top.addWidget(QLabel("👤 小号管理"))
        top.addStretch(1)
        btn_add = QPushButton("➕ 添加小号")
        btn_add.clicked.connect(self._on_add_sub)
        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.clicked.connect(self.refresh)
        top.addWidget(btn_refresh)
        top.addWidget(btn_add)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

    # ── 数据 ─────────────────────────────────────────────

    @property
    def _bridge(self) -> Any:
        if self._param_bridge and hasattr(self._param_bridge, 'account'):
            return self._param_bridge.account
        return None

    def refresh(self) -> None:
        """从 AccountBridge 重新读取账号列表并渲染"""
        bridge = self._bridge
        if bridge is None:
            self.table.setRowCount(0)
            return
        try:
            accounts = bridge.get_accounts_detail()
        except Exception:
            accounts = []
        self._render(accounts)

    def _render(self, accounts: list[dict[str, Any]]) -> None:
        self.table.setRowCount(len(accounts))
        self._row_by_id.clear()
        for row, acc in enumerate(accounts):
            aid = acc.get("account_id", "")
            self._row_by_id[aid] = row
            role = acc.get("role", "sub")
            self.table.setItem(row, 0, QTableWidgetItem(aid))
            self.table.setItem(row, 1, QTableWidgetItem(acc.get("name", "")))
            self.table.setItem(row, _COL_ROLE, QTableWidgetItem("主号" if role == "main" else "小号"))
            self.table.setItem(row, _COL_DEVICE, QTableWidgetItem(acc.get("device_id", "")))
            self.table.setItem(row, _COL_REGION, QTableWidgetItem(acc.get("region", "cn")))
            self.table.setItem(row, _COL_STATUS, QTableWidgetItem("已配置"))
            enabled = bool(acc.get("enabled", True))
            it_enabled = QTableWidgetItem("✅" if enabled else "❌")
            it_enabled.setForeground(Qt.green if enabled else Qt.red)
            self.table.setItem(row, _COL_ENABLED, it_enabled)

    def update_accounts(self, accounts: list[dict]) -> None:
        """兼容旧版：sub_account_status 状态事件，仅更新已有行的状态列"""
        for acc in accounts:
            key = acc.get("account_id") or acc.get("name") or ""
            row = self._row_by_id.get(key)
            if row is None:
                continue
            status = acc.get("status", "unknown")
            online = bool(acc.get("online"))
            self.table.setItem(row, _COL_STATUS, QTableWidgetItem(
                "在线·" + status if online else status))

    # ── 添加小号 ─────────────────────────────────────────

    def _on_add_sub(self) -> None:
        bridge = self._bridge
        if bridge is None:
            QMessageBox.warning(self, "提示", "未连接到账号管理，无法添加小号。")
            return
        dlg = AddSubAccountDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        aid = dlg.account_id()
        if not aid:
            QMessageBox.warning(self, "提示", "账号ID不能为空。")
            return
        ok = bridge.add_account(
            account_id=aid,
            name=dlg.name(),
            role="sub",
            device_id=dlg.device_id(),
            region=dlg.region(),
            enabled=dlg.enabled(),
            remark=dlg.remark(),
        )
        if ok:
            self.refresh()
            QMessageBox.information(self, "成功", f"小号「{aid}」已添加。")
        else:
            QMessageBox.warning(self, "失败", "添加失败：账号ID可能已存在或账号服务不可用。")
