"""
防封号引擎模块 ★ 核心模块

职责：生成随机化的操作参数，使脚本行为接近真人，规避机械式点击检测。
- 正态分布随机偏移（点击不精确到中心点）
- 随机延迟（操作间隔不固定）
- 贝塞尔曲线鼠标移动轨迹（模拟人手移动）
- 随机长暂停（模拟走神）
- 运行时长/次数限制（硬性安全阀）

这是本项目最重要的模块之一，所有点击操作必须经过此模块处理。
"""

import random
import time
import numpy as np
from datetime import datetime, timedelta

from core.logger import get_logger
from core.exceptions import AntiBanRiskError

logger = get_logger("core.anti_detect")


class AntiDetect:
    """防封号引擎，生成随机化操作参数"""

    def __init__(self, config: dict = None):
        # 防封号参数，从全局配置读取
        cfg = config or {}
        anti_cfg = cfg.get("anti_detect", {})

        self.click_offset_radius = anti_cfg.get("click_offset_radius", 12)
        self.delay_jitter = anti_cfg.get("delay_jitter", 0.6)
        self.long_pause_prob = anti_cfg.get("long_pause_prob", 0.05)
        self.max_daily_runtime = anti_cfg.get("max_daily_runtime", 8)    # 小时
        self.max_daily_actions = anti_cfg.get("max_daily_actions", 2000)
        self.min_interval = anti_cfg.get("min_interval", 0.8)            # 秒

        # 运行时统计
        self._daily_action_count = 0
        self._start_time = datetime.now()
        self._last_action_time = 0

        logger.info(f"防封号引擎已初始化: 偏移半径={self.click_offset_radius}, "
                    f"延迟抖动={self.delay_jitter}, 走神概率={self.long_pause_prob}")

    # ===== 随机偏移 =====

    def random_offset(self, cx: int, cy: int, radius: int = None) -> tuple:
        """在中心点周围生成正态分布的随机偏移坐标

        正态分布使中心概率高、边缘概率低，符合人类瞄准习惯。
        绝不点击精确中心点。

        Args:
            cx: 目标中心 X 坐标
            cy: 目标中心 Y 坐标
            radius: 偏移半径（像素），None 则使用默认值

        Returns:
            (x, y) 偏移后的坐标
        """
        r = radius if radius is not None else self.click_offset_radius

        # 正态分布偏移（中心概率高，边缘概率低）
        dx = int(np.random.normal(0, r / 2))
        dy = int(np.random.normal(0, r / 2))

        # 限制不超出半径范围
        dx = max(-r, min(r, dx))
        dy = max(-r, min(r, dy))

        return (cx + dx, cy + dy)

    # ===== 随机延迟 =====

    def random_delay(self, base: float = 1.0, jitter: float = None) -> float:
        """生成随机延迟时间

        Args:
            base: 基础延迟（秒）
            jitter: 抖动范围（秒），None 则使用默认值

        Returns:
            延迟时间（秒）
        """
        j = jitter if jitter is not None else self.delay_jitter
        delay = base + random.uniform(0, j)
        return delay

    def sleep(self, base: float = 1.0, jitter: float = None):
        """执行随机延迟睡眠

        Args:
            base: 基础延迟（秒）
            jitter: 抖动范围（秒）
        """
        delay = self.random_delay(base, jitter)

        # 确保不小于最小操作间隔
        elapsed = time.time() - self._last_action_time
        if elapsed < self.min_interval:
            delay = max(delay, self.min_interval - elapsed)

        time.sleep(delay)
        self._last_action_time = time.time()

    # ===== 贝塞尔曲线鼠标轨迹 =====

    def human_move_path(self, x1: int, y1: int, x2: int, y2: int) -> list:
        """生成贝塞尔曲线鼠标移动路径（模拟人手移动）

        真人移动鼠标不是瞬移，而是有弧度的曲线。
        使用二次贝塞尔曲线，控制点在直线两侧随机偏移。

        Args:
            x1, y1: 起点
            x2, y2: 终点

        Returns:
            路径点列表 [(x, y), ...]
        """
        # 移动步数随机（15~35步，模拟不同移动速度）
        steps = random.randint(15, 35)
        path = []

        # 控制点在直线中点附近随机偏移，使曲线有弧度
        mid_x = (x1 + x2) / 2 + random.uniform(-30, 30)
        mid_y = (y1 + y2) / 2 + random.uniform(-30, 30)

        for i in range(steps + 1):
            t = i / steps
            # 二次贝塞尔曲线公式
            x = (1 - t) ** 2 * x1 + 2 * (1 - t) * t * mid_x + t ** 2 * x2
            y = (1 - t) ** 2 * y1 + 2 * (1 - t) * t * mid_y + t ** 2 * y2
            path.append((int(x), int(y)))

        return path

    # ===== 滑动时长随机化 =====

    def random_swipe_duration(self) -> int:
        """随机滑动时长（毫秒）"""
        return random.randint(200, 500)

    # ===== 随机长暂停（模拟走神）=====

    def maybe_long_pause(self) -> bool:
        """按概率触发长暂停，模拟真人走神

        5% 概率触发 5~15 秒的长暂停。
        真人不可能持续高效操作，偶尔会停下来。

        Returns:
            True 表示触发了长暂停
        """
        if random.random() < self.long_pause_prob:
            pause_time = random.uniform(5, 15)
            logger.info(f"触发随机长暂停（模拟走神）: {pause_time:.1f}s")
            time.sleep(pause_time)
            return True
        return False

    # ===== 运行限制检查 =====

    def check_run_limit(self) -> bool:
        """检查是否超出运行时长/次数限制

        Returns:
            True 表示未超限，可以继续
        Raises:
            AntiBanRiskError: 超出限制时抛出
        """
        # 检查每日运行时长
        runtime = datetime.now() - self._start_time
        runtime_hours = runtime.total_seconds() / 3600
        if runtime_hours > self.max_daily_runtime:
            raise AntiBanRiskError(
                f"已超出每日最大运行时长 {self.max_daily_runtime}h "
                f"(当前 {runtime_hours:.1f}h)，自动停止以防封号"
            )

        # 检查每日操作次数
        if self._daily_action_count > self.max_daily_actions:
            raise AntiBanRiskError(
                f"已超出每日最大操作次数 {self.max_daily_actions} "
                f"(当前 {self._daily_action_count})，自动停止以防封号"
            )

        return True

    def record_action(self):
        """记录一次操作（供 Executor 调用）"""
        self._daily_action_count += 1

    @property
    def action_count(self) -> int:
        """当前操作次数"""
        return self._daily_action_count

    @property
    def runtime_seconds(self) -> float:
        """已运行秒数"""
        return (datetime.now() - self._start_time).total_seconds()
