"""
模拟器管理模块

职责：检测模拟器是否运行、自动启动模拟器、等待 ADB 就绪、自动定位模拟器自带的 adb.exe。
支持雷电(LDPlayer)、MuMu、夜神(Nox) 三种常见模拟器。

注意：系统 PATH 中的 adb.exe 可能损坏（如 System32 中的 adb 缺少 ADBWinApi.dll），
因此优先使用模拟器自带的 adb.exe，保证连接稳定性。
"""

import os
import subprocess
import time
from pathlib import Path

from core.logger import get_logger

logger = get_logger("device.emulator")

# 各模拟器的默认安装路径（按优先级排列）
EMULATOR_PATHS = {
    "ldplayer": [
        r"C:\LDPlayer\LDPlayer9\dnplayer.exe",
        r"C:\LDPlayer\LDPlayer4\dnplayer.exe",
        r"D:\LDPlayer\LDPlayer9\dnplayer.exe",
        r"D:\LDPlayer\LDPlayer4\dnplayer.exe",
        r"C:\Program Files\LDPlayer\LDPlayer9\dnplayer.exe",
        r"C:\Leidian\LDPlayer9\dnplayer.exe",
        r"D:\ChangZhi\dnplayer2\dnplayer.exe",
    ],
    # MuMu12 实际安装在 ...\Netease\MuMu\，主程序在 nx_main\MuMuNxMain.exe
    "mumu": [
        r"C:\Program Files\Netease\MuMu\nx_main\MuMuNxMain.exe",
        r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\MuMuPlayer.exe",
        r"C:\Program Files\Netease\MuMuPlayerGlobal-12.0\shell\MuMuPlayer.exe",
        r"D:\Program Files\Netease\MuMu\nx_main\MuMuNxMain.exe",
        r"D:\Program Files\Netease\MuMuPlayer-12.0\shell\MuMuPlayer.exe",
        r"C:\Program Files (x86)\Netease\MuMuPlayer-12.0\shell\MuMuPlayer.exe",
        r"C:\Program Files\MuMu\emulator\nemu\EmulatorShell\nemulator.exe",
        r"D:\MuMu\emulator\nemu\EmulatorShell\nemulator.exe",
    ],
    "nox": [
        r"C:\Program Files\Nox\bin\Nox.exe",
        r"C:\Program Files (x86)\Nox\bin\Nox.exe",
        r"D:\Program Files\Nox\bin\Nox.exe",
        r"D:\Nox\bin\Nox.exe",
        r"B:\Nox\bin\Nox.exe",
    ],
}

# 模拟器自带 adb.exe 的查找规则：基于模拟器安装目录的相对路径
# find_adb_path() 会先定位模拟器安装根目录，再在这些子路径中找 adb.exe
EMULATOR_ADB_SUBPATHS = {
    "ldplayer": ["adb.exe"],
    # MuMu12: adb 在 nx_main\adb.exe 或 nx_device\<版本>\shell\adb.exe
    "mumu": ["nx_main\\adb.exe"],
    "nox": ["nox_adb.exe", "adb.exe"],
}

# 各模拟器默认 ADB 端口
# 注意：MuMu12 默认 16384，老版 MuMu 用 7555
EMULATOR_PORTS = {
    "ldplayer": 5555,
    "mumu": 16384,      # MuMu12 默认端口
    "nox": 62001,
}

# 各模拟器的进程名（用于检测是否在运行）
EMULATOR_PROCESS_NAMES = {
    "ldplayer": ["dnplayer.exe", "LdVBoxHeadless.exe"],
    "mumu": ["MuMuNxMain.exe", "MuMuNxDevice.exe", "MuMuPlayer.exe", "nemulator.exe", "MuMuVMMHeadless.exe"],
    "nox": ["Nox.exe", "NoxVMHandle.exe"],
}


class EmulatorManager:
    """模拟器管理器：检测、启动、等待就绪、定位 adb"""

    def __init__(self, emulator_type: str = "ldplayer", custom_path: str = ""):
        """
        Args:
            emulator_type: 模拟器类型 ldplayer / mumu / nox
            custom_path: 自定义模拟器路径（优先使用）
        """
        self.emulator_type = emulator_type.lower()
        self.custom_path = custom_path

    def find_emulator_path(self) -> str:
        """查找模拟器可执行文件路径

        Returns:
            模拟器路径，找不到则返回空字符串
        """
        # 优先使用自定义路径
        if self.custom_path and os.path.isfile(self.custom_path):
            return self.custom_path

        # 从预设路径中查找
        paths = EMULATOR_PATHS.get(self.emulator_type, [])
        for path in paths:
            if os.path.isfile(path):
                logger.info(f"找到模拟器: {path}")
                return path

        return ""

    def find_emulator_root(self) -> str:
        """查找模拟器安装根目录

        通过模拟器 exe 路径向上推导根目录。

        Returns:
            模拟器安装根目录，找不到则返回空字符串
        """
        exe_path = self.find_emulator_path()
        if not exe_path:
            return ""

        # MuMu: exe 在 nx_main\MuMuNxMain.exe，根目录是上一级
        # 雷电: exe 在 LDPlayer9\dnplayer.exe，根目录是上一级
        # 夜神: exe 在 bin\Nox.exe，根目录是上一级
        exe = Path(exe_path)
        # 统一取 exe 所在目录的上一级作为根目录
        if exe.parent.name.lower() in ("nx_main", "shell", "bin"):
            return str(exe.parent.parent)
        return str(exe.parent)

    def find_adb_path(self) -> str:
        """查找可用的 adb.exe 路径

        优先级：
        1. 模拟器自带的 adb.exe（最可靠，版本匹配）
        2. 系统 PATH 中的 adb（需验证可用）
        3. 返回 "adb" 作为 fallback

        Returns:
            adb.exe 的绝对路径，或 "adb"
        """
        # 1. 尝试模拟器自带的 adb
        root = self.find_emulator_root()
        if root:
            subpaths = EMULATOR_ADB_SUBPATHS.get(self.emulator_type, [])
            for sub in subpaths:
                adb_path = os.path.join(root, sub)
                if os.path.isfile(adb_path):
                    if self._test_adb(adb_path):
                        logger.info(f"使用模拟器自带 adb: {adb_path}")
                        return adb_path
                    else:
                        logger.debug(f"模拟器 adb 不可用: {adb_path}")

            # MuMu12 特殊处理：nx_device\<版本>\shell\adb.exe
            if self.emulator_type == "mumu":
                nx_device_dir = os.path.join(root, "nx_device")
                if os.path.isdir(nx_device_dir):
                    for ver in os.listdir(nx_device_dir):
                        adb_candidate = os.path.join(nx_device_dir, ver, "shell", "adb.exe")
                        if os.path.isfile(adb_candidate) and self._test_adb(adb_candidate):
                            logger.info(f"使用 MuMu 自带 adb: {adb_candidate}")
                            return adb_candidate

        # 2. 尝试系统 PATH 中的 adb
        system_adb = self._find_system_adb()
        if system_adb:
            logger.info(f"使用系统 adb: {system_adb}")
            return system_adb

        # 3. fallback
        logger.warning("未找到可用的 adb，使用默认 'adb'（可能不可用）")
        return "adb"

    def _test_adb(self, adb_path: str) -> bool:
        """测试 adb.exe 是否可正常执行

        System32 中的 adb.exe 可能因缺少 ADBWinApi.dll 而无法运行（exit 127），
        必须实际运行 version 命令验证。
        """
        try:
            result = subprocess.run(
                [adb_path, "version"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace"
            )
            return result.returncode == 0 and "Android Debug Bridge" in (result.stdout or "")
        except Exception:
            return False

    def _find_system_adb(self) -> str:
        """在系统 PATH 中查找可用的 adb.exe"""
        # 遍历 PATH 环境变量
        path_env = os.environ.get("PATH", "")
        for p_dir in path_env.split(os.pathsep):
            if not p_dir:
                continue
            adb_candidate = os.path.join(p_dir, "adb.exe")
            if os.path.isfile(adb_candidate) and self._test_adb(adb_candidate):
                return adb_candidate
        return ""

    def is_running(self) -> bool:
        """检测模拟器进程是否在运行

        Returns:
            True 表示模拟器进程存在
        """
        process_names = EMULATOR_PROCESS_NAMES.get(self.emulator_type, [])

        try:
            # 使用 tasklist 查找进程
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
                encoding="gbk", errors="replace"
            )
            # 注意：result.stdout 是字符串，必须 splitlines() 才能逐行遍历
            # （直接 for line in str 会逐字符遍历，导致检测失效）
            output_lower = result.stdout.lower()
            for name in process_names:
                if name.lower() in output_lower:
                    return True
        except Exception as e:
            logger.debug(f"进程检测失败: {e}")

        return False

    def launch(self) -> bool:
        """启动模拟器

        Returns:
            True 表示启动命令已执行
        """
        exe_path = self.find_emulator_path()
        if not exe_path:
            logger.error(f"未找到模拟器程序，类型={self.emulator_type}")
            logger.info("请在设置中手动指定模拟器路径，或手动启动模拟器")
            return False

        logger.info(f"启动模拟器: {exe_path}")

        try:
            subprocess.Popen(
                [exe_path],
                creationflags=subprocess.DETACHED_PROCESS
            )
            logger.info("模拟器启动命令已发送，等待启动...")
            return True

        except Exception as e:
            logger.error(f"模拟器启动失败: {e}")
            return False

    def wait_for_adb(self, adb_client, port: int = None, timeout: int = 60) -> bool:
        """等待模拟器 ADB 接口就绪

        Args:
            adb_client: ADBClient 实例
            port: ADB 端口，None 则使用默认端口
            timeout: 最大等待时间（秒）

        Returns:
            True 表示 ADB 已就绪
        """
        if port is None:
            port = EMULATOR_PORTS.get(self.emulator_type, 5555)

        device_id = f"127.0.0.1:{port}"
        logger.info(f"等待 ADB 就绪: {device_id} (超时 {timeout}s)")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # 尝试连接
                result = adb_client._run_command(
                    ["connect", device_id], use_device=False
                )
                if "connected" in result or "already connected" in result:
                    # 验证设备状态
                    state = adb_client._run_command(
                        ["-s", device_id, "get-state"], use_device=False
                    ).strip()
                    if state == "device":
                        logger.info(f"ADB 已就绪: {device_id}")
                        adb_client.device_id = device_id
                        adb_client._connected = True
                        return True
            except Exception:
                pass

            # 等待后重试
            time.sleep(3)
            elapsed = int(time.time() - start_time)
            if elapsed % 10 == 0:
                logger.info(f"等待模拟器启动中... ({elapsed}s/{timeout}s)")

        logger.error(f"等待 ADB 就绪超时 ({timeout}s)")
        return False

    def ensure_running(self, adb_client, port: int = None, timeout: int = 90) -> bool:
        """确保模拟器已运行且 ADB 就绪

        如果模拟器未运行则自动启动，然后等待 ADB 就绪。
        同时会自动定位模拟器自带的 adb.exe 并更新 adb_client.adb_path。

        Args:
            adb_client: ADBClient 实例
            port: ADB 端口
            timeout: 等待超时时间

        Returns:
            True 表示模拟器已就绪
        """
        if port is None:
            port = EMULATOR_PORTS.get(self.emulator_type, 5555)

        # 0. 自动定位可用的 adb.exe（系统 adb 可能损坏）
        reliable_adb = self.find_adb_path()
        if reliable_adb and reliable_adb != "adb":
            adb_client.adb_path = reliable_adb
            logger.info(f"已切换到可靠 adb: {reliable_adb}")

        # 1. 检查模拟器是否在运行
        if self.is_running():
            logger.info("检测到模拟器进程已在运行")
        else:
            # 2. 模拟器未运行，尝试自动启动
            logger.info("模拟器未运行，尝试自动启动...")
            if not self.launch():
                logger.error("无法自动启动模拟器，请手动启动后重试")
                return False

            # 等待模拟器进程出现
            logger.info("等待模拟器进程启动...")
            for _ in range(20):
                time.sleep(2)
                if self.is_running():
                    logger.info("模拟器进程已启动")
                    break
            else:
                logger.error("模拟器进程启动超时")
                return False

        # 3. 等待 ADB 就绪
        return self.wait_for_adb(adb_client, port, timeout)
