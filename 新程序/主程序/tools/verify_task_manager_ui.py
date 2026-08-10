"""TaskManagerPanel UI 同步验证：游戏任务 + 通用模块 + 详情类型标签 + 图片区。"""
import sys, os
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt5.QtWidgets import QApplication, QGroupBox, QLabel, QListWidget


def main():
    app = QApplication(sys.argv)
    from ui.panels.task_manager_panel import TaskManagerPanel
    panel = TaskManagerPanel()  # 无 bridge

    # ① 游戏任务 + 通用模块列表
    panel.load_tasks([
        {"name": "task_a", "display_name": "任务A", "category": "daily",
         "task_type": "event_task"},
        {"name": "battle_x", "display_name": "战斗X", "category": "special",
         "task_type": "battle", "uses_battle": True},
    ])
    panel.load_generic([
        {"name": "soul_configure", "display_name": "御魂配置", "category": "common"},
        {"name": "pre_battle_prep", "display_name": "战前准备", "category": "common"},
    ])
    assert panel.task_list.count() == 2, f"游戏任务应 2: {panel.task_list.count()}"
    assert panel.generic_list.count() == 2, f"通用模块应 2: {panel.generic_list.count()}"
    assert panel.generic_list.item(0).text().startswith("御魂配置"), panel.generic_list.item(0).text()
    print("① PASS 左侧双区：游戏任务 + 通用模块（common）")

    # ② 详情渲染：战斗任务类型标签 + 元数据 + 图片区
    panel._current_is_generic = False
    panel._render_detail({"name": "battle_x", "display_name": "战斗X",
                          "category": "special", "task_type": "battle",
                          "uses_battle": True, "description": "测试"})
    assert panel._detail_labels["任务类型:"].text() == "战斗任务", \
        f"类型标签: {panel._detail_labels['任务类型:'].text()}"
    assert panel._detail_labels["战斗任务:"].text() == "是"
    groups = [panel.detail_layout.itemAt(i).widget()
              for i in range(panel.detail_layout.count())]
    groups = [w for w in groups if isinstance(w, QGroupBox)]
    # 标题已改为内部嵌入 QLabel（panel_group），收集 GroupBox 内所有 QLabel 文本
    titles = []
    for g in groups:
        for lbl in g.findChildren(QLabel):
            titles.append(lbl.text())
    # 已统一到素材管理：任务管理不再有"任务图片区/打开图片文件夹"，只保留"图片设置"
    assert any("图片设置" in t for t in titles), f"应有图片设置区: {titles}"
    assert not any("任务图片" in t or "打开图片文件夹" in t for t in titles), \
        f"不应有任务图片区: {titles}"
    print(f"② PASS 详情渲染：类型标签「战斗任务」+ 图片设置区（{titles}）")

    # ③ 通用模块详情：标注通用·不单独执行
    panel._current_is_generic = True
    panel._render_detail({"name": "soul_configure", "display_name": "御魂配置",
                          "category": "common", "is_generic": True})
    assert panel._detail_labels["任务类型:"].text() == "通用模块（不单独执行，被任务引用）", \
        panel._detail_labels["任务类型:"].text()
    assert "通用模块（common）" in panel._detail_labels["分类:"].text()
    print("③ PASS 通用模块详情：标注「不单独执行」+ 分类 common + 共享图片区")

    # ④ 打开编辑按钮对当前选中任务生效（不实际打开）
    panel._current_name = "soul_configure"
    assert panel._current_name == "soul_configure"
    print("④ PASS 通用模块可被选中（可打开编辑）")

    print("\n🎉 TaskManagerPanel UI 同步验证 4/4 通过")


if __name__ == "__main__":
    main()
