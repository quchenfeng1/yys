"""
阴阳师自动化识图脚本 - 主入口（v2.1 无黑窗版）

启动后弹出 GUI 菜单界面，在界面中点击「运行」才开始执行脚本。
v2.1：启动时安装全局 subprocess 无黑窗补丁，所有子进程绝不弹出 CMD 窗口。

使用方法：
    pythonw main.py       # 无控制台窗口（推荐）
    或双击 启动.bat
"""

import sys
import os
from pathlib import Path

# 确保项目根目录在 Python 路径中
PROJECT_ROOT = Path(__file__).parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ==================== v2.1：全局禁止子进程弹黑窗 ★ ====================
# 必须在最早期调用，早于任何 subprocess 导入
from tools.subprocess_utils import install_global_patch
install_global_patch()

# 环境变量设置
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("QT_SCALE_FACTOR", "1")


def main():
    """启动 GUI 主界面"""
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt
    from ui.main_window import MainWindow

    # 高 DPI 支持
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("阴阳师自动化脚本")

    # 设置应用样式
    app.setStyle("Fusion")

    # 创建并显示主窗口
    window = MainWindow()
    window.show()

    # 进入事件循环
    sys.exit(app.exec_())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        # 写入崩溃日志
        import traceback
        error_msg = traceback.format_exc()
        error_file = PROJECT_ROOT / "crash.log"
        try:
            with open(error_file, "w", encoding="utf-8") as f:
                f.write(f"Crash Report\n")
                f.write(f"Time: {__import__('datetime').datetime.now()}\n")
                f.write(f"Error: {e}\n\n")
                f.write(error_msg)
        except Exception:
            pass

        # 尝试弹窗提示
        try:
            from PyQt5.QtWidgets import QMessageBox, QApplication
            app = QApplication(sys.argv)
            QMessageBox.critical(None, "Launch Failed",
                f"Script launch failed:\n{e}\n\nDetails written to crash.log")
        except Exception:
            # PyQt5 不可用，尝试 Windows MessageBox（pythonw 模式下可见）
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(0,
                    f"Script launch failed:\n{e}\n\nDetails: {error_file}",
                    "YYS Script - Error", 0x10)
            except Exception:
                pass
        sys.exit(1)
