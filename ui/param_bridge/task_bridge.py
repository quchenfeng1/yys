"""
任务参数传参（10-传参模块 子模块）

UI 任务行控件 ↔ 配置 + 定时模块。
"""

from core.event_bus import event_bus, Events


class TaskBridge:
    """任务参数传参。"""

    def __init__(self, config_manager, scheduler, state_manager):
        self._config = config_manager
        self._scheduler = scheduler
        self._state_mgr = state_manager

    def bind_enabled_checkbox(self, checkbox, task_name: str):
        """启用开关 ↔ 配置。"""
        key = f"tasks.{task_name}.enabled"
        checkbox.setChecked(self._config.get(key, False))
        checkbox.toggled.connect(lambda v: self._config.set(key, v))

    def bind_priority_spinbox(self, spinbox, task_name: str, min_val=1, max_val=99):
        """优先级输入 ↔ 配置。"""
        key = f"tasks.{task_name}.priority"
        spinbox.setRange(min_val, max_val)
        spinbox.setValue(self._config.get(key, 10))
        spinbox.valueChanged.connect(lambda v: self._config.set(key, v))

    def bind_next_run_display(self, label, task_name: str):
        """下次执行时间显示 ← 定时模块。"""
        def _refresh():
            nr = self._scheduler.get_next_run_time(task_name)
            if nr:
                from datetime import datetime
                delta = nr - datetime.now()
                hours = int(delta.total_seconds() // 3600)
                minutes = int((delta.total_seconds() % 3600) // 60)
                label.setText(f"{hours}时{minutes}分后" if delta.total_seconds() > 0 else "已到期")
            else:
                label.setText("—")
        _refresh()
        event_bus.subscribe(Events.SCHEDULE_UPDATED, lambda task=None: _refresh())

    def bind_skip_button(self, button, task_name: str):
        """跳过本次 → 推进 next_run_time。"""
        button.clicked.connect(lambda: self._scheduler.update_next_run(
            task_name, self._scheduler.get_next_run_time(task_name)
        ))

    def bind_single_step_button(self, button, task_name: str, run_callback):
        """单步执行 → 忽略 next_run_time 强制执行一次。"""
        button.clicked.connect(lambda: run_callback(task_name))
