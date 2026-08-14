"""
17-可视化构建模块：UI↔核心桥（VisualBridge）。

面板 → 规则库 / 示教引擎 / 素材元素的桥（保持 UI↔核心解耦，沿用 param_bridge 模式）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.event_bus import get_global_bus
from core.events import Events
from core.game_profile import scan_games
from visual.operation_store import OperationStore


class VisualBridge:
    """可视化构建桥（支持顶部游戏下拉：操作/素材按所选游戏获取）"""

    def __init__(self, event_bus=None, store=None, teach_engine=None,
                 game_profile=None, registry=None, assets_dir="",
                 operation_store=None, scene_store=None,
                 connection=None, run_controller=None):
        self._bus = event_bus or get_global_bus()
        self._store = store
        self._teach = teach_engine
        self._profile = game_profile
        self._registry = registry
        self._assets_dir = Path(assets_dir) if assets_dir else Path(".")
        self._op_store = operation_store
        self._scene_store = scene_store  # 识别素材库（SceneStore）
        self._connection = connection
        self._run_controller = run_controller
        # 游戏列表 + 当前游戏（顶部下拉）
        root = Path(self._profile.root) if self._profile else Path(".")
        self._games = scan_games(root)
        self._current_game = self._profile.game_id if self._profile else "yys"

    # ── 运行环境状态 ────────────────────────────────────
    def is_connected(self) -> bool:
        """设备/模拟器是否已连接（测试启动前置条件）"""
        if self._connection is not None and hasattr(self._connection, "is_connected"):
            try:
                return bool(self._connection.is_connected())
            except Exception:
                return False
        return False

    def is_script_running(self) -> bool:
        """正式任务（脚本）是否正在运行（与测试启动互斥）"""
        if self._run_controller is not None and \
                hasattr(self._run_controller, "is_running"):
            try:
                return bool(self._run_controller.is_running)
            except Exception:
                return False
        return False

    # ── 当前游戏 ────────────────────────────────────────
    def game_list(self) -> list[tuple[str, str]]:
        """游戏列表 [(game_id, display_name)]（顶部下拉数据源）"""
        return [(g.game_id, g.display_name) for g in self._games]

    @property
    def current_game(self) -> str:
        return self._current_game

    def set_current_game(self, game_id: str) -> None:
        self._current_game = game_id

    def _game(self, game_id: str | None = None) -> Any:
        """按 game_id 取 GameProfile（默认当前游戏）"""
        gid = game_id or self._current_game
        for g in self._games:
            if g.game_id == gid:
                return g
        return self._profile

    def _op_store_for(self, game_id: str | None = None) -> OperationStore | None:
        """操作 store：无参/当前游戏 → 注入 _op_store，否则按当前游戏构建；
        显式其他游戏 → 按该游戏构建。"""
        if game_id is None or game_id == self._current_game:
            if self._op_store is not None:
                return self._op_store
            gp = self._game(None)  # 当前游戏
            if gp is not None:
                return OperationStore([gp.shared_operations_dir,
                                       gp.operations_dir])
            return self._op_store
        gp = self._game(game_id)
        if gp is None:
            return self._op_store
        return OperationStore([gp.shared_operations_dir, gp.operations_dir])

    # ── 任务 CRUD ────────────────────────────────────────
    def list_tasks(self) -> list[dict]:
        if self._store is None:
            return []
        return self._store.list()

    def load_task(self, name: str) -> dict:
        return self._store.load(name)

    def get_task(self, name: str) -> dict | None:
        """获取任务定义（示教运行中优先返回示教引擎内存版本，含最新示教产物）"""
        if self._teach is not None and self._teach.current_task == name \
                and self._teach._task:
            return self._teach._task
        try:
            return self._store.load(name)
        except Exception:
            return None

    def save_task(self, task: dict) -> None:
        """保存任务（合并示教产物），发布变更事件"""
        name = task.get("name", "")
        # 合并示教引擎内存中的示教产物（场景/点击点/OCR区域）
        teach_task = self.get_task(name)
        if teach_task is not None:
            task.setdefault("teach", {})
            if teach_task.get("teach"):
                task["teach"] = teach_task["teach"]
        self._store.save(task)
        self._bus.publish(Events.VISUAL_TASK_CHANGED, source="visual_bridge",
                          task_name=name)

    def create_task(self, name: str, display_name: str = "",
                    category: str = "daily") -> dict:
        task = self._store.create(name, display_name, category)
        self._bus.publish(Events.VISUAL_TASK_CHANGED, source="visual_bridge",
                          task_name=name)
        return task

    def delete_task(self, name: str) -> bool:
        ok = self._store.delete(name)
        if ok:
            self._bus.publish(Events.VISUAL_TASK_CHANGED, source="visual_bridge",
                              task_name=name)
        return ok

    def task_assets_dir(self, name: str) -> Path:
        return self._store.task_assets_dir(name)

    # ── 示教运行 ─────────────────────────────────────────
    def teach_run(self, name: str) -> bool:
        if self._teach is None:
            return False
        return self._teach.teach_run(name)

    def teach_stop(self) -> None:
        if self._teach is not None:
            self._teach.stop()

    def teach_running(self) -> bool:
        return self._teach is not None and self._teach.is_running

    def current_teach_task(self) -> str:
        return self._teach.current_task if self._teach else ""

    # ── 下拉数据源（节点参数）────────────────────────────
    def scene_items(self) -> list[str]:
        """场景下拉：识别素材库（跨任务复用）+ 当前任务已录场景（去重）"""
        items: list[str] = []
        seen: set[str] = set()
        if self._scene_store is not None:
            for s in self._scene_store.list():
                sid = s.get("id", "")
                if sid and sid not in seen:
                    seen.add(sid)
                    items.append(sid)
        task = self._teach._task if self._teach and self._teach._task else {}
        for s in task.get("teach", {}).get("scenes", []):
            sid = s.get("id", "")
            if sid and sid not in seen:
                seen.add(sid)
                items.append(sid)
        return items

    def capture_screen(self):
        """截取一张当前画面（手动示教按钮用），返回 ndarray 或 None"""
        teach = self._teach
        if teach is None:
            return None
        ex = getattr(teach, "_executor", None)
        if ex is not None and hasattr(ex, "_recognizer"):
            try:
                img = ex._recognizer._get_screenshot()
                if img is not None:
                    return img
            except Exception:
                pass
        if ex is not None and hasattr(ex, "_connection"):
            try:
                return ex._connection.screenshot(use_cache=False)
            except Exception:
                return None
        return None

    def save_scene(self, scene: dict) -> None:
        """保存识别素材到素材库（跨任务复用）"""
        if self._scene_store is not None:
            self._scene_store.save(scene)

    def point_items(self) -> list[str]:
        task = self._teach._task if self._teach and self._teach._task else {}
        return [p.get("id", "") for p in task.get("teach", {}).get("points", [])]

    def ocr_items(self) -> list[str]:
        task = self._teach._task if self._teach and self._teach._task else {}
        return [r.get("id", "") for r in task.get("teach", {}).get("ocr_regions", [])]

    def element_items(self, game_id: str | None = None) -> list[str]:
        """素材元素列表（matcher 节点下拉）：assets 下全部 .png 相对路径。
        无参/当前游戏 → 注入的 assets_dir；其他游戏 → 该游戏 assets。
        """
        if game_id is None or game_id == self._current_game:
            assets_dir = self._assets_dir
        else:
            gp = self._game(game_id)
            assets_dir = gp.assets_dir if gp is not None else self._assets_dir
        items: list[str] = []
        if not assets_dir.exists():
            return items
        for p in sorted(assets_dir.rglob("*.png")):
            try:
                rel = p.relative_to(assets_dir).as_posix()
            except Exception:
                continue
            if rel.startswith("."):
                continue
            items.append(rel)
        return items

    # ── 通用操作（4.26 Operation）────────────────────────
    def operation_items(self, game_id: str | None = None) -> list[str]:
        """所选游戏可用操作名列表（operation 节点下拉）"""
        store = self._op_store_for(game_id)
        if store is None:
            return []
        return store.names()

    def operation_list(self, game_id: str | None = None) -> list[dict]:
        """操作列表（节点库「通用节点」Tab 用）：所选游戏 [{name, display_name, ...}]"""
        store = self._op_store_for(game_id)
        if store is None:
            return []
        return store.list()

    def load_operation(self, name: str, game_id: str | None = None) -> dict | None:
        store = self._op_store_for(game_id)
        if store is None:
            return None
        try:
            return store.load(name)
        except Exception:
            return None

    def save_operation(self, operation: dict, game_id: str | None = None) -> None:
        store = self._op_store_for(game_id)
        if store is not None:
            store.save(operation)

    def create_operation(self, name: str, display_name: str = "",
                         game_id: str | None = None) -> dict:
        store = self._op_store_for(game_id)
        if store is None:
            raise RuntimeError("OperationStore 不可用")
        return store.create(name, display_name)

    def delete_operation(self, name: str, game_id: str | None = None) -> bool:
        store = self._op_store_for(game_id)
        if store is None:
            return False
        return store.delete(name)

    def collect_params(self, task: dict) -> list[dict]:
        """参数上浮（4.27）：扫描任务图中 operation 节点，收集 hoist 参数"""
        from visual.visual_schema import collect_task_params
        return collect_task_params(task, self.load_operation)

    def get_operation_inputs(self, op_name: str) -> list[dict]:
        op = self.load_operation(op_name)
        return op.get("inputs", []) if op else []

    def get_ocr(self):
        """从示教引擎的识别器提取 OcrLocator（复用现有 PaddleOCR 引擎）"""
        if self._teach is not None and self._teach._recognizer is not None:
            rec = self._teach._recognizer
            if hasattr(rec, "_ocr"):
                return rec._ocr
        return None

    # ── 示教产物下拉（实时：优先示教引擎内存版本）──────────
    def _teach_of(self, task_name: str) -> dict:
        task = self.get_task(task_name)
        return (task or {}).get("teach", {}) or {}

    def scene_items_for(self, task_name: str) -> list[str]:
        teach = self._teach_of(task_name)
        return [s.get("id", "") for s in teach.get("scenes", [])]

    def point_items_for(self, task_name: str) -> list[str]:
        teach = self._teach_of(task_name)
        return [p.get("id", "") for p in teach.get("points", [])]

    def ocr_items_for(self, task_name: str) -> list[str]:
        teach = self._teach_of(task_name)
        return [r.get("id", "") for r in teach.get("ocr_regions", [])]
