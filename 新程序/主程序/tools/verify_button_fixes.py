"""验证按钮功能修复：菜单/沙盒/自检/批量/日历/主题/面板显隐/日志工具栏。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJ)

from PyQt5.QtWidgets import QApplication, QCheckBox, QPushButton

app = QApplication([])
from ui.theme import apply_theme
apply_theme(app)

ok = 0
fail = 0

def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
        print(f"✅ {name}")
    else:
        fail += 1
        print(f"❌ {name}")

# ① 菜单树含设置入口（配置+UI设置已合并为「设置」）
from ui.panels.menu_tree import MenuTree
mt = MenuTree()
check("菜单树含设置项", "config" in mt._items)
check("菜单树无独立 ui_settings 项", "ui_settings" not in mt._items)

# ② 控制栏含沙盒开关 + 自检按钮 + 信号
from ui.panels.control_bar import ControlBar
cb = ControlBar()
check("控制栏含沙盒开关", isinstance(cb.chk_dry_run, QCheckBox))
check("控制栏含自检按钮", isinstance(cb.btn_self_check, QPushButton))
check("控制栏 dry_run_toggled 信号存在", hasattr(cb, 'dry_run_toggled'))
check("控制栏 self_check_clicked 信号存在", hasattr(cb, 'self_check_clicked'))
# 沙盒信号发出测试
emitted = []
cb.dry_run_toggled.connect(lambda v: emitted.append(v))
cb.chk_dry_run.setChecked(True)
check("沙盒开关发出 True", emitted and emitted[-1] is True)

# ③ RunBridge 含 set_dry_mode / run_self_check
from ui.param_bridge.run_bridge import RunBridge
rb = RunBridge()
check("RunBridge.set_dry_mode 存在", hasattr(rb, 'set_dry_mode'))
check("RunBridge.run_self_check 存在", hasattr(rb, 'run_self_check'))
res = rb.run_self_check()
check("run_self_check 返回 dict", isinstance(res, dict))

# ④ 游戏任务面板（批量编辑/导入日历已按用户要求移除）
from ui.panels.game_task_panel import GameTaskPanel
gp = GameTaskPanel()
check("游戏任务面板可正常实例化", gp is not None)
check("游戏任务面板已移除批量编辑按钮", not hasattr(gp, 'btn_batch'))
check("游戏任务面板已移除导入日历", not hasattr(gp, '_import_calendar'))

# ⑤ UI 设置面板含主题切换 + 面板显隐（合并后 6 项可隐藏；
# 「设置」面板为元控制面板，不可隐藏 → 不列入）
from ui.panels.ui_settings_panel import UISettingsPanel
up = UISettingsPanel()
check("UI设置含 _set_theme", hasattr(up, '_set_theme'))
check("UI设置含 _toggle_panel", hasattr(up, '_toggle_panel'))
check("UI设置含面板显隐复选框", len(up._panel_checks) >= 6)

# ⑤.5 设置面板（配置 + UI设置 两个 Tab）
from ui.panels.settings_panel import SettingsPanel
sp = SettingsPanel()
check("设置面板含 2 个 Tab", sp.tabs.count() == 2)
check("Tab1 为全局配置", "全局配置" in sp.tabs.tabText(0))
check("Tab2 为界面设置", "界面设置" in sp.tabs.tabText(1))

# ⑥ 日志面板含筛选/清除/导出
from ui.panels.log_panel import LogPanel
lp = LogPanel()
check("日志面板含级别筛选", hasattr(lp, 'level_combo'))
check("日志面板含 clear_log", hasattr(lp, 'clear_log'))
check("日志面板含 export_log", hasattr(lp, 'export_log'))
lp.append_log("测试信息", level="INFO")
lp.append_log("测试警告", level="WARNING")
check("日志缓存 2 条", len(lp._log_cache) == 2)
lp.level_combo.setCurrentIndex(3)  # 0=全部,1=DEBUG,2=INFO,3=WARNING
check("筛选后仅 1 条", lp.log_view.document().blockCount() == 1)
lp.clear_log()
check("清除后缓存清空", len(lp._log_cache) == 0)

# ⑦ 主题 apply_theme 支持 dark
apply_theme(app, theme="dark")
check("apply_theme(dark) 可执行", True)
apply_theme(app, theme="light")
check("apply_theme(light) 可执行", True)

# ⑧ MainWindow 方法存在性（不实例化完整窗口）
import inspect
import ui.main_window as mw
src = inspect.getsource(mw.MainWindow)
check("MainWindow 含 set_panel_visible", "def set_panel_visible" in src)
check("MainWindow 含 set_theme", "def set_theme" in src)
check("MainWindow 含 _on_self_check", "def _on_self_check" in src)

print(f"\n🎉 按钮功能修复验证 {ok}/{ok + fail} 通过")

# 退出前清理：停止 EventBus 分发线程 + 显式析构 Qt 控件，
# 避免 offscreen 下 Qt C++ 层退出竞态导致 SIGSEGV（真实程序走事件循环无此问题）
try:
    from core.event_bus import get_global_bus
    get_global_bus().stop()
except Exception:
    pass
import gc
for _w in (mt, cb, gp, up, sp, lp):
    try:
        _w.deleteLater()
    except Exception:
        pass
_app = QApplication.instance()
if _app is not None:
    try:
        _app.processEvents()
    except Exception:
        pass
gc.collect()

sys.exit(0 if fail == 0 else 1)
