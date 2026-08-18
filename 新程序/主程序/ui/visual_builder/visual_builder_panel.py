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

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QGroupBox,
                             QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QScrollArea, QSpinBox,
                             QTabWidget, QVBoxLayout, QWidget)

from core.event_bus import get_global_bus
from core.events import Events
from ui.visual_builder.graph_canvas import GraphCanvas
from ui.visual_builder.open_task_dialog import OpenTaskDialog
from ui.visual_builder.teach_console import TeachConsole


class VisualBuilderPanel(QWidget):
    """可视化构建面板"""

    # 后台线程事件 → UI 线程信号（queued 连接，线程安全）
    _node_exec_sig = pyqtSignal(str)
    _teach_done_sig = pyqtSignal()
    _node_img_sig = pyqtSignal(str, bytes)

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
        # 游戏选择已移除（2026-08-16）：由主窗口顶部控制栏全局选择
        self._open_label = QLabel("未打开任务")
        self._open_label.setStyleSheet("color:#1e6fd9;font-weight:bold;")
        toolbar.addWidget(self._open_label)
        toolbar.addStretch(1)
        self._open_btn = QPushButton("📂 打开任务")
        self._open_btn.clicked.connect(self._open_task)
        toolbar.addWidget(self._open_btn)
        self._materials_btn = QPushButton("📚 素材管理")
        self._materials_btn.setToolTip(
            "管理本任务素材库：只有加入的素材才出现在节点下拉")
        self._materials_btn.clicked.connect(self._open_material_dialog)
        toolbar.addWidget(self._materials_btn)
        self._save_btn = QPushButton("💾 保存")
        self._save_btn.clicked.connect(self._save)
        self._teach_btn = QPushButton("🧪 测试启动")
        self._teach_btn.setToolTip("在模拟器上单独试跑当前任务（与正式脚本互斥）")
        self._teach_btn.clicked.connect(self._teach_run)
        self._step_btn = QPushButton("👣 单步测试")
        self._step_btn.setToolTip(
            "逐步调试：每个节点执行前暂停并红框高亮，"
            "点「⏭ 下一步」执行一步，便于定位出问题的节点")
        self._step_btn.clicked.connect(lambda: self._teach_run(step_mode=True))
        self._next_btn = QPushButton("⏭ 下一步")
        self._next_btn.setToolTip("执行当前红框高亮节点，停到下一个节点")
        self._next_btn.clicked.connect(self._teach_step_next)
        self._next_btn.setEnabled(False)
        self._stop_btn = QPushButton("⏹ 停止")
        self._stop_btn.clicked.connect(self._stop)
        self._stop_btn.setEnabled(False)
        toolbar.addWidget(self._save_btn)
        toolbar.addWidget(self._teach_btn)
        toolbar.addWidget(self._step_btn)
        toolbar.addWidget(self._next_btn)
        toolbar.addWidget(self._stop_btn)
        root.addLayout(toolbar)

        # ── 主体：双视图 Tab ────────────────────────────
        right = QTabWidget()
        # 流程编排 Tab：参数上浮配置区 + 节点画布
        flow_tab = QWidget()
        flow_lay = QVBoxLayout(flow_tab)
        flow_lay.setContentsMargins(0, 0, 0, 0)
        flow_lay.setSpacing(4)
        # 参数上浮区已移除（2026-08-15：通用操作体系删除，参数由节点内嵌编辑）
        self._param_widgets: dict[str, Any] = {}
        self._param_list: list[dict] = []

        if self._bridge is not None:
            self._canvas = GraphCanvas(
                # 素材下拉：任务素材库（只有加入的素材才可选）
                element_provider=self._task_element_items,
                scene_provider=self._task_scene_items,
                point_provider=lambda: self._teach_items("points"),
                ocr_provider=lambda: self._teach_items("ocr_regions"),
                # 信号触发器下拉：任务素材库中各场景对应的信号
                signal_provider=self._task_signal_items,
                # OCR读取下拉：任务素材库中的 OCR 识别素材
                ocr_material_provider=self._task_ocr_items,
                # 节点组合：右侧「节点组合」Tab（所选游戏的节点组合库）
                compound_list_provider=self._bridge.compound_list,
                compound_loader=self._bridge.load_compound,
                save_compound_cb=self._bridge.save_compound,
                delete_compound_cb=self._bridge.delete_compound,
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
                scene_commit_callback=self._on_scene_committed,
                element_commit_callback=self._on_element_committed,
                point_commit_callback=self._on_point_committed,
                ocr_commit_callback=self._on_ocr_committed,
                capture_callback=self._bridge.capture_screen,
                # 🏁 结束示教 → 切回流程编排页
                end_teach_callback=lambda: self._right_tabs.setCurrentIndex(0),
            )
        else:
            self._teach_console = TeachConsole(event_bus=self._bus)
        right.addTab(self._teach_console, "画面示教")
        # 排除示教 Tab（2026-08-15）：独立页面，标注图标排除特征
        from ui.visual_builder.exclusion_teach import ExclusionTeachWidget
        self._exclusion_teach = ExclusionTeachWidget(
            assets_dir=self._bridge._assets_dir if self._bridge else "",
            capture_callback=(self._bridge.capture_screen
                              if self._bridge else None),
            icon_list_provider=self._task_element_items,
        )
        right.addTab(self._exclusion_teach, "排除示教")
        # 变量配置 Tab（2026-08-15）：变量组生成输入框，常量组只读展示
        self._var_tab = QWidget()
        var_lay = QVBoxLayout(self._var_tab)
        var_lay.setContentsMargins(8, 8, 8, 8)
        self._var_scroll = QScrollArea()
        self._var_scroll.setWidgetResizable(True)
        self._var_container = QWidget()
        self._var_form = QVBoxLayout(self._var_container)
        self._var_form.setSpacing(8)
        self._var_scroll.setWidget(self._var_container)
        var_lay.addWidget(self._var_scroll, 1)
        right.addTab(self._var_tab, "变量配置")
        self._var_inputs: dict[str, Any] = {}   # 变量键 → 输入控件

        # ── 全局任务 Tab（2026-08-16 信号体系）：任务上层兑底图编辑 ──
        gtab = QWidget()
        gl = QVBoxLayout(gtab)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(4)
        gt_bar = QHBoxLayout()
        gt_lab = QLabel("全局任务：所有任务未处理信号/异常的兑底流程（走完结束节点=原任务安全结束）")
        gt_lab.setStyleSheet("color:#8a94a6;font-size:12px;")
        gt_bar.addWidget(gt_lab)
        gt_bar.addStretch(1)
        self._global_save_btn = QPushButton("💾 保存全局任务")
        self._global_save_btn.clicked.connect(self._save_global_task)
        gt_bar.addWidget(self._global_save_btn)
        gl.addLayout(gt_bar)
        if self._bridge is not None:
            self._global_canvas = GraphCanvas(
                element_provider=self._bridge.icon_items,
                scene_provider=lambda: [s.get("id", "")
                                        for s in self._bridge.scene_list()],
                ocr_provider=self._bridge.ocr_items,
                signal_provider=lambda: [s for s, _ in
                                         (self._bridge.signal_options() or [])],
                compound_list_provider=self._bridge.compound_list,
                compound_loader=self._bridge.load_compound,
                save_compound_cb=self._bridge.save_compound,
                delete_compound_cb=self._bridge.delete_compound,
            )
        else:
            self._global_canvas = GraphCanvas()
        gl.addWidget(self._global_canvas, 1)
        right.addTab(gtab, "全局任务")
        # 加载已有全局任务图（无则空图）
        try:
            from visual import visual_schema as vs
            gt = self._bridge.global_task_load() if self._bridge else {}
            self._global_canvas.load_task(
                gt if gt else vs.default_task("_global_task"))
        except Exception:
            from visual import visual_schema as vs
            self._global_canvas.load_task(vs.default_task("_global_task"))

        self._right_tabs = right
        root.addWidget(right, 1)

        # 切到排除示教页 → 刷新操作识别素材下拉（2026-08-16：
        # 新保存的素材立即可选，无需先点一次截图才能展开正确列表）
        def _on_flow_tab_changed(idx: int) -> None:
            if idx >= 0 and right.widget(idx) is self._exclusion_teach:
                try:
                    self._exclusion_teach.refresh_icons()
                except Exception:
                    pass

        right.currentChanged.connect(_on_flow_tab_changed)

        # 图变更（变量组编辑/加载/增删节点）→ 刷新变量配置页
        self._canvas.graph_changed.connect(self._rebuild_var_tab)

        # 右键菜单「示教」请求
        self._canvas.teach_node_requested.connect(self._on_teach_node_requested)

        # 保存进度节点（2026-08-16）：并入任务定义 + 即时落盘
        self._canvas.progress_group_added.connect(self._on_progress_group_added)

        # 测试运行：当前执行节点红框高亮（事件总线 → Qt 信号跨线程投递）
        self._node_exec_sig.connect(self._canvas.highlight_node)
        self._bus.subscribe(Events.VISUAL_NODE_EXEC, self._on_node_exec)
        # 截图器帧 → 截图器节点内嵌预览
        self._node_img_sig.connect(self._canvas.set_node_preview)
        self._bus.subscribe(Events.VISUAL_IMAGE_PREVIEW, self._on_image_preview)
        # 运行结束（后台线程事件）→ 复位测试/单步按钮状态
        self._teach_done_sig.connect(self._on_teach_finished)
        self._bus.subscribe(Events.VISUAL_TEACH_PROGRESS, self._on_teach_progress)

        self._refresh_open_label()

    # ── 游戏切换 ────────────────────────────────────────
    def on_game_switched(self) -> None:
        """全局游戏切换（主窗口顶部控制栏）→ 刷新画布通用节点/素材下拉"""
        try:
            self._canvas.refresh_compound_list()
            self._canvas.refresh_combos()
        except Exception:
            pass

    # ── 当前打开项状态 ──────────────────────────────────
    def _current_name(self) -> str:
        return self._open_key.get("name", "") if self._open_key else ""

    def _teach_items(self, key: str) -> list[str]:
        """当前打开项的示教产物 ID 列表"""
        if self._open_key is None or self._open_store is None:
            return []
        try:
            data = self._open_store.load(self._current_name())
        except Exception:
            return []
        teach = data.get("teach", {}) or {}
        return [x.get("id", "") for x in teach.get(key, [])]

    def _task_materials(self) -> dict:
        """当前任务素材库 {scenes: [], elements: [], ocr: []}"""
        mats = (self._current_task.get("materials") or {})
        return {"scenes": list(mats.get("scenes", [])),
                "elements": list(mats.get("elements", [])),
                "ocr": list(mats.get("ocr", []))}

    def _task_scene_items(self) -> list[str]:
        """场景判定下拉源：任务素材库中的场景 id"""
        return self._task_materials()["scenes"]

    def _task_signal_items(self) -> list[str]:
        """信号触发器下拉源：任务素材库中每个场景对应的信号名。

        场景保存时录入了「场景信号」（如 模拟器），触发器监听该信号；
        场景无信号时回退用场景 id。去重（多个场景可能同名信号）。
        """
        out: list[str] = []
        seen: set[str] = set()
        for sid in self._task_materials()["scenes"]:
            scene = None
            if self._bridge is not None:
                try:
                    scene = self._bridge.load_scene(sid)
                except Exception:
                    pass
            sig = (scene or {}).get("signal") or sid
            if sig and sig not in seen:
                seen.add(sig)
                out.append(sig)
        return out

    def _task_element_items(self) -> list[str]:
        """点击器下拉源：任务素材库中的图标素材路径"""
        return self._task_materials()["elements"]

    def _task_ocr_items(self) -> list[str]:
        """OCR读取下拉源：任务素材库中的 OCR 识别素材路径"""
        return self._task_materials()["ocr"]

    def _open_material_dialog(self) -> None:
        """📚 素材管理：左全局库 → 右键加入本任务；右任务库 → 移除"""
        if self._open_key is None or self._open_store is None:
            QMessageBox.information(self, "素材管理", "请先「📂 打开任务」")
            return
        if self._bridge is None:
            return
        from ui.visual_builder.material_dialog import MaterialManagerDialog
        mats = self._task_materials()
        dlg = MaterialManagerDialog(
            global_elements=self._bridge.icon_items(),
            global_scenes=self._bridge.scene_list(),
            global_ocr=self._bridge.ocr_items(),
            task_scenes=mats["scenes"],
            task_elements=mats["elements"],
            task_ocr=mats["ocr"],
            parent=self,
        )
        if dlg.exec_() != dlg.Accepted:
            return
        self._current_task.setdefault("materials", {})["scenes"] = \
            dlg.result_materials()["scenes"]
        self._current_task.setdefault("materials", {})["elements"] = \
            dlg.result_materials()["elements"]
        self._current_task.setdefault("materials", {})["ocr"] = \
            dlg.result_materials()["ocr"]
        # 静默保存到任务文件 + 刷新画布下拉
        try:
            self._open_store.save(self._current_task)
        except Exception as e:
            QMessageBox.warning(self, "素材管理", f"保存失败: {e}")
            return
        self._canvas.refresh_combos()

    def _on_teach_node_requested(self, node_id: str, node_type: str) -> None:
        """右键菜单「示教」请求：截一张图录入识别特征"""
        if self._bridge is None:
            return
        self._start_teach(node_id, node_type)

    def _start_teach(self, node_id: str, node_type: str) -> None:
        """截一张图 → 进入画面示教页，目标节点 node_id（带上任务名用于素材目录）"""
        img = self._bridge.capture_screen()
        self._teach_console.begin_manual(img, node_id, node_type,
                                         task_name=self._current_name())
        self._right_tabs.setCurrentWidget(self._teach_console)

    def _on_node_exec(self, **kw) -> None:
        """测试运行节点执行事件（后台线程）→ Qt 信号投递到 UI 线程高亮"""
        nid = kw.get("node_id", "") or ""
        self._node_exec_sig.emit(nid)

    def _on_image_preview(self, **kw) -> None:
        """截图器帧事件（后台线程）→ Qt 信号投递到 UI 线程预览"""
        nid = kw.get("node_id", "") or ""
        data = kw.get("data") or b""
        if nid and data:
            try:
                from loguru import logger as _lg
                _lg.info(f"[预览] 收到截图器帧: {nid} ({len(data)} bytes)")
            except Exception:
                pass
            self._node_img_sig.emit(nid, bytes(data))

    def _on_scene_committed(self, scene: dict, node_id: str) -> str:
        """手动示教提交：场景双写 + 自动加入任务素材 + 回填节点 + 刷新下拉。

        双写（2026-08-15 彻底修复"保存为场景不入库"反复出现）：
        - 素材库（跨任务复用）
        - 任务 teach.scenes（第二存储路径：素材库失败时运行/下拉照样可用）
        返回状态文本供示教页显示，失败原因不再静默吞掉。
        """
        from visual import visual_schema as vs
        sid = scene.get("id", "")
        if not sid:
            return "⚠ 场景保存失败：缺少场景名"
        errors: list[str] = []
        if self._bridge is not None:
            try:
                if not self._bridge.save_scene(scene):
                    errors.append("素材库写入失败（未配置素材库目录）")
            except Exception as e:
                errors.append(f"素材库写入失败: {e}")
        # 任务内副本（第二存储路径）
        try:
            vs.add_scene(self._current_task, scene)
        except Exception as e:
            errors.append(f"任务副本写入失败: {e}")
        # 任务素材库（下拉源）
        mats = self._current_task.setdefault("materials", {})
        scenes = mats.setdefault("scenes", [])
        if sid not in scenes:
            scenes.append(sid)
        if not self._save_materials_silent():
            errors.append("任务文件保存失败")
        if node_id:
            self._canvas.refresh_combos()
            self._canvas.set_node_scene(node_id, sid)
        self._canvas.refresh_combos()
        if errors:
            from loguru import logger as _lg
            _lg.error(f"[场景保存] {sid}: " + "; ".join(errors))
            return f"⚠ 场景「{sid}」已录入任务，但：{'；'.join(errors)}"
        return f"✔ 场景「{sid}」已保存到素材库"

    def _on_element_committed(self, template: str, region: str, node_id: str) -> None:
        """识图元素示教提交：模板已存 assets → 自动加入任务素材 + 回填节点 + 刷新"""
        mats = self._current_task.setdefault("materials", {})
        elems = mats.setdefault("elements", [])
        if template and template not in elems:
            elems.append(template)
            self._save_materials_silent()
        self._canvas.refresh_combos()
        if node_id:
            self._canvas.set_node_element(node_id, template, region or "")

    def _on_ocr_committed(self, template: str, node_id: str) -> None:
        """OCR识别素材示教提交：条目已存 assets → 加入任务素材 + 回填节点 + 刷新"""
        mats = self._current_task.setdefault("materials", {})
        ocr_list = mats.setdefault("ocr", [])
        if template and template not in ocr_list:
            ocr_list.append(template)
            self._save_materials_silent()
        self._canvas.refresh_combos()
        if node_id:
            self._canvas.set_node_element(node_id, template, "")

    def _on_point_committed(self, point: dict, node_id: str) -> None:
        """点击点示教提交：写入任务 teach.points → 保存 → 刷新下拉"""
        teach = self._current_task.setdefault("teach", {})
        points = teach.setdefault("points", [])
        pid = point.get("id", "")
        if pid and not any(p.get("id") == pid for p in points):
            points.append(point)
            self._save_materials_silent()
        self._canvas.refresh_combos()

    def _save_materials_silent(self) -> bool:
        """素材变更后静默保存任务文件（不弹提示）；失败记日志并返回 False"""
        if self._open_store is None:
            return True   # 未打开任务时无文件可写（内存任务仍有效）
        try:
            self._open_store.save(self._current_task)
            return True
        except Exception as e:
            from loguru import logger as _lg
            _lg.error(f"[素材保存] 任务文件保存失败: {e}")
            return False

    def open_task_and_select(self, task_name: str, node_id: str = "") -> None:
        """异常任务「处理」跳转（2026-08-16）：打开任务并红框定位异常节点。"""
        if self._bridge is None:
            return
        try:
            data = self._bridge.load_task(task_name)
        except Exception:
            return
        self._open_key = {"game": self._bridge.current_game,
                          "kind": "task", "name": task_name}
        self._open_store = self._bridge._store
        self._current_task = data or {}
        try:
            self._canvas.load_task(self._current_task)
        except Exception:
            return
        self._refresh_open_label()
        self._right_tabs.setCurrentIndex(0)
        if node_id:
            try:
                self._canvas.highlight_node(node_id)
            except Exception:
                pass

    def _save_global_task(self) -> None:
        """保存全局任务兑底图（2026-08-16）。"""
        if self._bridge is None:
            return
        try:
            task = self._global_canvas.export_task(
                self._bridge.global_task_load() or {})
        except Exception:
            task = self._global_canvas.export_task({})
        ok = self._bridge.global_task_save(task)
        QMessageBox.information(self, "全局任务",
                                "全局任务已保存" if ok else "保存失败")

    def _refresh_open_label(self) -> None:
        if self._open_key is None:
            self._open_label.setText("未打开任务")
            self._save_btn.setEnabled(False)
            self._teach_btn.setEnabled(False)
        else:
            display = self._current_task.get("display_name",
                                             self._current_name())
            self._open_label.setText(
                f"游戏任务：{display}（{self._open_key['game']}）")
            self._save_btn.setEnabled(True)
            self._teach_btn.setEnabled(True)

    # ── 打开任务 ────────────────────────────────────────
    def _open_task(self) -> None:
        if self._bridge is None or self._bridge._profile is None:
            QMessageBox.information(self, "提示", "可视化构建未就绪")
            return
        # 默认游戏 = 全局当前游戏（顶部控制栏选择）
        cur_game = getattr(self._bridge, 'current_game', '') or 'yys'
        dlg = OpenTaskDialog(self._bridge._profile, cur_game, self)
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
        """编程式打开任务到画布（弹窗与测试共用）"""
        if store is None:
            # 按游戏构造任务存储
            try:
                from core.game_profile import GameProfile
                gp = GameProfile(root=self._bridge._profile.root,
                                 game_id=game_id)
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
        self._refresh_open_label()
        # 同步任务名给示教台：右键保存图标素材进正确的任务素材目录
        self._teach_console.set_task_name(name)
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
        # 变量配置页当前输入 → 任务 param_values（与图定义分开存）
        task["param_values"] = self._collect_var_inputs()
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
                self._canvas.refresh_compound_list()
        except Exception:
            pass
        QMessageBox.information(self, "已保存", f"「{name}」已保存")

    # ── 示教运行 / 停止 / 单步 ─────────────────────────
    def _teach_run(self, step_mode: bool = False) -> None:
        if self._bridge is None or self._open_key is None:
            QMessageBox.information(self, "提示", "请先打开任务")
            return
        # 测试启动前置条件：模拟器已连接
        if not self._bridge.is_connected():
            QMessageBox.warning(self, "测试启动", "请先连接模拟器再测试启动")
            return
        # 互斥：正式脚本运行中禁止测试启动
        if self._bridge.is_script_running():
            QMessageBox.warning(self, "测试启动", "脚本正在运行，请先停止脚本")
            return
        # 示教运行仅支持当前游戏的任务
        cur_game = self._bridge._profile.game_id if self._bridge._profile else "yys"
        if self._open_key["game"] != cur_game:
            QMessageBox.information(
                self, "提示",
                "测试启动目前仅支持当前游戏的任务；\n"
                "其它游戏请先保存，再通过调度/任务队列运行")
            return
        self._save()
        name = self._current_name()
        ok = self._bridge.teach_run(name, step_mode=step_mode,
                                    params=self._collect_var_inputs())
        if not ok:
            QMessageBox.warning(self, "测试启动", "测试已在运行或任务加载失败")
            return
        self._stop_btn.setEnabled(True)
        self._teach_btn.setEnabled(False)
        self._step_btn.setEnabled(False)
        self._next_btn.setEnabled(step_mode)
        parent = self._teach_console.parentWidget()
        if isinstance(parent, QTabWidget):
            parent.setCurrentWidget(self._teach_console)

    def _teach_step_next(self) -> None:
        """单步调试：放行一步；运行结束自动禁用"""
        if self._bridge is None:
            return
        self._bridge.teach_step()
        if not self._bridge.teach_step_mode():
            self._next_btn.setEnabled(False)

    def _on_teach_progress(self, **kw) -> None:
        """示教运行日志事件（后台线程）→ 结束信号投递 UI 线程"""
        if kw.get("phase") == "finished":
            self._teach_done_sig.emit()

    def _on_teach_finished(self) -> None:
        """运行结束：复位测试/单步按钮状态"""
        self._next_btn.setEnabled(False)
        self._step_btn.setEnabled(True)
        self._teach_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)

    def _stop(self) -> None:
        if self._bridge is not None:
            self._bridge.teach_stop()
        self._stop_btn.setEnabled(False)
        self._next_btn.setEnabled(False)
        self._teach_btn.setEnabled(True)
        self._step_btn.setEnabled(True)

    def _load_signal_table(self, task: dict) -> None:
        """场景信号表 UI 已移除（2026-08-16）：隐式自动回查不再配置，
        识图失败请显式连线 miss/false 端口。保留空壳兼容旧调用。"""
        return None

    # ── 变量配置（2026-08-15）───────────────────────────
    def _rebuild_var_tab(self) -> None:
        """按当前画布任务重建「变量配置」页：变量组→输入框，常量组→只读。

        触发：图变更信号（变量组编辑保存/任务加载/节点增删）。
        """
        from visual import visual_schema as vs
        while self._var_form.count():
            item = self._var_form.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._var_inputs = {}
        try:
            task = self._canvas.export_task(self._current_task)
        except Exception:
            task = self._current_task
        groups = vs.collect_var_groups(task.get("graph", {}))
        if not groups:
            lab = QLabel(
                "（图中没有变量组/常量组节点——从节点库「变量」分类添加，"
                "点节点上的【详情编辑】定义变量）")
            lab.setWordWrap(True)
            lab.setStyleSheet("color:#8a94a6;padding:8px;")
            self._var_form.addWidget(lab)
            self._var_form.addStretch(1)
            return
        values = vs.effective_param_values(task)
        for g in groups:
            title = g.get("group_name", "变量组")
            if g.get("kind") == "constant_group":
                title = f"📌 {title}（常量·只读）"
            gb = QGroupBox(title)
            # 标题与边框留白（2026-08-16）：标题上移、左对齐组框左边框
            gb.setStyleSheet(
                "QGroupBox {"
                " font-size:12px; font-weight:bold; color:#333;"
                " border:1px solid #c8ccd4; border-radius:4px;"
                " margin-top:8px;"
                " padding:12px 10px 8px 10px;"
                " background:#f7f8fa; }"
                "QGroupBox::title {"
                " subcontrol-origin: margin;"
                " subcontrol-position: top left;"
                " left:0px; padding:0 8px;"
                " background:#f7f8fa; color:#333; }")
            glay = QVBoxLayout(gb)
            glay.setSpacing(4)
            for v in g.get("variables", []):
                key = str(v.get("key", "") or "").strip()
                label = str(v.get("label", "") or key)
                row = QHBoxLayout()
                lab = QLabel(label)
                lab.setFixedWidth(140)
                lab.setToolTip(f"变量键: {key}")
                row.addWidget(lab)
                if g.get("kind") == "constant_group":
                    val_lab = QLabel(str(v.get("value", "")))
                    val_lab.setStyleSheet(
                        "color:#5aa9f0;font-weight:bold;")
                    row.addWidget(val_lab)
                else:
                    w = self._make_var_input(key, v.get("type", "text"),
                                             values.get(key))
                    if v.get("callable"):
                        # 可调用变量（2026-08-16）：默认锁编辑，点 🔒 解锁
                        row.addWidget(self._make_callable_lock(w))
                        if isinstance(w, QLineEdit):
                            w.setReadOnly(True)
                        elif hasattr(w, "setEnabled"):
                            w.setEnabled(False)
                    row.addWidget(w, 1)
                    self._var_inputs[key] = w
                row.addStretch(0)
                glay.addLayout(row)
            self._var_form.addWidget(gb)
        self._var_form.addStretch(1)
        # 重名/跨组冲突提示（不阻断，仅标出）
        conflicts = vs.check_var_conflicts(groups)
        if conflicts:
            cg = QGroupBox("⚠ 变量冲突（运行时以后定义覆盖，建议修正）")
            cg.setStyleSheet(
                "QGroupBox {"
                " font-size:12px; font-weight:bold; color:#333;"
                " border:1px solid #c8ccd4; border-radius:4px;"
                " margin-top:8px;"
                " padding:12px 10px 8px 10px;"
                " background:#f7f8fa; }"
                "QGroupBox::title {"
                " subcontrol-origin: margin;"
                " subcontrol-position: top left;"
                " left:0px; padding:0 8px;"
                " background:#f7f8fa; color:#333; }")
            cl = QVBoxLayout(cg)
            for e in conflicts:
                lab = QLabel("• " + e)
                lab.setStyleSheet("color:#e06c6c;")
                lab.setWordWrap(True)
                cl.addWidget(lab)
            self._var_form.addWidget(cg)

    def _make_var_input(self, key: str, vtype: str, value):
        """按变量类型创建输入控件（int/float/text/bool）"""
        if vtype == "int":
            w = QSpinBox()
            w.setRange(-999999, 999999)
            try:
                w.setValue(int(float(value)))
            except Exception:
                w.setValue(0)
        elif vtype == "float":
            w = QDoubleSpinBox()
            w.setRange(-1e9, 1e9)
            w.setDecimals(3)
            try:
                w.setValue(float(value))
            except Exception:
                w.setValue(0.0)
        elif vtype == "bool":
            w = QCheckBox()
            try:
                w.setChecked(str(value).strip().lower()
                             in ("1", "true", "yes", "是"))
            except Exception:
                w.setChecked(False)
        else:
            w = QLineEdit("" if value is None else str(value))
        w.setToolTip(f"变量键: {key}（其它节点用 ${{{key}}} 引用）")
        return w

    def _on_progress_group_added(self, group: dict) -> None:
        """画布右键「保存为进度节点」→ 并入当前任务 progress_groups（2026-08-16）。

        节点只属于一个组：与新组重叠的节点报错拒绝。
        """
        from uuid import uuid4
        nodes = [str(n) for n in (group.get("nodes") or []) if n]
        if not nodes:
            return
        groups = self._current_task.setdefault("progress_groups", [])
        existing = {n for g in groups for n in (g.get("nodes") or [])}
        overlap = [n for n in nodes if n in existing]
        if overlap:
            QMessageBox.warning(
                self, "保存进度节点",
                f"{len(overlap)} 个节点已属于其它进度组，请调整框选后重试")
            return
        groups.append({
            "id": uuid4().hex[:12],
            "name": str(group.get("name") or "进度点"),
            "nodes": nodes,
        })
        # 已打开的任务 → 即时落盘
        try:
            if self._open_store is not None and self._current_task.get("name"):
                self._open_store.save(self._current_task)
        except Exception:
            pass
        QMessageBox.information(
            self, "保存进度节点",
            f"进度点「{group.get('name')}」已保存（{len(nodes)} 个节点）。\n"
            f"当前任务共 {len(groups)} 个进度点，任务队列将按此显示 o-o-o 进度。")

    def _make_callable_lock(self, input_widget) -> QPushButton:
        """可调用变量：🔒/💾 切换按钮（2026-08-16）。

        运行中由「参数处理」节点改变，UI 默认锁编辑；
        点 🔒 解锁编辑，再点 💾 保存（值随任务保存写入 param_values）。
        """
        btn = QPushButton("🔒")
        btn.setFixedWidth(34)
        btn.setToolTip("可调用变量：运行中由「参数处理」节点实时改变。\n"
                       "点击解锁编辑，再次点击保存。")

        def _toggle():
            if isinstance(input_widget, QLineEdit):
                locked = input_widget.isReadOnly()
                input_widget.setReadOnly(not locked)
                btn.setText("🔒" if locked else "💾")
                btn.setToolTip("编辑完成后点击保存" if not locked
                               else "可调用变量：运行中由「参数处理」节点实时改变。\n"
                                    "点击解锁编辑，再次点击保存。")
            elif hasattr(input_widget, "setEnabled"):
                enabled = input_widget.isEnabled()
                input_widget.setEnabled(not enabled)
                btn.setText("🔒" if enabled else "💾")
                btn.setToolTip("编辑完成后点击保存" if not enabled
                               else "可调用变量：运行中由「参数处理」节点实时改变。\n"
                                    "点击解锁编辑，再次点击保存。")

        btn.clicked.connect(_toggle)
        return btn

    def _collect_var_inputs(self) -> dict:
        """收集变量配置页当前输入（变量键→值；只含变量组，常量组在定义里）"""
        out: dict = {}
        for key, w in self._var_inputs.items():
            if isinstance(w, QSpinBox):
                out[key] = w.value()
            elif isinstance(w, QDoubleSpinBox):
                out[key] = w.value()
            elif isinstance(w, QCheckBox):
                out[key] = w.isChecked()
            elif isinstance(w, QLineEdit):
                out[key] = w.text().strip()
        return out
