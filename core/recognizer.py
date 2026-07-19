"""
图像识别模块

职责：在截图中定位目标图片，返回匹配位置与置信度。
- 主用模板匹配（cv2.matchTemplate + TM_CCOEFF_NORMED）
- 灰度匹配（默认转灰度，提升速度）
- 区域限定（支持 region 参数限定搜索范围）
- 素材缓存（启动时扫描 assets/ 全部 PNG，按相对路径建立索引）

素材索引规则：
    扫描 assets/ 下所有 .png 文件，按相对路径（去掉扩展名）建立索引。
    支持多层目录，索引名用 "/" 分隔。例如：
      assets/common/battle/challenge_btn.png  ->  "common/battle/challenge_btn"
      assets/scenes/login/enter_game.png     ->  "scenes/login/enter_game"
      assets/tasks/permanent/yuhun/entry.png ->  "tasks/permanent/yuhun/entry"
"""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List

import cv2
import numpy as np
from PIL import Image

from core.logger import get_logger
from core.exceptions import RecognizeError

logger = get_logger("core.recognizer")

PROJECT_ROOT = Path(__file__).parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"


def _imread_unicode(path: Path) -> Optional[np.ndarray]:
    """读取图片（兼容中文路径）

    cv2.imread 不支持中文路径，改用 PIL 读取后转 BGR。
    """
    try:
        pil_img = Image.open(path)
        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")
        img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        return img
    except Exception as e:
        logger.warning(f"图片读取失败: {path} ({e})")
        return None


@dataclass
class MatchResult:
    """匹配结果"""
    name: str               # 模板名
    center: tuple           # 中心坐标 (x, y)
    topleft: tuple          # 左上角坐标 (x, y)
    size: tuple             # 匹配区域大小 (w, h)
    confidence: float       # 置信度 0~1


class Recognizer:
    """图像识别器，基于 OpenCV 模板匹配"""

    def __init__(self, screenshot_func, threshold: float = 0.8, grayscale: bool = True):
        """
        Args:
            screenshot_func: 截图函数，调用返回 OpenCV BGR 图像
            threshold: 默认匹配阈值
            grayscale: 是否灰度匹配
        """
        self._screenshot_func = screenshot_func
        self.threshold = threshold
        self.grayscale = grayscale
        self._templates = {}    # 素材缓存: {name: (gray_img, w, h)}

        self._load_templates()

    def _load_templates(self):
        """扫描 assets/ 目录，加载所有 PNG 素材到内存缓存

        素材按相对路径建立索引，如 "common/battle/challenge_btn"。
        支持多层目录结构（common/scenes/tasks/teams 四层分类）。
        """
        self._templates.clear()
        count = 0

        if not ASSETS_DIR.exists():
            logger.warning(f"素材目录不存在: {ASSETS_DIR}")
            return

        for root, dirs, files in os.walk(ASSETS_DIR):
            for f in files:
                if not f.lower().endswith(".png"):
                    continue

                filepath = Path(root) / f
                # 计算索引名: 相对于 assets/ 的路径，去掉 .png，统一用 /
                rel_path = filepath.relative_to(ASSETS_DIR)
                name = str(rel_path.with_suffix("")).replace("\\", "/")

                # 加载图片（兼容中文路径）
                img = _imread_unicode(filepath)
                if img is None:
                    continue

                if self.grayscale:
                    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                else:
                    img_gray = img

                h, w = img_gray.shape[:2]
                self._templates[name] = (img_gray, w, h)
                count += 1

        logger.info(f"素材加载完成: {count} 张模板")

    def reload(self):
        """重新加载素材（素材更新后调用）"""
        logger.info("重新加载素材...")
        self._load_templates()

    def list_templates(self) -> list:
        """列出所有已加载的素材名"""
        return list(self._templates.keys())

    def has_template(self, template_name: str) -> bool:
        """检查素材是否存在"""
        return template_name in self._templates

    def _get_template(self, template_name: str):
        """获取模板图片"""
        if template_name not in self._templates:
            raise RecognizeError(f"素材未找到: {template_name}")
        return self._templates[template_name]

    def _take_screenshot(self) -> np.ndarray:
        """截图"""
        img = self._screenshot_func()
        if img is None:
            raise RecognizeError("截图失败，无法进行识别")
        return img

    def find(self, template_name: str, region: tuple = None,
             threshold: float = None) -> Optional[MatchResult]:
        """在截图中查找目标图片，返回第一个匹配结果

        Args:
            template_name: 模板名，如 "scenes/login/splash_skip"
            region: 限定搜索区域 (x, y, w, h)，None 表示全屏搜索
            threshold: 匹配阈值，None 使用默认值

        Returns:
            MatchResult 或 None（未找到）
        """
        thresh = threshold if threshold is not None else self.threshold
        template_gray, tw, th = self._get_template(template_name)

        # 截图
        screen = self._take_screenshot()

        # 灰度转换
        if self.grayscale:
            screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        else:
            screen_gray = screen

        # 区域裁剪
        if region:
            x, y, w, h = region
            screen_gray = screen_gray[y:y+h, x:x+w]
        else:
            x, y = 0, 0

        # 模板匹配
        result = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        if max_val >= thresh:
            # 匹配成功
            topleft = (max_loc[0] + x, max_loc[1] + y)
            center = (topleft[0] + tw // 2, topleft[1] + th // 2)
            return MatchResult(
                name=template_name,
                center=center,
                topleft=topleft,
                size=(tw, th),
                confidence=max_val
            )

        return None

    def find_all(self, template_name: str, region: tuple = None,
                 threshold: float = None) -> List[MatchResult]:
        """查找所有匹配结果

        Args:
            template_name: 模板名
            region: 限定搜索区域
            threshold: 匹配阈值

        Returns:
            匹配结果列表
        """
        thresh = threshold if threshold is not None else self.threshold
        template_gray, tw, th = self._get_template(template_name)

        screen = self._take_screenshot()
        if self.grayscale:
            screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        else:
            screen_gray = screen

        if region:
            x, y, w, h = region
            screen_gray = screen_gray[y:y+h, x:x+w]
        else:
            x, y = 0, 0

        result = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)

        # 找出所有超过阈值的位置
        locations = np.where(result >= thresh)
        matches = []

        for pt in zip(*locations[::-1]):
            topleft = (pt[0] + x, pt[1] + y)
            center = (topleft[0] + tw // 2, topleft[1] + th // 2)
            confidence = result[pt[1], pt[0]]
            matches.append(MatchResult(
                name=template_name,
                center=center,
                topleft=topleft,
                size=(tw, th),
                confidence=float(confidence)
            ))

        return matches

    def exists(self, template_name: str, threshold: float = None) -> bool:
        """检查目标图片是否存在于当前画面

        Args:
            template_name: 模板名
            threshold: 匹配阈值

        Returns:
            True/False
        """
        return self.find(template_name, threshold=threshold) is not None

    def wait(self, template_name: str, timeout: float = 10,
             interval: float = 0.5) -> Optional[MatchResult]:
        """等待目标图片出现

        Args:
            template_name: 模板名
            timeout: 超时时间（秒）
            interval: 检查间隔（秒）

        Returns:
            MatchResult 或 None（超时未找到）
        """
        import time
        start = time.time()
        while time.time() - start < timeout:
            result = self.find(template_name)
            if result:
                logger.debug(f"等待到 {template_name} (置信度={result.confidence:.3f})")
                return result
            time.sleep(interval)

        logger.debug(f"等待 {template_name} 超时 ({timeout}s)")
        return None

    def wait_any(self, template_names: list, timeout: float = 10,
                 interval: float = 0.5) -> Optional[tuple]:
        """等待多个目标图片中的任意一个出现

        Args:
            template_names: 模板名列表
            timeout: 超时时间
            interval: 检查间隔

        Returns:
            (template_name, MatchResult) 或 None（超时）
        """
        import time
        start = time.time()
        while time.time() - start < timeout:
            for name in template_names:
                result = self.find(name)
                if result:
                    logger.debug(f"等待到 {name} (置信度={result.confidence:.3f})")
                    return (name, result)
            time.sleep(interval)

        logger.debug(f"等待 {template_names} 超时 ({timeout}s)")
        return None
