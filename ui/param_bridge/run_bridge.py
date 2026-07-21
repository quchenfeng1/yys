"""
运行传参（10-传参模块 子模块）

UI 启停按钮 ↔ 运行控制模块，通过事件总线桥接。
UI 按钮不直接调用 RunController，而是发布事件。
"""

from core.event_bus import event_bus, Events


class RunBridge:
    """运行传参。UI 启停 ↔ 事件总线。"""

    def bind_start_button(self, button):
        """启动按钮 → 发布 start_requested。"""
        button.clicked.connect(lambda: event_bus.publish(Events.START_REQUESTED))

    def bind_stop_button(self, button):
        """停止按钮 → 发布 stop_requested。"""
        button.clicked.connect(lambda: event_bus.publish(Events.STOP_REQUESTED))

    def bind_pause_button(self, button):
        """暂停按钮 → 发布 pause_requested。"""
        button.clicked.connect(lambda: event_bus.publish(Events.PAUSE_REQUESTED))

    def bind_resume_button(self, button):
        """恢复按钮 → 发布 resume_requested。"""
        button.clicked.connect(lambda: event_bus.publish(Events.RESUME_REQUESTED))

    def bind_status_label(self, label):
        """状态标签 ← 订阅 run_status。"""
        from core.state_manager import state_manager

        def _on_state(**data):
            if data.get("key") == "run_status":
                text = {
                    "running": "运行中", "paused": "已暂停",
                    "stopped": "已停止", "stopping": "停止中",
                }.get(data.get("new_value"), str(data.get("new_value")))
                label.setText(text)

        event_bus.subscribe(Events.STATE_CHANGED, _on_state)

    def bind_current_task_label(self, label):
        """当前任务标签 ← 订阅 task_started / task_done。"""
        event_bus.subscribe(Events.TASK_STARTED, lambda task_name: label.setText(f"正在执行: {task_name}"))
        event_bus.subscribe(Events.TASK_DONE, lambda task_name, success: label.setText("空闲"))
