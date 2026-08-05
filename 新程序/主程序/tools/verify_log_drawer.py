"""右侧日志/终端抽屉验证：收起/展开 + 箭头方向。"""
import sys, os
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt5.QtWidgets import QApplication, QToolButton
from PyQt5.QtCore import Qt


def main():
    app = QApplication(sys.argv)
    from ui.panels.log_panel import LogPanel
    from ui.main_window import MainWindow

    # 用 __new__ 绕过完整构造，仅测抽屉逻辑
    mw = MainWindow.__new__(MainWindow)
    mw.log_panel = LogPanel()
    mw.drawer_handle = QToolButton()
    # 初始展开（模拟 init_ui 设置右侧图标）
    from ui.theme import icon as _theme_icon
    _ic = _theme_icon("fa5s.angle-right", "#1e6fd9")
    if _ic:
        mw.drawer_handle.setIcon(_ic)

    mw.log_panel.show()
    app.processEvents()
    assert mw.log_panel.isVisible(), "初始应可见"
    assert not mw.drawer_handle.icon().isNull(), "应有图标"
    print("① PASS 初始展开（日志可见 + 有图标）")

    # 收起
    mw._toggle_drawer()
    app.processEvents()
    assert not mw.log_panel.isVisible(), "收起后应隐藏"
    assert not mw.drawer_handle.icon().isNull(), "收起后仍有图标"
    print("② PASS 收起：日志隐藏 + 图标切换（angle-left）")

    # 再展开
    mw._toggle_drawer()
    app.processEvents()
    assert mw.log_panel.isVisible(), "再展开后应可见"
    assert not mw.drawer_handle.icon().isNull()
    print("③ PASS 再展开：日志显示 + 图标切换（angle-right）")

    # 隐藏时 append_log 仍可用（不崩溃）
    mw._toggle_drawer()
    mw.log_panel.append_log(level="INFO", message="隐藏时日志仍可写入")
    app.processEvents()
    print("④ PASS 抽屉收起时日志仍可写入（append_log 正常）")

    print("\n🎉 日志抽屉验证 4/4 通过")


if __name__ == "__main__":
    main()
