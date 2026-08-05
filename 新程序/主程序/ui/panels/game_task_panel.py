"""
UI 子面板：游戏任务面板（任务列表 + 动态配置表单 + 保存）。

按《任务设计指导书》§4：
- 左侧：任务列表（含模块声明标记）
- 右侧：动态配置表单，根据任务 uses_* 声明显示/隐藏对应配置区
- 保存：写回 tasks.yaml（TaskBridge.save_task_config）
"""
from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QPushButton, QScrollArea, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget,
)

# 设计书 §5.2 重复规则（on_enter 由配置文件直接设置，不在表单下拉）
REPEAT_TYPES = [
    ("daily", "每日"),
    ("weekly", "每周"),
    ("monthly_start", "每月初"),
    ("interval_days", "间隔N天"),
    ("interval_hours", "间隔N小时"),
    ("once", "单次"),
    ("expire_at", "依赖外部失效"),
    ("special", "活动窗口"),
    ("trigger", "特殊条件触发"),
]


class GameTaskPanel(QWidget):
    """游戏任务面板（列表 + 动态配置表单）"""

    def __init__(self, param_bridge: Any = None, parent=None):
        super().__init__(parent)
        self._param_bridge = param_bridge
        self._current_name: str = ""
        self._form_widgets: dict[str, Any] = {}
        self._loaded_next_run: str = ""  # 渲染表单时系统显示的 next_run（区分手动修改）
        self._slot_rows: list = []  # 执行时段动态行 [[开始QLineEdit, 结束QLineEdit], ...]
        self._slot_container: Any = None

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
        w = self._form_widgets
        name = detail.get("name", "")
        display = detail.get("display_name", "") or name
        task_type = detail.get("task_type", "event_task")
        uses_battle = bool(detail.get("uses_battle", False))
        uses_team = bool(detail.get("uses_team", False))
        uses_soul = bool(detail.get("uses_soul", False))
        uses_stamina = bool(detail.get("uses_stamina", False))

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

        # ── 双 Tab：执行配置 / 战斗配置 ──
        self._uses_battle = uses_battle
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

        cb_repeat = QComboBox()
        for val, label in REPEAT_TYPES:
            cb_repeat.addItem(label, val)
        repeat = detail.get("repeat") or {}
        rep_type = repeat.get("type", "daily") if isinstance(repeat, dict) else "daily"
        idx = cb_repeat.findData(rep_type)
        cb_repeat.setCurrentIndex(idx if idx >= 0 else 0)
        f_sched.addRow("重复规则:", cb_repeat)
        w["repeat_type"] = cb_repeat

        # 触发模板（trigger 专属，识别列表）
        _tt_label = QLabel("触发模板:")
        ed_tt = QLineEdit()
        ed_tt.setPlaceholderText("逗号分隔素材模板名，如 trigger/activity_enter, trigger/red_dot")
        _rep_tt = (repeat.get("trigger_templates") if isinstance(repeat, dict)
                   else getattr(repeat, 'trigger_templates', None)) or []
        if _rep_tt:
            ed_tt.setText(", ".join(_rep_tt))
        f_sched.addRow(_tt_label, ed_tt)
        _tt_label.setVisible(False)
        ed_tt.setVisible(False)
        w["trigger_label"] = _tt_label
        w["trigger_templates"] = ed_tt

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
        f_sched.addRow("每周几:", wd_widget)
        w["weekday"] = wd_widget
        w["weekday_checks"] = wd_checks

        # 间隔值（interval_days/interval_hours 专属）
        sp_interval = QSpinBox()
        sp_interval.setRange(1, 9999)
        sp_interval.setValue(int((repeat.get("value") or 1) if isinstance(repeat, dict) else 1))
        f_sched.addRow("间隔值:", sp_interval)
        w["interval"] = sp_interval

        # ── 执行时段（1 个 = time_start/time_end；2+ 个 = time_slots） ──
        self._slot_rows = []
        self._slot_container = QVBoxLayout()
        slots = detail.get("time_slots") or []
        if len(slots) >= 2:
            for s, e in slots:
                self._add_slot_row(str(s or ""), str(e or ""))
        else:
            self._add_slot_row(detail.get("time_start") or "06:00",
                               detail.get("time_end") or "23:59")
        f_sched.addRow("执行时段:", self._slot_container)
        btn_add_slot = QPushButton("➕ 添加时段")
        slot_holder = QWidget()
        sh = QHBoxLayout(slot_holder)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.addWidget(btn_add_slot)
        sh.addStretch(1)
        btn_add_slot.clicked.connect(lambda: self._add_slot_row("", ""))
        f_sched.addRow("", slot_holder)
        w["add_slot_btn"] = btn_add_slot

        sp_daily = QSpinBox()
        sp_daily.setRange(0, 999)
        sp_daily.setSpecialValueText("不限")
        sp_daily.setValue(int(detail.get("max_daily") or 0))
        f_sched.addRow("每日上限:", sp_daily)
        w["max_daily"] = sp_daily

        # 活动有效期（active_range，如 7/21–10/1）
        ar = detail.get("active_range") or []
        ed_ar_start = QLineEdit(str(ar[0]) if ar and ar[0] else "")
        ed_ar_start.setPlaceholderText("YYYY-MM-DD 留空不限")
        f_sched.addRow("开始日期:", ed_ar_start)
        w["active_range_start"] = ed_ar_start
        ed_ar_end = QLineEdit(str(ar[1]) if len(ar) > 1 and ar[1] else "")
        ed_ar_end.setPlaceholderText("YYYY-MM-DD 留空不限")
        f_sched.addRow("结束日期:", ed_ar_end)
        w["active_range_end"] = ed_ar_end

        # 累计次数（活动期累计上限）
        sp_total = QSpinBox()
        sp_total.setRange(0, 999999)
        sp_total.setSpecialValueText("不限")
        sp_total.setValue(int(detail.get("total_count") or 0))
        f_sched.addRow("累计次数:", sp_total)
        w["total_count"] = sp_total

        # 重复规则类型切换 → 联动启用/禁用
        cb_repeat.currentIndexChanged.connect(self._update_repeat_fields)

        te.addWidget(g_sched)

        # ── 📊 执行模式（必配，设计书 §5.2 execution_mode） ──
        g_freq, freq_content = panel_group("📊 执行模式（必配）")
        f_freq = QFormLayout()
        freq_content.addLayout(f_freq)

        # 执行模式：按天执行一次 / 每时间段各执行一次
        cb_mode = QComboBox()
        cb_mode.addItem("按天执行（一天一次）", "daily")
        cb_mode.addItem("按时间段执行（每时段各一次）", "per_slot")
        er_mode = detail.get("execution_mode") or "daily"
        idx = cb_mode.findData(er_mode)
        cb_mode.setCurrentIndex(idx if idx >= 0 else 0)
        f_freq.addRow("执行模式:", cb_mode)
        w["execution_mode"] = cb_mode

        sp_loop = QSpinBox()
        sp_loop.setRange(1, 999)
        # 调度器优先读取 repeat.loop_count，表单显示也优先 repeat 内值，保持同步
        rep_loop = repeat.get("loop_count") if isinstance(repeat, dict) else None
        sp_loop.setValue(int(rep_loop or detail.get("loop_count") or 1))
        f_freq.addRow("每轮循环:", sp_loop)  # 任务体内 BattleLoop 次数
        w["loop_count"] = sp_loop

        te.addWidget(g_freq)

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

        # ══════════ Tab2 战斗配置（uses_battle=True） ══════════
        if uses_battle:
            tab_battle = QWidget()
            tb = QVBoxLayout(tab_battle)
            tb.setContentsMargins(6, 6, 6, 6)

            # ── 🎴 御魂配置（选择御魂） ──
            g_soul, soul_content = panel_group("🎴 御魂配置（选择御魂）")
            f_soul = QFormLayout()
            soul_content.addLayout(f_soul)
            _soul = detail.get("soul_setup") if isinstance(detail.get("soul_setup"), dict) else {}
            ed_grp = QLineEdit(str(_soul.get("group", "")))
            ed_grp.setPlaceholderText("组名，如：御魂副本")
            f_soul.addRow("组名:", ed_grp)
            w["soul_group"] = ed_grp
            ed_steam = QLineEdit(str(_soul.get("team", "")))
            ed_steam.setPlaceholderText("队伍名，如：御魂十层")
            f_soul.addRow("队伍名:", ed_steam)
            w["soul_team"] = ed_steam
            _pos = _soul.get("position") or [1, 1]
            sp_pg = QSpinBox()
            sp_pg.setRange(1, 99)
            sp_pg.setValue(int(_pos[0]) if len(_pos) > 0 and _pos[0] else 1)
            f_soul.addRow("位置·分组序号:", sp_pg)  # 第 N 个分组按钮
            w["soul_pos_group"] = sp_pg
            sp_pt = QSpinBox()
            sp_pt.setRange(1, 99)
            sp_pt.setValue(int(_pos[1]) if len(_pos) > 1 and _pos[1] else 1)
            f_soul.addRow("位置·队伍序号:", sp_pt)  # 第 M 个队伍名
            w["soul_pos_team"] = sp_pt
            tb.addWidget(g_soul)

            # ── 🛡 战前准备 ──
            g_prep, prep_content = panel_group("🛡 战前准备")
            f_prep = QFormLayout()
            prep_content.addLayout(f_prep)
            cb_lock = QCheckBox("锁定队伍（选是则无法更换）")
            cb_lock.setChecked(bool(detail.get("lock_team", False)))
            f_prep.addRow("是否锁定队伍:", cb_lock)
            w["lock_team"] = cb_lock
            cb_chg = QCheckBox("更换队伍（第1次战斗前解锁，第2次战斗前锁定）")
            cb_chg.setChecked(bool(detail.get("change_team", False)))
            f_prep.addRow("是否更换队伍:", cb_chg)
            w["change_team"] = cb_chg
            tb.addWidget(g_prep)

            # ── ⚔ 战斗参数 ──
            g_bparam, bparam_content = panel_group("⚔ 战斗参数")
            f_bparam = QFormLayout()
            bparam_content.addLayout(f_bparam)
            ed_teamid = QLineEdit(detail.get("team_id") or "")
            ed_teamid.setPlaceholderText("选择或输入阵容 ID")
            f_bparam.addRow("阵容预设:", ed_teamid)
            w["team_id"] = ed_teamid
            sp_floor = QSpinBox()
            sp_floor.setRange(1, 999)
            sp_floor.setSpecialValueText("默认")
            sp_floor.setValue(int(detail.get("floor") or 0))
            f_bparam.addRow("副本层数:", sp_floor)
            w["floor"] = sp_floor
            sp_fail = QSpinBox()
            sp_fail.setRange(1, 99)
            sp_fail.setValue(int(detail.get("max_fail_streak") or 10))
            f_bparam.addRow("失败容忍:", sp_fail)
            w["max_fail_streak"] = sp_fail
            tb.addWidget(g_bparam)

            # ── 🍃 体力配置（uses_stamina=True 显示） ──
            if uses_stamina:
                g_sta, sta_content = panel_group("🍃 体力配置")
                f_sta = QFormLayout()
                sta_content.addLayout(f_sta)
                sp_stamina = QSpinBox()
                sp_stamina.setRange(0, 999)
                sp_stamina.setSpecialValueText("不检查")
                sp_stamina.setValue(int(detail.get("stamina_required") or 0))
                f_sta.addRow("体力门槛:", sp_stamina)
                w["stamina_required"] = sp_stamina
                tb.addWidget(g_sta)

            tb.addStretch(1)
            tabs.addTab(tab_battle, "⚔ 战斗配置")

        self.form_layout.addWidget(tabs)

        # 💾 保存
        btn_save = QPushButton("💾 保存配置")
        btn_save.clicked.connect(self._save)
        self.form_layout.addWidget(btn_save)

        # 初始化重复规则联动状态
        self._update_repeat_fields()

        self.form_layout.addStretch()

    # ── 执行时段动态行 ────────────────────────────────────────

    def _add_slot_row(self, start: str = "", end: str = "") -> None:
        """添加一行执行时段（开始 ~ 结束）"""
        row = QHBoxLayout()
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
        self._slot_container.addLayout(row)
        self._slot_rows.append(pair)
        btn_del.clicked.connect(lambda: self._remove_slot_row(row, pair))

    def _remove_slot_row(self, row: QHBoxLayout, pair: list) -> None:
        """删除一行执行时段（至少保留一行）"""
        if len(self._slot_rows) <= 1:
            return
        for i in range(self._slot_container.count()):
            item = self._slot_container.itemAt(i)
            if item is not None and item.layout() is row:
                self._slot_container.removeItem(item)
                break
        while row.count():
            item = row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if pair in self._slot_rows:
            self._slot_rows.remove(pair)

    # ── 重复规则联动 ────────────────────────────────────────

    def _update_repeat_fields(self, *args) -> None:
        """根据重复规则类型启用/禁用 每周几 / 间隔值 / 时段 / 执行模式 / 触发模板"""
        w = self._form_widgets
        rt = w.get("repeat_type")
        if rt is None:
            return
        rtype = rt.currentData()
        is_trigger = (rtype == "trigger")

        wd = w.get("weekday")
        iv = w.get("interval")
        if wd is not None:
            wd.setEnabled(not is_trigger and rtype == "weekly")
        if iv is not None:
            iv.setEnabled(not is_trigger and rtype in ("interval_days", "interval_hours"))

        # 触发模板行（trigger 专属，仅 trigger 时显示）
        for key in ("trigger_templates", "trigger_label"):
            c = w.get(key)
            if c is not None:
                c.setVisible(is_trigger)

        # 时段行（trigger 无时间配置 → 禁用）
        for pair in getattr(self, "_slot_rows", []) or []:
            for ed in pair:
                ed.setEnabled(not is_trigger)
        add_btn = w.get("add_slot_btn")
        if add_btn is not None:
            add_btn.setEnabled(not is_trigger)

        # 其他时间/次数控件（trigger 禁用）
        for key in ("max_daily", "active_range_start", "active_range_end",
                    "total_count", "execution_mode", "loop_count"):
            c = w.get(key)
            if c is not None:
                c.setEnabled(not is_trigger)

    # ── 保存（设计书 §5.1 字段写回 tasks.yaml） ────────────

    def _collect_config(self) -> dict[str, Any]:
        """收集表单值 → tasks.yaml 配置 dict"""
        w = self._form_widgets
        rtype = w["repeat_type"].currentData()
        repeat_dict: dict[str, Any] = {"type": rtype, "value": 1}
        # 每轮循环也写入 repeat（调度器优先读取 repeat.loop_count）
        repeat_dict["loop_count"] = w["loop_count"].value()
        if rtype in ("interval_days", "interval_hours"):
            repeat_dict["value"] = w["interval"].value()
        elif rtype == "weekly":
            wd_checks = w.get("weekday_checks") or {}
            selected = [val for val, _cb in wd_checks.items() if _cb.isChecked()]
            if selected:
                repeat_dict["weekdays"] = selected

        # 活动有效期（两个日期都留空 → 不写）
        ar_start = w["active_range_start"].text().strip()
        ar_end = w["active_range_end"].text().strip()
        active_range = None
        if ar_start or ar_end:
            active_range = [ar_start or None, ar_end or None]

        # 执行时段：trigger 类型无时间配置；否则 1 行 → time_start/time_end；2+ 行 → time_slots
        is_trigger = (rtype == "trigger")
        if is_trigger:
            # 触发式任务：识别列表写入 repeat.trigger_templates，时间字段全部置空
            tt = w.get("trigger_templates")
            templates = []
            if tt is not None:
                templates = [t.strip() for t in tt.text().split(",") if t.strip()]
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
            "max_daily": None if is_trigger else (w["max_daily"].value() or None),
            "repeat": repeat_dict,
            "active_range": None if is_trigger else active_range,
            "total_count": None if is_trigger else (w["total_count"].value() or None),
            "execution_mode": w["execution_mode"].currentData(),
            "loop_count": w["loop_count"].value(),
        }
        if "max_fail_streak" in w:
            config["max_fail_streak"] = w["max_fail_streak"].value()
        if "team_id" in w:
            config["team_id"] = w["team_id"].text().strip() or None
        if "floor" in w:
            config["floor"] = w["floor"].value() or None
        if "stamina_required" in w:
            config["stamina_required"] = w["stamina_required"].value()

        # ── 战斗配置（战斗配置 Tab，uses_battle=True 时） ──
        if getattr(self, "_uses_battle", False):
            # 御魂配置：组名 / 队伍名 / 位置 [分组序号, 队伍序号]
            if "soul_group" in w:
                config["soul_setup"] = {
                    "group": w["soul_group"].text().strip(),
                    "team": w["soul_team"].text().strip() if "soul_team" in w else "",
                    "position": [
                        w["soul_pos_group"].value() if "soul_pos_group" in w else 1,
                        w["soul_pos_team"].value() if "soul_pos_team" in w else 1,
                    ],
                }
            # 战前准备：是否锁定 / 是否更换队伍
            if "lock_team" in w:
                config["lock_team"] = w["lock_team"].isChecked()
            if "change_team" in w:
                config["change_team"] = w["change_team"].isChecked()
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
                    pass
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

