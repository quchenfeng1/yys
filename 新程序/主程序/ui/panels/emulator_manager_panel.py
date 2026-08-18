"""
UI 子面板：EmulatorManagerPanel 模拟器管理（2026-08-16）。

功能：
- 列出模拟器条目（名称 / 地址 / 在线状态）
- 手动添加：名称 + host + port
- 扫描在线模拟器：EmulatorDetector 发现在线设备 → 选中起名保存
- 编辑 / 删除

数据操作全部经回调注入（SystemBridge），面板无核心依赖；
增删改后发 emulators_changed → 主窗口刷新顶部模拟器下拉。
"""
from __future__ import annotations

from typing import Any, Callable

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

_COLUMNS = ["名称", "地址", "状态", "备注"]


class _EmulatorEditDialog(QDialog):
    """模拟器条目编辑弹窗（名称 / host / port / 备注）"""

    def __init__(self, parent=None, title: str = "添加模拟器",
                 name: str = "", host: str = "127.0.0.1",
                 port: int = 16384, remark: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.ed_name = QLineEdit(name)
        self.ed_host = QLineEdit(host)
        self.ed_host.setPlaceholderText("127.0.0.1")
        self.sp_port = QSpinBox()
        self.sp_port.setRange(1, 65535)
        self.sp_port.setValue(port)
        self.ed_remark = QLineEdit(remark)
        form.addRow("名称", self.ed_name)
        form.addRow("ADB 主机", self.ed_host)
        form.addRow("ADB 端口", self.sp_port)
        form.addRow("备注", self.ed_remark)
        lay.addLayout(form)
        btn_row = QHBoxLayout()
        btn_ok = QPushButton("保存")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        lay.addLayout(btn_row)

    def values(self) -> dict:
        return {
            "name": self.ed_name.text().strip(),
            "host": self.ed_host.text().strip() or "127.0.0.1",
            "port": self.sp_port.value(),
            "remark": self.ed_remark.text().strip(),
        }


class EmulatorManagerPanel(QWidget):
    """模拟器管理面板（数据经回调注入）"""

    emulators_changed = pyqtSignal()  # 增删改后 → 主窗口刷新下拉

    def __init__(
        self,
        list_provider: Callable[[], list[dict]] | None = None,
        save_callback: Callable[[dict], bool] | None = None,
        delete_callback: Callable[[str], bool] | None = None,
        scan_callback: Callable[[], list[dict]] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._list_provider = list_provider or (lambda: [])
        self._save_callback = save_callback or (lambda entry: False)
        self._delete_callback = delete_callback or (lambda eid: False)
        self._scan_callback = scan_callback or (lambda: [])
        self._online_serials: set[str] = set()
        self._setup_ui()
        self.refresh()

    # ── UI ──────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        top = QHBoxLayout()
        top.addWidget(QLabel("📱 模拟器管理"))
        top.addStretch(1)
        btn_add = QPushButton("＋ 手动添加")
        btn_add.clicked.connect(self._on_add)
        btn_scan = QPushButton("🔍 扫描在线模拟器")
        btn_scan.clicked.connect(self._on_scan)
        btn_edit = QPushButton("✏️ 编辑")
        btn_edit.clicked.connect(self._on_edit)
        btn_del = QPushButton("🗑 删除")
        btn_del.clicked.connect(self._on_delete)
        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.clicked.connect(self.refresh)
        for b in (btn_add, btn_scan, btn_edit, btn_del, btn_refresh):
            top.addWidget(b)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        self._hint = QLabel("提示：模拟器条目全局共享；切换后顶部下拉立即生效。")
        layout.addWidget(self._hint)

    # ── 数据 ────────────────────────────────────────────

    def _entries(self) -> list[dict]:
        try:
            return list(self._list_provider() or [])
        except Exception:
            return []

    def _entry_ids(self) -> list[str]:
        return [e.get("id", "") for e in self._entries() if e.get("id")]

    def refresh(self) -> None:
        """刷新列表 + 在线状态（重新扫描在线设备标记）"""
        try:
            online = self._scan_callback() or []
        except Exception:
            online = []
        self._online_serials = {o.get("serial", "") for o in online if o.get("serial")}
        self._fill()

    def _fill(self) -> None:
        entries = self._entries()
        self.table.setRowCount(len(entries))
        for row, e in enumerate(entries):
            serial = f"{e.get('host', '127.0.0.1')}:{e.get('port', 0)}"
            status = "🟢 在线" if serial in self._online_serials else "⚪ 未扫描到"
            vals = [e.get("name", "") or e.get("id", ""), serial, status,
                    e.get("remark", "")]
            for col, v in enumerate(vals):
                self.table.setItem(row, col, QTableWidgetItem(str(v)))
            item = self.table.item(row, 0)
            if item is not None:
                item.setData(256, e.get("id", ""))  # UserRole 存 id

    def _selected_id(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 0)
        return item.data(256) if item else ""

    # ── 交互 ────────────────────────────────────────────

    def _on_add(self) -> None:
        dlg = _EmulatorEditDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        vals = dlg.values()
        if not vals["name"]:
            QMessageBox.warning(self, "提示", "名称不能为空")
            return
        if self._save_callback({"id": "", **vals}):
            self.emulators_changed.emit()
            self.refresh()
        else:
            QMessageBox.warning(self, "提示", "保存失败（名称或 ID 冲突？）")

    def _on_edit(self) -> None:
        eid = self._selected_id()
        if not eid:
            QMessageBox.information(self, "提示", "请先选中一行")
            return
        entry = next((e for e in self._entries() if e.get("id") == eid), None)
        if entry is None:
            return
        dlg = _EmulatorEditDialog(
            self, title="编辑模拟器",
            name=entry.get("name", ""),
            host=entry.get("host", "127.0.0.1"),
            port=int(entry.get("port", 16384)),
            remark=entry.get("remark", ""),
        )
        if dlg.exec_() != QDialog.Accepted:
            return
        vals = dlg.values()
        if self._save_callback({"id": eid, **vals}):
            self.emulators_changed.emit()
            self.refresh()
        else:
            QMessageBox.warning(self, "提示", "保存失败")

    def _on_delete(self) -> None:
        eid = self._selected_id()
        if not eid:
            QMessageBox.information(self, "提示", "请先选中一行")
            return
        name = next((e.get("name", eid)
                     for e in self._entries() if e.get("id") == eid), eid)
        if QMessageBox.question(
            self, "确认删除", f"删除模拟器「{name}」？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        if self._delete_callback(eid):
            self.emulators_changed.emit()
            self.refresh()
        else:
            QMessageBox.warning(self, "提示", "删除失败")

    def _on_scan(self) -> None:
        """扫描在线模拟器 → 用户选择 → 预填添加弹窗。"""
        try:
            online = self._scan_callback() or []
        except Exception:
            online = []
        if not online:
            QMessageBox.information(
                self, "扫描结果",
                "未发现在线模拟器。\n请确认模拟器已启动并开启 ADB 调试。")
            return
        self._online_serials = {o.get("serial", "") for o in online if o.get("serial")}
        self._fill()
        dlg = QDialog(self)
        dlg.setWindowTitle("选择在线模拟器")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"发现 {len(online)} 台在线设备，选择后保存为条目："))
        lst = QListWidget()
        for o in online:
            label = f"{o.get('serial', '')}  （{o.get('type', 'unknown')}）"
            it = QListWidgetItem(label)
            it.setData(256, o)
            lst.addItem(it)
        lay.addWidget(lst)
        btn_row = QHBoxLayout()
        btn_ok = QPushButton("保存为条目")
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(dlg.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        lay.addLayout(btn_row)

        def _save_picked():
            it = lst.currentItem()
            if it is None:
                QMessageBox.information(dlg, "提示", "请先选择一台设备")
                return
            o = it.data(256) or {}
            serial = o.get("serial", "")
            host, _, port_s = serial.rpartition(":")
            edit = _EmulatorEditDialog(
                dlg, title="保存模拟器条目",
                name=serial,
                host=host or "127.0.0.1",
                port=int(port_s or 0) or 16384,
            )
            if edit.exec_() == QDialog.Accepted:
                vals = edit.values()
                if not vals["name"]:
                    vals["name"] = serial
                if self._save_callback({"id": "", **vals}):
                    self.emulators_changed.emit()
                    self.refresh()
                    dlg.accept()
                else:
                    QMessageBox.warning(dlg, "提示", "保存失败")

        btn_ok.clicked.connect(_save_picked)
        dlg.exec_()
