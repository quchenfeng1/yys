"""
截图模块

职责：封装截图逻辑，提供统一的截图接口。
当前通过 ADB 截图（后台模式），后续可扩展 mss 前台截图模式。
"""

import time
import numpy as np

from core.logger import get_logger

logger = get_logger("device.screenshot")


class Screenshot:
    """截图封装，支持 ADB 后台截图"""

    def __init__(self, adb_client):
        self.adb = adb_client

    def capture(self) -> np.ndarray:
        """截图，返回 OpenCV BGR 格式图像"""
        return self.adb.screenshot()

    def capture_region(self, region: tuple) -> np.ndarray:
        """截取指定区域

        Args:
            region: (x, y, w, h) 左上角坐标和宽高
        """
        img = self.capture()
        x, y, w, h = region
        return img[y:y+h, x:x+w]

    def capture_and_save(self, filepath: str) -> bool:
        """截图并保存到文件"""
        import cv2
        img = self.capture()
        success = cv2.imwrite(filepath, img)
        if success:
            logger.debug(f"截图已保存: {filepath}")
        return success
