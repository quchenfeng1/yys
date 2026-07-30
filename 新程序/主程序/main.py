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

from PyQt5.QtWidgets import QApplication

from core.bootstrap import ApplicationBootstrap
from core.event_bus import get_global_bus
from core.events import Events
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("阴阳师自动化工具")
    app.setOrganizationName("YYS")

    # 启动引导（7层初始化）
    bootstrap = ApplicationBootstrap(root_dir=Path(__file__).parent)
    if not bootstrap.start():
        print("启动失败，请检查日志。")
        sys.exit(1)

    # 创建并显示主窗口
    window = MainWindow()
    window.show()

    # 注册信号处理（优雅退出）
    signal.signal(signal.SIGINT, lambda sig, frame: app.quit())

    # 进入事件循环
    exit_code = app.exec_()

    # 优雅关闭
    bootstrap.shutdown()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
    main()
