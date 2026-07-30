"""
开发辅助工具：子进程工具。

用于启动/管理外部子进程。
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from typing import Any, Callable


class SubprocessManager:
    """子进程管理器"""

    def __init__(self):
        self._processes: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def start(
        self,
        name: str,
        cmd: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stdout_callback: Callable[[str], None] | None = None,
        stderr_callback: Callable[[str], None] | None = None,
    ) -> bool:
        """启动子进程"""
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            with self._lock:
                self._processes[name] = proc

            # 异步读取输出
            if stdout_callback:
                threading.Thread(
                    target=self._read_output,
                    args=(proc.stdout, stdout_callback),
                    daemon=True,
                ).start()
            if stderr_callback:
                threading.Thread(
                    target=self._read_output,
                    args=(proc.stderr, stderr_callback),
                    daemon=True,
                ).start()

            return True
        except Exception:
            return False

    @staticmethod
    def _read_output(stream, callback: Callable[[str], None]) -> None:
        """读取子进程输出"""
        try:
            for line in iter(stream.readline, ""):
                if line:
                    callback(line.rstrip("\n"))
        except Exception:
            pass
        finally:
            stream.close()

    def stop(self, name: str) -> bool:
        """停止子进程"""
        with self._lock:
            proc = self._processes.pop(name, None)
        if proc:
            proc.terminate()
            proc.wait(timeout=5)
            return True
        return False

    def stop_all(self) -> int:
        """停止所有子进程"""
        count = 0
        for name in list(self._processes.keys()):
            if self.stop(name):
                count += 1
        return count

    def is_running(self, name: str) -> bool:
        """检查子进程是否运行"""
        proc = self._processes.get(name)
        if proc is None:
            return False
        return proc.poll() is None

    def get_status(self) -> dict[str, str]:
        """获取所有进程状态"""
        return {
            name: "running" if self.is_running(name) else "stopped"
            for name in self._processes
        }
