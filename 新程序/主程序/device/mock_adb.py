"""
01-设备连接模块（模拟实现 MockADBClient）

无真实模拟器时的 ADB 模拟层。
接口与 device/adb_client.ADBClient 完全兼容，注入 ConnectionManager 后
上层（识别/执行/调度/UI）无需任何改动即可运行。

行为：
- echo() / connect() → 恒 True（模拟设备在线）
- get_first_device() → "mock:5555"
- wm_size() → (1080, 1920)（模拟屏幕分辨率）
- screencap() → 合成截图：把 assets/ 下素材模板嵌入固定位置，
  使图像识别能命中；无素材时返回纯色场景图
- tap/swipe/text/keyevent → 仅记录，不执行真实命令
- 所有操作记录在 self.operations 中，便于验证断言
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import cv2


class _MockResult:
    """模拟 subprocess.CompletedProcess（仅提供被读取的字段）"""

    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class MockADBClient:
    """模拟 ADB 客户端（与 ADBClient 接口兼容）"""

    SCREEN_W: int = 1080
    SCREEN_H: int = 1920

    def __init__(
        self,
        adb_path: str = "mock",
        serial: str = "mock:5555",
        platform: str = "mock",
        screenshot_timeout: float = 15.0,
        input_timeout: float = 10.0,
        assets_dir: str | Path | None = None,
    ):
        self._adb_path = adb_path
        self._serial: str | None = serial or None
        self._platform = platform
        self._screenshot_timeout = screenshot_timeout
        self._input_timeout = input_timeout
        self._assets_dir = Path(assets_dir) if assets_dir else None

        # 合成截图相关
        self._templates: dict[str, np.ndarray] = {}
        self._positions: dict[str, tuple[int, int]] = {}
        self._screen: np.ndarray | None = None

        # 操作记录
        self.clicks: list[tuple[int, int]] = []
        self.swipes: list[tuple] = []
        self.inputs: list[str] = []
        self.keys: list[int] = []
        self.screenshot_count: int = 0
        self.operations: list[dict[str, Any]] = []

        self._load_templates()

    # ── 属性（与 ADBClient 对齐） ─────────────────────────────

    @property
    def serial(self) -> str | None:
        return self._serial

    @serial.setter
    def serial(self, value: str) -> None:
        self._serial = value

    @property
    def adb_path(self) -> str:
        return self._adb_path

    @property
    def platform(self) -> str:
        return self._platform

    # ── 合成素材加载 ──────────────────────────────────────────

    def _load_templates(self) -> None:
        """扫描 assets 目录，加载全部 PNG 模板（相对路径为键）"""
        if not self._assets_dir or not self._assets_dir.exists():
            return
        for p in sorted(self._assets_dir.rglob("*.png")):
            try:
                img = cv2.imread(str(p))
                if img is None:
                    continue
                rel = p.relative_to(self._assets_dir).with_suffix("")
                self._templates[str(rel).replace("\\", "/")] = img
            except Exception:
                continue

    def _build_screen(self) -> np.ndarray:
        """
        合成屏幕：深灰背景 + 全部素材模板竖排嵌入。
        保证识别器对已存在素材的模板匹配能命中（完全一致 → 高置信度）。
        """
        screen = np.full((self.SCREEN_H, self.SCREEN_W, 3), 30, dtype=np.uint8)
        self._positions.clear()
        y = 60
        for name, tpl in self._templates.items():
            th, tw = tpl.shape[:2]
            if th > self.SCREEN_H - y:
                break
            x = 100
            if x + tw > self.SCREEN_W:
                x = 0
            screen[y:y + th, x:x + tw] = tpl
            self._positions[name] = (x, y)
            y += th + 40

        # 无素材时打上标识，便于肉眼区分模拟模式
        if not self._templates:
            cv2.putText(screen, "MOCK SCREEN (no assets)", (60, 200),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2)
        return screen

    # ── 连接 ──────────────────────────────────────────────────

    def connect(self, serial: str | None = None) -> bool:
        """模拟建立连接（恒成功）"""
        if serial:
            self._serial = serial
        return True

    def disconnect(self) -> None:
        """模拟断开（无操作）"""
        pass

    def echo(self) -> bool:
        """模拟设备在线"""
        return True

    def list_devices(self) -> list[dict[str, str]]:
        """返回一个模拟设备"""
        return [{"serial": self._serial or "mock:5555", "state": "device"}]

    def get_first_device(self) -> str | None:
        """返回模拟设备 serial"""
        return self._serial or "mock:5555"

    # ── 设备操作（仅记录） ────────────────────────────────────

    def tap(self, x: int, y: int) -> None:
        self.clicks.append((int(x), int(y)))
        self.operations.append({"op": "tap", "x": int(x), "y": int(y)})

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.swipes.append((int(x1), int(y1), int(x2), int(y2)))
        self.operations.append({
            "op": "swipe", "x1": int(x1), "y1": int(y1),
            "x2": int(x2), "y2": int(y2), "duration_ms": duration_ms,
        })

    def text(self, text: str) -> None:
        self.inputs.append(text)
        self.operations.append({"op": "text", "text": text})

    def keyevent(self, key: int) -> None:
        self.keys.append(int(key))
        self.operations.append({"op": "keyevent", "key": int(key)})

    def am_start(self, package: str, activity: str) -> bool:
        self.operations.append({"op": "am_start", "package": package, "activity": activity})
        return True

    def foreground_package(self) -> str | None:
        """模拟返回一个未知包名（触发上层回退逻辑）"""
        return None

    def run(self, args: list[str], timeout: float | None = None) -> _MockResult:
        """模拟统一命令出口（pidof 等回退查询返回空）"""
        return _MockResult()

    # ── 系统信息 ──────────────────────────────────────────────

    def wm_size(self) -> tuple[int, int]:
        return (self.SCREEN_W, self.SCREEN_H)

    def get_device_model(self) -> str:
        return "Mock Emulator"

    def get_android_version(self) -> str:
        return "10"

    # ── 截图 ──────────────────────────────────────────────────

    def screencap(self) -> bytes:
        """返回合成截图的 PNG 二进制流（ConnectionManager 用 imdecode 解码）"""
        self._screen = self._build_screen()
        self.screenshot_count += 1
        ok, buf = cv2.imencode(".png", self._screen)
        return buf.tobytes()

    def screenshot(self, output_path: str = "/sdcard/screenshot.png") -> bytes:
        """兼容旧方法：直接返回合成截图"""
        return self.screencap()

    def pull_screenshot(self, local_path: str) -> bool:
        """截屏并写入本地文件"""
        try:
            data = self.screencap()
            with open(local_path, "wb") as f:
                f.write(data)
            return True
        except Exception:
            return False

    # ── 测试辅助 ──────────────────────────────────────────────

    @property
    def template_positions(self) -> dict[str, tuple[int, int]]:
        """各模板在合成截图中的位置（供断言使用）"""
        return dict(self._positions)
