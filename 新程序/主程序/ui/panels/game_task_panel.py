"""
UI 子面板：游戏任务面板（任务列表 + 动态配置表单 + 保存）。

按《任务设计指导书》§4：
- 左侧：任务列表（含模块声明标记）
- 右侧：动态配置表单，根据任务 uses_* 声明显示/隐藏对应配置区
- 保存：写回 tasks.yaml（TaskBridge.save_task_config）
"""
from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QPushButton, QScrollArea,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

# 设计书 §5.2 重复规则（单次任务两种模式：每次启动执行 on_enter / 只执行一次 once）
# special / expire_at 已从下拉移除（与 daily/active_range 重叠），代码层保留兼容旧配置
# 2026-08-16 退役：trigger「特殊条件触发」从下拉移除（新体系 = 图内任务信号触发器节点），
# 代码层保留兼容旧配置（渲染旧 trigger 任务时临时插入「已下线」选项，保存不丢字段）
REPEAT_TYPES = [
    ("daily", "每日"),
    ("weekly", "每周"),
    ("monthly_start", "每月初"),
    ("interval_days", "间隔N天"),
    ("interval_hours", "间隔N小时"),
    ("on_enter", "每次启动执行"),
    ("once", "只执行一次"),
]

# 旧 trigger 配置渲染时的兼容选项（不下拉提供，仅回显）
LEGACY_TRIGGER = ("trigger", "特殊条件触发（已下线）")

# 变量/常量组标题与边框留白（2026-08-16）：标题上移、左对齐组框左边框
_VAR_GROUP_QSS = (
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
    " background:#f7f8fa; color:#333; }"
)


class GameTaskPanel(QWidget):
    """游戏任务面板（列表 + 动态配置表单）"""

    # 后台线程事件 → 主线程 UI 更新（可调用变量实时同步，2026-08-16）
    _ui_signal = pyqtSignal(object)

    def __init__(self, param_bridge: Any = None, visual_bridge: Any = None,
                 parent=None):
        super().__init__(parent)
        self._param_bridge = param_bridge
        self._visual_bridge = visual_bridge  # 可视化桥（变量/常量 tab 数据源，2026-08-16）
        self._current_name: str = ""
        self._form_widgets: dict[str, Any] = {}
        self._var_inputs: dict[str, Any] = {}   # 变量配置 tab：变量键 → 输入控件
        self._var_task: dict | None = None      # 当前可视化任务定义（变量 tab 渲染用）
        self._callable_display: dict[str, tuple] = {}  # 可调用变量键 → (值标签, 编辑框)
        self._loaded_next_run: str = ""  # 渲染表单时系统显示的 next_run（区分手动修改）
        self._slot_rows: list = []  # 执行时段动态行 [[开始QLineEdit, 结束QLineEdit], ...]（读取用）
        self._slot_row_widgets: list = []  # 执行时段每行容器 QWidget（整体显隐用，含✕删除按钮）
        self._slot_container: Any = None

        self._ui_signal.connect(lambda fn: fn())

        # 可调用变量实时同步订阅（后台线程 → 信号 → 主线程更新）
        bus = getattr(visual_bridge, "_bus", None)
        if bus is None:
            try:
                from core.event_bus import get_global_bus
                bus = get_global_bus()
            except Exception:
                bus = None
        if bus is not None:
            try:
                from core.events import Events
                bus.subscribe(Events.CALLABLE_VAR_CHANGED,
                              self._on_callable_changed)
            except Exception:
                pass

        layout = QHBoxLayout(self)

        # ── 左侧任务列表 ──────────────────────────────────
        left = QVBoxLayout()
        left.addWidget(QLabel("任务列表"))
        self.task_list = QListWidget()
        self.task_list.currentItemChanged.connect(self._on_task_selected)
        left.addWidget(self.task_list)

        # ── 右侧动态配置表单（滚动区） ────────────────────
        right = QVBoxLayout()
        right.addWidget(QLabel("任务配置"))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.form_container = QWidget()
        self.form_layout = QVBoxLayout(self.form_container)
        self.scroll.setWidget(self.form_container)
        right.addWidget(self.scroll, 1)

        layout.addLayout(left, 1)
        layout.addLayout(right, 2)

    # ── 数据加载 ─────────────────────────────────────────────

    def load_tasks(self, metas: list[dict[str, Any]]) -> None:
        """加载任务元数据列表（由 MainWindow 调用，设计书 §4.3）"""
        self.task_list.blockSignals(True)
        self.task_list.clear()
        for meta in metas:
            name = meta.get("name", "")
            display = meta.get("display_name", "") or name
            task_type = meta.get("task_type", "event_task")
            label = f"{display}  [{task_type}]"
            self.task_list.addItem(label)
            item = self.task_list.item(self.task_list.count() - 1)
            item.setData(Qt.UserRole, name)
            # 标记战斗任务
            if meta.get("uses_battle"):
                item.setToolTip("战斗任务：含战斗配置区")
            elif meta.get("is_visual"):
                item.setToolTip("可视化任务：变量/常量参数 + 调度推送设置")
        self.task_list.blockSignals(False)
        # 默认选中第一个
        if self.task_list.count() > 0:
            self.task_list.setCurrentRow(0)

    # ── 选择任务 → 渲染表单 ────────────────────────────────

    def _on_task_selected(self, current, previous) -> None:
        if current is None:
            return
        name = current.data(Qt.UserRole)
        if not name:
            return
        self._current_name = name
        detail = self._get_detail(name)
        self._render_form(detail)

    def _get_detail(self, name: str) -> dict[str, Any]:
        """从 TaskBridge 获取任务详情（声明 + 配置）"""
        bridge = self._param_bridge
        if bridge and hasattr(bridge, 'task') and hasattr(bridge.task, 'get_task_detail'):
            try:
                return bridge.task.get_task_detail(name)
            except Exception:
                pass
        return {"name": name, "display_name": name}

    def refresh_next_run_time(self) -> None:
        """
        实时同步「下次执行」输入框（任务执行完/被中断后，由 MainWindow 调用）。

        从调度器查询最新 next_run_time 更新到输入框与 _loaded_next_run；
        若用户正在手动编辑（输入框内容 ≠ 已加载值）则跳过，避免覆盖编辑中的内容
        （保存时 _save 会走 update_next_run 手动指定路径）。
        """
        if not self._current_name:
            return
        ed = self._form_widgets.get("next_run_time")
        if ed is None:
            return
        bridge = self._param_bridge
        if not (bridge and hasattr(bridge, 'task')
                and hasattr(bridge.task, 'get_next_run_time')):
            return
        # 用户正在手动编辑 → 跳过（防止实时同步覆盖手输值）
        cur_text = ed.text().strip()
        if cur_text and cur_text != self._loaded_next_run:
            return
        try:
            nrt = bridge.task.get_next_run_time(self._current_name)
            new_text = nrt or ""
            if new_text != self._loaded_next_run:
                ed.setText(new_text)
                self._loaded_next_run = new_text
        except Exception:
            pass

    def _get_signal_options(self) -> list[tuple[str, str]]:
        """触发信号下拉：优先 SceneStore 场景信号（素材库重构后，2026-08-16）。

        返回 [(信号名, 显示标签), ...]。回退旧 manifest（scene/ 素材 signal）。
        """
        # 新源：SceneStore 场景（visual_bridge.signal_options → [(信号, 场景id)]）
        vb = getattr(self, "_visual_bridge", None)
        if vb is not None and hasattr(vb, 'signal_options'):
            try:
                opts = vb.signal_options()
                if opts:
                    return [(sig, f"场景:{sid}") for sig, sid in opts]
            except Exception:
                pass
        # 旧源：assets manifest（兼容未重构的旧素材）
        try:
            from core.asset_meta import AssetMetaStore
            from core.game_profile import current_game_assets
            assets_dir = current_game_assets()
            meta = AssetMetaStore(assets_dir)
            # all_signals: {素材识别名: 信号名}
            return [(sig, rel) for rel, sig in meta.all_signals().items() if sig]
        except Exception:
            return []

    def _get_sub_options(self) -> list[tuple[str, str]]:
        """
        从「小号管理」（AccountBridge）读取启用的 sub 账号。
        返回 [(account_id, 显示名), ...]；无账号管理数据时返回空列表。
        """
        bridge = self._param_bridge
        if not (bridge and hasattr(bridge, 'account')):
            return []
        try:
            accounts = bridge.account.get_all_accounts()
        except Exception:
            return []
        opts: list[tuple[str, str]] = []
        for a in accounts or []:
            role = getattr(a, 'role', None)
            if role != "sub":
                continue
            if not getattr(a, 'enabled', True):
                continue
            aid = getattr(a, 'account_id', '') or ''
            if not aid:
                continue
            name = getattr(a, 'name', '') or aid
            opts.append((aid, f"{name}（{aid}）"))
        return opts

    # ── 动态表单渲染（设计书 §4.2 预览） ──────────────────

    def _clear_form(self) -> None:
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._form_widgets.clear()

    def _render_form(self, detail: dict[str, Any]) -> None:
        self._clear_form()
        self._var_inputs = {}
        self._var_task = None
        self._callable_display = {}
        w = self._form_widgets
        name = detail.get("name", "")
        display = detail.get("display_name", "") or name
        task_type = detail.get("task_type", "event_task")

        # 标题
        title = QLabel(f"📋 {display}")
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        self.form_layout.addWidget(title)
        subtitle = QLabel(f"{task_type} · {detail.get('description', '')}")
        subtitle.setStyleSheet("color:#888;")
        self.form_layout.addWidget(subtitle)

        # ☑ 启用
        cb_enabled = QCheckBox("启用此任务")
        cb_enabled.setChecked(bool(detail.get("enabled", True)))
        w["enabled"] = cb_enabled
        self.form_layout.addWidget(cb_enabled)

        # ── Tab：执行配置（+ 可视化任务专属变量/常量 Tab，2026-08-16） ──
        tabs = QTabWidget()

        # ══════════ Tab1 执行配置 ══════════
        tab_exec = QWidget()
        te = QVBoxLayout(tab_exec)
        te.setContentsMargins(6, 6, 6, 6)

        # ── ⏱ 时间调度（必配） ──
        from ui.theme import panel_group
        g_sched, sched_content = panel_group("⏱ 时间调度（必配）")
        f_sched = QFormLayout()
        sched_content.addLayout(f_sched)

        # 重复规则：下拉选框（选择后联动显隐对应属性区）
        repeat = detail.get("repeat") or {}
        rep_type = repeat.get("type", "daily") if isinstance(repeat, dict) else "daily"
        lbl_repeat = QLabel("重复规则:")
        cb_repeat = QComboBox()
        for val, label in REPEAT_TYPES:
            cb_repeat.addItem(label, val)
        # 旧 trigger 配置兼容：下拉额外插入「已下线」选项用于回显，
        # 切换走后再选不回该类型（新任务无法创建 trigger）
        if rep_type == "trigger" and cb_repeat.findData("trigger") < 0:
            cb_repeat.addItem(LEGACY_TRIGGER[1], LEGACY_TRIGGER[0])
        idx = cb_repeat.findData(rep_type)
        cb_repeat.setCurrentIndex(idx if idx >= 0 else 0)
        f_sched.addRow(lbl_repeat, cb_repeat)
        w["repeat_type"] = cb_repeat
        w["repeat_type_label"] = lbl_repeat
        # 切换 → 联动显隐
        cb_repeat.currentIndexChanged.connect(self._update_repeat_fields)

        # ── trigger 旧字段兼容（2026-08-16 退役）：
        # 触发信号多选下拉已移除（新体系 = 图内任务信号触发器节点）；
        # 旧 trigger 配置的 trigger_templates 渲染时留存，保存时不丢失
        self._legacy_trigger_templates = [
            str(t) for t in ((repeat.get("trigger_templates")
                              if isinstance(repeat, dict)
                              else getattr(repeat, 'trigger_templates', None))
                             or [])]

        # 每周几（weekly 专属，多选：如每周三、周六都可执行；全不选=每天）
        wd_widget = QWidget()
        wd_row = QHBoxLayout(wd_widget)
        wd_row.setContentsMargins(0, 0, 0, 0)
        wd_row.setSpacing(6)
        wd_checks: dict[int, QCheckBox] = {}
        for label, val in [("周一", 0), ("周二", 1), ("周三", 2), ("周四", 3),
                           ("周五", 4), ("周六", 5), ("周日", 6)]:
            _cb = QCheckBox(label)
            wd_checks[val] = _cb
            wd_row.addWidget(_cb)
        wd_row.addStretch()
        # 读取：weekdays（多选）优先，回退 weekday（单值）
        rep_weekdays = None
        if isinstance(repeat, dict):
            rep_weekdays = repeat.get("weekdays") or (
                [repeat["weekday"]] if repeat.get("weekday") is not None else None)
        for val, _cb in wd_checks.items():
            _cb.setChecked(rep_weekdays is not None and val in rep_weekdays)
        lbl_weekday = QLabel("每周几:")
        f_sched.addRow(lbl_weekday, wd_widget)
        w["weekday_label"] = lbl_weekday
        w["weekday"] = wd_widget
        w["weekday_checks"] = wd_checks

        # 间隔值（interval_days/interval_hours 专属，label 按类型动态）
        sp_interval = QSpinBox()
        sp_interval.setRange(1, 9999)
        sp_interval.setValue(int((repeat.get("value") or 1) if isinstance(repeat, dict) else 1))
        sp_interval.setToolTip("间隔N小时：与执行时段组合时，在时段内每隔 N 小时触发一次；\n"
                               "超出当前时段自动跳到下一时段起点。")
        lbl_interval = QLabel("间隔值:")
        f_sched.addRow(lbl_interval, sp_interval)
        w["interval_label"] = lbl_interval
        w["interval"] = sp_interval

        # 每月几号（monthly_start 专属，1~28）
        sp_month = QSpinBox()
        sp_month.setRange(1, 28)
        sp_month.setValue(int((repeat.get("monthly_day") if isinstance(repeat, dict)
                               else 1) or 1))
        sp_month.setToolTip("每月第几天执行（1~28）")
        lbl_month = QLabel("每月几号:")
        f_sched.addRow(lbl_month, sp_month)
        lbl_month.setVisible(False)
        sp_month.setVisible(False)
        w["monthly_day_label"] = lbl_month
        w["monthly_day"] = sp_month

        # ── 执行时段（1 个 = time_start/time_end；2+ 个 = time_slots） ──
        self._slot_rows = []
        self._slot_row_widgets = []
        self._slot_container = QVBoxLayout()
        slots = detail.get("time_slots") or []
        if len(slots) >= 2:
            for s, e in slots:
                self._add_slot_row(str(s or ""), str(e or ""))
        else:
            self._add_slot_row(detail.get("time_start") or "06:00",
                               detail.get("time_end") or "23:59")
        lbl_slot = QLabel("执行时段:")
        f_sched.addRow(lbl_slot, self._slot_container)
        btn_add_slot = QPushButton("➕ 添加时段")
        slot_holder = QWidget()
        sh = QHBoxLayout(slot_holder)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.addWidget(btn_add_slot)
        sh.addStretch(1)
        btn_add_slot.clicked.connect(lambda: self._add_slot_row("", ""))
        f_sched.addRow("", slot_holder)
        w["slot_label"] = lbl_slot
        w["slot_holder"] = slot_holder
        w["add_slot_btn"] = btn_add_slot

        sp_daily = QSpinBox()
        sp_daily.setRange(0, 999)
        sp_daily.setSpecialValueText("不限")
        sp_daily.setValue(int(detail.get("max_daily") or 0))
        sp_daily.setToolTip("任务在活动周期内被触发的次数上限（0=不限）。\n"
                            "每次触发会执行包含循环体在内的全部步骤直到任务完成；\n"
                            "达到该次数后任务进入失效区。")
        lbl_daily = QLabel("周期触发次数:")
        f_sched.addRow(lbl_daily, sp_daily)
        w["max_daily_label"] = lbl_daily
        w["max_daily"] = sp_daily

        # 活动有效期（active_range，如 7/21–10/1）
        ar = detail.get("active_range") or []
        ed_ar_start = QLineEdit(str(ar[0]) if ar and ar[0] else "")
        ed_ar_start.setPlaceholderText("YYYY-MM-DD 留空不限")
        lbl_ar_start = QLabel("开始日期:")
        f_sched.addRow(lbl_ar_start, ed_ar_start)
        w["active_start_label"] = lbl_ar_start
        w["active_range_start"] = ed_ar_start
        ed_ar_end = QLineEdit(str(ar[1]) if len(ar) > 1 and ar[1] else "")
        ed_ar_end.setPlaceholderText("YYYY-MM-DD 留空不限")
        lbl_ar_end = QLabel("结束日期:")
        f_sched.addRow(lbl_ar_end, ed_ar_end)
        w["active_end_label"] = lbl_ar_end
        w["active_range_end"] = ed_ar_end

        # 活动循环次数（2026-08-16 移除）：改为图内「可调用变量 + 参数处理 + 判断」实现，
        # 不在执行配置中设定（详见示教节点设计构想.md 第十四节）

        te.addWidget(g_sched)

        # ── 其他：优先级 / 下次执行 ──
        g_other, other_content = panel_group("其他")
        f_other = QFormLayout()
        other_content.addLayout(f_other)
        sp_priority = QSpinBox()
        sp_priority.setRange(1, 99)
        sp_priority.setValue(int(detail.get("priority") or 10))
        f_other.addRow("优先级:", sp_priority)
        w["priority"] = sp_priority

        ed_next = QLineEdit(detail.get("next_run_time") or "")
        ed_next.setPlaceholderText("如 2026-07-31 08:00（留空自动计算）")
        f_other.addRow("下次执行:", ed_next)
        w["next_run_time"] = ed_next
        self._loaded_next_run = detail.get("next_run_time") or ""

        te.addWidget(g_other)
        te.addStretch(1)
        tabs.addTab(tab_exec, "⚙ 执行配置")

        # ══════════ Tab2/3 变量配置 + 常量展示（可视化任务专属，2026-08-16）
        # 旧「⚔ 战斗配置」Tab 已取消（业务参数由变量组/常量组承载）
        is_visual = bool(detail.get("is_visual"))
        if is_visual:
            self._var_task = self._load_visual_task(name)
            tabs.addTab(self._make_var_tab(), "🔢 变量配置")
            tabs.addTab(self._make_const_tab(), "📌 常量展示")

        self.form_layout.addWidget(tabs)

        # 💾 保存
        btn_save = QPushButton("💾 保存配置")
        btn_save.clicked.connect(self._save)
        self.form_layout.addWidget(btn_save)

        # 初始化重复规则联动状态
        self._update_repeat_fields()

        self.form_layout.addStretch()

    # ══════ 变量配置 / 常量展示（可视化任务专属，2026-08-16）══════

    def _load_visual_task(self, name: str) -> dict | None:
        """从可视化桥加载任务定义（变量/常量数据源）"""
        vb = self._visual_bridge
        if vb is None:
            return None
        try:
            task = vb.get_task(name)
            if task is None and hasattr(vb, 'load_task'):
                task = vb.load_task(name)
            return task or None
        except Exception:
            return None

    def _visual_groups(self, task: dict):
        """可视化任务变量组/常量组定义（按图内节点收集）"""
        from visual import visual_schema as vs
        try:
            return vs.collect_var_groups(task.get("graph", {}))
        except Exception:
            return []

    def _make_var_tab(self) -> QWidget:
        """🔢 变量配置：变量组按组名分组显示输入框，初值=任务 param_values"""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)
        self._var_inputs = {}
        task = self._var_task or {}
        groups = [g for g in self._visual_groups(task)
                  if g.get("kind") != "constant_group"]
        if not groups:
            lab = QLabel("（该任务图中没有变量组节点——\n"
                         "在可视化构建的节点库「变量」分类添加变量组并编辑变量）")
            lab.setWordWrap(True)
            lab.setStyleSheet("color:#8a94a6;padding:8px;")
            lay.addWidget(lab)
            lay.addStretch(1)
            return page
        from visual import visual_schema as vs
        values = vs.effective_param_values(task)
        # 可调用变量：运行值（跨运行保留）优先于 param_values 初值
        if (self._visual_bridge is not None
                and hasattr(self._visual_bridge, "callable_var_values")):
            try:
                values.update(self._visual_bridge.callable_var_values(
                    self._current_name))
            except Exception:
                pass
        for g in groups:
            gb = QGroupBox(f"🔢 {g.get('group_name', '变量组')}")
            gb.setStyleSheet(_VAR_GROUP_QSS)
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
                if v.get("callable"):
                    # 可调用变量：默认锁编辑，运行中实时刷新
                    row.addWidget(self._make_callable_var_row(
                        key, v.get("type", "text"), values.get(key)), 1)
                else:
                    wgt = self._make_var_input(key, v.get("type", "text"),
                                               values.get(key))
                    row.addWidget(wgt, 1)
                    self._var_inputs[key] = wgt
                glay.addLayout(row)
            lay.addWidget(gb)
        lay.addStretch(1)
        return page

    def _make_callable_var_row(self, key: str, vtype: str, value) -> QWidget:
        """可调用变量行（2026-08-16）：值标签 + 隐藏编辑框 + 🔒/💾 切换。

        默认锁编辑（显示实时值）；点 🔒 → 编辑框出现；改完点 💾 →
        写入运行值文件（同步到任务）并回到锁态。
        """
        holder = QWidget()
        h = QHBoxLayout(holder)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        text = "" if value is None else str(value)
        val_lab = QLabel(text)
        val_lab.setStyleSheet("color:#5aa9f0;font-weight:bold;")
        edit = QLineEdit(text)
        edit.hide()
        btn = QPushButton("🔒")
        btn.setFixedWidth(34)
        btn.setToolTip("可调用变量：运行中由「参数处理」节点实时改变。\n"
                       "点击解锁编辑，再次点击保存同步到任务。")

        def _toggle():
            if edit.isVisible():
                # 保存：写入运行值文件（跨运行生效）
                val = self._coerce_var_value(edit.text().strip(), vtype)
                if (self._visual_bridge is not None
                        and hasattr(self._visual_bridge, "set_callable_var")):
                    try:
                        self._visual_bridge.set_callable_var(
                            self._current_name, key, val)
                    except Exception:
                        pass
                val_lab.setText(str(val))
                edit.hide()
                val_lab.show()
                btn.setText("🔒")
                btn.setToolTip("可调用变量：运行中由「参数处理」节点实时改变。\n"
                               "点击解锁编辑，再次点击保存同步到任务。")
            else:
                edit.setText(val_lab.text())
                val_lab.hide()
                edit.show()
                edit.setFocus()
                btn.setText("💾")
                btn.setToolTip("编辑完成后点击保存")

        btn.clicked.connect(_toggle)
        h.addWidget(val_lab, 1)
        h.addWidget(edit, 1)
        h.addWidget(btn)
        self._callable_display[key] = (val_lab, edit)
        return holder

    @staticmethod
    def _coerce_var_value(txt: str, vtype: str):
        """按变量类型转换手动编辑的文本"""
        try:
            if vtype == "int":
                return int(float(txt))
            if vtype == "float":
                return float(txt)
            if vtype == "bool":
                return txt.strip().lower() in ("1", "true", "yes", "是")
        except Exception:
            pass
        return txt

    def _on_callable_changed(self, **kw) -> None:
        """（后台线程）参数处理改变可调用变量 → 投递主线程更新显示"""
        self._ui_signal.emit(lambda: self._ui_callable_changed(
            kw.get("task_id", ""), kw.get("key", ""), kw.get("value")))

    def _ui_callable_changed(self, task_id: str, key: str, value) -> None:
        """（主线程）更新当前任务的可调用变量实时值"""
        if not task_id or task_id != self._current_name:
            return
        widgets = self._callable_display.get(key)
        if not widgets:
            return
        lab, edit = widgets
        text = "" if value is None else str(value)
        edit.setText(text)
        if not edit.isVisible():
            lab.setText(text)

    # ══════ 常量展示（可视化任务专属，2026-08-16）══════

    def _make_const_tab(self) -> QWidget:
        """📌 常量展示：常量组按组名分组只读展示"""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)
        task = self._var_task or {}
        groups = [g for g in self._visual_groups(task)
                  if g.get("kind") == "constant_group"]
        if not groups:
            lab = QLabel("（该任务图中没有常量组节点——\n"
                         "在可视化构建的节点库「变量」分类添加常量组）")
            lab.setWordWrap(True)
            lab.setStyleSheet("color:#8a94a6;padding:8px;")
            lay.addWidget(lab)
            lay.addStretch(1)
            return page
        for g in groups:
            gb = QGroupBox(f"📌 {g.get('group_name', '常量组')}（只读）")
            gb.setStyleSheet(_VAR_GROUP_QSS)
            glay = QVBoxLayout(gb)
            glay.setSpacing(4)
            for v in g.get("variables", []):
                key = str(v.get("key", "") or "").strip()
                label = str(v.get("label", "") or key)
                row = QHBoxLayout()
                lab = QLabel(label)
                lab.setFixedWidth(140)
                lab.setToolTip(f"常量键: {key}")
                row.addWidget(lab)
                val_lab = QLabel(str(v.get("value", "")))
                val_lab.setStyleSheet("color:#5aa9f0;font-weight:bold;")
                row.addWidget(val_lab)
                row.addStretch(1)
                glay.addLayout(row)
            lay.addWidget(gb)
        lay.addStretch(1)
        return page

    def _make_var_input(self, key: str, vtype: str, value):
        """按变量类型创建输入控件（int/float/bool/text）"""
        if vtype == "int":
            w = QSpinBox()
            w.setRange(-999999, 999999)
            try:
                w.setValue(int(float(value)))
            except Exception:
                w.setValue(0)
        elif vtype == "float":
            from PyQt5.QtWidgets import QDoubleSpinBox
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

    def _collect_var_inputs(self) -> dict:
        """收集变量配置 tab 当前输入（变量键 → 值）"""
        from PyQt5.QtWidgets import QDoubleSpinBox
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

    def _save_var_inputs(self) -> None:
        """变量配置输入 → 写回可视化任务 param_values"""
        vb = self._visual_bridge
        if vb is None or self._var_task is None or not self._var_inputs:
            return
        name = self._var_task.get("name", "") or self._current_name
        try:
            task = vb.load_task(name)
        except Exception:
            return
        if not task:
            return
        task["param_values"] = self._collect_var_inputs()
        try:
            vb.save_task(task)
        except Exception:
            pass

    # ── 执行时段动态行 ────────────────────────────────────────

    def _add_slot_row(self, start: str = "", end: str = "") -> None:
        """添加一行执行时段（开始 ~ 结束）"""
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        ed_s = QLineEdit(start)
        ed_s.setPlaceholderText("HH:MM")
        ed_s.setMaximumWidth(80)
        ed_e = QLineEdit(end)
        ed_e.setPlaceholderText("HH:MM")
        ed_e.setMaximumWidth(80)
        btn_del = QPushButton("✕")
        btn_del.setMaximumWidth(28)
        btn_del.setFixedHeight(26)
        # 覆盖全局 QPushButton padding(5px 14px)：28px 宽被左右 padding 挤掉内容，只显示一个点
        btn_del.setStyleSheet("padding: 0px 2px; font-size: 14px; font-weight: normal;")
        btn_del.setToolTip("删除该时段")
        pair = [ed_s, ed_e]
        row.addWidget(ed_s)
        row.addWidget(QLabel("~"))
        row.addWidget(ed_e)
        row.addWidget(btn_del)
        row.addStretch(1)
        self._slot_container.addWidget(row_widget)
        self._slot_rows.append(pair)
        self._slot_row_widgets.append(row_widget)
        btn_del.clicked.connect(lambda: self._remove_slot_row(row_widget, pair))
        # 时段数量变化 → 重新评估执行模式（多时段强制 per_slot）
        self._update_repeat_fields()

    def _remove_slot_row(self, row_widget: QWidget, pair: list) -> None:
        """删除一行执行时段（至少保留一行）"""
        if len(self._slot_rows) <= 1:
            return
        for i in range(self._slot_container.count()):
            item = self._slot_container.itemAt(i)
            if item is not None and item.widget() is row_widget:
                self._slot_container.removeItem(item)
                break
        row_widget.deleteLater()
        if pair in self._slot_rows:
            self._slot_rows.remove(pair)
        if row_widget in self._slot_row_widgets:
            self._slot_row_widgets.remove(row_widget)
        # 时段数量变化 → 重新评估执行模式（单时段可自由切换 daily/per_slot）
        self._update_repeat_fields()

    # ── 重复规则联动（下拉选框）─────────────────────────

    def _current_repeat_type(self) -> str:
        """当前选中的重复规则类型（下拉选框）"""
        rt = self._form_widgets.get("repeat_type")
        if rt is not None:
            try:
                return rt.currentData() or "daily"
            except Exception:
                return "daily"
        return "daily"

    def _update_repeat_fields(self, *args) -> None:
        """按重复规则类型显隐对应属性区（下拉选框联动）。

        每类规则只展示其相关属性：
        每周几(weekday) 仅 weekly
          间隔值(interval) 仅 interval_days/hours（label 动态"间隔N天/间隔N小时"）
          trigger          → 触发信号
        trigger/on_enter/once → 无执行时段
          周期触发次数 / 活动有效期 / 活动循环次数 → 所有类型展示
        """
        w = self._form_widgets
        rtype = self._current_repeat_type()
        is_trigger = (rtype == "trigger")
        # 无时间调度的类型：trigger / on_enter（每次启动执行）/ once（只执行一次）
        no_schedule = rtype in ("trigger", "on_enter", "once")

        def _vis(key: str, visible: bool) -> None:
            c = w.get(key)
            if c is not None:
                c.setVisible(visible)

        # 每周几：仅 weekly
        show_weekly = (rtype == "weekly")
        _vis("weekday_label", show_weekly)
        _vis("weekday", show_weekly)

        # 每月几号：仅 monthly_start
        show_monthly = (rtype == "monthly_start")
        _vis("monthly_day_label", show_monthly)
        _vis("monthly_day", show_monthly)

        # 间隔值：interval_days / interval_hours，label 按类型动态
        show_interval = rtype in ("interval_days", "interval_hours")
        _vis("interval_label", show_interval)
        _vis("interval", show_interval)
        il = w.get("interval_label")
        if il is not None:
            if rtype == "interval_days":
                il.setText("间隔值(天):")
            elif rtype == "interval_hours":
                il.setText("间隔值(小时):")

        # 触发信号（trigger 专属）
        _vis("trigger_label", is_trigger)
        _vis("trigger_templates", is_trigger)

        # 执行时段：非 trigger/on_enter/once 展示（整行容器含✕删除按钮）
        _vis("slot_label", not no_schedule)
        _vis("slot_holder", not no_schedule)
        for rw in getattr(self, "_slot_row_widgets", []) or []:
            rw.setVisible(not no_schedule)
        ab = w.get("add_slot_btn")
        if ab is not None:
            ab.setVisible(not no_schedule)

        # 活动有效期：无时间调度（trigger/on_enter/once）隐藏（时间相关，避免遗留）
        _vis("active_start_label", not no_schedule)
        _vis("active_range_start", not no_schedule)
        _vis("active_end_label", not no_schedule)
        _vis("active_range_end", not no_schedule)

        # 周期触发次数（max_daily）：所有类型展示（含 trigger）——不隐藏
        # 活动循环次数（total_count）：所有类型展示（含 trigger）——不隐藏
        # （执行模式 execution_mode 已移除——调度层多时段固定按每时段各执行一次）

    # ── 保存（设计书 §5.1 字段写回 tasks.yaml） ────────────

    def _collect_config(self) -> dict[str, Any]:
        """收集表单值 → tasks.yaml 配置 dict

        ⚠️ 2026-08-16：「循环次数」(loop_count) 与「战斗配置」已由变量组/常量组
        承载，UI 不再写入（tasks.yaml 旧字段保留兼容，不主动覆盖）。
        """
        w = self._form_widgets
        rtype = self._current_repeat_type()
        repeat_dict: dict[str, Any] = {"type": rtype, "value": 1}
        if rtype in ("interval_days", "interval_hours"):
            repeat_dict["value"] = w["interval"].value()
        elif rtype == "weekly":
            wd_checks = w.get("weekday_checks") or {}
            selected = [val for val, _cb in wd_checks.items() if _cb.isChecked()]
            if selected:
                repeat_dict["weekdays"] = selected
        elif rtype == "monthly_start":
            repeat_dict["monthly_day"] = w["monthly_day"].value()

        # 活动有效期（两个日期都留空 → 不写）
        ar_start = w["active_range_start"].text().strip()
        ar_end = w["active_range_end"].text().strip()
        active_range = None
        if ar_start or ar_end:
            active_range = [ar_start or None, ar_end or None]

        # 执行时段：trigger/on_enter/once 无时间配置；否则 1 行 → time_start/time_end；2+ 行 → time_slots
        is_trigger = (rtype == "trigger")
        no_schedule = rtype in ("trigger", "on_enter", "once")
        if no_schedule:
            # 触发式任务：识别列表写入 repeat.trigger_templates，时间字段全部置空
            # 输入为 MultiSelectCombo（信号名多选）或 QLineEdit（旧文本输入）两种形态；
            # 2026-08-16 退役后不再渲染触发控件 → 留存旧值（不丢字段）
            templates = []
            if is_trigger:
                tt = w.get("trigger_templates")
                if tt is not None:
                    from ui.widgets.multi_select_combo import MultiSelectCombo
                    if isinstance(tt, MultiSelectCombo):
                        templates = [str(d) for d in tt.selected_data()]
                    else:
                        templates = [t.strip() for t in tt.text().split(",") if t.strip()]
                else:
                    templates = list(getattr(self, "_legacy_trigger_templates",
                                             []) or [])
            if templates:
                repeat_dict["trigger_templates"] = templates
            time_start, time_end, time_slots = None, None, None
        else:
            slot_pairs = []
            for ed_s, ed_e in getattr(self, "_slot_rows", []) or []:
                s = ed_s.text().strip()
                e = ed_e.text().strip()
                slot_pairs.append([s, e])
            slot_pairs = [p for p in slot_pairs if p[0] or p[1]]
            if len(slot_pairs) >= 2:
                time_start, time_end, time_slots = None, None, slot_pairs
            elif len(slot_pairs) == 1:
                time_start, time_end, time_slots = (
                    slot_pairs[0][0] or None, slot_pairs[0][1] or None, None)
            else:
                time_start, time_end, time_slots = None, None, None

        config: dict[str, Any] = {
            "enabled": w["enabled"].isChecked(),
            "priority": w["priority"].value(),
            "time_start": time_start,
            "time_end": time_end,
            "time_slots": time_slots,
            "max_daily": (w["max_daily"].value() or None),  # 周期触发次数（所有类型）
            "repeat": repeat_dict,  # loop_count 只存 repeat 内（scheduler 优先读取），顶层不再重复存储
            "active_range": None if is_trigger else active_range,
        }
        if "max_fail_streak" in w:
            config["max_fail_streak"] = w["max_fail_streak"].value()
        return config

    def _save(self) -> None:
        """保存当前表单到 tasks.yaml（通过 TaskBridge）"""
        if not self._current_name:
            return
        bridge = self._param_bridge
        if not bridge or not hasattr(bridge, 'task'):
            return
        config = self._collect_config()
        try:
            bridge.task.save_task_config(self._current_name, config)

            # 手动更改任务配置 → 重置该任务周期进度（下次从第 1 次开始执行）
            # （周期任务断点续跑语义：改配置即重新开始一个周期）
            run_bridge = getattr(bridge, 'run', None)
            if run_bridge is not None and hasattr(run_bridge, 'reset_task_cycle'):
                try:
                    run_bridge.reset_task_cycle(self._current_name)
                except Exception:
                    pass

            # 下次执行时间输入框
            nrt_widget = self._form_widgets.get("next_run_time")
            nrt_text = nrt_widget.text().strip() if nrt_widget else ""

            # 仅当用户手动修改了「下次执行」才走 update_next_run
            # （系统显示的值未改 → 热重载使配置生效 + 自动计算/提前评估）
            if nrt_text and nrt_text != self._loaded_next_run:
                # 用户手动指定 → 直接写入调度器（不热重载，避免覆盖）
                from datetime import datetime
                try:
                    bridge.task.update_next_run(
                        self._current_name,
                        datetime.fromisoformat(nrt_text),
                    )
                except ValueError:
                    # 非法日期 → 降级为热重载（避免配置变更静默不生效）
                    if hasattr(bridge.task, 'reload_scheduler'):
                        bridge.task.reload_scheduler(self._current_name)
            else:
                # 未指定 / 系统值未修改 → 热重载配置（保存立即生效）+ 自动计算下次执行
                if hasattr(bridge.task, 'reload_scheduler'):
                    bridge.task.reload_scheduler(self._current_name)

            # 查询下次执行时间并显示
            nrt = bridge.task.get_next_run_time(self._current_name) if hasattr(
                bridge.task, 'get_next_run_time') else None
            if nrt:
                if nrt_widget:
                    nrt_widget.setText(nrt)
                self._show_status(f"✅ 已保存 · 下次执行: {nrt}")
            else:
                self._show_status("✅ 配置已保存")
            # 可视化任务：变量配置输入写回任务 param_values
            self._save_var_inputs()
        except Exception:
            self._show_status("保存失败")

    def _show_status(self, message: str) -> None:
        """在表单底部显示保存状态"""
        for i in range(self.form_layout.count()):
            item = self.form_layout.itemAt(i)
            w = item.widget() if item else None
            if w is not None and getattr(w, "_status_label", False):
                w.setText(message)
                return
        label = QLabel(message)
        label._status_label = True
        label.setStyleSheet("color:#4CAF50;")
        self.form_layout.addWidget(label)

