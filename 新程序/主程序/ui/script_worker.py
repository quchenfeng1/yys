"""
09-运行控制中心 Qt 适配

ScriptWorker QThread（封装 RunController）。
对应设计书 §5.3 ScriptWorker 方法定义。
"""
from __future__ import annotations

from PyQt5.QtCore import QThread, pyqtSignal

from core.run_controller import RunController


class ScriptWorker(QThread):
    """
    脚本工作线程（§5.3 ScriptWorker）。

    QThread 适配层，封装 RunController 核心逻辑，
    添加 pyqtSignal 与 UI 通信。
    """

    # §5.3 信号
    started = pyqtSignal()
    finished = pyqtSignal()
    error_occurred = pyqtSignal(str)
    progress_updated = pyqtSignal(float, str)
    log_signal = pyqtSignal(str)  # §5.3 日志信号

    def __init__(self, controller: RunController, parent=None):
        super().__init__(parent)
        self._controller = controller

    # ── §5.3 方法 ──────────────────────────────────────────

    def run(self) -> None:
        """QThread 入口 → 调用 RunController.execute()"""
        self.started.emit()
        try:
            self._controller.execute()
            self._controller.wait_for_stop()
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            self.finished.emit()

    def request_stop(self) -> None:
        """请求停止"""
        self._controller.stop()

    def is_stopped(self) -> bool:
        """检查是否已停止（§5.3）"""
        return self._controller.is_stopped()

    def request_pause(self) -> None:
        """请求暂停"""
        self._controller.pause()

    def request_resume(self) -> None:
        """请求恢复"""
        self._controller.resume()

    def emit_log(self, message: str) -> None:
        """发送日志信号"""
        self.log_signal.emit(message)
