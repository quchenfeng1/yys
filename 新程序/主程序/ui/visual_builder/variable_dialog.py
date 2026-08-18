"""17-可视化构建模块：变量组/常量组编辑弹窗（2026-08-15）。

- VariableGroupDialog：变量组【详情】——表格 4 列（显示名/变量键/类型/默认值）
- ConstantGroupDialog：常量组【详情】——表格 3 列（显示名/变量键/值）
- 类型下拉：int / float / text / bool（与 visual_schema.VAR_TYPES 一致）
- 校验：变量键必须 [A-Za-z_][A-Za-z0-9_]*；组内键唯一
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                             QHBoxLayout, QHeaderView, QMessageBox,
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QVBoxLayout)

from visual import visual_schema as vs


def validate_variables(variables: list[dict]) -> str:
    """校验变量定义列表：返回错误文本（空串=合法）。"""
    if not variables:
        return "请至少添加一行变量定义"
    keys: set[str] = set()
    for v in variables:
        key = str(v.get("key", "") or "").strip()
        if not vs.is_valid_var_key(key):
            return f"变量键「{key}」不合法：只允许字母/数字/下划线，且不能以数字开头"
        if key in keys:
            return f"变量键「{key}」在组内重复"
        keys.add(key)
    return ""


def _coerce_default(value, vtype: str):
    """把表格文本按类型转默认值；非法回退原字符串"""
    if vtype == "int":
        try:
            return int(float(value))
        except Exception:
            return 0
    if vtype == "float":
        try:
            return float(value)
        except Exception:
            return 0.0
    if vtype == "bool":
        return str(value).strip().lower() in ("1", "true", "yes", "是")
    return "" if value is None else str(value)


class _BaseVarDialog(QDialog):
    """变量/常量组编辑弹窗基类（表格 + 增删行 + 校验）"""

    def __init__(self, title: str, columns: list[tuple[str, str]],
                 variables: list[dict], parent=None):
        # columns: [(key, 列头), ...]；key ∈ label/key/type/value
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(620, 420)
        self._col_keys = [k for k, _ in columns]
        root = QVBoxLayout(self)
        self._table = QTableWidget(0, len(columns))
        self._table.setHorizontalHeaderLabels([h for _, h in columns])
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        # 单击单元格即进入编辑（默认需双击/再点一次，用户体验差）
        self._table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectItems)
        # AllEditTriggers 的 SelectedClicked 只对已选中项生效——第一次点击
        # 时单元格尚未选中，仍要点两次。改为 mousePress 时直接 edit(index)
        self._table.viewport().installEventFilter(self)
        root.addWidget(self._table, 1)

        btns = QHBoxLayout()
        add_btn = QPushButton("➕ 添加行")
        add_btn.clicked.connect(self._add_row)
        del_btn = QPushButton("🗑 删除选中行")
        del_btn.clicked.connect(self._del_rows)
        ok_btn = QPushButton("✔ 确定")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(add_btn)
        btns.addWidget(del_btn)
        btns.addStretch(1)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        root.addLayout(btns)

        self.variables: list[dict] = []
        for v in variables:
            if isinstance(v, dict):
                self._add_row(v)

    def _new_item(self, text):
        return QTableWidgetItem("" if text is None else str(text))

    def eventFilter(self, obj, event):
        """鼠标按下单元格 → 立即进入编辑（单击一次即可输入）。

        QComboBox（类型列）等 cellWidget 不拦截，保证其自身交互正常。
        ⚠️ 不能在 mousePress 处理栈中同步 edit()——编辑器（QLineEdit）创建
        会与鼠标按下事件竞态，真实 Windows 崩溃 0xC0000409（与节点按钮
        开弹窗同源）；用 QTimer.singleShot 推迟到事件循环。
        """
        if (obj is self._table.viewport()
                and event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton):
            idx = self._table.indexAt(event.pos())
            if idx.isValid() \
                    and self._table.cellWidget(idx.row(), idx.column()) is None:
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, lambda i=idx: self._table.edit(i))
        return super().eventFilter(obj, event)

    def _add_row(self, preset: dict | None = None) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        preset = preset or {}
        for col, key in enumerate(self._col_keys):
            if key == "type":
                combo = QComboBox()
                combo.addItems(vs.VAR_TYPES)
                combo.setCurrentText(str(preset.get("type", "int")))
                self._table.setCellWidget(row, col, combo)
            elif key == "callable":
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
                              | Qt.ItemIsSelectable)
                item.setCheckState(
                    Qt.Checked if preset.get("callable") else Qt.Unchecked)
                self._table.setItem(row, col, item)
            else:
                self._table.setItem(row, col, self._new_item(
                    preset.get(key, "")))

    def _del_rows(self) -> None:
        rows = sorted({i.row() for i in self._table.selectedIndexes()},
                      reverse=True)
        for r in rows:
            self._table.removeRow(r)

    def _row_data(self, row: int) -> dict:
        out: dict = {}
        for col, key in enumerate(self._col_keys):
            if key == "type":
                w = self._table.cellWidget(row, col)
                out[key] = w.currentText() if w is not None else "int"
            elif key == "callable":
                item = self._table.item(row, col)
                out[key] = (item is not None
                            and item.checkState() == Qt.Checked)
            else:
                item = self._table.item(row, col)
                out[key] = (item.text().strip() if item else "")
        return out

    def _on_ok(self) -> None:
        rows: list[dict] = []
        for r in range(self._table.rowCount()):
            d = self._row_data(r)
            if not str(d.get("key", "")).strip():
                continue   # 跳过整行为空的占位行
            d.setdefault("label", "")
            if not d.get("label"):
                d["label"] = d["key"]
            rows.append(d)
        err = validate_variables(rows)
        if err:
            QMessageBox.warning(self, "校验失败", err)
            return
        self.variables = rows
        self.accept()


class VariableGroupDialog(_BaseVarDialog):
    """变量组：显示名/变量键/类型/默认值/可调用"""

    def __init__(self, group_name: str, variables: list[dict], parent=None):
        super().__init__(
            f"变量组「{group_name}」- 变量定义",
            [("label", "UI显示名"), ("key", "变量键"),
             ("type", "类型"), ("default", "默认值"),
             ("callable", "可调用")],
            variables, parent)
        if not variables:
            self._add_row()

    def _on_ok(self) -> None:
        # callable 列仅对勾选的变量有意义；未勾选时强制 False
        super()._on_ok()
        for v in self.variables:
            v["callable"] = bool(v.get("callable"))


class ConstantGroupDialog(_BaseVarDialog):
    """常量组：显示名/变量键/值"""

    def __init__(self, group_name: str, variables: list[dict], parent=None):
        super().__init__(
            f"常量组「{group_name}」- 常量定义",
            [("label", "UI显示名"), ("key", "变量键"), ("value", "值")],
            variables, parent)
        if not variables:
            self._add_row()
