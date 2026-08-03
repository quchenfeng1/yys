"""任务图片关联验证：asset_catalog 目录约定 + new_task 自动建图夹 + UI 面板离屏。"""
import sys, os, tempfile
from pathlib import Path

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

import numpy as np
import cv2


def _put(folder, name):
    img = np.full((40, 40, 3), 120, dtype=np.uint8)
    cv2.imwrite(str(folder / name), img)


def main():
    print("── [A] AssetCatalog 目录约定 ──")
    from core.asset_catalog import AssetCatalog
    tmp = Path(tempfile.mkdtemp(prefix="assets_"))
    cat = AssetCatalog(tmp)
    scene = cat.ensure_scene_dir()
    shared = cat.ensure_shared_dir()
    taskdir = cat.ensure_task_dir("my_task")
    assert scene.exists() and shared.exists() and taskdir.exists()
    assert scene.name == "scene" and shared.name == "_shared"
    assert taskdir == tmp / "tasks" / "my_task"

    _put(taskdir, "btn_a.png")
    _put(taskdir, "btn_b.png")
    imgs = cat.list_task_images("my_task")
    assert {i["name"] for i in imgs} == {"btn_a", "btn_b"}, imgs
    assert all(i["rel"].startswith("tasks/my_task/") for i in imgs), imgs
    print("① PASS AssetCatalog 目录创建 + 图片列举 + 相对引用路径")

    print("\n── [B] TaskManager.new_task 自动建图片文件夹 ──")
    from core.task_manager import TaskManager
    root = Path(tempfile.mkdtemp(prefix="proj_"))
    (root / "config").mkdir()
    (root / "config" / "tasks.yaml").write_text("tasks:\n", encoding="utf-8")
    mgr = TaskManager(tasks_dir=root / "tasks", assets_dir=root / "assets")
    mgr.new_task("special", "pic_battle", "图片战斗", task_type="battle")
    assert (root / "assets" / "tasks" / "pic_battle").exists(), "战斗任务应建专属图片夹"
    assert (root / "assets" / "scene").exists(), "应建识图文件夹"
    mgr.new_task("daily", "pic_event", "图片非战斗", task_type="event_task")
    assert (root / "assets" / "tasks" / "pic_event").exists()
    mgr.new_task("common", "pic_generic", "图片通用", task_type="generic")
    assert (root / "assets" / "tasks" / "_shared").exists(), "通用应建共享夹"
    print("② PASS new_task 自动创建任务图片文件夹（专属/共享/识图）")

    print("\n── [C] ImageManagerPanel 离屏 UI ──")
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from ui.panels.image_manager_panel import ImageManagerPanel
    panel = ImageManagerPanel()  # 无 bridge：仅固定项（识图/共享）
    panel._assets_dir = root / "assets"
    from core.asset_catalog import AssetCatalog
    panel._catalog = AssetCatalog(root / "assets")
    panel._reload_locations()
    assert panel.location_list.count() >= 2, f"应含识图/共享: {panel.location_list.count()}"
    # 放一张图到 pic_battle 专属夹，选中该位置应列出
    _put(root / "assets" / "tasks" / "pic_battle", "entry.png")
    panel._current_key = lambda: "pic_battle"
    panel._refresh()
    assert panel.image_list.count() == 1, f"应列出 1 张: {panel.image_list.count()}"
    # 识图文件夹空
    panel._current_key = lambda: "scene"
    panel._refresh()
    assert panel.image_list.count() == 0, f"识图夹应为空: {panel.image_list.count()}"
    print("③ PASS ImageManagerPanel 位置列表 + 任务图片列举/识图夹")

    print("\n🎉 任务图片关联验证 3/3 通过")


if __name__ == "__main__":
    main()
