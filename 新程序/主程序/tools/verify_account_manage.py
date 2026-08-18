"""端到端验证：小号管理「添加小号」功能。

验证点：
  1. accounts.yaml 新格式（accounts: 列表）→ ConfigManager 校验 + AccountManager 正确加载（main+sub1）
  2. AccountManager.add_account 添加小号 → 写盘 → 重新加载可见
  3. AccountManager.update_account / remove_account
  4. AccountBridge 桥接（get_accounts_detail / get_sub_accounts / add_account）
  5. SubAccountPanel 渲染账号列表 + 添加小号后刷新
  6. game_task_panel 组队多选下拉能读到新增小号（联动）
"""
import os, sys, tempfile, shutil, copy
from pathlib import Path
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt5.QtWidgets import QApplication


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

    # ════════════ 0. 临时配置目录 ════════════
    tmp = Path(tempfile.mkdtemp(prefix="acct_"))
    acct_path = tmp / "accounts.yaml"
    shutil.copy(os.path.join(_PROJ_ROOT, "config", "accounts.yaml"), acct_path)

    # ════════════ 1. ConfigManager 加载新格式 ════════════
    print("\n── [1/6] accounts.yaml 新格式加载 ──")
    from core.config_manager import ConfigManager
    cm = ConfigManager(config_dir=tmp, enable_hot_reload=False)
    cm._load_accounts_internal()  # 从磁盘加载 + 校验
    raw = cm.get_section("accounts")
    check("accounts 列表有 2 个账号", len(raw.get("accounts", [])) == 2,
          str(raw.get("accounts")))

    from core.account_manager import AccountManager
    am = AccountManager(config=cm, connection=None)
    accs = am.get_all_accounts()
    check("AccountManager 加载 2 个账号", len(accs) == 2, f"实际 {len(accs)}")
    check("sub_accounts 含 sub1",
          [a.account_id for a in am.sub_accounts] == ["sub1"],
          str([a.account_id for a in am.sub_accounts]))
    check("main 角色正确", am.main_account and am.main_account.account_id == "main")

    # ════════════ 2. add_account 添加小号 ════════════
    print("\n── [2/6] add_account 添加小号 ──")
    ok_add = am.add_account({
        "account_id": "sub2", "name": "小号二", "role": "sub",
        "device_id": "127.0.0.1:9999", "region": "cn", "enabled": True,
    })
    check("add_account 返回 True", ok_add)
    check("内存中 sub2 存在", am.get_account("sub2") is not None)
    # 写盘校验：重新从磁盘加载
    cm2 = ConfigManager(config_dir=tmp, enable_hot_reload=False)
    cm2._load_accounts_internal()
    raw2 = cm2.get_section("accounts")
    ids2 = [a.get("account_id") for a in raw2.get("accounts", [])]
    check("写盘后磁盘含 sub2", "sub2" in ids2, str(ids2))
    # 重复添加应失败
    ok_dup = am.add_account({"account_id": "sub2", "name": "重复", "role": "sub"})
    check("重复 account_id 添加失败", not ok_dup)

    # ════════════ 3. update_account / remove_account ════════════
    print("\n── [3/6] update_account / remove_account ──")
    ok_upd = am.update_account("sub2", device_id="1.2.3.4:5555", region="jp")
    check("update_account 返回 True", ok_upd)
    check("device_id 已更新", am.get_account("sub2").device_id == "1.2.3.4:5555")
    ok_rm = am.remove_account("sub2")
    check("remove_account 返回 True", ok_rm)
    check("内存中 sub2 已删除", am.get_account("sub2") is None)
    cm3 = ConfigManager(config_dir=tmp, enable_hot_reload=False)
    cm3._load_accounts_internal()
    ids3 = [a.get("account_id") for a in cm3.get_section("accounts").get("accounts", [])]
    check("写盘后磁盘无 sub2", "sub2" not in ids3, str(ids3))

    # ════════════ 4. AccountBridge 桥接 ════════════
    print("\n── [4/6] AccountBridge 桥接 ──")
    from ui.param_bridge.account_bridge import AccountBridge
    bridge = AccountBridge(am)
    detail = bridge.get_accounts_detail()
    check("get_accounts_detail 返回 2 条", len(detail) == 2, str(len(detail)))
    check("get_sub_accounts 返回 sub1", [d["account_id"] for d in bridge.get_sub_accounts()] == ["sub1"])
    ok_ba = bridge.add_account(account_id="sub9", name="小号九", role="sub",
                               device_id="127.0.0.1:1234")
    check("bridge.add_account 成功", ok_ba)
    check("bridge 添加后可见", any(d["account_id"] == "sub9" for d in bridge.get_accounts_detail()))
    bridge.remove_account("sub9")
    check("bridge.remove_account 成功", not any(d["account_id"] == "sub9" for d in bridge.get_accounts_detail()))

    # ════════════ 5. SubAccountPanel 渲染 + 添加刷新 ════════════
    print("\n── [5/6] SubAccountPanel 小号管理面板 ──")
    from ui.panels.sub_account_panel import SubAccountPanel, AddSubAccountDialog
    bridge2 = AccountBridge(am)
    pbridge = type("B", (), {"account": bridge2})()
    panel = SubAccountPanel(param_bridge=pbridge)
    panel.refresh()
    check("面板渲染 2 行", panel.table.rowCount() == 2, f"行数 {panel.table.rowCount()}")
    check("列头包含 账号ID/显示名/角色/设备ID/区服/状态/启用",
          [panel.table.horizontalHeaderItem(i).text() for i in range(panel.table.columnCount())]
          == ["账号ID", "显示名", "角色", "设备ID", "区服", "状态", "启用"])
    # 添加小号弹窗存在
    dlg = AddSubAccountDialog()
    dlg.ed_id.setText("sub7")
    dlg.ed_device.setText("127.0.0.1:7777")
    check("弹窗读取账号ID/设备ID", dlg.account_id() == "sub7" and dlg.device_id() == "127.0.0.1:7777")
    # 模拟 _on_add_sub 的保存逻辑（不弹 QMessageBox）
    ok_dlg = bridge2.add_account(account_id=dlg.account_id(), name=dlg.name(), role="sub",
                                 device_id=dlg.device_id(), region=dlg.region(),
                                 enabled=dlg.enabled(), remark=dlg.remark())
    panel.refresh()
    check("面板添加后 3 行", panel.table.rowCount() == 3, f"行数 {panel.table.rowCount()}")
    check("面板含 sub7 行", "sub7" in panel._row_by_id)

    # ════════════ 6. game_task_panel 组队下拉联动 ════════════
    print("\n── [6/6] 组队 UI 已取消（2026-08-16，业务参数由变量/常量承载）──")
    from ui.panels.game_task_panel import GameTaskPanel
    gpanel = GameTaskPanel(param_bridge=pbridge)
    opts = gpanel._get_sub_options()
    check("_get_sub_options 读到全部小号（sub1, sub7）",
          [d for d, _ in opts] == ["sub1", "sub7"], str(opts))
    gpanel._render_form({
        "name": "combat_test", "display_name": "战斗测试", "task_type": "battle",
        "uses_battle": True, "loop_count": 3, "teaming": {"sub_ids": ["sub7"]},
    })
    w = gpanel._form_widgets
    check("组队下拉控件已取消（战斗配置移除）",
          "teaming_sub_ids" not in w,
          str([k for k in w if "team" in k]))
    cfg = gpanel._collect_config()
    check("config 不再收集 teaming", "teaming" not in cfg, str(cfg))

    # 清理
    shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'=' * 46}")
    print(f"🎉 小号管理添加功能验证 {ok}/{ok + fail} 通过")
    if fail:
        print("存在失败项，请检查。")
        sys.exit(1)


if __name__ == "__main__":
    main()
