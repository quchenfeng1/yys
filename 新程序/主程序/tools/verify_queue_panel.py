"""TaskQueuePanel 卡片样式离屏验证（临时）"""
import os, sys
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt5.QtWidgets import QApplication


def main():
    app = QApplication(sys.argv)
    # 模拟真实环境：应用全局主题（qt-material），确认面板在其下仍保持紧凑
    from ui.theme import apply_theme
    apply_theme(app)
    from ui.panels.task_queue_panel import TaskQueuePanel

    panel = TaskQueuePanel()
    panel.update_panel(
        current="combat_test  (战斗测试)",
        pending=[
            {"name": "combat_test", "next_run": "08-04 06:00", "priority": 5},
            {"name": "daily_test", "next_run": "08-04 06:00", "priority": 10},
        ],
        upcoming=[
            {"name": "once_test", "next_run": "08-04 06:00"},
            {"name": "unplanned", "next_run": ""},  # 无下次时间 → 待调度（无触发按钮）
            # 触发式任务统一归入「已失效」区（不再显示在未开始）
        ],
        invalid=[
            {"name": "trig_test", "status": "待触发", "detail": "等待外部触发（按钮/识图）"},
            {"name": "old_task", "status": "已过期", "detail": "累计 5/5 次已完成"},
            {"name": "once_test", "status": "本轮已完成", "detail": "下次启动执行"},
        ],
    )
    app.processEvents()

    # 断言列表项数量
    assert panel.pending_list.count() == 2, panel.pending_list.count()
    assert panel.upcoming_list.count() == 2, panel.upcoming_list.count()
    assert panel.invalid_list.count() == 3, panel.invalid_list.count()
    print(f"① PASS 三列表卡片项数正确 (待执行 {panel.pending_list.count()} / 未开始 {panel.upcoming_list.count()} / 已失效 {panel.invalid_list.count()})")

    # 触发式任务卡片应包含"⚡触发"按钮（在已失效区）
    from PyQt5.QtWidgets import QPushButton
    btns = panel.invalid_list.findChildren(QPushButton)
    assert len(btns) == 1, f"应有 1 个触发按钮（已失效区）: {len(btns)}"
    print("② PASS 已失效区触发式任务卡片带 ⚡触发 按钮")

    # 未开始区不应再有触发按钮（普通等待任务误触发隐患已修复）
    up_btns = panel.upcoming_list.findChildren(QPushButton)
    assert len(up_btns) == 0, f"未开始区不应有触发按钮: {len(up_btns)}"
    print("③ PASS 未开始区无触发按钮（普通任务不误触发）")

    # 未开始区待调度卡片（无 next_run）应显示"待调度"徽标
    from PyQt5.QtWidgets import QLabel
    card = panel.upcoming_list.itemWidget(panel.upcoming_list.item(0))
    labels = [lbl.text() for lbl in card.findChildren(QLabel)]
    assert any(t in ("未开始", "待调度") for t in labels), f"徽标缺失: {labels}"
    print("④ PASS 未开始区卡片带状态徽标")

    # 进度条独立更新（update_panel 不覆盖 set_progress 的值）
    panel.set_progress(42)
    assert panel.progress_bar.value() == 42, panel.progress_bar.value()
    panel.update_panel("x", [], [], [])
    assert panel.progress_bar.value() == 42, "update_panel 不应覆盖进度条"
    print("⑤ PASS 进度条独立更新且不被 update_panel 覆盖")

    # 保存截图
    panel.resize(1000, 620)
    panel.show()
    app.processEvents()
    shot = panel.grab()
    out = os.path.join(_PROJ_ROOT, "ui_queue_preview.png")
    shot.save(out)
    print(f"⑥ PASS 截图已保存: {out}")
    print("\n🎉 TaskQueuePanel 卡片样式验证 6/6 通过")


if __name__ == "__main__":
    main()
