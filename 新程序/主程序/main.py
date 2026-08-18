"""
程序入口
【16-应用启动引导】

启动流程:
1. 创建 QApplication
2. 初始化 ApplicationBootstrap（7层15步）
3. 创建并显示主窗口
4. 进入 Qt 事件循环
5. 退出时优雅关闭所有模块
"""

import sys
import signal
from pathlib import Path

# ── 无控制台启动（pythonw）兼容（2026-08-16）────────────────
# pythonw 下 sys.stdout / sys.stderr 为 None，任何 print/警告写 stderr 都会
# 抛 AttributeError 导致启动静默失败 → 启动前重定向到 logs/console.log
if sys.stdout is None or sys.stderr is None:
    _ROOT = Path(__file__).resolve().parent
    _log_dir = _ROOT / "logs"
    try:
        _log_dir.mkdir(parents=True, exist_ok=True)
        _stream = open(_log_dir / "console.log", "a",
                       encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = _stream
        if sys.stderr is None:
            sys.stderr = _stream
    except Exception:
        import os
        _devnull = open(os.devnull, "w")
        sys.stdout = sys.stdout or _devnull
        sys.stderr = sys.stderr or _devnull

from PyQt5.QtWidgets import QApplication

from core.bootstrap import ApplicationBootstrap


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("阴阳师自动化工具")
    app.setOrganizationName("YYS")

    # 启动引导（7层初始化）
    bootstrap = ApplicationBootstrap(root_dir=Path(__file__).parent)
    if not bootstrap.start():
        print("启动失败，请检查日志。")
        sys.exit(1)

    # 使用 bootstrap 已创建的 MainWindow（含 param_bridge/event_bus/image_mgr 注入）
    window = bootstrap.get("main_window")
    if window is None:
        print("启动失败：MainWindow 未初始化。")
        sys.exit(1)
    window.show()

    # 退出前有序销毁顶层窗口（2026-08-16）：Windows 平台下 Qt 主题 + 隐藏/显示
    # 过的自绘控件在解释器退出时直接销毁会偶发 0xC0000005；改为
    # aboutToQuit 时 hide + deleteLater + 处理 DeferredDelete，事件循环内完成销毁
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

    # 注册信号处理（优雅退出）
    signal.signal(signal.SIGINT, lambda sig, frame: app.quit())

    # 进入事件循环
    exit_code = app.exec_()

    # 优雅关闭
    bootstrap.shutdown()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
