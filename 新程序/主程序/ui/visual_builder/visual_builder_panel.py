"""
17-可视化构建模块：主面板（P0/P1/P2，VisualBuilderPanel）。

布局：
- 顶部工具栏：标题 + 当前打开项标签 + 「📂 打开任务」+ 保存 / 示教运行 / 停止
- 主体：双视图 Tab
  - 流程编排：参数上浮配置区 + NodeGraphQt 节点画布
  - 画面示教：截图指示器

打开任务：弹窗（OpenTaskDialog）选择 游戏 → 通用操作/游戏任务 → 打开到画布编辑。
支持打开任意游戏的可视化任务或通用操作（复用同一画布编辑子图）。
"""
from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QGroupBox, QHBoxLayout,
                             QInputDialog, QLabel, QLineEdit, QMessageBox,
                             QPushButton, QSpinBox, QTabWidget, QVBoxLayout,
                             QWidget)

from core.event_bus import get_global_bus
from ui.visual_builder.graph_canvas import GraphCanvas
from ui.visual_builder.open_task_dialog import OpenTaskDialog
from ui.visual_builder.teach_console import TeachConsole


class VisualBuilderPanel(QWidget):
    """可视化构建面板"""

    def __init__(self, visual_bridge=None, parent=None):
        super().__init__(parent)
        self._bridge = visual_bridge
        self._bus = get_global_bus()
        self._open_key: dict | None = None   # {"game","kind","name"}
        self._open_store: Any = None          # 当前打开项所属 store
        self._current_task: dict = {}         # 画布任务 dict

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── 顶部工具栏 ──────────────────────────────────
        toolbar = QHBoxLayout()
        self._title = QLabel("🛠 可视化构建")
        self._title.setStyleSheet("font-weight:bold;font-size:14px;")
        toolbar.addWidget(self._title)
        # 游戏选择下拉（决定通用操作/素材等数据源）
        toolbar.addWidget(QLabel("游戏:"))
        self._game_combo = QComboBox()
        if self._bridge is not None:
            cur = self._bridge.current_game
            for gid, gname in self._bridge.game_list():
                self._game_combo.addItem(f"{gname}（{gid}）", gid)
                if gid == cur:
                    self._game_combo.setCurrentIndex(
                        self._game_combo.count() - 1)
        self._game_combo.currentIndexChanged.connect(self._on_game_changed)
        toolbar.addWidget(self._game_combo)
        self._open_label = QLabel("未打开任务")
        self._open_label.setStyleSheet("color:#1e6fd9;font-weight:bold;")
        toolbar.addWidget(self._open_label)
        toolbar.addStretch(1)
        self._open_btn = QPushButton("📂 打开任务")
        self._open_btn.clicked.connect(self._open_task)
        toolbar.addWidget(self._open_btn)
        self._save_btn = QPushButton("💾 保存")
        self._save_btn.clicked.connect(self._save)
        self._teach_btn = QPushButton("🎓 示教运行")
        self._teach_btn.clicked.connect(self._teach_run)
        self._stop_btn = QPushButton("⏹ 停止")
        self._stop_btn.clicked.connect(self._stop)
        self._stop_btn.setEnabled(False)
        toolbar.addWidget(self._save_btn)
        toolbar.addWidget(self._teach_btn)
        toolbar.addWidget(self._stop_btn)
        root.addLayout(toolbar)

        # ── 主体：双视图 Tab ────────────────────────────
        right = QTabWidget()
        # 流程编排 Tab：参数上浮配置区 + 节点画布
        flow_tab = QWidget()
        flow_lay = QVBoxLayout(flow_tab)
        flow_lay.setContentsMargins(0, 0, 0, 0)
        flow_lay.setSpacing(4)
        self._params_group = QGroupBox("🎯 任务参数（参数上浮 4.27）")
        self._params_group.setCheckable(True)
        self._params_group.setChecked(True)
        self._params_layout = QVBoxLayout(self._params_group)
        self._params_layout.setContentsMargins(8, 12, 8, 8)
        self._params_group.setVisible(False)
        flow_lay.addWidget(self._params_group)
        self._param_widgets: dict[str, Any] = {}
        self._param_list: list[dict] = []
        if self._bridge is not None:
            self._canvas = GraphCanvas(
                element_provider=self._bridge.element_items,
                operation_provider=self._bridge.operation_items,
                operation_loader=self._bridge.load_operation,
                # 示教产物下拉：按当前打开项实时拉取（任务或操作）
                scene_provider=lambda: self._teach_items("scenes"),
                point_provider=lambda: self._teach_items("points"),
                ocr_provider=lambda: self._teach_items("ocr_regions"),
                # 通用节点：右侧「通用节点」Tab（所选游戏的通用操作）
                operation_list_provider=self._bridge.operation_list,
            )
        else:
            self._canvas = GraphCanvas()
        flow_lay.addWidget(self._canvas, 1)
        right.addTab(flow_tab, "流程编排")
        if self._bridge is not None:
            self._teach_console = TeachConsole(
                event_bus=self._bus,
                store=self._bridge._store,
                assets_dir=self._bridge._assets_dir,
                ocr=self._bridge.get_ocr(),
            )
        else:
            self._teach_console = TeachConsole(event_bus=self._bus)
        right.addTab(self._teach_console, "画面示教")
        root.addWidget(right, 1)

        self._refresh_open_label()

    # ── 游戏切换 ────────────────────────────────────────
    def _on_game_changed(self) -> None:
        """顶部游戏下拉切换：更新 bridge 当前游戏 → 刷新画布操作/素材下拉"""
        gid = self._game_combo.currentData()
        if self._bridge is not None and gid:
            self._bridge.set_current_game(gid)
            self._canvas.refresh_operation_list()
            self._canvas.refresh_combos()

    # ── 当前打开项状态 ──────────────────────────────────
    def _current_name(self) -> str:
        return self._open_key.get("name", "") if self._open_key else ""

    def _teach_items(self, key: str) -> list[str]:
        """当前打开项（任务或操作）的示教产物 ID 列表"""
        if self._open_key is None or self._open_store is None:
            return []
        try:
            data = self._open_store.load(self._current_name())
        except Exception:
            return []
        teach = data.get("teach", {}) or {}
        return [x.get("id", "") for x in teach.get(key, [])]

    def _refresh_open_label(self) -> None:
        if self._open_key is None:
            self._open_label.setText("未打开任务")
            self._save_btn.setEnabled(False)
            self._teach_btn.setEnabled(False)
        else:
            kind_label = "通用操作" if self._open_key["kind"] == "operation" \
                else "游戏任务"
            display = self._current_task.get("display_name",
                                             self._current_name())
            self._open_label.setText(
                f"{kind_label}：{display}（{self._open_key['game']}）")
            self._save_btn.setEnabled(True)
            self._teach_btn.setEnabled(True)

    # ── 打开任务 ────────────────────────────────────────
    def _open_task(self) -> None:
        if self._bridge is None or self._bridge._profile is None:
            QMessageBox.information(self, "提示", "可视化构建未就绪")
            return
        dlg = OpenTaskDialog(self._bridge._profile,
                             self._game_combo.currentData(), self)
        if dlg.exec_() != dlg.Accepted:
            return
        sel = dlg.selected()
        if sel is None:
            return
        game_id, kind, name = sel
        try:
            store = dlg._store_for(game_id, kind)
        except Exception as e:
            QMessageBox.warning(self, "打开失败", str(e))
            return
        self.open_visual(game_id, kind, name, store)

    def open_visual(self, game_id: str, kind: str, name: str,
                    store=None) -> bool:
        """编程式打开任务/操作到画布（弹窗与测试共用）"""
        if store is None:
            # 按游戏构造存储
            try:
                from core.game_profile import GameProfile
                gp = GameProfile(root=self._bridge._profile.root,
                                 game_id=game_id)
                if kind == "operation":
                    from visual.operation_store import OperationStore
                    store = OperationStore([gp.shared_operations_dir,
                                            gp.operations_dir])
                else:
                    from visual.rule_store import VisualTaskStore
                    store = VisualTaskStore(gp.visual_tasks_dir)
            except Exception:
                return False
        try:
            data = store.load(name)
        except Exception as e:
            QMessageBox.warning(self, "打开失败", str(e))
            return False
        self._open_key = {"game": game_id, "kind": kind, "name": name}
        self._open_store = store
        self._current_task = data
        self._canvas.load_task(data)
        self._rebuild_params(data)
        self._refresh_open_label()
        return True

    # ── 保存 ─────────────────────────────────────────────
    def _save(self) -> None:
        if self._open_key is None or self._open_store is None:
            QMessageBox.information(self, "提示", "请先「📂 打开任务」")
            return
        name = self._current_name()
        task = self._canvas.export_task(self._current_task)
        task["name"] = name
        task["display_name"] = self._current_task.get("display_name", name)
        task["category"] = self._current_task.get("category", "daily")
        # 参数上浮（4.27）：收集 UI 配置区值 → param_values
        param_values: dict[str, Any] = {}
        for path, w in self._param_widgets.items():
            param_values[path] = self._param_value(w)
        task["param_values"] = param_values
        # 通用操作：合并原 inputs（画布只导出 graph）
        if self._open_key["kind"] == "operation":
            try:
                orig = self._open_store.load(name)
                task["inputs"] = orig.get("inputs", [])
            except Exception:
                pass
        try:
            self._open_store.save(task)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return
        self._current_task = task
        # 通知 bridge（当前游戏任务 → 注册/列表刷新）
        try:
            if self._bridge is not None:
                from core.events import Events
                self._bus.publish(Events.VISUAL_TASK_CHANGED,
                                  source="visual_builder", task_name=name)
                self._canvas.refresh_operation_list()
        except Exception:
            pass
        QMessageBox.information(self, "已保存", f"「{name}」已保存")

    # ── 示教运行 / 停止 ─────────────────────────────────
    def _teach_run(self) -> None:
        if self._bridge is None or self._open_key is None:
            QMessageBox.information(self, "提示", "请先打开任务")
            return
        # 示教运行仅支持当前游戏的可视化任务（teach_engine 从当前游戏 store 加载）
        cur_game = self._bridge._profile.game_id if self._bridge._profile else "yys"
        if self._open_key["kind"] != "task" or \
                self._open_key["game"] != cur_game:
            QMessageBox.information(
                self, "提示",
                "示教运行目前仅支持当前游戏的可视化任务；\n"
                "通用操作或其它游戏请先保存，再通过调度/任务队列运行")
            return
        self._save()
        name = self._current_name()
        ok = self._bridge.teach_run(name)
        if not ok:
            QMessageBox.warning(self, "示教", "示教已在运行或任务加载失败")
            return
        self._stop_btn.setEnabled(True)
        self._teach_btn.setEnabled(False)
        parent = self._teach_console.parentWidget()
        if isinstance(parent, QTabWidget):
            parent.setCurrentWidget(self._teach_console)

    def _stop(self) -> None:
        if self._bridge is not None:
            self._bridge.teach_stop()
        self._stop_btn.setEnabled(False)
        self._teach_btn.setEnabled(True)

    # ── 参数上浮配置区（4.27）────────────────────────────
    def _on_new_operation(self) -> dict | None:
        """新建通用操作（画布右侧「通用节点」Tab 的 ＋新建 按钮）"""
        if self._bridge is None:
            return None
        name, ok = QInputDialog.getText(self, "新建通用操作",
                                        "操作名（英文，如 configure_team）:")
        if not ok or not name.strip():
            return None
        name = name.strip()
        if self._bridge._op_store is not None and \
                self._bridge._op_store.exists(name):
            QMessageBox.warning(self, "已存在", f"操作「{name}」已存在")
            return None
        display, ok2 = QInputDialog.getText(self, "新建通用操作",
                                            "显示名（如 配置阵容）:",
                                            text=name)
        if not ok2:
            return None
        try:
            return self._bridge.create_operation(name, display.strip() or name)
        except Exception as e:
            QMessageBox.warning(self, "新建失败", str(e))
            return None

    def _rebuild_params(self, task: dict) -> None:
        """按任务 operation 节点的 hoist 参数动态生成配置控件"""
        while self._params_layout.count():
            item = self._params_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._param_widgets = {}
        self._param_list = []
        if self._bridge is None:
            self._params_group.setVisible(False)
            return
        params = self._bridge.collect_params(task)
        if not params:
            self._params_group.setVisible(False)
            return
        self._params_group.setVisible(True)
        self._param_list = params
        values = task.get("param_values", {}) or {}
        for p in params:
            row = QHBoxLayout()
            row.setContentsMargins(4, 1, 4, 1)
            lab = QLabel(p.get("label", p.get("path", "")))
            lab.setMinimumWidth(90)
            row.addWidget(lab)
            w = self._make_param_widget(p, values.get(p["path"], p.get("default")))
            row.addWidget(w, 1)
            self._params_layout.addLayout(row)
            self._param_widgets[p["path"]] = w

    def _make_param_widget(self, p: dict, value: Any) -> Any:
        ptype = p.get("type", "text")
        if ptype == "combo":
            cb = QComboBox()
            opts = p.get("options", []) or []
            cb.addItems([str(o) for o in opts])
            if value is not None:
                cb.setCurrentText(str(value))
            return cb
        if ptype == "checkbox":
            ch = QCheckBox()
            ch.setChecked(bool(value))
            return ch
        if ptype == "spinbox":
            sb = QSpinBox()
            sb.setRange(-999999, 999999)
            try:
                sb.setValue(int(value))
            except Exception:
                sb.setValue(0)
            return sb
        le = QLineEdit("" if value is None else str(value))
        return le

    def _param_value(self, w: Any) -> Any:
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, QSpinBox):
            return w.value()
        return w.text()
