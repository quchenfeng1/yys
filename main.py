"""
阴阳师自动化识图脚本 - 主入口

启动后弹出 GUI 菜单界面，在界面中点击「运行」才开始执行脚本。
脚本会自动检测并启动模拟器，无需预先打开模拟器。

使用方法：
    python main.py        # 启动 GUI 界面
    或双击 启动.bat
"""

import sys
import os
from pathlib import Path

# 确保项目根目录在 Python 路径中
PROJECT_ROOT = Path(__file__).parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 环境变量设置（避免 PyQt5 在某些环境下报错）
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
        # GUI 启动失败时，将错误写入文件（pythonw 无控制台输出）
        import traceback
        error_msg = traceback.format_exc()
        error_file = PROJECT_ROOT / "crash.log"
        try:
            with open(error_file, "w", encoding="utf-8") as f:
                f.write(f"阴阳师脚本启动失败\n")
                f.write(f"时间: {__import__('datetime').datetime.now()}\n")
                f.write(f"错误: {e}\n\n")
                f.write(error_msg)
        except Exception:
            pass

        # 尝试弹窗提示（如果 PyQt5 可用）
        try:
            from PyQt5.QtWidgets import QMessageBox, QApplication
            app = QApplication(sys.argv)
            QMessageBox.critical(None, "启动失败",
                f"脚本启动失败:\n{e}\n\n详细信息已写入 crash.log")
            sys.exit(1)
        except Exception:
            # PyQt5 也不可用，只能退出
            sys.exit(1)
