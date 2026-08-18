"""端到端验证：组队小号从「小号管理」多选下拉（MultiSelectCombo）接入 game_task_panel。

验证点：
  1. MultiSelectCombo 控件：set_items / set_selected / selected_data / 点选 toggle
  2. game_task_panel 带 AccountBridge（有 sub 账号）→ 渲染出多选下拉，回显已存 sub_ids
  3. _collect_config 从多选下拉收集 sub_ids → teaming.sub_ids
  4. 无账号管理数据（无 bridge）→ 回退 QLineEdit 文本输入，_collect_config 兼容
"""
import os, sys
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt5.QtWidgets import QApplication, QLineEdit


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

    # ════════════ 1. MultiSelectCombo 控件行为 ════════════
    print("\n── [1/4] MultiSelectCombo 控件 ──")
    from ui.widgets.multi_select_combo import MultiSelectCombo
    cb = MultiSelectCombo()
    cb.set_items([("sub1", "小号一（sub1）"), ("sub2", "小号二（sub2）"), ("main", "大号（main）")])
    check("set_items 后 has_items=True", cb.has_items())
    check("初始无选中", cb.selected_data() == [])

    cb.set_selected(["sub1", "sub2"])
    check("set_selected 回显勾选", cb.selected_data() == ["sub1", "sub2"], str(cb.selected_data()))
    check("收起文本显示已选", "小号一" in cb.lineEdit().text() and "小号二" in cb.lineEdit().text(),
          cb.lineEdit().text())

    # 点选 toggle：取消 sub1
    from PyQt5.QtCore import Qt
    idx1 = None
    for i in range(cb.model().rowCount()):
        if cb.model().item(i).data(Qt.UserRole) == "sub1":
            idx1 = cb.model().index(i, 0)
            break
    check("找到 sub1 选项索引", idx1 is not None)
    cb._toggle(idx1)
    check("点选后 sub1 被取消", cb.selected_data() == ["sub2"], str(cb.selected_data()))

    # 清除选择
    cb.clear_selection()
    check("clear_selection 清空", cb.selected_data() == [])

    # ════════════ 2. game_task_panel 组队 UI 已取消（2026-08-16）════════════
    print("\n── [2/4] game_task_panel 组队 UI 已取消 ──")
    from core.account_manager import AccountManager, AccountInfo
    am = AccountManager(connection=None)
    am._accounts = {
        "main": AccountInfo(account_id="main", name="大号", role="main", enabled=True),
        "sub1": AccountInfo(account_id="sub1", name="小号一", role="sub", enabled=True),
        "sub2": AccountInfo(account_id="sub2", name="小号二", role="sub", enabled=True),
        "sub3": AccountInfo(account_id="sub3", name="小号三", role="sub", enabled=False),  # 禁用不显示
    }
    am._current_id = "main"

    from ui.param_bridge.account_bridge import AccountBridge
    bridge = type("Bridge", (), {"account": AccountBridge(am)})()

    from ui.panels.game_task_panel import GameTaskPanel
    panel = GameTaskPanel(param_bridge=bridge)
    detail = {
        "name": "combat_test", "display_name": "战斗测试", "task_type": "battle",
        "uses_battle": True, "loop_count": 5,
        "teaming": {"sub_ids": ["sub1", "sub2"]},
    }
    panel._render_form(detail)
    w = panel._form_widgets
    check("组队下拉控件已取消（业务参数由变量/常量承载）",
          "teaming_sub_ids" not in w, str(list(w.keys())[:20]))
    # _get_sub_options 方法保留（供其它 UI 复用）
    check("_get_sub_options 仍返回启用的 sub",
          [d for d, _ in panel._get_sub_options()] == ["sub1", "sub2"],
          str(panel._get_sub_options()))

    # ════════════ 3. _collect_config 不再收集组队字段 ════════════
    print("\n── [3/4] _collect_config 不再收集组队字段 ──")
    config = panel._collect_config()
    check("config 无 teaming", "teaming" not in config, str(config))

    # ════════════ 4. 无账号数据 → 行为不变 ════════════
    print("\n── [4/4] 无小号管理数据 ──")
    panel2 = GameTaskPanel()  # 无 bridge
    panel2._render_form({
        "name": "combat_test", "display_name": "战斗测试", "task_type": "battle",
        "uses_battle": True, "teaming": {"sub_ids": ["sub1", "sub2"]},
    })
    w2 = panel2._form_widgets
    check("无 bridge 同样无组队控件", "teaming_sub_ids" not in w2)
    cfg4 = panel2._collect_config()
    check("config 无 teaming", "teaming" not in cfg4, str(cfg4))

    print(f"\n{'=' * 46}")
    print(f"🎉 组队小号多选下拉验证 {ok}/{ok + fail} 通过")
    if fail:
        print("存在失败项，请检查。")
        sys.exit(1)


if __name__ == "__main__":
    main()
