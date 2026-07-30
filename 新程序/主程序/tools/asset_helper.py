"""
开发辅助工具：素材辅助工具。

用于截取游戏屏幕并快速裁剪为模板图片。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np


class AssetHelper:
    """素材辅助工具"""

    @staticmethod
    def crop_template(
        image: np.ndarray,
        x: int, y: int, w: int, h: int,
        output_path: str,
    ) -> bool:
        """从截图中裁剪出模板图片"""
        try:
            crop = image[y : y + h, x : x + w]
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(path), crop)
            return True
        except Exception:
            return False

    @staticmethod
    def resize_template(
        input_path: str,
        output_path: str,
        scale: float = 1.0,
        width: int | None = None,
        height: int | None = None,
    ) -> bool:
        """调整模板图片大小"""
        try:
            img = cv2.imread(input_path)
            if img is None:
                return False

            if width and height:
                dim = (width, height)
            else:
                h, w = img.shape[:2]
                dim = (int(w * scale), int(h * scale))

            resized = cv2.resize(img, dim, interpolation=cv2.INTER_AREA)
            cv2.imwrite(output_path, resized)
            return True
        except Exception:
            return False

    @staticmethod
    def batch_rename(directory: str, prefix: str = "", suffix: str = "") -> int:
        """批量重命名素材文件"""
        count = 0
        path = Path(directory)
        for f in path.glob("*.png"):
            new_name = f"{prefix}{f.stem}{suffix}{f.suffix}"
            f.rename(f.parent / new_name)
            count += 1
        return count

    @staticmethod
    def check_template_quality(image_path: str) -> dict[str, Any]:
        """检查模板图片质量"""
        img = cv2.imread(image_path)
        if img is None:
            return {"valid": False, "error": "无法读取图片"}

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        edges = cv2.Canny(gray, 50, 150)

        return {
            "valid": True,
            "width": w,
            "height": h,
            "channels": img.shape[2] if len(img.shape) == 3 else 1,
            "edge_ratio": float(np.count_nonzero(edges)) / (w * h),
            "mean_brightness": float(np.mean(gray)),
        }
