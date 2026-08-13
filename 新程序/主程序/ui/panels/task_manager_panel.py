"""
UI 子面板：TaskManagerPanel 任务文件管理（13-任务文件管理）。

按《13-任务文件管理》说明书：
- 左侧：任务库列表（扫描 tasks/ 的元数据）
- 操作：新建任务 / 删除（重命名 .deleted）/ 打开编辑 / 导入导出配置备份
- 右侧：选中任务的详情（元数据 + uses_* 声明 + 文件路径）
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QListWidget, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

CATEGORIES = ["daily", "permanent", "event", "special"]

_TASK_TYPE_LABELS = {
    "event_task": "非战斗任务",
    "battle": "战斗任务",
    "generic": "通用任务（不单独执行）",
    "trigger": "触发任务（特殊条件触发）",
}


class AssetPickerDialog(QDialog):
    """从统一图片库（assets/）选择一张图片。

    左侧列出全部图片（相对 assets/ 的引用路径），右侧预览；
    确定后 selected() 返回选中的引用路径。
    """

    def __init__(self, parent=None, assets_dir: str | Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("选择控制素材（素材管理已添加）")
        self.resize(680, 480)
        self._selected_rel: str | None = None
        self._images: list[dict] = []

        from core.asset_catalog import AssetCatalog
        from core.game_profile import current_game_assets
        base = Path(assets_dir) if assets_dir else current_game_assets()
        catalog = AssetCatalog(base)
        # 任务引用的都是"控制素材"（tasks/_shared/ 按钮/控件）；识图素材由场景识别模块统一处理
        self._images = catalog.list_shared_images()

        layout = QVBoxLayout(self)
        mid = QHBoxLayout()

        # 左：图片列表
        left = QVBoxLayout()
        left.addWidget(QLabel("图片（引用路径）"))
        self.list_widget = QListWidget()
        for img in self._images:
            self.list_widget.addItem(img["rel"])
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        left.addWidget(self.list_widget)
        mid.addLayout(left, 2)

        # 右：预览
        right = QVBoxLayout()
        right.addWidget(QLabel("预览"))
        self.preview = QLabel("（选择图片预览）")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("border:1px solid #555; background:#222; color:#888;")
        self.preview.setMinimumSize(280, 320)
        right.addWidget(self.preview, 1)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color:#aaa;")
        right.addWidget(self.info, 0)
        mid.addLayout(right, 2)

        layout.addLayout(mid)

        # 按钮
        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_ok = QPushButton("选择")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        layout.addLayout(btns)

        if self._images:
            self.list_widget.setCurrentRow(0)

    def _on_row_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._images):
            return
        img = self._images[row]
        # 去扩展名：配置的是识别素材名（与 images 映射/Executor 解析一致）
        rel = img["rel"]
        name = rel.rsplit("/", 1)[-1]
        if "." in name:
            rel = rel.rsplit(".", 1)[0]
        self._selected_rel = rel
        pix = QPixmap(img["abs"])
        if not pix.isNull():
            self.preview.setPixmap(pix.scaled(
                self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.info.setText(f"引用路径: {img['rel']}\n文件: {img['abs']}\n大小: {img['size']} B")

    def selected(self) -> str | None:
        """返回选中的素材识别名（去扩展名，相对 assets/）"""
        return self._selected_rel


class TaskManagerPanel(QWidget):
    """任务文件管理面板（列表 + 详情 + 新建/删除/打开/导入导出）"""

    def __init__(self, param_bridge: Any = None, parent=None):
        super().__init__(parent)
        self._param_bridge = param_bridge
        self._current_name: str = ""
        self._current_is_generic: bool = False
        self._detail_labels: dict[str, QLabel] = {}
        # §5.2 图片映射编辑态（ref → 素材路径）与所属任务
        self._images_editing: dict[str, str] = {}
        self._images_task: str = ""

        layout = QHBoxLayout(self)

        # ── 左侧任务库 + 通用模块 ─────────────────────────
        left = QVBoxLayout()
        left.addWidget(QLabel("🎮 游戏任务"))
        self.task_list = QListWidget()
        self.task_list.currentItemChanged.connect(self._on_task_selected)
        left.addWidget(self.task_list)
        left.addWidget(QLabel("🧩 通用模块（不单独执行，被任务引用）"))
        self.generic_list = QListWidget()
        self.generic_list.currentItemChanged.connect(self._on_generic_selected)
        left.addWidget(self.generic_list)

        btn_layout = QHBoxLayout()
        btn_new = QPushButton("新建")
        btn_new.clicked.connect(self._new_task)
        btn_del = QPushButton("删除")
        btn_del.clicked.connect(self._delete_task)
        btn_open = QPushButton("打开编辑")
        btn_open.clicked.connect(self._open_file)
        btn_export = QPushButton("导出")
        btn_export.clicked.connect(self._export_config)
        btn_import = QPushButton("导入")
        btn_import.clicked.connect(self._import_config)
        for b in (btn_new, btn_del, btn_open, btn_export, btn_import):
            btn_layout.addWidget(b)
        left.addLayout(btn_layout)

        # ── 右侧详情 ──────────────────────────────────────
        right = QVBoxLayout()
        right.addWidget(QLabel("任务详情"))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        container = QWidget()
        self.detail_layout = QVBoxLayout(container)
        self.scroll.setWidget(container)
        right.addWidget(self.scroll, 1)

        layout.addLayout(left, 1)
        layout.addLayout(right, 2)

        # 初始提示
        self._placeholder = QLabel("（从左侧选择任务查看详情）")
        self._placeholder.setStyleSheet("color:#888;")
        self.detail_layout.addWidget(self._placeholder)

    # ── 数据加载 ─────────────────────────────────────────────

    def load_tasks(self, metas: list) -> None:
        """加载任务元数据列表（dict 或 str 兼容，由 MainWindow 调用）"""
        self.task_list.blockSignals(True)
        self.task_list.clear()
        for m in metas:
            if isinstance(m, dict):
                name = m.get("name", "")
                display = m.get("display_name", "") or name
                category = m.get("category", "")
                label = f"{display}  [{category}]"
            else:
                name = str(m)
                display = name
                label = name
            self.task_list.addItem(label)
            item = self.task_list.item(self.task_list.count() - 1)
            item.setData(Qt.UserRole, name)
        self.task_list.blockSignals(False)
        if self.task_list.count() > 0:
            self.task_list.setCurrentRow(0)

    def load_generic(self, metas: list) -> None:
        """加载通用模块元数据列表（common，供其他游戏任务引用）"""
        self.generic_list.blockSignals(True)
        self.generic_list.clear()
        for m in metas:
            if isinstance(m, dict):
                name = m.get("name", "")
                display = m.get("display_name", "") or name
                label = f"{display}  [common]"
            else:
                name = str(m)
                label = name
            self.generic_list.addItem(label)
            item = self.generic_list.item(self.generic_list.count() - 1)
            item.setData(Qt.UserRole, name)
        self.generic_list.blockSignals(False)

    def _on_generic_selected(self, current, previous) -> None:
        """选中通用模块 → 显示详情（标注通用·不单独执行）"""
        if current is None:
            return
        name = current.data(Qt.UserRole)
        if not name:
            return
        self._current_name = name
        self._current_is_generic = True
        detail = self._get_detail(name)
        detail.setdefault("is_generic", True)
        detail.setdefault("category", "common")
        self._render_detail(detail)

    def _refresh(self) -> None:
        """重新拉取任务库 + 通用模块元数据并刷新列表"""
        bridge = self._param_bridge
        if not bridge or not hasattr(bridge, 'task'):
            return
        try:
            metas = bridge.task.get_task_metas()
            self.load_tasks(metas)
        except Exception:
            pass
        try:
            gmetas = bridge.task.get_generic_modules()
            self.load_generic(gmetas)
        except Exception:
            pass

    # ── 详情渲染 ─────────────────────────────────────────────

    def _on_task_selected(self, current, previous) -> None:
        if current is None:
            return
        name = current.data(Qt.UserRole)
        if not name:
            return
        self._current_name = name
        self._current_is_generic = False
        detail = self._get_detail(name)
        self._render_detail(detail)

    def _get_detail(self, name: str) -> dict[str, Any]:
        bridge = self._param_bridge
        if bridge and hasattr(bridge, 'task') and hasattr(bridge.task, 'get_task_detail'):
            try:
                return bridge.task.get_task_detail(name)
            except Exception:
                pass
        return {"name": name, "display_name": name}

    def _render_detail(self, detail: dict[str, Any]) -> None:
        # 清空详情区
        while self.detail_layout.count():
            item = self.detail_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._detail_labels.clear()

        name = detail.get("name", "")
        display = detail.get("display_name", "") or name
        is_generic = self._current_is_generic or detail.get("is_generic")

        title = QLabel(f"📋 {display}")
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        self.detail_layout.addWidget(title)

        from ui.theme import panel_group
        g, meta_content = panel_group("元数据")
        form = QFormLayout()
        meta_content.addLayout(form)
        task_type = detail.get("task_type", "")
        type_label = _TASK_TYPE_LABELS.get(task_type, task_type)
        if is_generic:
            type_label = "通用模块（不单独执行，被任务引用）"
        rows = [
            ("文件名:", name),
            ("显示名:", display),
            ("分类:", "通用模块（common）" if is_generic else detail.get("category", "")),
            ("任务类型:", type_label),
            ("描述:", detail.get("description", "")),
            ("战斗任务:", "是" if detail.get("uses_battle") else "否"),
            ("阵容配置:", "是" if detail.get("uses_team") else "否"),
            ("御魂配置:", "是" if detail.get("uses_soul") else "否"),
            ("体力检查:", "是" if detail.get("uses_stamina") else "否"),
            ("每轮循环:", str(detail.get("loop_count", 1))),
            ("超时(秒):", str(detail.get("timeout", 300))),
        ]
        for label, value in rows:
            vl = QLabel(str(value))
            vl.setWordWrap(True)
            form.addRow(label, vl)
            self._detail_labels[label] = vl
        self.detail_layout.addWidget(g)

        # ── 🎯 图片设置（逻辑名 → 素材路径，§5.2）──
        # 列出任务代码引用的图片清单，可逐张从素材管理已添加的图片中选择/清除
        # （统一在「素材管理」添加图片；识图素材由场景识别模块处理，任务只引用控制素材）
        g3, map_content = panel_group("🎯 图片设置（逻辑名 → 素材）")
        ml = map_content
        # 切换任务时重置编辑态；同任务重渲染保留已选未存项
        if self._images_task != name:
            self._images_editing = {}
            self._images_task = name
        refs_data: list[dict] = []
        bridge = self._param_bridge
        if bridge and hasattr(bridge, 'task') and hasattr(bridge.task, 'get_task_asset_refs'):
            try:
                refs_data = bridge.task.get_task_asset_refs(name)
            except Exception:
                refs_data = []
        for item in refs_data:
            ref = item.get("ref", "")
            if not ref:
                continue
            if ref not in self._images_editing:
                mapped = item.get("mapped")
                if mapped:
                    self._images_editing[ref] = str(mapped)
            cur_text = self._images_editing.get(ref) or "未设置（用逻辑名直接识别）"
            row = QWidget()
            rh = QHBoxLayout(row)
            rh.setContentsMargins(0, 0, 0, 0)
            lbl_ref = QLabel(ref)
            lbl_ref.setToolTip("任务代码中引用的素材名（逻辑名）")
            rh.addWidget(lbl_ref, 2)
            lbl_cur = QLabel(cur_text)
            lbl_cur.setWordWrap(True)
            lbl_cur.setStyleSheet("color:#999;")
            rh.addWidget(lbl_cur, 3)
            btn_pick = QPushButton("选图")
            btn_pick.clicked.connect(lambda _=False, r=ref: self._pick_image(r))
            btn_clear = QPushButton("清除")
            btn_clear.clicked.connect(lambda _=False, r=ref: self._clear_image(r))
            rh.addWidget(btn_pick)
            rh.addWidget(btn_clear)
            ml.addWidget(row)
        if not refs_data:
            ml.addWidget(QLabel("（未在任务代码中发现图片引用）"))
        else:
            btn_save_img = QPushButton("💾 保存图片配置")
            btn_save_img.clicked.connect(self._save_images)
            ml.addWidget(btn_save_img)
        self.detail_layout.addWidget(g3)

        self.detail_layout.addStretch()

    # ── §5.2 图片设置操作 ─────────────────────────────────

    def _pick_image(self, ref: str) -> None:
        """为逻辑名选择一张素材图片（从统一图片库）"""
        dlg = AssetPickerDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        rel = dlg.selected()
        if not rel:
            return
        self._images_editing[ref] = rel
        # 同任务内重渲染详情，保留编辑态
        self._render_detail(self._get_detail(self._current_name))

    def _clear_image(self, ref: str) -> None:
        """清除逻辑名的素材映射（回退为逻辑名直接识别）"""
        self._images_editing.pop(ref, None)
        self._render_detail(self._get_detail(self._current_name))

    def _save_images(self) -> None:
        """保存图片映射到 tasks.yaml 的 images 字段（§5.2）"""
        bridge = self._param_bridge
        if not (bridge and hasattr(bridge, 'task')):
            QMessageBox.warning(self, "保存失败", "未连接到任务配置。")
            return
        try:
            bridge.task.save_task_images(self._current_name, dict(self._images_editing))
            QMessageBox.information(self, "成功", "图片配置已保存到 tasks.yaml。")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    # ── 操作（经 TaskBridge → TaskManager） ─────────────────

    def _new_task(self) -> None:
        bridge = self._param_bridge
        if not bridge or not hasattr(bridge, 'task'):
            return
        # 任务类型（core/task_template.py）：非战斗/战斗/通用/触发
        from core.task_template import TASK_TYPES, TASK_TYPE_LABELS
        type_items = [f"{TASK_TYPE_LABELS[t]}（{t}）" for t in TASK_TYPES]
        type_label, ok0 = QInputDialog.getItem(self, "新建任务", "任务类型:",
                                               type_items, 0, False)
        if not ok0:
            return
        task_type = TASK_TYPES[type_items.index(type_label)]

        name, ok = QInputDialog.getText(self, "新建任务", "任务文件名（英文，不含 .py）:")
        if not ok or not name.strip():
            return
        display, ok2 = QInputDialog.getText(self, "新建任务", "显示名（可留空）:")
        if not ok2:
            return
        # 通用任务固定放 common/（不单独执行）；其余选择分类
        if task_type == "generic":
            category = "common"
        else:
            category, ok3 = QInputDialog.getItem(self, "新建任务", "分类:",
                                                 CATEGORIES, 0, False)
            if not ok3:
                return
        try:
            bridge.task.new_task(category, name.strip(), display.strip(), task_type=task_type)
            self._refresh()
        except Exception as e:
            QMessageBox.warning(self, "新建失败", str(e))

    def _delete_task(self) -> None:
        bridge = self._param_bridge
        if not bridge or not hasattr(bridge, 'task'):
            return
        if not self._current_name:
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"删除任务「{self._current_name}」？\n（重命名为 .deleted 保留内容，可恢复）",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                bridge.task.delete_task(self._current_name)
                self._refresh()
            except Exception as e:
                QMessageBox.warning(self, "删除失败", str(e))

    def _open_file(self) -> None:
        bridge = self._param_bridge
        if not bridge or not hasattr(bridge, 'task'):
            return
        if not self._current_name:
            return
        try:
            bridge.task.open_file(self._current_name)
        except Exception as e:
            QMessageBox.warning(self, "打开失败", str(e))

    # ── 配置备份导入导出（06-配置管理中心） ─────────────────

    def _export_config(self) -> None:
        bridge = self._param_bridge
        if not bridge or not hasattr(bridge, 'config'):
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出配置备份",
                                              "yys_config_backup.zip", "ZIP (*.zip)")
        if not path:
            return
        try:
            bridge.config.export_config(path)
            QMessageBox.information(self, "导出成功", f"已导出到 {path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _import_config(self) -> None:
        bridge = self._param_bridge
        if not bridge or not hasattr(bridge, 'config'):
            return
        path, _ = QFileDialog.getOpenFileName(self, "导入配置备份", "", "ZIP (*.zip)")
        if not path:
            return
        reply = QMessageBox.question(
            self, "确认导入",
            "导入将覆盖现有配置，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            bridge.config.import_config(path)
            QMessageBox.information(self, "导入成功", "配置已恢复")
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))
