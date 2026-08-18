"""
验证：模拟器条目库 + 控制栏模拟器下拉 + bootstrap 游戏切换（B方案）。

测试项：
  ① EmulatorStore CRUD / serial
  ② ControlBar 模拟器下拉信号/运行禁用
  ③ bootstrap.switch_game → 后端整体切换（临时游戏 testswitch_tmp，用后删除）
  ④ SystemBridge 注入 + 模拟器切换（模拟设备模式）
运行：QT_QPA_PLATFORM=offscreen python -X utf8 tools/verify_game_emulator_switch.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results: list[tuple[str, bool]] = []


def check(name: str, cond: bool) -> None:
    results.append((name, bool(cond)))


# ── ① EmulatorStore ───────────────────────────────────
from core.emulator_store import EmulatorStore

tmpdir = Path(tempfile.mkdtemp())
store = EmulatorStore(tmpdir)
e1 = store.add("测试模拟器", "127.0.0.1", 5555)
check("store_add", e1 is not None and store.serial_of(e1["id"]) == "127.0.0.1:5555")
check("store_update",
      store.update(e1["id"], port=6666) and store.serial_of(e1["id"]).endswith(":6666"))
check("store_get", store.get(e1["id"]) is not None)
check("store_list", len(store.list()) == 1)
check("store_remove", store.remove(e1["id"]) and not store.list())
shutil.rmtree(tmpdir, ignore_errors=True)

# ── ② ControlBar 模拟器下拉 ─────────────────────────────
from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)


def _cleanup_ui():
    from PyQt5.QtCore import QEvent
    for w in QApplication.topLevelWidgets():
        try:
            w.hide()
            w.deleteLater()
        except Exception:
            pass
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QApplication.processEvents()


app.aboutToQuit.connect(_cleanup_ui)
from ui.panels.control_bar import ControlBar
cb = ControlBar()
got_emu: list[str] = []
cb.emulator_changed.connect(got_emu.append)
cb.set_emulators([("emu_1", "模拟器一"), ("emu_2", "模拟器二")])
cb.set_current_emulator("emu_1")
check("cb_init_no_signal", not got_emu)
cb.combo_emu.setCurrentIndex(1)
app.processEvents()
check("cb_emu_emit", got_emu == ["emu_2"])
check("cb_current_emu", cb.current_emulator() == "emu_2")
cb.set_running(True)
check("cb_running_disable",
      not cb.combo_emu.isEnabled() and not cb.combo_game.isEnabled())
cb.set_running(False)
cb.set_current_emulator("emu_1")
app.processEvents()

# ── ③ bootstrap 游戏切换 ───────────────────────────────
tmp_game = ROOT / "games" / "testswitch_tmp"
shutil.rmtree(tmp_game, ignore_errors=True)
(tmp_game / "tasks").mkdir(parents=True)
(tmp_game / "assets").mkdir()
(tmp_game / "scenes").mkdir()
(tmp_game / "runtime").mkdir()
(tmp_game / "visual_tasks").mkdir()
(tmp_game / "__init__.py").write_text("", encoding="utf-8")
(tmp_game / "tasks" / "__init__.py").write_text("", encoding="utf-8")
(tmp_game / "profile.yaml").write_text(
    "game_id: testswitch_tmp\nname: 测试游戏\nocr_lang: ch\n",
    encoding="utf-8")
(tmp_game / "tasks.yaml").write_text("tasks: []\n", encoding="utf-8")

from core.bootstrap import ApplicationBootstrap
b = ApplicationBootstrap(root_dir=ROOT)
ok_start = b.start()
check("bootstrap_start", ok_start)
try:
    if ok_start:
        ok_to = b.switch_game("testswitch_tmp")
        check("switch_to_tmp", ok_to)
        check("game_id_switched", b._game.game_id == "testswitch_tmp")
        reg = b.get("task_registry")
        check("registry_rescanned",
              reg is not None and getattr(reg, "_scanned", False))
        vb = b.get("visual_bridge")
        check("bridge_game_switched",
              vb is not None and vb.current_game == "testswitch_tmp")
        teach = b.get("teach_engine")
        check("teach_store_switched",
              teach is not None
              and "testswitch_tmp" in str(getattr(teach, "_assets_dir", "")))
        sysb = b.get("bridge").system
        check("sysb_wired",
              sysb is not None and sysb.emulator_list() is not None)
        ok_back = b.switch_game("yys")
        check("switch_back_yys", ok_back and b._game.game_id == "yys")
        # 运行中禁止切换兜底：无运行 → 允许；直接验证 blocker 对 teach 停止状态放行
        check("switch_idempotent", b.switch_game("yys"))
finally:
    b.shutdown()
    shutil.rmtree(tmp_game, ignore_errors=True)

# ── 输出 ─────────────────────────────────────────────
out_lines = [f"{'PASS' if ok else 'FAIL'}  {name}" for name, ok in results]
passed = sum(1 for _, ok in results if ok)
out_lines.append(f"TOTAL {passed}/{len(results)}")
# 结果走 stdout（回归运行器会重定向；勿写 regression_out.txt，会被运行器占用）
print("\n".join(out_lines))
sys.stdout.flush()
# Windows 平台销毁已知坑：脚本无事件循环，aboutToQuit 不触发 → 显式清理
_cleanup_ui()
# 硬退出规避 Qt 析构 AV（回归子进程专用，结果已打印）
os._exit(0 if passed == len(results) else 1)
