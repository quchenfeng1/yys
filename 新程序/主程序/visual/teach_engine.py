"""
17-可视化构建模块：示教引擎（P1，脚本图片指示器核心）。

职责：
- 示教运行可视化任务（后台线程执行节点图）；
- 遇未知画面（场景未命中/元素未找到）→ 保存截图 → 发布 VISUAL_UNKNOWN → 阻断执行；
- UI 收到后显示截图并接收用户指示（标注场景/指示点击/跳过）→ 发布
  VISUAL_ACTION_RECEIVED → 示教引擎更新任务定义（场景/点击点/OCR区域）→ 恢复执行。

线程模型：
- 执行线程（后台）：on_unknown 中阻塞等待指示（threading.Event）；
- UI 线程：订阅 VISUAL_ACTION_RECEIVED，处理指示后 set 事件恢复。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import cv2

from core.event_bus import get_global_bus
from core.events import Events
from visual import visual_schema as vs
from visual.graph_runner import run_graph
from visual.nodes import GraphContext


class TeachEngine:
    """示教引擎：可视化任务示教运行 + 未知画面交互"""

    def __init__(self, event_bus=None, store=None, assets_dir="",
                 executor=None, recognizer=None, anti_detect=None,
                 monitor=None, scene_store=None):
        self._bus = event_bus or get_global_bus()
        self._store = store
        self._assets_dir = Path(assets_dir) if assets_dir else Path(".")
        self._executor = executor
        self._recognizer = recognizer
        self._anti_detect = anti_detect
        self._monitor = monitor
        self._scene_store = scene_store  # 识别素材库（SceneStore）

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._running = False
        self._task_name = ""
        self._task: dict = {}
        self._pending: dict | None = None   # {"event","screenshot_path","info"}
        self._unknown_count = 0

        # 订阅用户指示（UI → 示教引擎）
        self._bus.subscribe(Events.VISUAL_ACTION_RECEIVED, self._on_action_received)

    # ── 运行控制 ──────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_task(self) -> str:
        return self._task_name

    def teach_run(self, task_name: str) -> bool:
        """示教运行指定可视化任务（后台线程）"""
        if self._running:
            return False
        if self._store is None:
            return False
        try:
            self._task = self._store.load(task_name)
        except Exception:
            return False
        self._task_name = task_name
        self._running = True
        self._stop_event.clear()
        self._unknown_count = 0
        self._worker = threading.Thread(target=self._worker_run,
                                        daemon=True,
                                        name=f"teach-{task_name}")
        self._worker.start()
        self._log(f"示教运行开始: {task_name}")
        return True

    def stop(self) -> None:
        """停止示教运行"""
        self._stop_event.set()
        with self._lock:
            if self._pending:
                # 解除阻断等待
                self._pending["event"].set()
                self._pending = None
        self._log("示教运行已停止")

    def save_task(self) -> None:
        """保存当前示教任务（场景/点击点已更新）"""
        if self._store is not None and self._task:
            try:
                self._store.save(self._task)
            except Exception:
                pass

    # ── 后台执行 ──────────────────────────────────────────

    def _worker_run(self) -> None:
        try:
            ocr = None
            if self._recognizer is not None and hasattr(self._recognizer, "_ocr"):
                ocr = self._recognizer._ocr
            gctx = GraphContext(
                executor=self._executor,
                recognizer=self._recognizer,
                ocr=ocr,
                anti_detect=self._anti_detect,
                monitor=self._monitor,
                task=self._task,
                assets_dir=self._assets_dir,
                stop_event=self._stop_event,
                on_unknown=self._on_unknown,
                scene_loader=(self._scene_store.load
                              if self._scene_store is not None else None),
                dry_run=False,
            )
            result = run_graph(self._task.get("graph", {}), gctx)
            if result.status == "error":
                self._log(f"示教执行出错: {result.error_message}", level="error")
            elif result.status == "interrupted":
                self._log("示教执行被中断")
            else:
                self._log(f"示教执行完成: {result.reason}")
            # 保存（可能示教过程添加了场景/点击点）
            self.save_task()
        except Exception as e:
            self._log(f"示教运行异常: {e}", level="error")
        finally:
            self._running = False
            self._bus.publish(Events.VISUAL_TEACH_PROGRESS,
                              task=self._task_name, phase="finished")

    def _on_unknown(self, screen, info: dict) -> None:
        """未知画面（执行线程）：保存截图 → 发布事件 → 阻断等待指示"""
        self._unknown_count += 1
        try:
            # 保存截图到任务素材目录
            assets_dir = self._store.task_assets_dir(self._task_name) if self._store else Path(".")
            ts = int(time.time() * 1000)
            path = assets_dir / f"unknown_{ts}.png"
            cv2.imwrite(str(path), screen)
        except Exception:
            path = Path("")

        evt = threading.Event()
        with self._lock:
            self._pending = {
                "event": evt,
                "screenshot_path": str(path),
                "info": info or {},
                "count": self._unknown_count,
            }

        self._log(f"遇未知画面 #{self._unknown_count}: {info.get('type', '?')}"
                  f"（等待指示…）")
        self._bus.publish(Events.VISUAL_UNKNOWN,
                          task=self._task_name,
                          screenshot_path=str(path),
                          info=info or {},
                          count=self._unknown_count)

        # 阻断执行线程，等待 UI 指示
        evt.wait(timeout=600)
        with self._lock:
            self._pending = None

    # ── 指示处理（UI 线程）────────────────────────────────

    def _on_action_received(self, **kw) -> None:
        """接收 UI 指示：更新任务定义 → 恢复执行"""
        action = kw.get("action", "")
        with self._lock:
            pending = self._pending
        if pending is None:
            return

        try:
            if action == "add_scene" and kw.get("scene"):
                scene = kw["scene"]
                vs.add_scene(self._task, scene)  # 任务内副本（兼容旧行为）
                # 保存到识别素材库（跨任务/跨节点复用）
                if self._scene_store is not None:
                    try:
                        self._scene_store.save(scene)
                    except Exception:
                        pass
                # 回填：若是「未设置的识图节点」触发的示教，把场景 id 写回该节点
                info = pending.get("info") or {}
                if info.get("type") == "scene_new" and info.get("node"):
                    self._fill_node_scene(info["node"], scene.get("id", ""))
                self._log(f"已记录场景: {scene.get('name', scene.get('id'))}")
            elif action == "add_point" and kw.get("point"):
                vs.add_point(self._task, kw["point"])
                self._log(f"已记录点击点: {kw['point'].get('label', kw['point'].get('id'))}")
            elif action == "add_element" and kw.get("template"):
                # 识图器示教：回填模板路径 + 搜索区域到目标节点
                info = pending.get("info") or {}
                if info.get("type") == "element_new" and info.get("node"):
                    self._fill_node_element(info["node"],
                                            kw.get("template", ""),
                                            kw.get("region", ""))
                self._log(f"已记录识图元素: {kw.get('template')}")
            elif action == "add_ocr_region" and kw.get("region"):
                vs.add_ocr_region(self._task, kw["region"])
                self._log(f"已记录OCR区域: {kw['region'].get('label', kw['region'].get('id'))}")
            elif action == "skip":
                self._log(f"跳过未知画面 #{pending.get('count')}")
            elif action == "stop":
                self._stop_event.set()
            # 保存任务定义（示教产物）
            self.save_task()
        finally:
            # 解除阻断
            pending["event"].set()

    def _fill_node_scene(self, node_id: str, scene_id: str) -> None:
        """把识别素材 id 回填到画布上对应节点的 params.scene"""
        if not node_id or not scene_id:
            return
        for nd in self._task.get("graph", {}).get("nodes", []):
            if nd.get("id") == node_id:
                nd.setdefault("params", {})["scene"] = scene_id
                return

    def _fill_node_element(self, node_id: str, template: str, region: str) -> None:
        """把识图模板路径 + 搜索区域回填到画布上对应节点"""
        if not node_id or not template:
            return
        for nd in self._task.get("graph", {}).get("nodes", []):
            if nd.get("id") == node_id:
                p = nd.setdefault("params", {})
                p["template"] = template
                p["region"] = region or p.get("region", "")
                return

    # ── 工具 ──────────────────────────────────────────────

    def _log(self, message: str, level: str = "info") -> None:
        if self._monitor is not None and hasattr(self._monitor, "log"):
            try:
                self._monitor.log(level.upper(), message, module="17-可视化构建")
            except Exception:
                pass
        self._bus.publish(Events.VISUAL_TEACH_PROGRESS,
                          task=self._task_name, message=message, level=level)
