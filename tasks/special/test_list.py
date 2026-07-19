"""
ui页面队列测试 — 模拟运行60秒，每5秒输出进度
"""

display_name = "ui页面队列测试"
description = "模拟运行60秒，每5秒打印进度，测试任务队列显示"
task_type = "event_task"

import time
from tasks.base.task_step import TaskStep, StepResult
from tasks.base.task_context import TaskContext


class TestListTask(TaskStep):
    """模拟运行任务：60秒内每5秒输出进度。"""
    name = "test_list"
    display_name = "ui页面队列测试"
    description = "模拟运行60秒，每5秒打印进度"
    is_generic = False
    timeout = 70

    def execute(self, context: TaskContext) -> StepResult:
        log = context.log or print
        total = 60
        interval = 5
        elapsed = 0
        log(f"[test_list] 开始测试，预计运行 {total}s")
        while elapsed < total:
            time.sleep(interval)
            elapsed += interval
            log(f"[test_list] 测试文件运行 {elapsed}s / {total}s")
        return StepResult.success(f"测试完成，运行了 {total}s")
