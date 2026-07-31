"""
02-图像识别模块

Recognizer 主入口（素材缓存+截图缓存+模板匹配+多尺度+元数据驱动）。
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from core.event_bus import EventBus, get_global_bus
from core.events import Events
from core.exceptions import (
    AssetNotFoundError, AssetMissingError, AssetCorruptedError,
    MatchNotFoundError, RecognitionError, RecognitionTimeoutError,
    TemplateNotFoundError, OCRNotAvailableError,
)
from core.image_manager import ImageManager


class MatchMode(str, Enum):
    """识别模式枚举（§5.3）"""
    AUTO = "auto"              # 模板优先，按元数据决定是否回退 OCR
    TEMPLATE_ONLY = "template"  # 仅模板匹配
    OCR_ONLY = "ocr"            # 仅 OCR 文字定位


@dataclass
class MatchResult:
    """匹配结果（与设计书 §5.2 一致）"""
    template_name: str
    confidence: float
    x: int
    y: int
    width: int
    height: int
    center_x: int = 0
    center_y: int = 0
    scale: float = 1.0
    method: str = "template"  # template | ocr | hybrid

    def __post_init__(self):
        self.center_x = self.x + self.width // 2
        self.center_y = self.y + self.height // 2


class Recognizer:
    """图像识别引擎"""

    def __init__(
        self,
        image_manager: ImageManager | None = None,
        event_bus: EventBus | None = None,
        ocr_locator: Any = None,
        connection: Any = None,     # ConnectionManager
        config: Any = None,         # ConfigManager
        monitor: Any = None,        # Monitor
        threshold: float = 0.8,
        screenshot_ttl: float = 0.2,
        result_cache_ttl: float = 1.0,
        asset_dir: str = "assets",
    ):
        self._img_mgr = image_manager or ImageManager()
        self._event_bus = event_bus or get_global_bus()
        self._bus = self._event_bus  # 兼容别名
        self._ocr = ocr_locator
        self._connection = connection
        self._config = config
        self._monitor = monitor
        self._lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._threshold = threshold
        self._screenshot_ttl = screenshot_ttl
        self._result_cache_ttl = result_cache_ttl
        self._asset_dir = asset_dir

        # 素材元数据 _meta.json
        self._meta: dict[str, dict] = {}

        # 截图缓存
        self._screenshot_cache: np.ndarray | None = None
        self._last_frame_time: float = 0.0

        # 素材缓存 {name: np.ndarray}（BGR 彩色图，匹配时动态转灰度）
        self._asset_cache: dict[str, np.ndarray] = {}

        # 结果缓存 {template_name: (match_result, timestamp)}
        self._result_cache: dict[str, tuple[Any, float]] = {}

        # 性能记录（deque 线程安全）
        self._latency_records: deque[float] = deque(maxlen=200)

        # 启动时加载素材
        self._load_templates()
        self._load_meta()

    # ── 配置 ──────────────────────────────────────────────────

    @property
    def threshold(self) -> float:
        return self._threshold

    @threshold.setter
    def threshold(self, value: float) -> None:
        self._threshold = max(0.0, min(1.0, value))

    # ── 素材加载（§3.3） ─────────────────────────────────────

    @staticmethod
    def _imread_unicode(path: str) -> np.ndarray | None:
        """支持中文路径的 cv2.imread 替代方案（§5.5）"""
        try:
            return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            return None

    def _load_templates(self) -> None:
        """递归扫描 assets/，以 BGR 彩色图加载全部素材到 _asset_cache"""
        asset_path = Path(self._asset_dir)
        if not asset_path.exists():
            return

        count = 0
        for f in sorted(asset_path.rglob("*.png")):
            rel = str(f.relative_to(asset_path).with_suffix(""))
            # 替换路径分隔符为 /
            rel = rel.replace("\\", "/")
            img = self._imread_unicode(str(f))
            if img is None:
                print(f"警告: 素材加载失败: {f}")
                continue
            if img.size == 0:
                print(f"警告: 素材为空: {f}")
                continue
            self._asset_cache[rel] = img
            count += 1

        if count == 0:
            import logging
            logging.error("警告: assets/ 目录为空，所有识别将返回 None")
        else:
            import logging
            logging.info(f"已加载 {count} 个素材")

    def _load_meta(self) -> None:
        """加载 _meta.json 素材元数据"""
        meta_path = Path(self._asset_dir) / "_meta.json"
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    self._meta = json.load(f)
            except Exception:
                self._meta = {}

    # ── 截图管理 ──────────────────────────────────────────────

    def _get_screenshot(self) -> np.ndarray:
        """
        获取截图（缓存机制）。
        - 缓存有效（_last_frame_time 在 TTL 内）→ 直接返回缓存
        - 缓存过期 → 调 _connection.screenshot() 获取新截图
        """
        with self._cache_lock:
            now = time.time()
            if self._screenshot_cache is not None and (now - self._last_frame_time) < self._screenshot_ttl:
                return self._screenshot_cache

        # 缓存过期或无 connection，调外部 screenshot
        if self._connection:
            try:
                img = self._connection.screenshot(use_cache=True)
                with self._cache_lock:
                    self._screenshot_cache = img
                    self._last_frame_time = time.time()
                return img
            except Exception as e:
                raise RecognitionError(f"截图无效: {e}") from e
        raise RecognitionError("无可用截图来源")

    def update_screenshot(self, image: np.ndarray) -> None:
        """外部注入截图（测试/离线模式用）"""
        with self._cache_lock:
            self._screenshot_cache = image
            self._last_frame_time = time.time()

    # ── 模板管理 ──────────────────────────────────────────────

    def _get_template(self, name: str) -> np.ndarray:
        """从 _asset_cache 获取模板 BGR 图，匹配时动态转灰度"""
        if name not in self._asset_cache:
            raise AssetNotFoundError(f"素材不存在: {name}")
        return self._asset_cache[name]

    def preload_templates(self, names: list[str]) -> dict[str, bool]:
        """预加载多个模板"""
        results = {}
        for name in names:
            if name in self._asset_cache:
                results[name] = True
            else:
                results[name] = False
        return results

    def clear_template_cache(self, name: str | None = None) -> None:
        """清除模板缓存"""
        if name:
            self._asset_cache.pop(name, None)
        else:
            self._asset_cache.clear()

    # ── 匹配（含多尺度 + 缓存 + 耗时记录） ────────────────────

    def find_one(
        self,
        template_name: str,
        screenshot: np.ndarray | None = None,
        threshold: float | None = None,
        region: tuple[int, int, int, int] | None = None,
    ) -> MatchResult:
        """单目标匹配（含多尺度 0.8~1.2 + 结果缓存）"""
        start = time.time()

        # 1. 校验模板存在
        if template_name not in self._asset_cache:
            raise AssetNotFoundError(f"素材不存在: {template_name}")

        # 2. 结果缓存
        cached = self._get_cached_result(template_name)
        if cached is not None:
            return cached

        # 3. 获取截图
        if screenshot is None:
            screen = self._get_screenshot()
        else:
            screen = screenshot

        # 4. 灰度化
        if len(screen.shape) == 3:
            screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        else:
            screen_gray = screen

        if region:
            x, y, w, h = region
            screen_gray = screen_gray[y:y+h, x:x+w]

        tpl_bgr = self._asset_cache[template_name]
        tpl_gray = cv2.cvtColor(tpl_bgr, cv2.COLOR_BGR2GRAY)

        # 5. 检查尺寸
        th, tw = tpl_gray.shape[:2]
        sh, sw = screen_gray.shape[:2]
        if th > sh or tw > sw:
            raise RecognitionError(f"模板({tw}x{th})大于截图({sw}x{sh})")

        thresh = threshold if threshold is not None else self._threshold

        # 6. 多尺度匹配（0.8~1.2，步长 0.05）
        best_val = -1.0
        best_loc = (0, 0)
        best_scale = 1.0
        best_tpl = tpl_gray

        scales = [i * 0.05 + 0.8 for i in range(9)]  # [0.8, 0.85, ..., 1.2]
        for scale in scales:
            if scale == 1.0:
                resized = tpl_gray
            else:
                new_w = int(tw * scale)
                new_h = int(th * scale)
                if new_w > sw or new_h > sh:
                    continue
                resized = cv2.resize(tpl_gray, (new_w, new_h), interpolation=cv2.INTER_AREA)

            result = cv2.matchTemplate(screen_gray, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val > best_val:
                best_val = max_val
                best_loc = max_loc
                best_scale = scale
                best_tpl = resized

        if best_val < thresh:
            self._bus.publish(Events.IMAGE_MATCH_NOT_FOUND, source="recognizer",
                             template=template_name, confidence=float(best_val))
            raise MatchNotFoundError(
                f"未找到匹配: {template_name} (最佳置信度: {best_val:.3f} < {thresh:.3f})"
            )

        h, w = best_tpl.shape[:2]
        match = MatchResult(
            template_name=template_name,
            confidence=float(best_val),
            x=int(best_loc[0]),
            y=int(best_loc[1]),
            width=w,
            height=h,
            scale=best_scale,
        )

        # 7. 写入缓存 + 记录耗时
        self._set_cached_result(template_name, match)
        elapsed = (time.time() - start) * 1000
        self._latency_records.append(elapsed)

        self._bus.publish(Events.IMAGE_MATCH_FOUND, source="recognizer",
                         template=template_name, confidence=match.confidence)
        return match

    def find_all(
        self,
        template_name: str,
        screenshot: np.ndarray | None = None,
        threshold: float | None = None,
        max_results: int = 10,
    ) -> list[MatchResult]:
        """多目标匹配，返回所有高于阈值的结果"""
        if template_name not in self._asset_cache:
            return []
        screen = self._get_screenshot() if screenshot is None else screenshot
        thresh = threshold if threshold is not None else self._threshold

        tpl_bgr = self._asset_cache[template_name]
        tpl = cv2.cvtColor(tpl_bgr, cv2.COLOR_BGR2GRAY)
        if len(screen.shape) == 3:
            screen = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)

        result = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
        h, w = tpl.shape[:2]

        locations = np.where(result >= thresh)
        matches: list[MatchResult] = []
        points = list(zip(*locations[::-1]))
        used = set()

        for pt in points:
            key = (pt[0] // 10, pt[1] // 10)
            if key in used:
                continue
            used.add(key)
            matches.append(MatchResult(
                template_name=template_name,
                confidence=float(result[pt[1], pt[0]]),
                x=int(pt[0]),
                y=int(pt[1]),
                width=w,
                height=h,
            ))
            if len(matches) >= max_results:
                break

        return matches

    def find_best(
        self,
        template_names: list[str],
        screenshot: np.ndarray | None = None,
        threshold: float | None = None,
    ) -> tuple[str, MatchResult] | None:
        """从多个模板中找出最佳匹配"""
        best: tuple[str, MatchResult] | None = None
        best_conf = -1.0
        for name in template_names:
            try:
                match = self.find_one(name, screenshot, threshold)
                if match.confidence > best_conf:
                    best_conf = match.confidence
                    best = (name, match)
            except MatchNotFoundError:
                continue
        return best

    def multi_match(
        self,
        templates: dict[str, float | None],
        screenshot: np.ndarray | None = None,
    ) -> dict[str, MatchResult | None]:
        """批量匹配"""
        results: dict[str, MatchResult | None] = {}
        for name, thresh in templates.items():
            try:
                results[name] = self.find_one(name, screenshot, thresh)
            except MatchNotFoundError:
                results[name] = None
        return results

    # ── 文档要求的 API（§5.3） ───────────────────────────────

    def find(
        self,
        name: str,
        region: tuple[int, int, int, int] | None = None,
        threshold: float | None = None,
        mode: str | MatchMode = MatchMode.AUTO,
    ) -> MatchResult | None:
        """
        统一的 find 入口（支持 MatchMode 枚举，§5.3）。

        模式：
        - AUTO: 模板优先，置信度不足时按 _meta.json 决定是否回退 OCR
        - TEMPLATE_ONLY: 仅模板匹配
        - OCR_ONLY: 仅 OCR 文字定位
        - "smart": 根据 _meta.json 元数据自动选择
        """
        # 统一为字符串
        if isinstance(mode, MatchMode):
            mode = mode.value
        # 校验模板存在
        if name not in self._asset_cache:
            return None

        if mode in ("ocr_only", "ocr"):
            if self._ocr and self._ocr.is_ready:
                screen = self._get_screenshot()
                if region:
                    x, y, w, h = region
                    screen = screen[y:y+h, x:x+w]
                ocr_results = self._ocr.find_text(screen, name)
                if ocr_results:
                    best = max(ocr_results, key=lambda r: r.confidence)
                    match = MatchResult(
                        template_name=name,
                        confidence=best.confidence,
                        x=best.x + (region[0] if region else 0),
                        y=best.y + (region[1] if region else 0),
                        width=best.width,
                        height=best.height,
                        method="ocr",
                    )
                    self._set_cached_result(name, match)
                    return match
            return None

        if mode == "smart":
            meta = self._meta.get(name, {})
            if meta.get("fallback_to_ocr"):
                mode = MatchMode.AUTO.value
            else:
                mode = MatchMode.TEMPLATE_ONLY.value

        try:
            return self.find_one(name, threshold=threshold, region=region)
        except MatchNotFoundError:
            if mode == "auto" and self._ocr and self._ocr.is_ready:
                meta = self._meta.get(name, {})
                if meta.get("fallback_to_ocr", False):
                    screen = self._get_screenshot()
                    if region:
                        x, y, w, h = region
                        screen = screen[y:y+h, x:x+w]
                    ocr_results = self._ocr.find_text(screen, name)
                    if ocr_results:
                        best = max(ocr_results, key=lambda r: r.confidence)
                        match = MatchResult(
                            template_name=name,
                            confidence=best.confidence,
                            x=best.x + (region[0] if region else 0),
                            y=best.y + (region[1] if region else 0),
                            width=best.width,
                            height=best.height,
                            method="ocr",
                        )
                        self._set_cached_result(name, match)
                        return match
            return None

    def exists(self, name: str, threshold: float | None = None) -> bool:
        """判断目标是否存在（内部调 find，不抛异常）"""
        try:
            return self.find(name, threshold=threshold) is not None
        except Exception:
            return False

    def wait(
        self,
        name: str,
        timeout: float = 30.0,
        interval: float = 0.5,
        stop_event: threading.Event | None = None,
    ) -> Any | None:
        """
        等待模板出现。自适应退避策略：
        - 前 5 秒高频轮询（interval）
        - 之后降频至 min(interval*4, 2.0)s
        - 临近超时恢复高频
        stop_event 设置后立即返回 None。
        """
        if name not in self._asset_cache:
            return None

        start = time.time()
        while True:
            if stop_event and stop_event.is_set():
                return None
            try:
                return self.find_one(name)
            except MatchNotFoundError:
                elapsed = time.time() - start
                if elapsed >= timeout:
                    return None
                # 自适应退避
                if elapsed < 5:
                    sleep_t = interval
                elif elapsed < timeout - 3:
                    sleep_t = min(interval * 4, 2.0)
                else:
                    sleep_t = interval
                time.sleep(sleep_t)

    def wait_any(
        self,
        names: list[str],
        timeout: float = 30.0,
        stop_event: threading.Event | None = None,
    ) -> tuple[str, Any] | None:
        """等待多个模板中任一出现，stop_event 可打断"""
        start = time.time()
        while time.time() - start < timeout:
            if stop_event and stop_event.is_set():
                return None
            for name in names:
                if name in self._asset_cache:
                    try:
                        match = self.find_one(name)
                        return (name, match)
                    except MatchNotFoundError:
                        continue
            elapsed = time.time() - start
            if elapsed < 5:
                sleep_t = 0.5
            elif elapsed < timeout - 3:
                sleep_t = 2.0
            else:
                sleep_t = 0.5
            time.sleep(max(0.1, sleep_t))
        return None

    def match_any(
        self,
        names: list[str],
        region: tuple[int, int, int, int] | None = None,
        threshold: float | None = None,
    ) -> list[tuple[str, MatchResult]]:
        """
        识别列表批量识别（立即版，§5.3 match_any）。

        对列表内所有模板匹配当前画面，返回命中集合 [(模板名, MatchResult), ...]。
        未命中返回空列表。供 TriggerWatcher 触发监控使用——一次调用判断
        \"屏幕上当前出现了识别列表中的哪些\"。

        - 复用 find_one 的缓存/多尺度机制，不抛异常（缺失素材/识别失败直接跳过）
        - 截图走 _get_screenshot（受 _cache_lock/_screenshot_ttl 保护）
        """
        results: list[tuple[str, MatchResult]] = []
        for name in names:
            if name not in self._asset_cache:
                continue
            try:
                match = self.find_one(name, threshold=threshold, region=region)
                results.append((name, match))
            except (MatchNotFoundError, AssetNotFoundError, RecognitionError):
                continue
            except Exception:
                continue
        return results

    def clear_cache(self) -> None:
        """清空截图缓存和结果缓存（由 14-执行器模块 在步骤边界调用）"""
        with self._cache_lock:
            self._result_cache.clear()
            self._screenshot_cache = None
            self._latency_records.clear()

    def reload(self) -> None:
        """重新加载素材（清空缓存后重新扫描）"""
        self._asset_cache.clear()
        self._result_cache.clear()
        self._screenshot_cache = None
        self._load_templates()
        self._load_meta()

    def get_region_screenshot(
        self, x: int, y: int, w: int, h: int
    ) -> np.ndarray:
        """获取截图的指定区域"""
        screen = self._get_screenshot()
        return screen[y : y + h, x : x + w]

    def get_template_size(self, name: str) -> tuple[int, int]:
        """获取模板尺寸"""
        if name not in self._asset_cache:
            raise AssetNotFoundError(f"素材不存在: {name}")
        tpl = self._asset_cache[name]
        h, w = tpl.shape[:2]
        return (w, h)

    def suggest_template(self, screenshot: np.ndarray) -> str | None:
        """将截图与已知模板遍历匹配，返回置信度最高的模板名"""
        best_name = None
        best_conf = -1.0
        for name in self._asset_cache:
            try:
                match = self.find_one(name, screenshot=screenshot)
                if match.confidence > best_conf:
                    best_conf = match.confidence
                    best_name = name
            except Exception:
                continue
        return best_name

    # ── 结果缓存 ──────────────────────────────────────────────

    def _get_cached_result(self, name: str) -> Any | None:
        with self._cache_lock:
            entry = self._result_cache.get(name)
            if entry and time.time() - entry[1] < self._result_cache_ttl:
                return entry[0]
        return None

    def _set_cached_result(self, name: str, result: Any) -> None:
        with self._cache_lock:
            self._result_cache[name] = (result, time.time())
