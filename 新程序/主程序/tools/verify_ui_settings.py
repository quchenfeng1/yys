"""验证：UI 设置面板三个控件（日志级别/自动滚动/字体大小）联动 LogPanel，及设置面板不可隐藏。

覆盖：
  ① LogPanel 阈值筛选：选 INFO 时 INFO/WARNING/ERROR 显示、DEBUG 过滤（原为精确匹配 → 语义错误）
  ② set_level_filter 生效（设置面板日志级别 → LogPanel 筛选）
  ③ set_auto_scroll 生效（关闭后追加日志不滚动）
  ④ set_log_font_size 生效（日志/终端字体大小应用）
  ⑤ UISettingsPanel.bind_log_panel 应用初始值（INFO / 自动滚动 / 12px）
  ⑥ 调整设置面板控件 → 实时联动 LogPanel
  ⑦ 「设置」面板不可隐藏（_PANEL_TOGGLE_ITEMS 不含 config）
"""
import os, sys
from pathlib import Path

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

PASS = 0


def check(label, cond, detail=""):
    global PASS
    assert cond, f"FAIL: {label}  {detail}"
    PASS += 1
    print(f"PASS {label}")


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from ui.panels.log_panel import LogPanel, _meets_threshold

    # ═══ ① 阈值筛选语义 ═══
    check("① 阈值:INFO含INFO", _meets_threshold("INFO", "INFO"))
    check("① 阈值:INFO含WARNING", _meets_threshold("WARNING", "INFO"))
    check("① 阈值:INFO含ERROR", _meets_threshold("ERROR", "INFO"))
    check("① 阈值:INFO含SUCCESS", _meets_threshold("SUCCESS", "INFO"))
    check("① 阈值:INFO不含DEBUG", not _meets_threshold("DEBUG", "INFO"))
    check("① 阈值:INFO不含TRACE", not _meets_threshold("TRACE", "INFO"))
    check("① 阈值:WARNING不含SUCCESS", not _meets_threshold("SUCCESS", "WARNING"))
    check("① 阈值:空选全部", _meets_threshold("DEBUG", ""))

    # ═══ ② LogPanel set_level_filter ═══
    lp = LogPanel()
    lp.set_level_filter("INFO")
    check("② set_level_filter", lp.level_combo.currentData() == "INFO",
          str(lp.level_combo.currentData()))

    # ═══ ③ set_auto_scroll ═══
    lp.set_auto_scroll(False)
    check("③ set_auto_scroll", lp._auto_scroll is False)

    # ═══ ④ set_log_font_size ═══
    lp.set_log_font_size(16)
    check("④ set_log_font_size",
          "font-size: 16px" in lp.log_view.styleSheet()
          and "font-size: 16px" in lp.terminal_view.styleSheet(),
          lp.log_view.styleSheet())

    # ═══ ⑤⑥ UISettingsPanel 联动 ═══
    from ui.panels.ui_settings_panel import UISettingsPanel
    panel = UISettingsPanel()
    # 模拟 MainWindow.bind_log_panel：注入 log_panel
    panel.bind_log_panel(lp)
    check("⑤ 绑定应用初始级别", lp.level_combo.currentData() == "INFO")
    check("⑤ 绑定应用初始自动滚动", lp._auto_scroll is True)
    check("⑤ 绑定应用初始字体", "font-size: 12px" in lp.log_view.styleSheet())

    # 实时调整 → 联动
    panel.log_level_combo.setCurrentText("WARNING")
    check("⑥ 级别联动", lp.level_combo.currentData() == "WARNING",
          str(lp.level_combo.currentData()))
    panel.auto_scroll_cb.setChecked(False)
    check("⑥ 自动滚动联动", lp._auto_scroll is False)
    panel.font_size_slider.setValue(18)
    check("⑥ 字体联动", "font-size: 18px" in lp.log_view.styleSheet())

    # ═══ ⑦ 设置面板不可隐藏 ═══
    from ui.panels.ui_settings_panel import _PANEL_TOGGLE_ITEMS
    keys = [k for k, _, _ in _PANEL_TOGGLE_ITEMS]
    check("⑦ 设置面板不可隐藏", "config" not in keys, str(keys))
    check("⑦ 其余面板可隐藏", {"game_task", "task_queue", "task_manager",
                            "image", "accounts", "history"} <= set(keys))

    print(f"\n🎉 UI 设置联动与日志筛选验证 {PASS} 项通过")


if __name__ == "__main__":
    main()
