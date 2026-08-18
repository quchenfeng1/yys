"""TaskManagerPanel UI 同步验证（2026-08-16 改写）：游戏任务 + 详情类型标签 + 图片区。

通用模块区已退役（coop 等通用模块删除）→ 断言不存在；
新增「🖼 流程示图」Tab 断言存在。
"""
import sys, os
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt5.QtWidgets import QApplication, QGroupBox, QLabel, QListWidget


def main():
    app = QApplication(sys.argv)
    from ui.panels.task_manager_panel import TaskManagerPanel
    panel = TaskManagerPanel()  # 无 bridge

    # ① 游戏任务列表（通用模块区已退役）
    panel.load_tasks([
        {"name": "task_a", "display_name": "任务A", "category": "daily",
         "task_type": "event_task"},
        {"name": "battle_x", "display_name": "战斗X", "category": "special",
         "task_type": "battle", "uses_battle": True},
    ])
    assert panel.task_list.count() == 2, f"游戏任务应 2: {panel.task_list.count()}"
    assert not hasattr(panel, "generic_list"), "通用模块区应已移除"
    tab_texts = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    assert "流程示图" in panel.tabs.tabText(1), f"应有流程示图 Tab: {tab_texts}"
    print("① PASS 左侧任务列表 + 通用模块区已移除 + 流程示图 Tab")

    # ② 详情渲染：战斗任务类型标签 + 元数据 + 图片区
    panel._render_detail({"name": "battle_x", "display_name": "战斗X",
                          "category": "special", "task_type": "battle",
                          "uses_battle": True, "description": "测试"})
    assert panel._detail_labels["任务类型:"].text() == "战斗任务", \
        f"类型标签: {panel._detail_labels['任务类型:'].text()}"
    assert panel._detail_labels["战斗任务:"].text() == "是"
    groups = [panel.detail_layout.itemAt(i).widget()
              for i in range(panel.detail_layout.count())]
    groups = [w for w in groups if isinstance(w, QGroupBox)]
    titles = []
    for g in groups:
        for lbl in g.findChildren(QLabel):
            titles.append(lbl.text())
    assert any("图片设置" in t for t in titles), f"应有图片设置区: {titles}"
    assert not any("任务图片" in t or "打开图片文件夹" in t for t in titles), \
        f"不应有任务图片区: {titles}"
    print(f"② PASS 详情渲染：类型标签「战斗任务」+ 图片设置区（{titles}）")

    # ③ 普通任务详情：分类直接显示
    panel._render_detail({"name": "task_a", "display_name": "任务A",
                          "category": "daily", "task_type": "event_task"})
    assert panel._detail_labels["分类:"].text() == "daily", \
        panel._detail_labels["分类:"].text()
    print("③ PASS 普通任务详情：分类 daily")

    print("\n🎉 TaskManagerPanel UI 同步验证 3/3 通过")


if __name__ == "__main__":
    main()
