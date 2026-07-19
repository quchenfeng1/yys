"""
任务步骤上下文（04-任务模块 子模块）

TaskContext 在 TaskGraph 执行期间在各步骤间传递，携带共享资源。
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TaskContext:
    """步骤间共享的上下文。"""

    task_name: str = ""                        # 任务名
    task_config: dict = field(default_factory=dict)  # 任务配置
    state: dict = field(default_factory=dict)        # 临时状态（步骤间传参）

    # 以下由框架注入
    executor: Any = None                       # Executor
    recognizer: Any = None                     # Recognizer
    connection: Any = None                     # ConnectionManager
    team_manager: Any = None                   # TeamManager
    scheduler: Any = None                      # Scheduler（供 report_expire 等调用）
    log: Any = None                            # 日志回调: log(msg) 将消息发送到 UI 终端

    def get(self, key: str, default: Any = None) -> Any:
        return self.state.get(key, default)

    def set(self, key: str, value: Any):
        self.state[key] = value
