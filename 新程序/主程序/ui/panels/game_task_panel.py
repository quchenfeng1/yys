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
    QLabel, QLineEdit, QListWidget, QPushButton, QScrollArea,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

# 设计书 §5.2 重复规则（单次任务两种模式：每次启动执行 on_enter / 只执行一次 once）
# special / expire_at 已从下拉移除（与 daily/active_range 重叠），代码层保留兼容旧配置
REPEAT_TYPES = [
    ("daily", "每日"),
    ("weekly", "每周"),
    ("monthly_start", "每月初"),
    ("interval_days", "间隔N天"),
    ("interval_hours", "间隔N小时"),
    ("on_enter", "每次启动执行"),
    ("once", "只执行一次"),
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
        self._slot_rows: list = []  # 执行时段动态行 [[开始QLineEdit, 结束QLineEdit], ...]（读取用）
        self._slot_row_widgets: list = []  # 执行时段每行容器 QWidget（整体显隐用，含✕删除按钮）
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
        """从素材管理读取 scene/ 识图素材配置的识别信号列表。

        返回 [(信号名, 素材识别名), ...]，供触发模板多选下拉使用。
        """
        try:
            from core.asset_meta import AssetMetaStore
            from pathlib import Path
            assets_dir = Path(__file__).resolve().parents[2] / "assets"
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

        # 重复规则：下拉选框（选择后联动显隐对应属性区）
        repeat = detail.get("repeat") or {}
        rep_type = repeat.get("type", "daily") if isinstance(repeat, dict) else "daily"
        lbl_repeat = QLabel("重复规则:")
        cb_repeat = QComboBox()
        for val, label in REPEAT_TYPES:
            cb_repeat.addItem(label, val)
        idx = cb_repeat.findData(rep_type)
        cb_repeat.setCurrentIndex(idx if idx >= 0 else 0)
        f_sched.addRow(lbl_repeat, cb_repeat)
        w["repeat_type"] = cb_repeat
        w["repeat_type_label"] = lbl_repeat
        # 切换 → 联动显隐
        cb_repeat.currentIndexChanged.connect(self._update_repeat_fields)

        # 触发模板（trigger 专属）：优先信号名多选下拉（素材管理 scene/ 配置的 signal），
        # 无可用信号时回退自由文本输入（兼容旧素材路径写法）。
        _tt_label = QLabel("触发信号:")
        _rep_tt = (repeat.get("trigger_templates") if isinstance(repeat, dict)
                   else getattr(repeat, 'trigger_templates', None)) or []
        _signals = self._get_signal_options()  # [(信号名, 素材识别名)]
        if _signals:
            from ui.widgets.multi_select_combo import MultiSelectCombo
            ed_tt = MultiSelectCombo()
            # data=信号名（保存进 trigger_templates），label 显示"信号名（素材名）"
            items = [(sig, f"{sig}（{rel}）") for sig, rel in _signals]
            sig_names = {sig for sig, _ in _signals}
            rel_by_sig = {rel: sig for sig, rel in _signals}
            # 兼容旧配置：非信号名的旧值（素材路径）补入选项，避免保存时丢字段
            for t in _rep_tt:
                if t and t not in sig_names and t not in rel_by_sig:
                    items.append((t, f"{t}（旧素材路径）"))
            ed_tt.set_items(items)
            # 回显：信号名直接勾选；素材路径 → 若对应素材有信号名则用信号名勾选，否则原样勾选
            checked = []
            for t in _rep_tt:
                if t in sig_names:
                    checked.append(t)
                elif t in rel_by_sig:
                    checked.append(rel_by_sig[t])
                elif t:
                    checked.append(t)
            ed_tt.set_selected(checked)
            ed_tt.setPlaceholderText("选择识别信号（素材管理 scene/ 素材已配置）")
        else:
            ed_tt = QLineEdit()
            ed_tt.setPlaceholderText("逗号分隔素材名，如 trigger/activity_enter（素材管理配置信号后可选）")
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

        # 活动循环次数（循环体循环次数上限；每轮循环成功 +1，显示累计，达到 → 失效区）
        sp_total = QSpinBox()
        sp_total.setRange(0, 999999)
        sp_total.setSpecialValueText("不限")
        sp_total.setValue(int(detail.get("total_count") or 0))
        sp_total.setToolTip("循环体循环次数上限（0=不限）。\n"
                            "每完成一轮循环累计一次，右侧显示累计循环次数；\n"
                            "累计达到该上限后任务进入失效区。")
        lbl_total = QLabel("活动循环次数:")
        total_holder = QWidget()
        th = QHBoxLayout(total_holder)
        th.setContentsMargins(0, 0, 0, 0)
        th.setSpacing(6)
        th.addWidget(sp_total)
        lbl_cycle_done = QLabel("")
        th.addWidget(lbl_cycle_done)
        th.addStretch(1)
        f_sched.addRow(lbl_total, total_holder)
        w["total_label"] = lbl_total
        w["total_count"] = sp_total
        w["cycle_done_label"] = lbl_cycle_done

        te.addWidget(g_sched)

        # ── 📊 循环次数（任务循环体执行几次） ──
        g_freq, freq_content = panel_group("📊 循环次数")
        f_freq = QFormLayout()
        freq_content.addLayout(f_freq)

        sp_loop = QSpinBox()
        sp_loop.setRange(1, 999)
        # 调度器优先读取 repeat.loop_count，表单显示也优先 repeat 内值，保持同步
        rep_loop = repeat.get("loop_count") if isinstance(repeat, dict) else None
        sp_loop.setValue(int(rep_loop or detail.get("loop_count") or 1))
        sp_loop.setToolTip("任务的循环体执行几次（每次触发跑几轮战斗等）\n"
                           "与「周期最大触发次数」（每天触发几次）不同，二者相乘为周期总工作量。")
        f_freq.addRow("循环次数:", sp_loop)
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

            # ── 👥 组队配置（主号带队带小号刷副本，§3.10 组队协调） ──
            g_coop, coop_content = panel_group("👥 组队配置（带小号刷副本）")
            f_coop = QFormLayout()
            coop_content.addLayout(f_coop)
            _teaming = detail.get("teaming") if isinstance(detail.get("teaming"), dict) else {}
            # 组队小号：优先从「小号管理」多选下拉；无小号数据时回退文本输入
            sub_options = self._get_sub_options()
            if sub_options:
                from ui.widgets.multi_select_combo import MultiSelectCombo
                ed_subs = MultiSelectCombo()
                ed_subs.set_items(sub_options)
                saved = _teaming.get("sub_ids") or []
                ed_subs.set_selected([s for s in saved
                                      if any(s == d for d, _ in sub_options)])
            else:
                ed_subs = QLineEdit(", ".join(_teaming.get("sub_ids") or []) if _teaming else "")
                ed_subs.setPlaceholderText("如 sub1, sub2（留空不组队；菜单「小号管理」添加小号后可选）")
            f_coop.addRow("组队小号:", ed_subs)
            w["teaming_sub_ids"] = ed_subs
            # 说明：当前仅支持主号带队（大号创建队伍，小号接受邀请+准备）
            # 轮数复用上方「每轮循环」（loop_count），不单独配置
            lbl_coop = QLabel("主号带队（大号创建队伍，小号接受邀请+准备）\n"
                              "组队轮数 = 上方「每轮循环」（每次触发打几轮）")
            lbl_coop.setWordWrap(True)
            lbl_coop.setStyleSheet("color: #888; font-size: 12px;")
            f_coop.addRow("说明:", lbl_coop)
            tb.addWidget(g_coop)

            tb.addStretch(1)
            tabs.addTab(tab_battle, "⚔ 战斗配置")

        self.form_layout.addWidget(tabs)

        # 💾 保存
        btn_save = QPushButton("💾 保存配置")
        btn_save.clicked.connect(self._save)
        self.form_layout.addWidget(btn_save)

        # 初始化重复规则联动状态
        self._update_repeat_fields()
        # 刷新「活动循环次数」累计显示（已循环 x/y）
        self._refresh_cycle_done()

        self.form_layout.addStretch()

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

    def _refresh_cycle_done(self) -> None:
        """刷新「活动循环次数」累计显示（已循环 x/y 轮）。

        从调度器读取活动循环累计进度（record_cycle 每轮循环 +1），
        显示在活动循环次数输入框右侧；未设置上限时仅显示累计值。
        """
        if not self._current_name:
            return
        w = self._form_widgets
        lbl = w.get("cycle_done_label")
        if lbl is None:
            return
        bridge = self._param_bridge
        cur, limit = 0, None
        if bridge and hasattr(bridge, 'task') and hasattr(bridge.task, 'get_cycle_progress'):
            try:
                cur, limit = bridge.task.get_cycle_progress(self._current_name)
            except Exception:
                cur, limit = 0, None
        if limit is not None:
            lbl.setText(f"已循环 {cur}/{limit} 轮")
            lbl.setStyleSheet("color:#888; font-size:12px;")
            if cur >= limit:
                lbl.setStyleSheet("color:#e53935; font-size:12px;")
        elif cur:
            lbl.setText(f"已循环 {cur} 轮")
            lbl.setStyleSheet("color:#888; font-size:12px;")
        else:
            lbl.setText("")

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
        """收集表单值 → tasks.yaml 配置 dict"""
        w = self._form_widgets
        rtype = self._current_repeat_type()
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
            # 输入为 MultiSelectCombo（信号名多选）或 QLineEdit（旧文本输入）两种形态
            templates = []
            if is_trigger:
                tt = w.get("trigger_templates")
                if tt is not None:
                    from ui.widgets.multi_select_combo import MultiSelectCombo
                    if isinstance(tt, MultiSelectCombo):
                        templates = [str(d) for d in tt.selected_data()]
                    else:
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
            "max_daily": (w["max_daily"].value() or None),  # 周期触发次数（所有类型）
            "repeat": repeat_dict,  # loop_count 只存 repeat 内（scheduler 优先读取），顶层不再重复存储
            "active_range": None if is_trigger else active_range,
            "total_count": (w["total_count"].value() or None),  # 活动循环次数（所有类型，含 trigger）
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
            # 组队配置（主号带队带小号刷副本，§3.10）
            # 轮数复用「每轮循环」（loop_count），teaming 只存小号列表
            if "teaming_sub_ids" in w:
                wid = w["teaming_sub_ids"]
                from ui.widgets.multi_select_combo import MultiSelectCombo
                if isinstance(wid, MultiSelectCombo):
                    subs = wid.selected_data()
                else:
                    subs = [s.strip() for s in wid.text().split(",") if s.strip()]
                if subs:
                    config["teaming"] = {"sub_ids": subs}
                else:
                    config["teaming"] = None
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
            # 保存后刷新累计循环次数显示
            self._refresh_cycle_done()
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

