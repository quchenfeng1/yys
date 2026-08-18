"""
17-可视化构建模块：VisualTask（数据驱动任务运行时，P0）。

实现 BaseTask 接口：execute() 时加载节点图 → 构造 GraphContext →
run_graph() 执行。与其他 .py 任务并存，经 TaskRegistry 注册后可被调度器调度。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from tasks.base.base_task import BaseTask
from tasks.base.task_result import TaskResult, TaskStatus
from visual import visual_schema as vs
from visual.graph_runner import GraphRunResult, run_graph
from visual.nodes import GraphContext, query_signal_table

_STATUS_MAP = {
    "success": TaskStatus.SUCCESS,
    "error": TaskStatus.FAIL,
    "interrupted": TaskStatus.ABORTED,
    "stopped": TaskStatus.ABORTED,
    "abnormal": TaskStatus.FAIL,   # 异常：由全局任务安全结束，计为失败
    "paused": TaskStatus.ABORTED,  # 暂停挂起：data['paused']=True，RunController 接管
}


class VisualTask(BaseTask):
    """可视化任务（节点图数据驱动）。"""

    task_id: str = ""
    category: str = "daily"

    # 类级注入（动态子类化时设置）
    _definition: dict = {}
    _assets_dir: str | Path = ""
    _runtime_dir: str | Path = ""   # 游戏 runtime 目录（可调用变量存储，2026-08-16）
    _screen_size: tuple = (1080, 1920)
    _display_name: str = ""
    _operation_store: Any = None   # OperationStore（4.26 通用操作）
    _compound_store: Any = None    # CompoundStore（通用节点库）
    _scene_store: Any = None       # SceneStore（识别素材库，跨任务复用）

    # ── 信号体系注入（2026-08-16，bootstrap 类级注入）──
    _anomaly_store: Any = None     # AnomalyStore（异常记录）
    _global_task_store: Any = None # GlobalTaskStore（全局任务兜底图）
    _signal_emit_cb: Any = None    # (name, payload) 发布任务信号
    _on_wait_cb: Any = None        # (task_id, signal, event, node_id) 暂停注册
    _scheduler_op_cb: Any = None   # (op, task_id) 调度器操作
    _anomaly_count: int = 5        # 异常判定连续次数
    _anomaly_window: int = 30      # 异常判定时间窗口（秒）

    def __init__(self, task_id: str, **kwargs: Any):
        super().__init__(task_id, **kwargs)
        if self._definition:
            self.task_id = self._definition.get("name", task_id) or task_id
            self.category = self._definition.get("category", "daily") or "daily"
        if not self._display_name:
            self._display_name = self._definition.get("display_name", "") or task_id
        self._in_global_task = False  # 全局任务执行中（防递归）

    def _get_compound(self, name: str) -> dict | None:
        """加载通用节点定义（复合节点内联执行用）"""
        if self._compound_store is None:
            return None
        try:
            return self._compound_store.load(name)
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

    @staticmethod
    def definition_is_trigger(defn: dict) -> bool:
        """图内是否含任务信号触发器（=触发任务判定，设计 v4）。"""
        try:
            for n in (defn.get("graph", {}) or {}).get("nodes", []):
                if n.get("type") == "task_signal_trigger":
                    return True
        except Exception:
            pass
        return False

    @classmethod
    def trigger_signal_names(cls) -> list[str]:
        """本任务触发信号名（任务信号触发器节点的 signal 参数）。"""
        out: list[str] = []
        try:
            for n in (cls._definition.get("graph", {}) or {}).get("nodes", []):
                if n.get("type") == "task_signal_trigger":
                    sig = str((n.get("params", {}) or {}).get("signal", "") or "")
                    if sig:
                        out.append(sig)
        except Exception:
            pass
        return out

    @staticmethod
    def _publish_callable_changed(task_id: str, key: str, value: Any) -> None:
        """可调用变量变化 → 事件总线（UI 实时同步，2026-08-16）"""
        try:
            from core.event_bus import get_global_bus
            from core.events import Events
            get_global_bus().publish(Events.CALLABLE_VAR_CHANGED,
                                     task_id=task_id, key=key, value=value)
        except Exception:
            pass

    @staticmethod
    def _publish_progress(snapshot: dict) -> None:
        """进度快照 → 事件总线（任务队列缩略图实时渲染，2026-08-16）"""
        try:
            from core.event_bus import get_global_bus
            from core.events import Events
            get_global_bus().publish(Events.VISUAL_PROGRESS, **snapshot)
        except Exception:
            pass

    def execute(self, context: Any = None) -> TaskResult:
        """执行节点图"""
        definition = self._definition or {}
        graph = definition.get("graph", {})

        # ── 恢复执行（2026-08-16）：暂停任务被信号唤醒后从暂停节点继续 ──
        resume = getattr(context, "resume", None) if context else None
        entry_id: str | None = None
        resume_wait = False
        preset_vars: dict = {}
        preset_data: dict = {}
        if isinstance(resume, dict):
            entry_id = resume.get("entry") or None
            preset_vars = resume.get("vars") or {}
            preset_data = resume.get("data") or {}
            resume_wait = bool(resume.get("resume_wait"))

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

        # 可调用变量持久化（2026-08-16）：运行值跨运行保留，
        # 任务启动时注入为外部参数覆盖（优先于 param_values）
        callable_store = None
        callable_overrides: dict = {}
        if self._runtime_dir:
            try:
                from visual.callable_store import CallableVarStore
                callable_store = CallableVarStore(
                    self.task_id, Path(self._runtime_dir) / "callable_vars",
                    publish=self._publish_callable_changed)
                callable_overrides = callable_store.snapshot()
            except Exception:
                callable_store = None

        # 进度组跟踪（2026-08-16）：o-o-o 缩略图状态机 + 事件发布。
        # 优先「设为阶段」的标签（有序，不依赖连线）；回退旧进度组（沿连线布局）
        progress_tracker = None
        try:
            groups = vs.stage_tags(definition)
            ordered = bool(groups)
            if not groups:
                groups = vs.normalize_progress_groups(definition)
            if groups:
                from visual.progress_tracker import ProgressTracker
                progress_tracker = ProgressTracker(
                    self.task_id, graph, groups,
                    publish=self._publish_progress, ordered=ordered)
        except Exception:
            progress_tracker = None

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
            get_compound=self._get_compound,
            scene_loader=(self._scene_store.load
                          if self._scene_store is not None else None),
            scene_lister=(self._scene_store.list
                          if self._scene_store is not None else None),
            # 外部参数：常量组值 + 任务保存值 + 可调用变量运行值（后者优先）
            param_values=vs.effective_param_values(
                definition, overrides=callable_overrides),
            callable_store=callable_store,
            task_id=self.task_id,
            on_node=(progress_tracker.node_started
                     if progress_tracker is not None else None),
            on_result=(progress_tracker.node_finished
                       if progress_tracker is not None else None),
            # ── 信号体系（2026-08-16）──
            signal_emit=self._make_signal_emit(),
            on_wait=self._on_wait_cb,
            scheduler_op=self._scheduler_op_cb,
            resume_wait=resume_wait,
        )
        # fallback 闭包引用 gctx 自身 → 构造后再挂载
        gctx.scene_fallback = self._make_scene_fallback(gctx, graph)
        # 恢复快照：变量/数据流还原
        try:
            gctx.vars.update(preset_vars)
            gctx.data.update(preset_data)
        except Exception:
            pass

        try:
            if entry_id:
                result = run_graph(graph, gctx, entry_id=entry_id)
            else:
                result = run_graph(graph, gctx)
        finally:
            if progress_tracker is not None:
                try:
                    progress_tracker.task_done()
                except Exception:
                    pass
            # 节流写盘兑底：异常/结束都强制 flush（最多丢最近 1s 累计）
            if callable_store is not None:
                try:
                    callable_store.flush()
                except Exception:
                    pass

        # 异常 → 记录 + 全局任务安全结束（2026-08-16 信号体系）
        if result.status == "abnormal":
            self._record_anomaly(reason=result.reason or "任务异常",
                                 node_id=str(gctx.data.get("_last_node_id", "") or ""),
                                 signal=str(gctx.data.get("scene_signal", "") or ""))
            self._run_global_task(context, result.reason or "任务异常")

        # 暂停挂起（2026-08-16）：返回快照供 RunController 保存
        if result.status == "paused":
            return TaskResult(
                task_id=self.task_id,
                status=_STATUS_MAP.get("paused", TaskStatus.ABORTED),
                reason=result.reason or "任务暂停",
                data={"paused": True,
                      "pause_node": gctx.data.get("_pause_node_id", ""),
                      "pause_signal": gctx.data.get("_pause_signal", ""),
                      "pause_seconds": gctx.data.get("_pause_seconds", 60),
                      "vars": result.vars, "graph_data": result.data},
            )

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

    # ── 信号体系辅助（2026-08-16）────────────────────────

    @staticmethod
    def _make_signal_emit():
        """任务信号发布回调（发布 Events.TASK_SIGNAL）。"""
        if VisualTask._signal_emit_cb is not None:
            return VisualTask._signal_emit_cb

        def _emit(name: str, payload: str = "") -> None:
            try:
                from core.event_bus import get_global_bus
                from core.events import Events
                get_global_bus().publish(Events.TASK_SIGNAL,
                                         signal=name, payload=payload)
            except Exception:
                pass
        return _emit

    def _make_scene_fallback(self, gctx: GraphContext, graph: dict):
        """未接线出口兑底（设计 v7）：场景识别器 + 异常判定 + 场景跳转。"""
        from visual.anomaly_detector import AnomalyDetector
        detector = AnomalyDetector(self._anomaly_count, self._anomaly_window)

        def _fallback(node_id: str, goto: str):
            # 记录当前节点（异常上报用）
            gctx.data["_last_node_id"] = node_id
            # 1. 任务场景识别器（识别本任务可用的场景素材）
            hit = ""
            try:
                hit = query_signal_table(gctx)
            except RuntimeError as e:
                return {"abnormal": True, "reason": str(e)}
            signal = str(gctx.data.get("scene_signal") or (hit or ""))
            # 2. 异常判定：连续同 (节点, 信号) / 窗口内同信号 N 次
            if detector.check(node_id, signal):
                return {"abnormal": True,
                        "reason": f"连续识别到同一场景信号 [{signal or '无'}] 达上限"}
            # 3. 命中 → 跳转场景信号接收节点（按场景 id 匹配）
            if hit:
                for n in graph.get("nodes", []):
                    if n.get("type") != "scene_signal_in":
                        continue
                    sid = str((n.get("params", {}) or {}).get("scene", "") or "")
                    if sid == hit:
                        return {"jump_to": n.get("id")}
            return None

        return _fallback

    def _record_anomaly(self, reason: str, node_id: str = "",
                        signal: str = "") -> None:
        """异常记录（AnomalyStore）+ 事件通知。"""
        store = self._anomaly_store
        if store is not None and hasattr(store, "record"):
            try:
                store.record(self.task_id, reason, node_id=node_id, signal=signal)
            except Exception:
                pass
        try:
            from core.event_bus import get_global_bus
            from core.events import Events
            get_global_bus().publish(Events.TASK_ANOMALY, task=self.task_id,
                                     reason=reason, node_id=node_id, signal=signal)
        except Exception:
            pass

    def _run_global_task(self, context: Any, reason: str) -> None:
        """执行全局任务（每个任务上层扣的兑底任务），安全结束。"""
        if self._in_global_task or self._global_task_store is None:
            return
        try:
            defn = self._global_task_store.load()
        except Exception:
            return
        graph = defn.get("graph", {}) if isinstance(defn, dict) else {}
        if not graph:
            return
        self._in_global_task = True
        try:
            from visual.graph_runner import run_graph as _run
            # 全局任务上下文：复用同一 executor/recognizer，异常原因写入数据流
            gctx = GraphContext(
                executor=getattr(context, "executor", None) if context else None,
                recognizer=getattr(context, "recognizer", None) if context else None,
                ocr=self._collect_ocr(context),
                stop_event=getattr(context, "stop_event", None) if context else None,
                task=defn,
                assets_dir=self._assets_dir,
                dry_run=bool(getattr(context, "dry_run", False) if context else False),
                get_compound=self._get_compound,
                scene_loader=(self._scene_store.load
                              if self._scene_store is not None else None),
                scene_lister=(self._scene_store.list
                              if self._scene_store is not None else None),
                task_id="_global_task",
                signal_emit=self._make_signal_emit(),
            )
            gctx.data["abnormal_reason"] = reason
            gctx.data["abnormal_task"] = self.task_id
            try:
                _run(graph, gctx)
            except Exception:
                pass
        finally:
            self._in_global_task = False
