"""
操作执行模块

职责：封装所有用户操作（点击、滑动、按键），强制经过防封号引擎处理。
这是防封号的关键守门人——任务层禁止绕过此模块直接调用 ADB。

所有点击操作流程：
1. 识别图片（或使用给定坐标）
2. 防封号引擎计算随机偏移
3. 防封号引擎生成自然移动轨迹
4. 执行点击（带随机延迟）
5. 记录操作次数（防超限）
"""

import time
from typing import Optional

from core.logger import get_logger
from core.anti_detect import AntiDetect
from core.recognizer import Recognizer, MatchResult
from core.exceptions import RecognizeError

logger = get_logger("core.executor")


class Executor:
    """操作执行器，所有用户操作的统一入口"""

    def __init__(self, adb_client, recognizer: Recognizer, anti_detect: AntiDetect):
        """
        Args:
            adb_client: ADB 客户端
            recognizer: 图像识别器
            anti_detect: 防封号引擎
        """
        self.adb = adb_client
        self.recognizer = recognizer
        self.anti = anti_detect

    def click_image(self, template_name: str, region: tuple = None,
                    timeout: float = 10, threshold: float = None) -> bool:
        """识别图片并点击

        流程：识别图片 → 防封号计算偏移 → 执行点击 → 随机延迟

        Args:
            template_name: 模板名，如 "scenes/login/splash_skip"
            region: 限定搜索区域 (x, y, w, h)
            timeout: 等待图片出现的超时时间
            threshold: 匹配阈值

        Returns:
            True 表示成功识别并点击，False 表示未找到
        """
        # 防封号：检查运行限制
        self.anti.check_run_limit()

        # 识别图片
        if timeout > 0:
            result = self.recognizer.wait(template_name, timeout=timeout)
        else:
            result = self.recognizer.find(template_name, threshold=threshold)

        if result is None:
            logger.warning(f"点击失败：未找到图片 {template_name}")
            return False

        # 防封号：在中心点周围生成随机偏移
        click_x, click_y = self.anti.random_offset(result.center[0], result.center[1])

        logger.info(f"点击 {template_name} @ ({click_x},{click_y}) "
                    f"[原图中心={result.center}, 置信度={result.confidence:.3f}]")

        # 执行点击
        self.adb.click(click_x, click_y)

        # 防封号：随机延迟
        self.anti.sleep(base=0.8, jitter=0.5)

        # 防封号：记录操作
        self.anti.record_action()

        # 防封号：偶尔触发长暂停（模拟走神）
        self.anti.maybe_long_pause()

        return True

    def click_point(self, x: int, y: int):
        """直接坐标点击（仍经防封号偏移）

        Args:
            x, y: 目标坐标
        """
        self.anti.check_run_limit()

        # 防封号：随机偏移
        click_x, click_y = self.anti.random_offset(x, y)

        logger.info(f"点击坐标 ({click_x},{click_y}) [原坐标=({x},{y})]")

        self.adb.click(click_x, click_y)

        # 随机延迟
        self.anti.sleep(base=0.8, jitter=0.5)
        self.anti.record_action()
        self.anti.maybe_long_pause()

    def click_if_exists(self, template_name: str, threshold: float = None) -> bool:
        """存在则点击，不存在则跳过（不等待）

        Args:
            template_name: 模板名
            threshold: 匹配阈值

        Returns:
            True 表示存在并点击了，False 表示不存在
        """
        result = self.recognizer.find(template_name, threshold=threshold)
        if result is None:
            return False

        # 防封号处理
        self.anti.check_run_limit()
        click_x, click_y = self.anti.random_offset(result.center[0], result.center[1])

        logger.info(f"条件点击 {template_name} @ ({click_x},{click_y}) "
                    f"[置信度={result.confidence:.3f}]")

        self.adb.click(click_x, click_y)
        self.anti.sleep(base=0.8, jitter=0.5)
        self.anti.record_action()

        return True

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = None):
        """滑动（duration 随机化）

        Args:
            x1, y1: 起点
            x2, y2: 终点
            duration: 滑动时长（毫秒），None 则随机生成
        """
        self.anti.check_run_limit()

        if duration is None:
            duration = self.anti.random_swipe_duration()

        # 防封号：起止点也加随机偏移
        sx, sy = self.anti.random_offset(x1, y1, radius=5)
        ex, ey = self.anti.random_offset(x2, y2, radius=5)

        logger.info(f"滑动 ({sx},{sy}) -> ({ex},{ey}) dur={duration}ms")

        self.adb.swipe(sx, sy, ex, ey, duration)

        self.anti.sleep(base=1.0, jitter=0.5)
        self.anti.record_action()

    def long_press(self, x: int, y: int, duration: int = 1000):
        """长按（通过 swipe 实现，起点终点相同）

        Args:
            x, y: 坐标
            duration: 长按时长（毫秒）
        """
        self.anti.check_run_limit()

        cx, cy = self.anti.random_offset(x, y, radius=5)
        logger.info(f"长按 ({cx},{cy}) dur={duration}ms")

        self.adb.swipe(cx, cy, cx, cy, duration)

        self.anti.sleep(base=1.0, jitter=0.5)
        self.anti.record_action()

    def input_text(self, text: str):
        """输入文本（用于账号密码）

        Args:
            text: 要输入的文本
        """
        self.anti.check_run_limit()
        logger.info(f"输入文本: {text[:3]}***")
        self.adb.input_text(text)
        self.anti.sleep(base=0.5, jitter=0.3)
        self.anti.record_action()

    def random_sleep(self, min_s: float = 1.0, max_s: float = 3.0):
        """随机等待

        Args:
            min_s: 最小等待秒数
            max_s: 最大等待秒数
        """
        import random
        delay = random.uniform(min_s, max_s)
        logger.debug(f"随机等待 {delay:.2f}s")
        time.sleep(delay)

    def input_key(self, key: str):
        """按键

        Args:
            key: 按键名 BACK/HOME/MENU
        """
        self.anti.check_run_limit()
        logger.info(f"按键: {key}")
        self.adb.input_key(key)
        self.anti.sleep(base=0.5, jitter=0.3)
        self.anti.record_action()
