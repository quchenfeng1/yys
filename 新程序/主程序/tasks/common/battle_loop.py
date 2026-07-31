"""
通用模块：战斗循环（支持运行时进度恢复，说明书 04 §BattleLoop）。

流程：
- 从 context.state 读取已完成场次（{task_id: {completed, total, updated}}）
- 从剩余场次开始执行（断点续跑：异常关闭后下次从 completed 继续）
- 每场战斗结束：completed += 1，写回 context.state，并调用
  context.progress_saver(task_id, completed, total) 立即持久化
  （异常关闭最多丢失最近 1 场）
"""
from __future__ import annotations

import time

from tasks.base.task_step import TaskStep, StepResult, StepStatus


class BattleLoop(TaskStep):
    """战斗循环：自动重复战斗，支持断点恢复"""

    is_generic = True

    def execute(self, context: Any = None) -> StepResult:
        max_battles = int(self.params.get("max_battles", 0) or 0)  # 0 = 无限
        wait_time = float(self.params.get("wait_time", 60) or 0)  # 每场等待秒数

        task_id = ""
        state = None
        saver = None
        if context is not None:
            task_id = getattr(context, 'task_id', '') or getattr(context, 'task_name', '')
            state = getattr(context, 'state', None)
            saver = getattr(context, 'progress_saver', None)

        # 断点恢复：从 context.state 读取已完成场次
        completed = 0
        if state is not None and isinstance(state, dict) and task_id:
            entry = state.get(task_id)
            if isinstance(entry, dict):
                try:
                    completed = int(entry.get("completed", 0) or 0)
                except (TypeError, ValueError):
                    completed = 0

        # 剩余场次（max_battles<=0 → 无限循环）
        remaining = (max_battles - completed) if max_battles > 0 else -1

        while remaining < 0 or remaining > 0:
            if self.check_interrupt(context):
                return StepResult(status=StepStatus.SKIP, message="被中断")

            # 等待当前场次结束（识别结算界面）
            if wait_time > 0:
                time.sleep(wait_time)

            completed += 1
            if max_battles > 0:
                remaining -= 1

            # 每场结束：写回 state + 立即持久化（异常关闭最多丢 1 场）
            self._save_progress(state, saver, task_id, completed, max_battles)

        return StepResult(
            status=StepStatus.SUCCESS,
            message=f"战斗循环完成，共 {completed} 场",
        )

    @staticmethod
    def _save_progress(state, saver, task_id: str, completed: int, total: int) -> None:
        """写回 context.state 并触发持久化回调"""
        try:
            if state is not None and isinstance(state, dict) and task_id:
                state[task_id] = {
                    "completed": int(completed),
                    "total": int(total),
                    "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
            if saver is not None:
                saver(task_id, int(completed), int(total))
        except Exception:
            pass
