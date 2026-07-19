"""
无黑窗子进程工具（全局使用）

确保所有 subprocess 调用在任何情况下都不会弹出 CMD 黑窗口。
Windows 下使用 CREATE_NO_WINDOW 标志 + shell=False 组合。

使用方式：
    from tools.subprocess_utils import run_no_window, run_no_window_bytes

    output = run_no_window(["adb", "devices"])
"""

import subprocess
import sys
import os

# Windows 专用：禁止子进程创建控制台窗口
if sys.platform == "win32":
    _NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    _STARTUP_INFO = None

    def _get_startupinfo():
        """获取隐藏窗口的 STARTUPINFO（延迟创建）。"""
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return si
else:
    _NO_WINDOW_FLAGS = 0
    _STARTUP_INFO = None

    def _get_startupinfo():
        return None


def run_no_window(cmd: list, timeout: int = 30, cwd: str = None,
                  env: dict = None) -> subprocess.CompletedProcess:
    """运行命令，绝对不弹出 CMD 黑窗口。

    Args:
        cmd: 命令列表，如 ["adb", "devices"]
        timeout: 超时秒数
        cwd: 工作目录
        env: 环境变量（默认继承 os.environ 并屏蔽 __PYVENV_LAUNCHER__）

    Returns:
        subprocess.CompletedProcess 对象
    """
    if env is None:
        env = os.environ.copy()
        # 屏蔽 __PYVENV_LAUNCHER__ 以避免 venv 子进程干扰
        env.pop("__PYVENV_LAUNCHER__", None)

    return subprocess.run(
        cmd,
        capture_output=True,
        text=False,
        timeout=timeout,
        cwd=cwd,
        env=env,
        creationflags=_NO_WINDOW_FLAGS,
        startupinfo=_get_startupinfo(),
        shell=False,
    )


def run_no_window_text(cmd: list, timeout: int = 30, cwd: str = None) -> str:
    """运行命令并返回 stdout 字符串（UTF-8解码）。"""
    result = run_no_window(cmd, timeout=timeout, cwd=cwd)
    return result.stdout.decode("utf-8", errors="replace") if result.stdout else ""


def run_no_window_bytes(cmd: list, timeout: int = 30, cwd: str = None) -> bytes:
    """运行命令并返回 stdout 原始字节。"""
    result = run_no_window(cmd, timeout=timeout, cwd=cwd)
    return result.stdout if result.stdout else b""


def run_no_window_status(cmd: list, timeout: int = 30, cwd: str = None) -> tuple[int, str, str]:
    """运行命令并返回 (returncode, stdout_str, stderr_str)。"""
    result = run_no_window(cmd, timeout=timeout, cwd=cwd)
    stdout_str = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
    stderr_str = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
    return result.returncode, stdout_str, stderr_str


# ==================== 全局补丁：禁止任何 subprocess.run 弹窗 ====================

_original_subprocess_run = subprocess.run


def _patched_run(*args, **kwargs):
    """全局补丁：自动注入 CREATE_NO_WINDOW 标志。

    拦截所有 subprocess.run() 调用，确保不会弹出 CMD 窗口。
    如果调用方已显式传入 creationflags，以调用方为准。
    """
    if sys.platform == "win32":
        if "creationflags" not in kwargs:
            kwargs["creationflags"] = _NO_WINDOW_FLAGS
        if "startupinfo" not in kwargs:
            kwargs["startupinfo"] = _get_startupinfo()
    # 确保 shell=False（防止 cmd.exe 中间层弹窗）
    kwargs.setdefault("shell", False)
    return _original_subprocess_run(*args, **kwargs)


def install_global_patch():
    """安装全局补丁：全局替换 subprocess.run。

    调用后，项目中任何代码使用 subprocess.run() 都不会弹出 CMD 窗口。
    应在 main.py 最早期调用。
    """
    subprocess.run = _patched_run


def uninstall_global_patch():
    """卸载全局补丁：恢复原始 subprocess.run。"""
    subprocess.run = _original_subprocess_run
