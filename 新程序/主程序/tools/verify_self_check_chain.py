"""验证：RunBridge.run_self_check 自检后端链路（2026-08-16）。

背景：UI「🔍 自检」按钮已移除（连接状态由顶部连接按钮反映），
后端 run_self_check 保留（config/ADB/素材/依赖 4 项检查，备查）。

覆盖：
  ① 全正常：4 项全绿
  ② 依赖齐全时 dependencies_complete=True
  ③ 缺依赖（executor=None）→ 报缺失
  ④ 配置非法 → config_valid False
  ⑤ ADB 断开 → adb_connectivity False
  ⑥ 素材缺失（任务 has_assets=False）→ 报缺失
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

    # ═══ ①② 全正常场景 ═══
    cfg_ok = FakeConfig()
    conn_ok = FakeConnection(connected=True)
    reg_ok = FakeRegistry([FakeTask("t1", has_assets=True)])
    ctrl_ok = build_ctrl(config=cfg_ok, connection=conn_ok, registry=reg_ok,
                         executor=FakeExec(), recognizer=FakeRecognizer())
    bridge = RunBridge(event_bus=None)
    bridge.set_controller(ctrl_ok)

    r = bridge.run_self_check()
    check("② 依赖齐全 dependencies_complete=True", r["dependencies_complete"] is True,
          str(r.get("missing_dependencies")))
    check("① 配置合法", r["config_valid"] is True)
    check("① ADB 已连接", r["adb_connectivity"] is True)
    check("① 素材完整", r["assets_complete"] is True)

    # ═══ ③ 缺依赖 ═══
    ctrl_nodep = build_ctrl(config=cfg_ok, connection=conn_ok, registry=reg_ok,
                            executor=None)  # executor 缺失
    bridge.set_controller(ctrl_nodep)
    r = bridge.run_self_check()
    check("③ 缺依赖被识别", r["dependencies_complete"] is False
          and "_executor" in (r.get("missing_dependencies") or []),
          str(r.get("missing_dependencies")))

    # ═══ ④ 配置非法 ═══
    cfg_bad = FakeConfig(errors=["schedule.enabled 非法"])
    ctrl_cfg = build_ctrl(config=cfg_bad, connection=conn_ok, registry=reg_ok,
                          executor=FakeExec())
    bridge.set_controller(ctrl_cfg)
    r = bridge.run_self_check()
    check("④ 配置非法被识别", r["config_valid"] is False
          and "schedule.enabled" in " ".join(r.get("config_errors") or []),
          str(r.get("config_errors")))

    # ═══ ⑤ ADB 断开 ═══
    conn_bad = FakeConnection(connected=False)
    ctrl_conn = build_ctrl(config=cfg_ok, connection=conn_bad, registry=reg_ok,
                           executor=FakeExec())
    bridge.set_controller(ctrl_conn)
    r = bridge.run_self_check()
    check("⑤ ADB 断开被识别", r["adb_connectivity"] is False)

    # ═══ ⑥ 素材缺失 ═══
    reg_bad = FakeRegistry([FakeTask("no_asset", has_assets=False)])
    ctrl_asset = build_ctrl(config=cfg_ok, connection=conn_ok, registry=reg_bad,
                            executor=FakeExec())
    bridge.set_controller(ctrl_asset)
    r = bridge.run_self_check()
    check("⑥ 素材缺失被识别", r["assets_complete"] is False
          and "no_asset" in (r.get("missing_assets") or []),
          str(r.get("missing_assets")))

    print(f"\n🎉 自检后端链路验证 {PASS} 项通过")


if __name__ == "__main__":
    main()
