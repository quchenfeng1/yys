"""
ADB 客户端模块

职责：封装 ADB 连接与底层设备操作，对上层屏蔽 ADB 命令细节。
- 连接模拟器/真机
- 截图（adb exec-out screencap，直接输出二进制流）
- 点击/滑动/按键
- 设置模拟器分辨率为 1280x720（核心需求）
- 启动/关闭 App
"""

import subprocess
import time
import numpy as np
import cv2

from core.logger import get_logger
from core.exceptions import DeviceConnectError

logger = get_logger("device.adb")


class ADBClient:
    """ADB 客户端，封装所有底层 ADB 操作"""

    def __init__(self, device_id: str = "127.0.0.1:5555", adb_path: str = "adb"):
        self.device_id = device_id
        self.adb_path = adb_path
        self._connected = False

    # ===== 连接管理 =====

    def connect(self) -> bool:
        """连接设备：先 adb connect，再验证连接状态"""
        logger.info(f"正在连接设备 {self.device_id} ...")

        # adb connect
        host_port = self.device_id
        result = self._run_command(["connect", host_port], use_device=False)
        if "connected" in result or "already connected" in result:
            logger.info(f"ADB connect 成功: {result.strip()}")
        else:
            logger.warning(f"ADB connect 返回: {result.strip()}")

        # 验证连接
        if self.is_connected():
            self._connected = True
            screen = self.get_screen_size()
            logger.info(f"设备已连接，屏幕分辨率: {screen}")
            return True
        else:
            raise DeviceConnectError(f"无法连接设备 {self.device_id}，请确认模拟器已启动且 ADB 端口正确")

    def is_connected(self) -> bool:
        """检测连接状态（用指定设备 ID 检查，避免多设备时出错）"""
        # 用带 -s 的 get-state 检查指定设备
        result = self._run_command(["get-state"], use_device=True)
        state = result.strip()
        if state == "device":
            return True
        # fallback: 用 devices 列表逐行精确匹配
        devices = self._run_command(["devices"], use_device=False)
        for line in devices.splitlines():
            if self.device_id in line and "\tdevice" in line:
                return True
        return False

    def disconnect(self):
        """断开连接"""
        self._run_command(["disconnect", self.device_id], use_device=False)
        self._connected = False
        logger.info(f"已断开设备 {self.device_id}")

    # ===== 分辨率设置（核心需求）=====

    def set_resolution(self, width: int = 1280, height: int = 720, dpi: int = 240) -> bool:
        """设置模拟器分辨率为 1280x720

        通过 adb shell wm size 和 wm density 命令设置。
        注意：部分模拟器需重启才能生效，建议在模拟器设置中也改为 1280x720。
        """
        logger.info(f"设置模拟器分辨率: {width}x{height} DPI={dpi}")

        # 设置分辨率
        result1 = self.shell(f"wm size {width}x{height}")
        logger.info(f"wm size 结果: {result1.strip()}")

        # 设置 DPI
        result2 = self.shell(f"wm density {dpi}")
        logger.info(f"wm density 结果: {result2.strip()}")

        # 验证
        actual = self.get_screen_size()
        if actual == (width, height):
            logger.info(f"分辨率设置成功: {actual}")
            return True
        else:
            logger.warning(f"分辨率实际为 {actual}，期望 {width}x{height}。"
                          "部分模拟器需在设置中手动修改或重启模拟器后生效。")
            return False

    def get_screen_size(self) -> tuple:
        """获取屏幕分辨率，返回 (width, height)

        优先返回 Override size（wm size 设置的覆盖值），
        没有 Override 时返回 Physical size。
        """
        result = self.shell("wm size")
        # 输出示例:
        #   Physical size: 720x1280
        #   Override size: 1280x720
        physical = None
        override = None
        for line in result.split("\n"):
            line_lower = line.lower()
            if "x" not in line:
                continue
            parts = line.split(":")[-1].strip()
            try:
                w, h = parts.split("x")
                size = (int(w), int(h))
            except ValueError:
                continue
            if "override" in line_lower:
                override = size
            elif "size" in line_lower:
                physical = size
        # 优先 Override（用户/脚本设置的覆盖值，实际生效的分辨率）
        return override if override else (physical if physical else (0, 0))

    # ===== 截图 =====

    def screenshot(self) -> np.ndarray:
        """截图，返回 OpenCV BGR 格式的 numpy 数组

        使用 adb exec-out screencap -p 直接输出二进制 PNG 流，避免文件读写延迟。
        """
        result = self._run_command_bytes(["exec-out", "screencap", "-p"])
        if not result:
            raise DeviceConnectError("截图失败：未获取到数据")

        # 将二进制 PNG 解码为 OpenCV 图像
        img_array = np.frombuffer(result, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            raise DeviceConnectError("截图解码失败：图像数据无效")

        return img

    # ===== 操作（仅坐标，不含防封号处理）=====

    def click(self, x: int, y: int):
        """点击坐标（仅坐标，不含防封号。上层应通过 Executor 调用以获得防封号保护）"""
        self.shell(f"input tap {x} {y}")
        logger.debug(f"ADB click: ({x}, {y})")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300):
        """滑动，duration 单位为毫秒"""
        self.shell(f"input swipe {x1} {y1} {x2} {y2} {duration}")
        logger.debug(f"ADB swipe: ({x1},{y1}) -> ({x2},{y2}) dur={duration}ms")

    def input_key(self, key: str):
        """按键（BACK/HOME/MENU/POWER）"""
        key_map = {
            "BACK": "4",
            "HOME": "3",
            "MENU": "82",
            "POWER": "26",
        }
        keycode = key_map.get(key.upper(), key)
        self.shell(f"input keyevent {keycode}")
        logger.debug(f"ADB key: {key}({keycode})")

    def input_text(self, text: str):
        """输入文本（用于账号密码输入）"""
        # 使用 am broadcast 输入文本（兼容中文需第三方输入法）
        # 英文/数字用 input text
        safe_text = text.replace(" ", "%s").replace("&", "\\&")
        self.shell(f"input text \"{safe_text}\"")
        logger.debug(f"ADB input text: {text}")

    # ===== App 管理 =====

    def get_app_pid(self, package: str) -> int:
        """获取 App 进程 PID，返回 0 表示未运行"""
        result = self.shell(f"pidof {package}")
        pid_str = result.strip().split()[0] if result.strip() else "0"
        try:
            return int(pid_str)
        except ValueError:
            return 0

    def is_app_running(self, package: str) -> bool:
        """检查 App 进程是否在运行（基于 pidof，比 dumpsys 更可靠）"""
        return self.get_app_pid(package) > 0

    def is_app_foreground(self, package: str) -> bool:
        """检查 App 是否在前台运行"""
        result = self.shell("dumpsys activity activities | grep mResumedActivity")
        return package in result

    def launch_app(self, package: str, activity: str = None) -> bool:
        """启动 App（若已在运行则跳过）

        Args:
            package: 包名，如 com.netease.onmyoji.wyzymnqsd_cps
            activity: 启动 Activity（可选，不传则用 monkey 启动）

        Returns:
            True 表示启动指令已发出且进程已就绪
        """
        # 若已在前台，无需启动
        if self.is_app_foreground(package):
            logger.info(f"App {package} 已在前台运行，跳过启动")
            return True

        # 若进程存在但不在前台，先拉到前台
        if self.is_app_running(package):
            logger.info(f"App {package} 已在后台运行，拉到前台")
            self.shell(f"am start -n {package}/{activity}") if activity else \
                self.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1")
            return True

        # 全新启动
        if activity:
            cmd = f"am start -n {package}/{activity}"
        else:
            cmd = f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
        result = self.shell(cmd)
        logger.info(f"启动 App {package}: {result.strip()}")

        if "Error" in result or "Exception" in result or "not found" in result.lower():
            # am start 失败，尝试 monkey 兜底
            if activity:
                logger.warning(f"am start 失败，尝试 monkey 启动: {result.strip()}")
                result2 = self.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1")
                logger.info(f"monkey 启动结果: {result2.strip()}")
                if "No activities found" in result2:
                    logger.error(f"App 启动失败（未找到启动入口）: {package}")
                    return False
            else:
                logger.error(f"App 启动失败: {result}")
                return False

        # 等待进程就绪
        return self.wait_for_app_ready(package, timeout=30)

    def wait_for_app_ready(self, package: str, timeout: int = 30) -> bool:
        """等待 App 进程出现（轮询 pidof）

        Args:
            package: 包名
            timeout: 最大等待秒数

        Returns:
            True 表示进程已出现
        """
        logger.info(f"等待 App {package} 进程就绪（最多 {timeout}s）...")
        for i in range(timeout):
            if self.is_app_running(package):
                pid = self.get_app_pid(package)
                logger.info(f"App {package} 已启动，PID={pid}（等待 {i+1}s）")
                return True
            time.sleep(1)
        logger.error(f"等待 App {package} 启动超时（{timeout}s）")
        return False

    def stop_app(self, package: str):
        """停止 App"""
        self.shell(f"am force-stop {package}")
        logger.info(f"已停止 App {package}")

    # ===== 内部方法 =====

    def _build_command(self, args: list, use_device: bool = True) -> list:
        """构建 adb 命令参数列表"""
        cmd = [self.adb_path]
        if use_device and self.device_id:
            cmd += ["-s", self.device_id]
        cmd += args
        return cmd

    def _run_command(self, args: list, use_device: bool = True, timeout: int = 30) -> str:
        """运行 adb 命令，返回 stdout 字符串"""
        cmd = self._build_command(args, use_device)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace"
            )
            if result.returncode != 0 and result.stderr:
                logger.debug(f"ADB 命令 stderr: {result.stderr.strip()}")
            return result.stdout
        except subprocess.TimeoutExpired:
            logger.error(f"ADB 命令超时: {' '.join(args)}")
            return ""
        except FileNotFoundError:
            raise DeviceConnectError(
                f"找不到 ADB 程序 '{self.adb_path}'，请确认 adb 已安装并在 PATH 中，"
                f"或在 config/global.yaml 中配置 adb.path"
            )

    def _run_command_bytes(self, args: list, use_device: bool = True, timeout: int = 30) -> bytes:
        """运行 adb 命令，返回 stdout 字节流（用于截图）"""
        cmd = self._build_command(args, use_device)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
            )
            return result.stdout
        except subprocess.TimeoutExpired:
            logger.error(f"ADB 命令超时: {' '.join(args)}")
            return b""

    def shell(self, command: str, timeout: int = 30) -> str:
        """执行 adb shell 命令"""
        return self._run_command(["shell", command], timeout=timeout)
