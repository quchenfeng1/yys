"""
OCR 定位工具

基于 RapidOCR 对参考图进行文字识别，
定位指定文字（如"进入游戏"）在屏幕上的位置，
并将结果保存为固定坐标配置。

无需复杂环境依赖，只依赖 rapidocr_onnxruntime。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "请安装 rapidocr_onnxruntime: pip install rapidocr-onnxruntime"
    ) from e

from core.logger import get_logger

logger = get_logger("core.ocr_locator")


class TextLocator:
    """文字定位器

    使用 RapidOCR 在图片中定位文字，返回文字区域中心点及外接矩形。
    """

    def __init__(self, engine: Optional[RapidOCR] = None):
        self.engine = engine or RapidOCR()

    def find_text(
        self,
        image: np.ndarray,
        target: str,
        min_confidence: float = 0.5,
    ) -> Optional[Tuple[int, int, int, int]]:
        """在图片中查找目标文字，返回其外接矩形 (x, y, w, h)

        Args:
            image: BGR 图像 (OpenCV 格式)
            target: 目标文字，如 "进入游戏"
            min_confidence: 最小置信度

        Returns:
            (x, y, w, h) 若找到；否则 None
        """
        results, _ = self.engine(image)
        if not results:
            return None

        # 选择置信度最高且匹配目标的区域
        best_match = None
        best_score = -1.0

        for line in results:
            box, text, score = line[0], line[1], float(line[2])
            if score < min_confidence:
                continue
            if target in text or text in target:
                # 计算外接矩形
                xs = [int(p[0]) for p in box]
                ys = [int(p[1]) for p in box]
                x, y = min(xs), min(ys)
                w, h = max(xs) - x, max(ys) - y
                if score > best_score:
                    best_score = score
                    best_match = (x, y, w, h)
                    logger.debug(
                        f"OCR 候选: text={text}, score={score:.3f}, box={best_match}"
                    )

        if best_match:
            logger.info(
                f"OCR 定位 '{target}' 成功: box={best_match}, score={best_score:.3f}"
            )
            return best_match

        logger.warning(f"OCR 未找到文字: {target}")
        return None

    def find_text_center(
        self,
        image: np.ndarray,
        target: str,
        min_confidence: float = 0.5,
    ) -> Optional[Tuple[int, int]]:
        """查找文字中心点坐标"""
        box = self.find_text(image, target, min_confidence)
        if box is None:
            return None
        x, y, w, h = box
        return (x + w // 2, y + h // 2)


def load_image(image_path: Path | str) -> np.ndarray:
    """加载图片为 OpenCV BGR 格式

    兼容中文路径。
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"图片不存在: {image_path}")

    # PIL 可以读取中文路径，再转成 BGR
    pil_img = Image.open(image_path)
    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    return img


def locate_reference_region(
    reference_image: Path | str,
    target_text: str = "进入游戏",
    min_confidence: float = 0.5,
) -> Optional[Tuple[int, int, int, int]]:
    """从参考图中定位文字区域

    Returns:
        (x, y, w, h) 或 None
    """
    img = load_image(reference_image)
    locator = TextLocator()
    return locator.find_text(img, target_text, min_confidence)
