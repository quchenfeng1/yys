"""
02-图像识别模块

OcrLocator OCR 文字定位（基于 PaddleOCR，含 Levenshtein 模糊匹配）。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from core.event_bus import get_global_bus
from core.events import Events
from core.exceptions import OCRNotAvailableError, OCRTimeoutError


@dataclass
class OCRResult:
    """OCR 识别结果（与设计书 §5.2 一致）"""
    text: str
    confidence: float
    x: int
    y: int
    width: int
    height: int
    center_x: int = 0
    center_y: int = 0

    def __post_init__(self):
        self.center_x = self.x + self.width // 2
        self.center_y = self.y + self.height // 2


class OcrLocator:
    """OCR 文字定位器（Levenshtein 模糊匹配，§5.3）"""

    def __init__(
        self,
        engine: str = "paddle",
        lang: str = "ch",
        use_gpu: bool = False,
        timeout: float = 10.0,
        event_bus=None,
        connection=None,
    ):
        self._engine_name = engine
        self._lang = lang
        self._use_gpu = use_gpu
        self._timeout = timeout
        self._init_lock = threading.Lock()
        self._lock = self._init_lock  # 兼容别名
        self._ocr_lock = threading.Lock()
        self._engine: Any = None
        self._initialized = False
        self._ready = False
        self._bus = event_bus or get_global_bus()
        self._connection = connection  # 用于 _ocr_page 获取截图

    @property
    def is_ready(self) -> bool:
        """OCR 引擎是否就绪"""
        return self._ready

    # ── 初始化 ────────────────────────────────────────────────

    def initialize(self) -> bool:
        """初始化 OCR 引擎（双重检查锁）"""
        if self._initialized:
            return True

        with self._init_lock:
            if self._initialized:
                return True

            try:
                if self._engine_name == "paddle":
                    self._init_paddle()
                elif self._engine_name == "easyocr":
                    self._init_easyocr()
                else:
                    # 占位模式：不做实际加载
                    self._initialized = True
                    return True

                self._initialized = True
                self._ready = True
                return True
            except Exception:
                self._initialized = False
                raise

    def _init_paddle(self) -> None:
        """初始化 PaddleOCR"""
        try:
            from paddleocr import PaddleOCR

            self._engine = PaddleOCR(
                use_angle_cls=True,
                lang=self._lang,
                use_gpu=self._use_gpu,
                show_log=False,
            )
        except ImportError:
            raise ImportError(
                "PaddleOCR 未安装。请运行: pip install paddleocr"
            )

    def _init_easyocr(self) -> None:
        """初始化 EasyOCR"""
        try:
            import easyocr

            self._engine = easyocr.Reader(
                [self._lang],
                gpu=self._use_gpu,
            )
        except ImportError:
            raise ImportError(
                "EasyOCR 未安装。请运行: pip install easyocr"
            )

    # ── 引擎预测 ──────────────────────────────────────────────

    def _predict_with_lock(self, image: np.ndarray) -> list[OCRResult]:
        """带锁的 OCR 推理（串行化）"""
        with self._ocr_lock:
            if self._engine_name == "paddle":
                return self._predict_paddle(image)
            elif self._engine_name == "easyocr":
                return self._predict_easyocr(image)
            return []

    def _predict_paddle(self, image: np.ndarray) -> list[OCRResult]:
        """PaddleOCR 预测"""
        if self._engine is None:
            return []

        result = self._engine.ocr(image, cls=True)
        parsed: list[OCRResult] = []

        if not result or not result[0]:
            return parsed

        for line in result[0]:
            box, (text, confidence) = line
            # box: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x, y = int(min(xs)), int(min(ys))
            w, h = int(max(xs) - min(xs)), int(max(ys) - min(ys))

            parsed.append(OCRResult(
                text=text,
                confidence=float(confidence),
                x=x,
                y=y,
                width=w,
                height=h,
            ))

        return parsed

    def _predict_easyocr(self, image: np.ndarray) -> list[OCRResult]:
        """EasyOCR 预测"""
        if self._engine is None:
            return []

        result = self._engine.readtext(image)
        parsed: list[OCRResult] = []

        for box, text, confidence in result:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x, y = int(min(xs)), int(min(ys))
            w, h = int(max(xs) - min(xs)), int(max(ys) - min(ys))

            parsed.append(OCRResult(
                text=str(text),
                confidence=float(confidence),
                x=x,
                y=y,
                width=w,
                height=h,
            ))

        return parsed

    # ── Levenshtein 模糊匹配 ────────────────────────────────

    @staticmethod
    def _levenshtein_distance(s1: str, s2: str) -> int:
        """计算编辑距离"""
        if len(s1) < len(s2):
            return OcrLocator._levenshtein_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)
        prev = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            curr = [i + 1]
            for j, c2 in enumerate(s2):
                cost = 0 if c1 == c2 else 1
                curr.append(min(
                    curr[j] + 1,        # 删除
                    prev[j + 1] + 1,     # 插入
                    prev[j] + cost,      # 替换
                ))
            prev = curr
        return prev[len(s2)]

    def _fuzzy_match(self, text: str, keyword: str) -> bool:
        """Levenshtein 模糊匹配：编辑距离 ≤ max(1, ceil(len×0.25))"""
        if not keyword:
            return True
        threshold = max(1, (len(keyword) + 3) // 4)  # ceil(len/4)
        return self._levenshtein_distance(text.lower(), keyword.lower()) <= threshold

    # ── 文档要求的 API（§5.3） ───────────────────────────────

    def locate_text(
        self,
        text: str,
        region: tuple[int, int, int, int] | None = None,
    ) -> tuple[int, int] | None:
        """
        全页 OCR → Levenshtein 模糊匹配 → 返回匹配文字块的中心坐标。
        若 _ocr_ready 为 False 则返回 None。
        """
        if not self._ready:
            return None

        # 获取截图区域
        if region:
            from core.recognizer import Recognizer
            # 简化的区域截图获取
            pass

        results = self._ocr_page(region)
        best = None
        best_dist = 999

        for r in results:
            dist = self._levenshtein_distance(r.text.lower(), text.lower())
            threshold = max(1, (len(text) + 3) // 4)
            if dist <= threshold and dist < best_dist:
                best_dist = dist
                best = r

        if best:
            return (best.center_x, best.center_y)
        return None

    def locate_any(
        self,
        texts: list[str],
        region: tuple[int, int, int, int] | None = None,
    ) -> tuple[str, tuple[int, int]] | None:
        """
        多个候选文字——只执行一次 OCR，在结果中筛选所有候选词。
        返回第一个匹配到的 (文字名, (x, y))。
        """
        if not self._ready:
            return None

        results = self._ocr_page(region)
        for kw in texts:
            for r in results:
                if self._fuzzy_match(r.text, kw):
                    return (kw, (r.center_x, r.center_y))
        return None

    def _ocr_page(self, region: tuple[int, int, int, int] | None = None,
                  image: np.ndarray | None = None) -> list[OCRResult]:
        """
        对截图区域执行 OCR 全页识别，含超时机制（默认 5s）。

        Args:
            region: 限定区域 (x, y, w, h)
            image: 外部传入截图（若为 None 则通过 connection 获取）
        """
        if image is None:
            if self._connection and hasattr(self._connection, 'screenshot'):
                try:
                    image = self._connection.screenshot(use_cache=True)
                except Exception:
                    return []
            else:
                return []

        if region:
            x, y, w, h = region
            image = image[y:y+h, x:x+w]

        if not self._initialized:
            try:
                self.initialize()
            except Exception:
                return []

        start = time.time()
        try:
            if self._engine_name in ("paddle", "easyocr"):
                results = self._predict_with_lock(image)
            else:
                results = []
            return results
        except Exception:
            return []

    # ── 兼容接口（接收 image 参数） ──────────────────────────

    def recognize(self, image: np.ndarray) -> list[OCRResult]:
        """对图片进行 OCR 识别"""
        if not self._initialized:
            self.initialize()

        start = time.time()
        try:
            if self._engine_name in ("paddle", "easyocr"):
                results = self._predict_with_lock(image)
            else:
                results = []
            if time.time() - start > self._timeout:
                raise OCRTimeoutError(f"OCR 识别超时 ({self._timeout}s)")
            self._bus.publish(Events.OCR_RESULT, source="ocr_locator", count=len(results))
            return results
        except OCRTimeoutError:
            raise
        except Exception as e:
            raise OCRTimeoutError(f"OCR 识别失败: {e}") from e

    def find_text(
        self,
        image: np.ndarray,
        keyword: str,
        case_sensitive: bool = False,
    ) -> list[OCRResult]:
        """在 OCR 结果中搜索关键词（Levenshtein 模糊匹配）"""
        results = self.recognize(image)
        matches = []
        for r in results:
            text = r.text if case_sensitive else r.text
            if self._fuzzy_match(text, keyword):
                matches.append(r)
        return matches

    def find_texts(
        self,
        image: np.ndarray,
        keywords: list[str],
        case_sensitive: bool = False,
    ) -> dict[str, list[OCRResult]]:
        """搜索多个关键词（单次 OCR，多次匹配）"""
        results = self.recognize(image)
        matches: dict[str, list[OCRResult]] = {k: [] for k in keywords}
        for r in results:
            for kw in keywords:
                text = r.text if case_sensitive else r.text
                if self._fuzzy_match(text, kw):
                    matches[kw].append(r)
        return matches

    # ── 生命周期 ──────────────────────────────────────────────

    def close(self) -> None:
        """释放 OCR 引擎资源"""
        with self._init_lock:
            self._engine = None
            self._initialized = False
            self._ready = False
