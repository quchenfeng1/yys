"""
执行记录持久化（05-定时模块 子模块）

管理 task_state.json 的读写，原子写盘防止崩溃损坏。
持久化每个任务的 next_run_time / success_count / today_count / expire_at。
"""

import json
import os
import tempfile
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional


# 默认持久化路径
DEFAULT_STATE_PATH = "config/runtime/task_state.json"


@dataclass
class TaskState:
    """单个任务的运行时状态记录。"""
    last_run_time: Optional[str] = None       # ISO 格式
    last_success: bool = True
    next_run_time: Optional[str] = None        # ISO 格式；null 表示无限制
    success_count: int = 0
    today_count: int = 0
    fail_streak: int = 0                       # 连续失败次数（成功后重置）
    expire_at: Optional[str] = None            # ISO 格式

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TaskState":
        return cls(
            last_run_time=d.get("last_run_time"),
            last_success=d.get("last_success", True),
            next_run_time=d.get("next_run_time"),
            success_count=d.get("success_count", 0),
            today_count=d.get("today_count", 0),
            fail_streak=d.get("fail_streak", 0),
            expire_at=d.get("expire_at"),
        )


class TaskStateStore:
    """执行记录持久化管理。原子写盘。"""

    def __init__(self, filepath: str = DEFAULT_STATE_PATH):
        self._filepath = filepath
        self._tasks: dict[str, TaskState] = {}
        self._version = 1

    # ==================== 加载 / 保存 ====================

    def load(self) -> dict[str, TaskState]:
        """从磁盘加载执行记录。文件不存在则返回空。"""
        if not os.path.exists(self._filepath):
            self._tasks = {}
            return self._tasks

        try:
            with open(self._filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._version = data.get("_version", 1)
            tasks_raw = data.get("tasks", {})
            self._tasks = {
                name: TaskState.from_dict(d) for name, d in tasks_raw.items()
            }
        except (json.JSONDecodeError, KeyError, TypeError):
            self._tasks = {}
        return self._tasks

    def save(self):
        """原子写盘：写临时文件 → 替换。Windows 兼容。"""
        import shutil
        target_dir = os.path.dirname(self._filepath) or "."
        os.makedirs(target_dir, exist_ok=True)
        data = {
            "_version": self._version,
            "_updated_at": datetime.now().isoformat(),
            "tasks": {name: st.to_dict() for name, st in self._tasks.items()},
        }
        # 写临时文件
        fd, tmp_path = tempfile.mkstemp(
            suffix=".json", dir=target_dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            # Windows 兼容：shutil.move 比 os.replace 更可靠
            shutil.move(tmp_path, self._filepath)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    # ==================== 读取 ====================

    def get(self, task_name: str) -> Optional[TaskState]:
        """获取任务状态。"""
        return self._tasks.get(task_name)

    def get_or_create(self, task_name: str) -> TaskState:
        """获取或创建任务状态。"""
        if task_name not in self._tasks:
            self._tasks[task_name] = TaskState()
        return self._tasks[task_name]

    def get_all(self) -> dict[str, TaskState]:
        return dict(self._tasks)

    # ==================== 更新 ====================

    def update(self, task_name: str, **kwargs):
        """更新任务状态字段。"""
        st = self.get_or_create(task_name)
        for key, value in kwargs.items():
            if hasattr(st, key):
                setattr(st, key, value)

    def set_next_run(self, task_name: str, dt: Optional[datetime]):
        """设置下次执行时间。"""
        st = self.get_or_create(task_name)
        st.next_run_time = dt.isoformat() if dt else None

    def increment_today_count(self, task_name: str):
        st = self.get_or_create(task_name)
        st.today_count += 1
        st.success_count += 1

    def reset_daily_counters(self):
        """每日 00:00 重置。"""
        for st in self._tasks.values():
            st.today_count = 0

    def reset_all(self):
        """重置所有状态（调试用）。"""
        self._tasks = {}
        if os.path.exists(self._filepath):
            os.remove(self._filepath)
