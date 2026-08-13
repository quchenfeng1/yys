"""验证：TaskManagerPanel 5 个管理按钮 handler + 图片清除（子代理审计缺口 #4/#14）。

覆盖：
  A. 新建任务（多级 QInputDialog → bridge.task.new_task → 刷新）
  B. 删除任务（确认 Yes → delete_task；No → 不删）
  C. 打开编辑（open_file）
  D. 导出配置（getSaveFileName → config.export_config）
  E. 导入配置（getOpenFileName + 确认 Yes/No）
  F. 图片清除 _clear_image
"""
import os, sys
from pathlib import Path
from types import SimpleNamespace

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

PASS = 0
FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


class FakeTaskBridge:
    def __init__(self):
        self.new_calls = []
        self.delete_calls = []
        self.open_calls = []
        self.metas = [{"name": "t1", "display_name": "T1", "category": "daily"}]
        self.generics = []

    def get_task_metas(self):
        return self.metas

    def get_generic_modules(self):
        return self.generics

    def get_task_detail(self, n):
        return {"name": n, "display_name": n, "task_type": "event_task",
                "uses_battle": False}

    def get_task_asset_refs(self, n):
        return [{"ref": "btn.start", "mapped": None}]

    def new_task(self, category, name, display, task_type=None):
        self.new_calls.append((category, name, display, task_type))

    def delete_task(self, n):
        self.delete_calls.append(n)

    def open_file(self, n):
        self.open_calls.append(n)

    def save_task_images(self, name, images):
        self.saved_images = images


class FakeConfigBridge:
    def __init__(self):
        self.exported = []
        self.imported = []

    def export_config(self, path):
        self.exported.append(path)

    def import_config(self, path):
        self.imported.append(path)


def main():
    from PyQt5.QtWidgets import QApplication, QMessageBox, QInputDialog, QFileDialog
    app = QApplication.instance() or QApplication([])
    import ui.panels.task_manager_panel as tmp
    from ui.panels.task_manager_panel import TaskManagerPanel

    task_b = FakeTaskBridge()
    cfg_b = FakeConfigBridge()
    panel = TaskManagerPanel(param_bridge=SimpleNamespace(task=task_b, config=cfg_b))
    panel.load_tasks(task_b.metas)
    panel.task_list.setCurrentRow(0)
    panel._on_task_selected(panel.task_list.currentItem(), None)
    check("0 已选中任务", panel._current_name == "t1", str(panel._current_name))

    # ═══ A. 新建任务 ═══
    print("\n[A] 新建任务")
    from core.task_template import TASK_TYPES, TASK_TYPE_LABELS
    # 类型 label = 第一项（event_task）
    first_label = f"{TASK_TYPE_LABELS[TASK_TYPES[0]]}（{TASK_TYPES[0]}）"
    inputs = iter([(first_label, True), ("my_task", True), ("我的任务", True),
                   (tmp.CATEGORIES[0], True)])
    orig_getItem, orig_getText = tmp.QInputDialog.getItem, tmp.QInputDialog.getText
    tmp.QInputDialog.getItem = lambda *a, **k: next(inputs)
    tmp.QInputDialog.getText = lambda *a, **k: next(inputs)
    try:
        panel._new_task()
    finally:
        tmp.QInputDialog.getItem, tmp.QInputDialog.getText = orig_getItem, orig_getText
    check("A1 new_task 被调（分类/文件名/显示名）",
          len(task_b.new_calls) == 1 and task_b.new_calls[0][:3] == (tmp.CATEGORIES[0], "my_task", "我的任务"),
          str(task_b.new_calls))
    check("A2 new_task 带 task_type", task_b.new_calls and task_b.new_calls[0][3] == "event_task",
          str(task_b.new_calls))

    # ═══ B. 删除任务 ═══
    print("\n[B] 删除任务")
    orig_question = tmp.QMessageBox.question
    tmp.QMessageBox.question = lambda *a, **k: QMessageBox.Yes
    try:
        panel._delete_task()
    finally:
        tmp.QMessageBox.question = orig_question
    check("B1 确认 Yes → delete_task('t1')", task_b.delete_calls == ["t1"],
          str(task_b.delete_calls))
    # No → 不删
    tmp.QMessageBox.question = lambda *a, **k: QMessageBox.No
    try:
        panel._delete_task()
    finally:
        tmp.QMessageBox.question = orig_question
    check("B2 确认 No → 不删除", len(task_b.delete_calls) == 1, str(task_b.delete_calls))

    # ═══ C. 打开编辑 ═══
    print("\n[C] 打开编辑")
    panel._open_file()
    check("C1 open_file('t1') 被调", task_b.open_calls == ["t1"], str(task_b.open_calls))

    # ═══ D. 导出配置 ═══
    print("\n[D] 导出配置")
    orig_save = tmp.QFileDialog.getSaveFileName
    tmp.QFileDialog.getSaveFileName = lambda *a, **k: ("/tmp/yys_backup.zip", "ZIP (*.zip)")
    orig_info = tmp.QMessageBox.information
    tmp.QMessageBox.information = lambda *a, **k: None
    try:
        panel._export_config()
    finally:
        tmp.QFileDialog.getSaveFileName = orig_save
        tmp.QMessageBox.information = orig_info
    check("D1 export_config 被调", cfg_b.exported == ["/tmp/yys_backup.zip"],
          str(cfg_b.exported))

    # ═══ E. 导入配置 ═══
    print("\n[E] 导入配置")
    orig_open = tmp.QFileDialog.getOpenFileName
    orig_info = tmp.QMessageBox.information
    tmp.QFileDialog.getOpenFileName = lambda *a, **k: ("/tmp/yys_backup.zip", "ZIP (*.zip)")
    tmp.QMessageBox.question = lambda *a, **k: QMessageBox.Yes
    tmp.QMessageBox.information = lambda *a, **k: None
    try:
        panel._import_config()
    finally:
        tmp.QFileDialog.getOpenFileName = orig_open
        tmp.QMessageBox.question = orig_question
        tmp.QMessageBox.information = orig_info
    check("E1 确认 Yes → import_config 被调",
          cfg_b.imported == ["/tmp/yys_backup.zip"], str(cfg_b.imported))
    # No → 不导入
    tmp.QFileDialog.getOpenFileName = lambda *a, **k: ("/tmp/yys_backup.zip", "ZIP (*.zip)")
    tmp.QMessageBox.question = lambda *a, **k: QMessageBox.No
    tmp.QMessageBox.information = lambda *a, **k: None
    try:
        panel._import_config()
    finally:
        tmp.QFileDialog.getOpenFileName = orig_open
        tmp.QMessageBox.question = orig_question
        tmp.QMessageBox.information = orig_info
    check("E2 确认 No → 不导入", len(cfg_b.imported) == 1, str(cfg_b.imported))

    # ═══ F. 图片清除 ═══
    print("\n[F] 图片清除")
    panel._images_editing = {"btn.start": "assets/foo.png"}
    panel._clear_image("btn.start")
    check("F1 _clear_image 移除映射", "btn.start" not in panel._images_editing,
          str(panel._images_editing))

    print(f"\n🎉 TaskManagerPanel 管理按钮验证 {PASS} 项通过"
          + ("" if FAIL == 0 else f"，失败 {FAIL} 项"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
