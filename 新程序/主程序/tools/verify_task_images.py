"""端到端验证：任务图片配置（逻辑名 → 素材路径，§5.2）。

验证点：
  1. TaskManager.get_task_asset_refs 从任务代码提取图片引用清单
  2. ConfigManager.update_task 持久化 images 到 tasks.yaml + 读回
  3. Scheduler/TaskConfig 解析 images 字段
  4. Executor.set_asset_aliases → click_image("逻辑名") 命中映射素材（真实识别）
  5. Executor 别名解析覆盖 click_if_exists/detect_scene/wait_any/ensure_scene
  6. TaskContext.resolve_asset
  7. UI：TaskManagerPanel 详情渲染图片设置区 + AssetPickerDialog
"""
import sys, os, tempfile, shutil
from pathlib import Path

import numpy as np
import cv2

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt5.QtWidgets import QApplication


def _make_template(name: str, size: tuple[int, int], seed: int) -> np.ndarray:
    w, h = size
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (255, 255, 255), 2)
    cv2.putText(img, name.split("/")[-1][:8], (6, h // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    return img


class MockConnection:
    """模拟设备：合成截图（含素材模板）+ 记录点击"""
    SCREEN_W, SCREEN_H = 1080, 1920

    def __init__(self, templates: dict[str, np.ndarray]):
        self.templates = templates
        self.clicks: list[tuple[int, int]] = []
        self._screen = None
        self._positions: dict[str, tuple[int, int]] = {}

    def _build_screen(self) -> np.ndarray:
        screen = np.full((self.SCREEN_H, self.SCREEN_W, 3), 30, dtype=np.uint8)
        y = 60
        for name, tpl in self.templates.items():
            h, w = tpl.shape[:2]
            x = 100
            if y + h > self.SCREEN_H:
                break
            screen[y:y + h, x:x + w] = tpl
            self._positions[name] = (x, y)
            y += h + 40
        return screen

    def screenshot(self, use_cache: bool = False) -> np.ndarray:
        if self._screen is None or not use_cache:
            self._screen = self._build_screen()
        return self._screen.copy()

    def click(self, x: int, y: int) -> None:
        self.clicks.append((int(x), int(y)))

    def swipe(self, *a, **k):
        pass

    def echo(self) -> bool:
        return True

    def is_connected(self) -> bool:
        return True


TASK_CODE = '''"""
临时验证任务：图片引用（逻辑名）
"""
display_name = "图片映射验证"
task_type = "event_task"

from tasks.base.base_task import BaseTask
from tasks.base.task_graph import TaskGraph
from tasks.base.task_step import StepResult, TaskStep


class StepOne(TaskStep):
    def execute(self, context=None):
        # 逻辑名引用（§5.2 可配置为素材路径）
        context.executor.click_image("btn.start")
        context.executor.click_if_exists("btn.close")
        context.executor.detect_scene(["scene.main"])
        context.executor.ensure_scene("scene.home")
        context.executor.wait_any(["scene.a", "scene.b"], timeout=5)
        return StepResult.success("ok")


class ImgmapDemo(BaseTask):
    task_id = "imgmap_demo"

    def _build_graph(self) -> TaskGraph:
        g = TaskGraph()
        g.add_step("one", StepOne())
        g.set_entry("one")
        return g
'''


def main():
    app = QApplication(sys.argv)
    ok, fail = 0, 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"✅ {name}")
        else:
            fail += 1
            print(f"❌ {name}  {detail}")

    # ════════════ 0. 临时目录 + 素材 + 任务文件 ════════════
    tmp = Path(tempfile.mkdtemp(prefix="imgmap_"))
    assets = tmp / "assets"
    (assets / "tasks" / "imgmap_demo").mkdir(parents=True, exist_ok=True)
    (assets / "tasks" / "_shared").mkdir(parents=True, exist_ok=True)
    (assets / "scene").mkdir(parents=True, exist_ok=True)
    # 真实素材（映射目标）
    cv2.imwrite(str(assets / "tasks" / "imgmap_demo" / "真实按钮.png"),
                _make_template("tasks/imgmap_demo/真实按钮", (160, 60), 11))
    cv2.imwrite(str(assets / "tasks" / "imgmap_demo" / "关闭.png"),
                _make_template("tasks/imgmap_demo/关闭", (120, 60), 12))
    # 控制素材（tasks/_shared/，任务选图只用它）
    cv2.imwrite(str(assets / "tasks" / "_shared" / "确认.png"),
                _make_template("tasks/_shared/确认", (140, 60), 13))
    cv2.imwrite(str(assets / "scene" / "main.png"),
                _make_template("scene/main", (200, 80), 21))
    cv2.imwrite(str(assets / "scene" / "home.png"),
                _make_template("scene/home", (200, 80), 22))
    cv2.imwrite(str(assets / "scene" / "a.png"),
                _make_template("scene/a", (160, 70), 31))
    cv2.imwrite(str(assets / "scene" / "b.png"),
                _make_template("scene/b", (160, 70), 32))

    # 任务文件（daily 分类）
    task_file = tmp / "tasks" / "daily" / "imgmap_demo.py"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(TASK_CODE, encoding="utf-8")

    # ════════════ 1. 发现层：get_task_asset_refs ════════════
    print("\n── [1/7] TaskManager.get_task_asset_refs ──")
    from core.task_manager import TaskManager
    tm = TaskManager(tasks_dir=tmp / "tasks", assets_dir=assets)
    refs = tm.get_task_asset_refs("imgmap_demo")
    check("提取 6 个引用", len(refs) == 6, str(refs))
    for expect in ("btn.start", "btn.close", "scene.main", "scene.home", "scene.a", "scene.b"):
        check(f"引用含 {expect}", expect in refs, str(refs))

    # ════════════ 2. 持久化：ConfigManager.update_task images ════════════
    print("\n── [2/7] ConfigManager 持久化 images ──")
    from core.config_manager import ConfigManager
    cm = ConfigManager(config_dir=tmp / "config", enable_hot_reload=False)
    images = {
        "btn.start": "tasks/imgmap_demo/真实按钮",
        "btn.close": "tasks/imgmap_demo/关闭",
        "scene.main": "scene/main",
        "scene.home": "scene/home",
        "scene.a": "scene/a",
        "scene.b": "scene/b",
    }
    cm.update_task("imgmap_demo", images=images)
    cfg_read = cm.get_task_config("imgmap_demo")
    check("tasks.yaml 读回 images", (cfg_read or {}).get("images") == images, str(cfg_read))
    check("写盘文件含 images", "images:" in (tmp / "config" / "tasks.yaml").read_text(encoding="utf-8"))

    # ════════════ 3. Scheduler/TaskConfig 解析 images ════════════
    print("\n── [3/7] Scheduler TaskConfig 解析 images ──")
    from core.scheduler import Scheduler, TaskConfig
    check("TaskConfig 含 images 字段", "images" in TaskConfig.__dataclass_fields__)
    # 轻量解析验证：构造 Scheduler 并加载
    try:
        class _Store:
            def __init__(self):
                self.data = {}

            def load(self):
                return type("D", (), {"data": self.data})()

            def save(self, d):
                self.data = d

            def get(self, n):
                return None

            def update(self, n, **k):
                pass

        sch = Scheduler(config=cm, store=_Store())
        sch.load_tasks_from_config()
        tc = sch.get_config("imgmap_demo")
        check("scheduler 解析 images", tc is not None and tc.images == images,
              str(getattr(tc, 'images', None) if tc else None))
    except Exception as e:
        check("scheduler 解析 images", False, f"异常: {e}")

    # ════════════ 4. Executor 别名解析 → 真实识别命中 ════════════
    print("\n── [4/7] Executor 别名解析识别命中 ──")
    from core.recognizer import Recognizer
    from core.anti_detect import AntiDetect
    from core.executor import Executor

    templates = {}
    for p in assets.rglob("*.png"):
        templates[str(p.relative_to(assets)).replace("\\", "/").rsplit(".", 1)[0]] = cv2.imread(str(p))
    conn = MockConnection(templates)
    rec = Recognizer(asset_dir=str(assets), connection=conn,
                     screenshot_ttl=0.05, result_cache_ttl=0.01)
    ex = Executor(recognizer=rec, anti_detect=AntiDetect(min_interval=0.001, max_interval=0.002,
                                                         action_jitter=False, random_fail_rate=0),
                  connection=conn, dry_run=False)
    # 注入别名（模拟 run_controller 行为）
    ex.set_asset_aliases(images)

    ok_start = ex.click_image("btn.start", timeout=3)  # 逻辑名 → 真实按钮
    check("click_image 经别名命中真实素材", ok_start and len(conn.clicks) >= 1,
          f"clicks={conn.clicks}")
    conn.clicks.clear()
    ok_close = ex.click_if_exists("btn.close")  # 逻辑名 → 关闭
    check("click_if_exists 经别名命中", ok_close and len(conn.clicks) >= 1,
          f"clicks={conn.clicks}")
    scene = ex.detect_scene(["scene.main"], timeout=2)
    check("detect_scene 经别名命中（返回映射路径）", scene == "scene/main", str(scene))
    ok_ensure = ex.ensure_scene("scene.home", timeout=2)
    check("ensure_scene 经别名命中 scene.home", ok_ensure)
    got = ex.wait_any(["scene.a", "scene.b"], timeout=2)
    check("wait_any 经别名命中", got is not None and got[0] in ("scene/a", "scene/b"),
          str(got))

    # 未映射逻辑名 → 原样识别（应失败，因为 assets 无 btn.start 素材）
    ex.set_asset_aliases({})  # 清空别名
    conn.clicks.clear()
    ok_none = ex.click_image("btn.start", timeout=1)
    check("无映射时逻辑名直接识别（不存在→不点击）", not ok_none and len(conn.clicks) == 0)

    # ════════════ 5. TaskContext.resolve_asset ════════════
    print("\n── [5/7] TaskContext.resolve_asset ──")
    from tasks.base.task_context import TaskContext
    ctx = TaskContext(task_id="imgmap_demo", task_name="imgmap_demo",
                      task_config={"images": images}, executor=ex)
    check("resolve_asset 命中映射", ctx.resolve_asset("btn.start") == "tasks/imgmap_demo/真实按钮")
    check("resolve_asset 未映射原样", ctx.resolve_asset("btn.other") == "btn.other")

    # ════════════ 6. UI：详情图片设置区 ════════════
    print("\n── [6/7] TaskManagerPanel 图片设置区 ──")
    from ui.panels.task_manager_panel import TaskManagerPanel, AssetPickerDialog
    # 构造 bridge
    from core.task_manager import TaskManager as TM2
    tm2 = TM2(tasks_dir=tmp / "tasks", assets_dir=assets)
    bridge = type("B", (), {
        "task": type("T", (), {
            "get_task_detail": lambda self, n: {"name": n, "display_name": "图片映射验证",
                                                "task_type": "event_task", "images": images},
            "get_task_asset_refs": lambda self, n: [{"ref": r, "mapped": images.get(r)}
                                                     for r in tm2.get_task_asset_refs(n)],
            "save_task_images": lambda self, n, im: cm.update_task(n, images=im),
        })(),
    })()
    panel = TaskManagerPanel(param_bridge=bridge)
    panel._current_name = "imgmap_demo"
    panel._render_detail({"name": "imgmap_demo", "display_name": "图片映射验证",
                          "task_type": "event_task", "images": images})
    check("编辑态含映射", panel._images_editing.get("btn.start") == "tasks/imgmap_demo/真实按钮",
          str(panel._images_editing))

    dlg = AssetPickerDialog(assets_dir=assets)
    # 任务选图只从「控制素材」tasks/_shared/ 选（识图素材由场景识别模块统一处理）
    check("选图对话框只列控制素材", dlg.list_widget.count() == 1
          and all("tasks/_shared/" in dlg.list_widget.item(i).text()
                  for i in range(dlg.list_widget.count())),
          f"count={dlg.list_widget.count()}")
    dlg.list_widget.setCurrentRow(0)
    check("选图对话框 selected 返回引用路径",
          dlg.selected() == "tasks/_shared/确认", str(dlg.selected()))

    # 模拟选图（直接改编辑态 + 保存；monkeypatch 模态框避免 offscreen 卡死）
    from PyQt5.QtWidgets import QMessageBox as _MB
    _MB.information = staticmethod(lambda *a, **k: None)
    _MB.warning = staticmethod(lambda *a, **k: None)
    panel._images_editing["btn.start"] = "scene/main"
    panel._save_images()
    cfg_after = cm.get_task_config("imgmap_demo")
    check("保存后 tasks.yaml images 更新", (cfg_after or {}).get("images", {}).get("btn.start") == "scene/main",
          str((cfg_after or {}).get("images")))

    # ════════════ 7. 回归：无别名时现有硬编码引用不受影响 ════════════
    print("\n── [7/7] 兼容性 ──")
    conn.clicks.clear()
    ex.set_asset_aliases({})
    ok_direct = ex.click_image("scene/home", timeout=3)
    check("无别名时按素材路径直接识别（兼容旧代码）", ok_direct and len(conn.clicks) >= 1)

    shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'=' * 46}")
    print(f"🎉 任务图片配置验证 {ok}/{ok + fail} 通过")
    if fail:
        print("存在失败项，请检查。")
        sys.exit(1)


if __name__ == "__main__":
    main()
