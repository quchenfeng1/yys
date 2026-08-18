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
from visual.compound_store import CompoundStore


class VisualBridge:
    """可视化构建桥（支持顶部游戏下拉：操作/素材按所选游戏获取）"""

    def __init__(self, event_bus=None, store=None, teach_engine=None,
                 game_profile=None, registry=None, assets_dir="",
                 compound_store=None, scene_store=None,
                 connection=None, run_controller=None, config=None,
                 signal_registry=None, anomaly_store=None,
                 global_task_store=None):
        self._bus = event_bus or get_global_bus()
        self._store = store
        self._teach = teach_engine
        self._profile = game_profile
        self._registry = registry
        self._assets_dir = Path(assets_dir) if assets_dir else Path(".")
        self._compound_store = compound_store  # 通用节点库（CompoundStore）
        self._scene_store = scene_store  # 识别素材库（SceneStore）
        self._connection = connection
        self._run_controller = run_controller
        self._config = config  # ConfigManager（tasks.yaml 调度条目注册，2026-08-16）
        # ── 信号体系（2026-08-16）──
        self._signal_registry = signal_registry
        self._anomaly_store = anomaly_store
        self._global_task_store = global_task_store
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

    def switch_game(self, game_profile, store=None, compound_store=None,
                    scene_store=None, teach_engine=None,
                    signal_registry=None, anomaly_store=None,
                    global_task_store=None) -> None:
        """B方案（2026-08-16）：整体切换到新游戏。

        bootstrap 已按新游戏重建 store/compound_store/scene_store 后注入；
        本方法同步桥内引用与当前游戏 id。
        """
        self._profile = game_profile
        self._current_game = game_profile.game_id if game_profile else "yys"
        try:
            self._games = scan_games(Path(game_profile.root)) if game_profile else []
        except Exception:
            pass
        if store is not None:
            self._store = store
        if compound_store is not None:
            self._compound_store = compound_store
        if scene_store is not None:
            self._scene_store = scene_store
        if teach_engine is not None:
            self._teach = teach_engine
        if signal_registry is not None:
            self._signal_registry = signal_registry
        if anomaly_store is not None:
            self._anomaly_store = anomaly_store
        if global_task_store is not None:
            self._global_task_store = global_task_store
        if game_profile is not None:
            self._assets_dir = game_profile.assets_dir

    def _game(self, game_id: str | None = None) -> Any:
        """按 game_id 取 GameProfile（默认当前游戏）"""
        gid = game_id or self._current_game
        for g in self._games:
            if g.game_id == gid:
                return g
        return self._profile

    def _compound_store_for(self, game_id: str | None = None) -> CompoundStore | None:
        """通用节点库：无参/当前游戏 → 注入 _compound_store，否则按当前游戏构建；
        显式其他游戏 → 按该游戏构建。"""
        if game_id is None or game_id == self._current_game:
            if self._compound_store is not None:
                return self._compound_store
            gp = self._game(None)  # 当前游戏
            if gp is not None:
                return CompoundStore([gp.shared_nodes_dir, gp.nodes_dir])
            return self._compound_store
        gp = self._game(game_id)
        if gp is None:
            return self._compound_store
        return CompoundStore([gp.shared_nodes_dir, gp.nodes_dir])

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

    # ── 可调用变量（2026-08-16）───────────────────────────
    def callable_var_values(self, task_name: str) -> dict:
        """可调用变量运行值（runtime/callable_vars/{task}.json，跨运行保留）"""
        try:
            import json
            gp = self._game(None)
            if gp is None:
                return {}
            path = Path(gp.runtime_dir) / "callable_vars" / f"{task_name}.json"
            if not path.exists():
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def set_callable_var(self, task_name: str, key: str, value) -> None:
        """UI 手动修改可调用变量：写入运行值文件（下次运行生效）"""
        try:
            import json
            gp = self._game(None)
            if gp is None:
                return
            path = Path(gp.runtime_dir) / "callable_vars" / f"{task_name}.json"
            data: dict = {}
            if path.exists():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        data = loaded
                except Exception:
                    data = {}
            data[key] = value
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(path)
        except Exception:
            pass

    # ── tasks.yaml 调度条目注册（2026-08-16）────────────
    def _ensure_schedule_entry(self, name: str, task: dict) -> None:
        """可视化任务保存/创建后，确保 tasks.yaml 存在对应调度条目。

        调度器只从 tasks.yaml 加载任务配置 → 可视化任务必须注册条目
        才能出现在游戏任务列表/任务队列并可配置调度。幂等：已存在不覆盖。
        """
        cfg = self._config
        if cfg is None:
            return
        try:
            existing = cfg.get_task_config(name) if hasattr(
                cfg, 'get_task_config') else None
        except Exception:
            existing = None
        if existing:
            return
        try:
            if hasattr(cfg, 'update_task'):
                cfg.update_task(
                    name,
                    category=task.get("category", "daily") or "daily",
                    display_name=task.get("display_name", "") or name,
                    enabled=True,
                )
        except Exception:
            pass

    def save_task(self, task: dict) -> None:
        """保存任务（合并示教产物），注册调度条目，发布变更事件"""
        name = task.get("name", "")
        # 合并示教引擎内存中的示教产物（场景/点击点/OCR区域）
        teach_task = self.get_task(name)
        if teach_task is not None:
            task.setdefault("teach", {})
            if teach_task.get("teach"):
                task["teach"] = teach_task["teach"]
        self._store.save(task)
        self._ensure_schedule_entry(name, task)
        self._bus.publish(Events.VISUAL_TASK_CHANGED, source="visual_bridge",
                          task_name=name)

    def create_task(self, name: str, display_name: str = "",
                    category: str = "daily") -> dict:
        task = self._store.create(name, display_name, category)
        self._ensure_schedule_entry(name, task)
        self._bus.publish(Events.VISUAL_TASK_CHANGED, source="visual_bridge",
                          task_name=name)
        return task

    def delete_task(self, name: str) -> bool:
        ok = self._store.delete(name)
        if not ok:
            return False
        # 清理调度条目 + 注册表（2026-08-16）：否则任务队列仍会显示已删任务
        # （_ensure_schedule_entry 在保存时写入 tasks.yaml，删除必须对称移除；
        #   CONFIG_CHANGED → 调度器热重载并清理 next_run 等状态）
        try:
            if self._config is not None and hasattr(self._config, "remove_task"):
                self._config.remove_task(name)
        except Exception:
            pass
        try:
            if self._registry is not None and hasattr(self._registry, "unregister"):
                self._registry.unregister(name)
        except Exception:
            pass
        self._bus.publish(Events.VISUAL_TASK_CHANGED, source="visual_bridge",
                          task_name=name)
        return ok

    def task_assets_dir(self, name: str) -> Path:
        return self._store.task_assets_dir(name)

    # ── 示教运行 ─────────────────────────────────────────
    def teach_run(self, name: str, step_mode: bool = False,
                  params: dict | None = None) -> bool:
        """测试启动；step_mode=True → 单步调试（每节点前暂停等下一步）；
        params = 外部参数覆盖值（变量组键→值，可选）"""
        if self._teach is None:
            return False
        return self._teach.teach_run(name, step_mode=step_mode,
                                     params=params)

    def teach_step(self) -> None:
        """单步调试：放行一步"""
        if self._teach is not None:
            self._teach.next_step()

    def teach_step_mode(self) -> bool:
        """是否处于单步调试运行中（下一步按钮状态）"""
        return self._teach is not None and self._teach.step_mode

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

    def scene_list(self) -> list[dict]:
        """场景素材列表（含显示名）[{id, name}]：素材管理弹窗全局库用"""
        out: list[dict] = []
        seen: set[str] = set()
        if self._scene_store is not None:
            for s in self._scene_store.list():
                sid = s.get("id", "")
                if sid and sid not in seen:
                    seen.add(sid)
                    out.append({"id": sid, "name": s.get("name", sid)})
        task = self._teach._task if self._teach and self._teach._task else {}
        for s in task.get("teach", {}).get("scenes", []):
            sid = s.get("id", "")
            if sid and sid not in seen:
                seen.add(sid)
                out.append({"id": sid, "name": s.get("name", sid)})
        return out

    def signal_options(self) -> list[tuple[str, str]]:
        """触发信号下拉源（2026-08-16 素材库重构后）：
        [(信号名, 场景id)]，来自 SceneStore 场景的 signal 字段。"""
        if self._scene_store is not None:
            try:
                return self._scene_store.signal_options()
            except Exception:
                pass
        return []

    def scene_signal_map(self) -> dict[str, str]:
        """场景信号映射 {特征块模板相对路径(去扩展名): 信号名}（RunController 注入用）"""
        if self._scene_store is not None:
            try:
                return self._scene_store.signal_map()
            except Exception:
                pass
        return {}

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

    def save_scene(self, scene: dict) -> bool:
        """保存识别素材到素材库（跨任务复用）；返回是否成功。

        素材库未配置（scene_store=None）时返回 False，由调用方双写到任务文件。
        """
        if self._scene_store is None:
            return False
        try:
            self._scene_store.save(scene)
            return True
        except Exception:
            return False

    def load_scene(self, scene_id: str) -> dict | None:
        """读取场景素材（含 signal 信号名，信号触发器下拉用）"""
        if self._scene_store is not None:
            try:
                return self._scene_store.load(scene_id)
            except Exception:
                pass
        return None

    def delete_scene(self, scene_id: str) -> bool:
        """删除场景识别素材（素材管理页删除用）；返回是否成功"""
        if self._scene_store is None:
            return False
        try:
            return self._scene_store.delete(scene_id)
        except Exception:
            return False

    def point_items(self) -> list[str]:
        task = self._teach._task if self._teach and self._teach._task else {}
        return [p.get("id", "") for p in task.get("teach", {}).get("points", [])]

    def ocr_items(self) -> list[str]:
        task = self._teach._task if self._teach and self._teach._task else {}
        return [r.get("id", "") for r in task.get("teach", {}).get("ocr_regions", [])]

    def element_items(self, game_id: str | None = None) -> list[str]:
        """素材元素列表（点击器下拉）：assets 下全部 .png 相对路径。
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

    def icon_items(self, game_id: str | None = None) -> list[str]:
        """示教图标素材列表（素材管理左侧「图标素材」+ 点击器下拉源）。

        图标素材 = 结构化条目（与场景素材同规格）：
          assets/**/icons/{条目名}.json 为主文件（image/region/threshold），
          PNG 只是图片数据。列表返回条目 json 的相对路径。
        兼容旧数据：无条目 json 的 icons/ 下 PNG、visual/ 根级平铺 PNG。
        """
        import json
        items: list[str] = []
        if game_id is None or game_id == self._current_game:
            assets_dir = self._assets_dir
        else:
            gp = self._game(game_id)
            assets_dir = gp.assets_dir if gp is not None else self._assets_dir
        if not assets_dir.exists():
            return items
        entry_jsons: set[str] = set()
        # 1) 条目化图标素材：**/icons/*.json（含 image 字段）
        for p in sorted(assets_dir.rglob("*.json")):
            try:
                rel = p.relative_to(assets_dir).as_posix()
            except Exception:
                continue
            if rel.startswith(".") or "/icons/" not in "/" + rel:
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8")) or {}
            except Exception:
                data = {}
            if not data.get("image"):
                continue  # 旧版 png 旁 region 元数据 → 不算条目
            entry_jsons.add(rel)
            items.append(rel)
        # 2) 旧产物兼容：visual/ 根级平铺 PNG；
        #    icons/ 目录内已有条目 json 时只列条目（PNG 是条目内部数据）
        entry_dirs = {e.rsplit("/", 1)[0] for e in entry_jsons}
        for p in sorted(assets_dir.rglob("*.png")):
            try:
                rel = p.relative_to(assets_dir).as_posix()
            except Exception:
                continue
            if rel.startswith("."):
                continue
            if "/scenes/" in "/" + rel:
                continue  # 场景特征块 PNG 不是图标素材
            if "/icons/" in "/" + rel:
                if rel.rsplit("/", 1)[0] in entry_dirs:
                    continue  # 该 icons 目录已条目化 → 只列条目 json
                items.append(rel)
            elif rel.startswith("visual/") and rel.count("/") == 1:
                items.append(rel)
        return items

    def ocr_items(self, game_id: str | None = None) -> list[str]:
        """OCR识别素材列表（素材管理左侧「OCR识别素材」+ OCR读取下拉源）。

        OCR识别素材 = 结构化条目：assets/**/ocr/{条目名}.json
        （image=蓝框遮罩图、region=红框搜索区域、ocr_box=黄框文字位置像素偏移）。
        """
        import json
        items: list[str] = []
        if game_id is None or game_id == self._current_game:
            assets_dir = self._assets_dir
        else:
            gp = self._game(game_id)
            assets_dir = gp.assets_dir if gp is not None else self._assets_dir
        if not assets_dir.exists():
            return items
        for p in sorted(assets_dir.rglob("*.json")):
            try:
                rel = p.relative_to(assets_dir).as_posix()
            except Exception:
                continue
            if rel.startswith(".") or "/ocr/" not in "/" + rel:
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8")) or {}
            except Exception:
                data = {}
            if data.get("image"):
                items.append(rel)
        return items

    # ── 通用节点（2026-08-15：框选封装 → 保存为通用节点，取代通用操作）──
    def compound_list(self, game_id: str | None = None) -> list[dict]:
        """通用节点列表（节点库「通用节点」Tab 用）：
        所选游戏 [{name, display_name, node_count}]"""
        store = self._compound_store_for(game_id)
        if store is None:
            return []
        return store.list()

    def load_compound(self, name: str, game_id: str | None = None) -> dict | None:
        store = self._compound_store_for(game_id)
        if store is None:
            return None
        try:
            return store.load(name)
        except Exception:
            return None

    def save_compound(self, node_def: dict, game_id: str | None = None) -> None:
        store = self._compound_store_for(game_id)
        if store is not None:
            store.save(node_def)

    def delete_compound(self, name: str, game_id: str | None = None) -> bool:
        store = self._compound_store_for(game_id)
        if store is None:
            return False
        return store.delete(name)

    # ── 信号管理面板数据源（2026-08-16）───────────────

    def scene_signal_list(self) -> list[dict]:
        if self._signal_registry is None:
            return []
        try:
            return self._signal_registry.scene_signals()
        except Exception:
            return []

    def task_signal_list(self) -> list[dict]:
        if self._signal_registry is None:
            return []
        try:
            return self._signal_registry.task_signals()
        except Exception:
            return []

    def trigger_signal_list(self) -> list[dict]:
        if self._signal_registry is None:
            return []
        try:
            return self._signal_registry.trigger_signals()
        except Exception:
            return []

    def custom_signal_list(self) -> list[str]:
        if self._signal_registry is None:
            return []
        try:
            return self._signal_registry.custom_signals()
        except Exception:
            return []

    def add_custom_signal(self, name: str) -> bool:
        if self._signal_registry is None:
            return False
        try:
            return bool(self._signal_registry.add_custom(name))
        except Exception:
            return False

    def remove_custom_signal(self, name: str) -> bool:
        if self._signal_registry is None:
            return False
        try:
            return bool(self._signal_registry.remove_custom(name))
        except Exception:
            return False

    # ── 全局任务（2026-08-16）──────────────────────────

    def global_task_load(self) -> dict:
        if self._global_task_store is None:
            return {}
        try:
            return self._global_task_store.load()
        except Exception:
            return {}

    def global_task_save(self, task: dict) -> bool:
        if self._global_task_store is None:
            return False
        try:
            return bool(self._global_task_store.save(task))
        except Exception:
            return False

    # ── 异常任务面板数据源（2026-08-16）─────────────────

    def anomaly_list(self, task_name: str | None = None) -> list[dict]:
        if self._anomaly_store is None:
            return []
        try:
            return self._anomaly_store.list(task_name)
        except Exception:
            return []

    def anomaly_mark_handled(self, anomaly_id: str) -> bool:
        if self._anomaly_store is None:
            return False
        try:
            return bool(self._anomaly_store.mark_handled(anomaly_id))
        except Exception:
            return False

    def anomaly_confirm_fixed(self, task_name: str) -> bool:
        if self._anomaly_store is None:
            return False
        try:
            return bool(self._anomaly_store.confirm_fixed(task_name))
        except Exception:
            return False

    def anomaly_abnormal_tasks(self) -> list[str]:
        if self._anomaly_store is None:
            return []
        try:
            return self._anomaly_store.abnormal_tasks()
        except Exception:
            return []

    def anomaly_unresolved_count(self, task_name: str) -> int:
        if self._anomaly_store is None:
            return 0
        try:
            return int(self._anomaly_store.unresolved_count(task_name))
        except Exception:
            return 0

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
