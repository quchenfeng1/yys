"""
17-可视化构建模块：VisualTask（数据驱动任务运行时，P0）。

实现 BaseTask 接口：execute() 时加载节点图 → 构造 GraphContext →
run_graph() 执行。与其他 .py 任务并存，经 TaskRegistry 注册后可被调度器调度。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from tasks.base.base_task import BaseTask
from tasks.base.task_result import TaskResult, TaskStatus
from visual.graph_runner import run_graph
from visual.nodes import GraphContext

_STATUS_MAP = {
    "success": TaskStatus.SUCCESS,
    "error": TaskStatus.FAIL,
    "interrupted": TaskStatus.ABORTED,
    "stopped": TaskStatus.ABORTED,
}


class VisualTask(BaseTask):
    """可视化任务（节点图数据驱动）。"""

    task_id: str = ""
    category: str = "daily"

    # 类级注入（动态子类化时设置）
    _definition: dict = {}
    _assets_dir: str | Path = ""
    _screen_size: tuple = (1080, 1920)
    _display_name: str = ""
    _operation_store: Any = None   # OperationStore（4.26 通用操作）

    def __init__(self, task_id: str, **kwargs: Any):
        super().__init__(task_id, **kwargs)
        if self._definition:
            self.task_id = self._definition.get("name", task_id) or task_id
            self.category = self._definition.get("category", "daily") or "daily"
        if not self._display_name:
            self._display_name = self._definition.get("display_name", "") or task_id

    def _get_operation(self, name: str) -> dict | None:
        """加载通用操作定义（4.26）；operation 节点内联执行用"""
        if self._operation_store is None:
            return None
        try:
            return self._operation_store.load(name)
        except Exception:
            return None

    @property
    def display_name(self) -> str:
        return self._display_name or self.task_id

    def _build_graph(self):
        # 可视化任务用节点图执行，不走 TaskGraph
        from tasks.base.task_graph import TaskGraph
        return TaskGraph()

    def _collect_ocr(self, context: Any) -> Any:
        """从 context/recognizer 提取 OCR 定位器（复用现有 OcrLocator）"""
        if context is None:
            return None
        for attr in ("ocr", "ocr_locator"):
            v = getattr(context, attr, None)
            if v is not None:
                return v
        rec = getattr(context, "recognizer", None)
        if rec is not None and hasattr(rec, "_ocr"):
            return rec._ocr
        return None

    def execute(self, context: Any = None) -> TaskResult:
        """执行节点图"""
        definition = self._definition or {}
        graph = definition.get("graph", {})

        # 屏幕尺寸（从连接/截图推断，失败回退）
        screen_size = self._screen_size
        try:
            if context is not None and getattr(context, "executor", None) is not None:
                ex = context.executor
                if hasattr(ex, "_connection") and getattr(ex._connection, "screenshot", None):
                    img = ex._connection.screenshot(use_cache=True)
                    if img is not None:
                        h, w = img.shape[:2]
                        screen_size = (w, h)
        except Exception:
            pass

        gctx = GraphContext(
            executor=getattr(context, "executor", None) if context else None,
            recognizer=getattr(context, "recognizer", None) if context else None,
            ocr=self._collect_ocr(context),
            stop_event=getattr(context, "stop_event", None) if context else None,
            cycle_limit_event=getattr(context, "cycle_limit_event", None) if context else None,
            task=definition,
            assets_dir=self._assets_dir,
            screen_size=screen_size,
            dry_run=bool(getattr(context, "dry_run", False) if context else False),
            get_operation=self._get_operation,
            param_values=definition.get("param_values", {}) or {},
        )

        result = run_graph(graph, gctx)
        status = _STATUS_MAP.get(result.status, TaskStatus.FAIL)
        reason = result.reason or result.error_message
        if result.status == "error":
            reason = f"可视化任务执行失败: {result.error_message}"
        return TaskResult(
            task_id=self.task_id,
            status=status,
            reason=reason,
            data={"vars": result.vars, "graph_data": result.data},
        )
