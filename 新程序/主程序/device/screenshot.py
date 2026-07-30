"""
01-设备连接模块

截图优化（压缩/缓存）。
职责:
- 截取设备屏幕
- 图片压缩与格式转换
- 截图缓存
"""
from __future__ import annotations

import threading
import time
from typing import Any

import cv2
import numpy as np

from core.exceptions import ScreenshotError
from device.adb_client import ADBClient


class ScreenshotManager:
    """
    截图管理器（支持三级质量模式）。

    质量模式：
    - normal（默认）：原始 screencap -p，最高质量
    - fast：JPEG 压缩（质量 85%），带宽减少 60~80%
    - low_res：临时 wm size 降低分辨率后截图（如 720p）
    """

    def __init__(
        self,
        adb_client: ADBClient,
        quality_mode: str = "normal",  # normal | fast | low_res
        jpeg_quality: int = 85,
        low_res_width: int = 720,
        cache_ttl: float = 0.5,
        temp_dir: str = "/tmp/yys_screenshots",
    ):
        self._adb = adb_client
        self._quality_mode = quality_mode
        self._jpeg_quality = jpeg_quality
        self._low_res_width = low_res_width
        self._cache_ttl = cache_ttl
        self._resize_ratio = 1.0
        self._temp_dir = temp_dir
        self._quality = jpeg_quality
        self._lock = threading.Lock()
        self._original_size: tuple[int, int] | None = None

        # 缓存
        self._cached_image: np.ndarray | None = None
        self._cached_time: float = 0.0

        import os
        os.makedirs(self._temp_dir, exist_ok=True)

    # ── 截图 ──────────────────────────────────────────────────

    def capture(self, use_cache: bool = True) -> np.ndarray:
        """
        获取截图。失败自动重试 1 次。

        Args:
            use_cache: 是否使用缓存

        Returns:
            BGR 格式的 numpy 数组
        """
        if use_cache and self._cached_image is not None:
            if time.time() - self._cached_time < self._cache_ttl:
                return self._cached_image

        last_error = None
        for attempt in range(2):  # 重试 1 次
            try:
                if self._quality_mode == "low_res":
                    image = self._capture_low_res()
                elif self._quality_mode == "fast":
                    image = self._capture_fast()
                else:
                    image = self._capture_normal()

                if image is None:
                    raise ScreenshotError("截图返回空数据")

                # 缩放
                if self._resize_ratio != 1.0:
                    h, w = image.shape[:2]
                    new_w = int(w * self._resize_ratio)
                    new_h = int(h * self._resize_ratio)
                    image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)

                with self._lock:
                    self._cached_image = image
                    self._cached_time = time.time()
                return image

            except Exception as e:
                last_error = e
                if attempt == 0:
                    time.sleep(0.5)
                continue

        raise ScreenshotError(f"截图失败(已重试): {last_error}")

    def _capture_normal(self) -> np.ndarray:
        """normal 模式：原始 screencap -p"""
        img_bytes = self._adb.screencap()
        img_array = np.frombuffer(img_bytes, dtype=np.uint8)
        image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if image is None:
            return self._fallback_pull()
        return image

    def _capture_fast(self) -> np.ndarray:
        """fast 模式：screencap + JPEG 压缩"""
        image = self._capture_normal()
        if image is not None:
            success, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality])
            if success:
                image = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        return image

    def _capture_low_res(self) -> np.ndarray:
        """
        ⚠️ low_res 模式（危险功能，默认禁用）。
        违反了设计书 §5.5"只读模拟器"原则。
        通过临时修改 wm size 降低截图分辨率，截图后恢复。
        仅在明确知晓风险并手动启用时使用。
        """
        import logging
        logging.warning("low_res 模式修改了模拟器 wm size，违反了只读原则")
        try:
            if self._original_size is None:
                self._original_size = self._adb.wm_size()
            ratio = self._low_res_width / self._original_size[0]
            new_h = int(self._original_size[1] * ratio)
            self._adb.run(["shell", "wm", "size", f"{self._low_res_width}x{new_h}"], timeout=5.0)
            image = self._capture_normal()
            self._adb.run(
                ["shell", "wm", "size", f"{self._original_size[0]}x{self._original_size[1]}"],
                timeout=5.0,
            )
            return image
        except Exception:
            return self._capture_normal()

    def _fallback_pull(self) -> np.ndarray | None:
        """降级到 pull 方式拉取截图"""
        import os, uuid
        fname = f"screenshot_{uuid.uuid4().hex[:8]}.png"
        local_path = os.path.join(self._temp_dir, fname)
        if self._adb.pull_screenshot(local_path):
            image = cv2.imread(local_path)
            try:
                os.remove(local_path)
            except Exception:
                pass
            return image
        return None

    def capture_to_bytes(self, format: str = ".jpg") -> bytes:
        """截图并编码为字节"""
        image = self.capture()
        success, buf = cv2.imencode(format, image, [cv2.IMWRITE_JPEG_QUALITY, self._quality])
        if not success:
            raise ScreenshotError("图片编码失败")
        return buf.tobytes()

    # ── 缓存管理 ──────────────────────────────────────────────

    def clear_cache(self) -> None:
        """清除截图缓存"""
        with self._lock:
            self._cached_image = None
            self._cached_time = 0.0

    def set_quality(self, quality: int) -> None:
        """设置 JPEG 压缩质量"""
        self._quality = max(1, min(100, quality))

    def set_resize_ratio(self, ratio: float) -> None:
        """设置缩放比例"""
        self._resize_ratio = max(0.1, min(2.0, ratio))
        self.clear_cache()

    @property
    def has_cache(self) -> bool:
        return self._cached_image is not None

    # ── 生命周期 ──────────────────────────────────────────────

    def close(self) -> None:
        """清理资源"""
        self.clear_cache()
