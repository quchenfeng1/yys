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
    # 18-游戏解耦：tasks.yaml 与 tasks/ 同层
    (root / "tasks.yaml").write_text("tasks:\n", encoding="utf-8")
    mgr = TaskManager(tasks_dir=root / "tasks", assets_dir=root / "assets")
    mgr.new_task("special", "pic_battle", "图片战斗", task_type="battle")
    assert (root / "assets" / "tasks" / "pic_battle").exists(), "战斗任务应建专属图片夹"
    assert (root / "assets" / "scene").exists(), "应建识图文件夹"
    mgr.new_task("daily", "pic_event", "图片非战斗", task_type="event_task")
    assert (root / "assets" / "tasks" / "pic_event").exists()
    mgr.new_task("common", "pic_generic", "图片通用", task_type="generic")
    assert (root / "assets" / "tasks" / "_shared").exists(), "通用应建共享夹"
    print("② PASS new_task 自动创建任务图片文件夹（专属/共享/识图）")

    print("\n── [C] ImageManagerPanel 离屏 UI（Tab：识图素材/控制素材）──")
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from ui.panels.image_manager_panel import ImageManagerPanel
    panel = ImageManagerPanel()  # 无 bridge：仅固定两类素材
    panel._assets_dir = root / "assets"
    from core.asset_catalog import AssetCatalog
    from core.asset_meta import AssetMetaStore
    panel._catalog = AssetCatalog(root / "assets")
    panel._meta = AssetMetaStore(root / "assets")
    panel._refresh()
    # Tab 结构：识图素材(scene/) + 控制素材(tasks/_shared/)
    assert panel.tabs.count() == 2, f"应含 2 个 Tab: {panel.tabs.count()}"
    assert "识图素材" in panel.tabs.tabText(0)
    assert "控制素材" in panel.tabs.tabText(1)
    # 控制素材 Tab：放一张图应列出
    _put(root / "assets" / "tasks" / "_shared", "control_btn.png")
    panel.tabs.setCurrentIndex(1)  # 控制素材
    panel._refresh()
    assert panel.control_list.count() == 1, f"应列出 1 张控制素材: {panel.control_list.count()}"
    # 识图素材 Tab 空（scene/ 无图）
    panel.tabs.setCurrentIndex(0)  # 识图素材
    panel._refresh()
    assert panel.scene_list.count() == 0, f"识图素材应为空: {panel.scene_list.count()}"
    # 当前目录随 Tab 切换正确
    panel.tabs.setCurrentIndex(1)
    assert str(panel._current_dir()).endswith("_shared"), str(panel._current_dir())
    panel.tabs.setCurrentIndex(0)
    assert str(panel._current_dir()).endswith("scene"), str(panel._current_dir())
    print("③ PASS ImageManagerPanel Tab 切换（识图/控制）+ 图片列举/目录定位")

    print("\n🎉 任务图片关联验证 3/3 通过")


if __name__ == "__main__":
    main()
