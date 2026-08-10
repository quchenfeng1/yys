"""端到端验证：UI「🔍 自检」按钮的调用链路与自检结果正确性。

链路：
  ControlBar.btn_self_check → self_check_clicked → MainWindow._on_self_check
    → RunBridge.run_self_check()（config/ADB/素材/依赖 4 项检查）
    → QMessageBox 弹窗展示结果

背景 bug（已修复）：run_self_check 用无下划线属性名 getattr(ctrl,'scheduler'/'connection'/
'config'/'registry')，但 RunController 内部全是私有属性 _scheduler/_config/... → 
依赖恒报缺失、ADB 恒报未连接、配置/素材恒跳过检查 → 自检结果全是假的。

覆盖：
  ① 按钮 → self_check_clicked 信号
  ② 全正常：4 项全绿 → 弹窗「✅ 自检通过」且含全部 ✅ 行
  ③ 依赖齐全时 dependencies_complete=True（修复验证）
  ④ 缺依赖（executor=None）→ 报缺失
  ⑤ 配置非法 → config_valid False
  ⑥ ADB 断开 → adb_connectivity False
  ⑦ 素材缺失（任务 has_assets=False）→ 报缺失
  ⑧ 无 param_bridge → 「运行控制器未连接」
"""
import os, sys, types
from pathlib import Path
from types import SimpleNamespace

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

PASS = 0


def check(label, cond, detail=""):
    global PASS
    assert cond, f"FAIL: {label}  {detail}"
    PASS += 1
    print(f"PASS {label}")


# ── 可配置替身 ──────────────────────────────────────────
class FakeConfig:
    def __init__(self, errors=None):
        self._errors = errors or []
    def validate(self):
        return list(self._errors)


class FakeConnection:
    def __init__(self, connected=True):
        self._connected = connected
    def is_connected(self):
        return self._connected


class FakeTask:
    task_id = name = ""
    def __init__(self, name, has_assets=True):
        self.task_id = name
        self.name = name
        self.has_assets = has_assets


class FakeRegistry:
    def __init__(self, tasks=None):
        self._tasks = tasks or []
    def get_all(self):
        return self._tasks


class FakeScheduler:
    pass


class FakeExec:
    pass


class FakeRecognizer:
    pass


def build_ctrl(config=None, connection=None, registry=None, executor=None,
                recognizer=None):
    """构造 RunController（可缺依赖以测自检）"""
    from core.run_controller import RunController
    return RunController(
        scheduler=FakeScheduler(),
        connection=connection,
        config=config,
        state_mgr=None,
        registry=registry,
        executor=executor,
        recognizer=recognizer,
        event_bus=None,
        monitor=None,
        account_mgr=None,
    )


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from ui.param_bridge.run_bridge import RunBridge
    from ui.main_window import MainWindow
    from ui.panels.control_bar import ControlBar

    # ═══ ① 按钮 → self_check_clicked 信号 ═══
    cb = ControlBar()
    clicked = []
    cb.self_check_clicked.connect(lambda: clicked.append(True))
    cb.btn_self_check.click()
    check("① 自检按钮发出信号", len(clicked) == 1)

    # ═══ ②③ 全正常场景 ═══
    cfg_ok = FakeConfig()
    conn_ok = FakeConnection(connected=True)
    reg_ok = FakeRegistry([FakeTask("t1", has_assets=True)])
    ctrl_ok = build_ctrl(config=cfg_ok, connection=conn_ok, registry=reg_ok,
                         executor=FakeExec(), recognizer=FakeRecognizer())
    bridge = RunBridge(event_bus=None)
    bridge.set_controller(ctrl_ok)

    r = bridge.run_self_check()
    check("③ 依赖齐全 dependencies_complete=True（修复）", r["dependencies_complete"] is True,
          str(r.get("missing_dependencies")))
    check("② 配置合法", r["config_valid"] is True)
    check("② ADB 已连接", r["adb_connectivity"] is True)
    check("② 素材完整", r["assets_complete"] is True)

    # ═══ MainWindow._on_self_check 文本组装（mock 弹窗） ═══
    captured = []
    orig_info = None
    from PyQt5.QtWidgets import QMessageBox
    if hasattr(QMessageBox, 'information'):
        orig_info = QMessageBox.information
    def fake_info(parent, title, text):
        captured.append((title, text))
    QMessageBox.information = staticmethod(fake_info)

    try:
        fake_win = SimpleNamespace(_param_bridge=SimpleNamespace(run=bridge))
        fake_win._on_self_check = types.MethodType(MainWindow._on_self_check, fake_win)
        fake_win._on_self_check()
    finally:
        if orig_info is not None:
            QMessageBox.information = orig_info
    check("② 弹窗标题「✅ 自检通过」", captured and captured[0][0] == "✅ 自检通过",
          str(captured))
    text = captured[0][1] if captured else ""
    check("② 弹窗含 4 个 ✅", text.count("✅") == 4, text)

    # ═══ ④ 缺依赖 ═══
    ctrl_nodep = build_ctrl(config=cfg_ok, connection=conn_ok, registry=reg_ok,
                            executor=None)  # executor 缺失
    bridge.set_controller(ctrl_nodep)
    r = bridge.run_self_check()
    check("④ 缺依赖被识别", r["dependencies_complete"] is False
          and "_executor" in (r.get("missing_dependencies") or []),
          str(r.get("missing_dependencies")))

    # ═══ ⑤ 配置非法 ═══
    cfg_bad = FakeConfig(errors=["schedule.enabled 非法"])
    ctrl_cfg = build_ctrl(config=cfg_bad, connection=conn_ok, registry=reg_ok,
                          executor=FakeExec())
    bridge.set_controller(ctrl_cfg)
    r = bridge.run_self_check()
    check("⑤ 配置非法被识别", r["config_valid"] is False
          and "schedule.enabled" in " ".join(r.get("config_errors") or []),
          str(r.get("config_errors")))

    # ═══ ⑥ ADB 断开 ═══
    conn_bad = FakeConnection(connected=False)
    ctrl_conn = build_ctrl(config=cfg_ok, connection=conn_bad, registry=reg_ok,
                           executor=FakeExec())
    bridge.set_controller(ctrl_conn)
    r = bridge.run_self_check()
    check("⑥ ADB 断开被识别", r["adb_connectivity"] is False)

    # ═══ ⑦ 素材缺失 ═══
    reg_bad = FakeRegistry([FakeTask("no_asset", has_assets=False)])
    ctrl_asset = build_ctrl(config=cfg_ok, connection=conn_ok, registry=reg_bad,
                            executor=FakeExec())
    bridge.set_controller(ctrl_asset)
    r = bridge.run_self_check()
    check("⑦ 素材缺失被识别", r["assets_complete"] is False
          and "no_asset" in (r.get("missing_assets") or []),
          str(r.get("missing_assets")))

    # ═══ ⑧ 无 param_bridge → 未连接提示 ═══
    captured2 = []
    def fake_info2(parent, title, text):
        captured2.append((title, text))
    orig_info2 = QMessageBox.information
    QMessageBox.information = staticmethod(fake_info2)
    try:
        fake_win2 = SimpleNamespace(_param_bridge=None)
        fake_win2._on_self_check = types.MethodType(MainWindow._on_self_check, fake_win2)
        fake_win2._on_self_check()
    finally:
        QMessageBox.information = orig_info2
    check("⑧ 无桥接提示未连接", captured2 and "未连接" in captured2[0][1], str(captured2))

    print(f"\n🎉 自检按钮调用链路验证 {PASS} 项通过")


if __name__ == "__main__":
    main()
