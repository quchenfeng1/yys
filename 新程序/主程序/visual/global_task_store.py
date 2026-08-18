"""
全局任务存储（2026-08-16 信号体系）。

全局任务 = 一张兜底图（可视化构建「全局任务」Tab 编辑）：
- 每个任务上层扣的一张相同的任务，接收未处理信号/运行异常
- 存储：games/{game}/global_task.json（特殊的、独一无二的任务，不被任务信号触发）
- 执行：异常发生后由 VisualTask 加载执行，走到结束节点 = 原任务安全结束
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class GlobalTaskStore:
    """全局任务存储（单文件原子写）。"""

    def __init__(self, path: str | Path):
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def load(self) -> dict:
        """加载全局任务定义（不存在返回空 dict）。"""
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def save(self, task: dict) -> bool:
        """原子保存全局任务定义。"""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(task, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self._path)
            return True
        except Exception:
            return False
