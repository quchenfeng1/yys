"""
14-执行器模块（Executor Module）

高层操作执行桥接层。封装"识图→安全偏移→设备操作"的完整链路，
为任务步骤提供 click_image()、wait_any()、ensure_scene() 等语义化操作接口。

操作链路：识别图片 → 防封号计算偏移 → 沙盒检查 → 执行点击 → 随机延迟 → 记录审计

对应模块说明：模块说明/14-执行器模块.md
"""

import random
import time
from typing import Optional

from core.logger import get_logger
from core.anti_detect import AntiDetect
from core.recognizer import Recognizer, MatchResult

logger = get_logger("core.executor")


class Executor:
    """操作执行器，所有用户操作的统一入口。

    桥接 02-图像识别模块、03-防封策略模块、01-设备连接模块，
    提供语义化的高层操作接口。
    """

    def __init__(self, recognizer: Recognizer, anti_detect: AntiDetect,
                 connection, monitor=None, config=None):
        """
        Args:
            recognizer: 图像识别模块
            anti_detect: 防封策略模块
            connection: 设备连接模块（ADBClient）
            monitor: 日志监控模块（可选）
            config: 配置模块（可选）
        """
        self.recognizer = recognizer
        self.anti = anti_detect
        self.connection = connection
        self.monitor = monitor
        self.config = config

        # 沙盒模式：True 时不实际执行点击，仅记录日志
        self._dry_run = False
        # 上一次操作的详细信息
        self._last_operation: Optional[dict] = None

    def click_image(self, template_name: str, region: tuple = None,
                    timeout: float = 10, threshold: float = None) -> bool:
        """识图→偏移→点击全链路

        流程：识别图片 → 防封号矩形内偏移 → 随机延迟 → 走神判断
              → 沙盒检查 → 执行点击 → 记录审计

        Args:
            template_name: 模板名，如 "scenes/login/splash_skip"
            region: 限定搜索区域 (x, y, w, h)
            timeout: 等待图片出现的超时时间（秒），0 表示不等待
            threshold: 匹配阈值

        Returns:
            True 表示成功识别并点击，False 表示未找到
        """
        start = time.time()

        # 1. 防封号：检查运行限制
        self.anti.check_run_limit()

        # 2. 识别图片
        if timeout > 0:
            result = self.recognizer.wait(template_name, timeout=timeout)
        else:
            result = self.recognizer.find(template_name, threshold=threshold)

        if result is None:
            logger.warning(f"点击失败：未找到图片 {template_name}")
            self._record_operation(template_name, False, None, time.time() - start)
            return False

        # 3. 防封号：在图标矩形范围内生成随机偏移（确保不超出目标边界）
        cx, cy = result.center
        w, h = result.size if hasattr(result, 'size') and result.size else (0, 0)
        if w > 0 and h > 0:
            click_x = cx - w // 2 + random.randint(0, w)
            click_y = cy - h // 2 + random.randint(0, h)
        else:
            click_x, click_y = self.anti.random_offset(cx, cy)

        logger.info(f"点击 {template_name} @ ({click_x},{click_y}) "
                    f"[原图中心=({cx},{cy}), 置信度={result.confidence:.3f}]")

        # 4. 防封号：随机延迟
        self.anti.sleep(base=0.8, jitter=0.5)

        # 5. 防封号：偶尔触发长暂停（模拟走神）
        self.anti.maybe_long_pause()

        # 6. 沙盒检查：dry_run 模式下不实际执行
        if self._dry_run:
            logger.info(f"[沙盒] 将要点击 {template_name} @ ({click_x},{click_y})")
            self._record_operation(template_name, True, result, time.time() - start)
            return True

        # 7. 执行点击
        self.connection.click(click_x, click_y)

        # 8. 记录操作
        self.anti.record_action()

        elapsed = time.time() - start
        self._record_operation(template_name, True, result, elapsed)
        return True

    def click_point(self, x: int, y: int):
        """直接坐标点击（仍经防封号偏移，不过识图）

        Args:
            x, y: 目标坐标
        """
        start = time.time()

        self.anti.check_run_limit()

        click_x, click_y = self.anti.random_offset(x, y)

        logger.info(f"点击坐标 ({click_x},{click_y}) [原坐标=({x},{y})]")

        self.anti.sleep(base=0.8, jitter=0.5)
        self.anti.maybe_long_pause()

        if self._dry_run:
            logger.info(f"[沙盒] 将要点击坐标 ({click_x},{click_y})")
            return

        self.connection.click(click_x, click_y)
        self.anti.record_action()

        self._last_operation = {
            "type": "click_point",
            "original": (x, y),
            "actual": (click_x, click_y),
            "success": True,
            "elapsed": time.time() - start,
        }

    def click_if_exists(self, template_name: str, threshold: float = None) -> bool:
        """存在则点击，不存在则跳过（不等待）

        Args:
            template_name: 模板名
            threshold: 匹配阈值

        Returns:
            True 表示存在并点击了，False 表示不存在
        """
        start = time.time()

        result = self.recognizer.find(template_name, threshold=threshold)
        if result is None:
            return False

        self.anti.check_run_limit()
        cx, cy = result.center
        click_x, click_y = self.anti.random_offset(cx, cy)

        logger.info(f"条件点击 {template_name} @ ({click_x},{click_y}) "
                    f"[置信度={result.confidence:.3f}]")

        self.anti.sleep(base=0.8, jitter=0.5)

        if not self._dry_run:
            self.connection.click(click_x, click_y)
        else:
            logger.info(f"[沙盒] 条件点击 {template_name}")

        self.anti.record_action()

        self._last_operation = {
            "type": "click_if_exists",
            "template": template_name,
            "success": True,
            "elapsed": time.time() - start,
        }
        return True

    # ==================== 滑动 / 按键 ====================

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

        sx, sy = self.anti.random_offset(x1, y1, radius=5)
        ex, ey = self.anti.random_offset(x2, y2, radius=5)

        logger.info(f"滑动 ({sx},{sy}) -> ({ex},{ey}) dur={duration}ms")

        if not self._dry_run:
            self.connection.swipe(sx, sy, ex, ey, duration)
        else:
            logger.info(f"[沙盒] 滑动 ({sx},{sy})->({ex},{ey})")

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

        if not self._dry_run:
            self.connection.swipe(cx, cy, cx, cy, duration)
        else:
            logger.info(f"[沙盒] 长按 ({cx},{cy})")

        self.anti.sleep(base=1.0, jitter=0.5)
        self.anti.record_action()

    def input_text(self, text: str):
        """输入文本（用于账号密码）

        Args:
            text: 要输入的文本
        """
        self.anti.check_run_limit()
        logger.info(f"输入文本: {text[:3]}***")

        if not self._dry_run:
            self.connection.input_text(text)
        else:
            logger.info(f"[沙盒] 输入文本")

        self.anti.sleep(base=0.5, jitter=0.3)
        self.anti.record_action()

    def input_key(self, key: str):
        """按键

        Args:
            key: 按键名 BACK/HOME/MENU
        """
        self.anti.check_run_limit()
        logger.info(f"按键: {key}")

        if not self._dry_run:
            self.connection.input_key(key)
        else:
            logger.info(f"[沙盒] 按键: {key}")

        self.anti.sleep(base=0.5, jitter=0.3)
        self.anti.record_action()

    # ==================== 等待 / 场景 ====================

    def wait_any(self, template_names: list, timeout: float = 10,
                 interval: float = 1.0):
        """等待多个模板中任一出现

        截图 → 遍历识别 names → 找到任一则返回 → 未找到则等待后重试

        Args:
            template_names: 模板名列表
            timeout: 总超时秒数
            interval: 每次等待间隔秒数

        Returns:
            (模板名, MatchResult) 或 None（超时）
        """
        deadline = time.time() + timeout

        while time.time() < deadline:
            for name in template_names:
                result = self.recognizer.find(name)
                if result is not None:
                    logger.info(f"wait_any 匹配到 {name} 置信度={result.confidence:.3f}")
                    return (name, result)

            delay = random.uniform(interval * 0.8, interval * 1.2)
            time.sleep(delay)

        logger.warning(f"wait_any 超时: {template_names} ({timeout}s)")
        return None

    def ensure_scene(self, template_name: str, timeout: float = 15) -> bool:
        """确保当前处于指定场景，不在则等待直到出现或超时

        Args:
            template_name: 目标场景模板名
            timeout: 超时秒数

        Returns:
            True 表示确认在目标场景，False 表示超时未出现
        """
        deadline = time.time() + timeout

        while time.time() < deadline:
            result = self.recognizer.find(template_name)
            if result is not None:
                logger.info(f"场景确认: {template_name} 置信度={result.confidence:.3f}")
                return True
            time.sleep(random.uniform(0.5, 1.0))

        logger.warning(f"场景确认超时: {template_name} ({timeout}s)")
        return False

    def detect_scene(self, candidates: list, timeout: float = 5):
        """遍历候选场景模板，返回最先匹配的场景名

        Args:
            candidates: 候选场景模板名列表
            timeout: 扫描超时秒数

        Returns:
            匹配到的场景名，或 None
        """
        deadline = time.time() + timeout

        while time.time() < deadline:
            for scene_name in candidates:
                result = self.recognizer.find(scene_name)
                if result is not None:
                    logger.info(f"场景检测: {scene_name} 置信度={result.confidence:.3f}")
                    return scene_name
            time.sleep(random.uniform(0.3, 0.6))

        logger.debug(f"场景检测无匹配: {candidates}")
        return None

    # ==================== 实用工具 ====================

    def random_sleep(self, min_s: float = 1.0, max_s: float = 3.0):
        """随机等待一段时间

        Args:
            min_s: 最小等待秒数
            max_s: 最大等待秒数
        """
        delay = random.uniform(min_s, max_s)
        logger.debug(f"随机等待 {delay:.2f}s")
        time.sleep(delay)

    # ==================== 沙盒模式 ====================

    def set_dry_run(self, enabled: bool):
        """设置沙盒模式

        沙盒模式下所有操作仅记录日志，不实际执行 ADB 点击。
        用于验证任务流程而不实际操作游戏。

        Args:
            enabled: True 启用沙盒，False 关闭
        """
        self._dry_run = enabled
        logger.info(f"沙盒模式 {'已启用' if enabled else '已关闭'}")

    def is_dry_run(self) -> bool:
        """查询当前是否沙盒模式"""
        return self._dry_run

    # ==================== 审计 ====================

    def get_last_operation(self) -> Optional[dict]:
        """获取上一次操作的详细信息

        Returns:
            包含坐标/模板/耗时/是否成功的字典，或 None
        """
        return self._last_operation

    def _record_operation(self, template: str, success: bool,
                          result: Optional[MatchResult], elapsed: float):
        """记录操作审计信息"""
        self._last_operation = {
            "type": "click_image",
            "template": template,
            "success": success,
            "confidence": result.confidence if result else None,
            "position": result.center if result else None,
            "elapsed": elapsed,
            "dry_run": self._dry_run,
        }
        if self.monitor and hasattr(self.monitor, 'record_operation'):
            try:
                self.monitor.record_operation(
                    operation_type="click_image",
                    template=template,
                    success=success,
                    elapsed=elapsed,
                )
            except Exception:
                pass
