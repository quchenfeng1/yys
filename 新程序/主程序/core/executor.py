"""
14-执行器模块

Executor 桥接层（§5.1 单文件）。
对应设计书 §2/§3/§4/§5/§6。

职责:
- 操作链路编排：识图→安全偏移→执行
- 高层语义化接口：click_image()、wait_any()、ensure_scene()
- 超时与重试封装
- 全链路记录到 Monitor
- 沙盒模式（_dry_run Event）
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.anti_detect import AntiDetect
from core.event_bus import EventBus, get_global_bus
from core.events import Events
from core.exceptions import ExecutorError, SceneTimeoutError
from core.recognizer import MatchResult, Recognizer


@dataclass
class LastOperation:
    """操作记录（§5.2）"""
    template: str = ""
    original_pos: tuple = (0, 0)
    safe_pos: tuple = (0, 0)
    duration_ms: float = 0.0
    confidence: float = 0.0
    success: bool = False
    dry_run: bool = False
    timestamp: float = 0.0


class Executor:
    """
    执行器（桥接层，§5.3 方法定义）。

    编排 recognizer → anti_detect → connection 调用链路。
    对外暴露语义化接口，调用方无需关心底层细节。
    """

    def __init__(
        self,
        recognizer: Recognizer,
        anti_detect: AntiDetect | None = None,
        connection: Any = None,
        monitor: Any = None,
        config: Any = None,
        event_bus: EventBus | None = None,
        dry_run: bool = False,
    ):
        self._recognizer = recognizer
        self._anti_detect = anti_detect or AntiDetect()
        self._connection = connection   # §2.1 ADBClient（点击/截图/滑动）
        self._monitor = monitor         # §2.1 日志监控（记录操作耗时）
        self._config = config           # §2.1 配置模块
        self._event_bus = event_bus or get_global_bus()
        self._bus = self._event_bus  # 兼容别名

        # §2.3 沙盒模式（Event 以便在操作中检查）
        self._dry_run_event = threading.Event()
        self._dry_run = self._dry_run_event  # 说明书 §2.3 要求名
        if dry_run:
            self._dry_run_event.set()

        # §2.3 上一次操作记录
        self._last_operation: LastOperation | None = None

        # 场景感知：上次感知到的场景（去重发布 scene_updated）
        self._last_scene: str | None = None

        # 设备操作回调（兼容旧版 set_click_handler）
        self._click_handler: Callable[[int, int], bool] | None = None
        self._swipe_handler: Callable[[int, int, int, int, float], bool] | None = None

    # ── 依赖注入 ──────────────────────────────────────────────

    def set_click_handler(self, handler: Callable[[int, int], bool]) -> None:
        """设置点击处理器"""
        self._click_handler = handler

    def set_swipe_handler(
        self, handler: Callable[[int, int, int, int, float], bool]
    ) -> None:
        """设置滑动处理器"""
        self._swipe_handler = handler

    # ── §2.3 + §4.4 沙盒模式 ───────────────────────────────

    @property
    def is_dry_run(self) -> bool:
        return self._dry_run_event.is_set()

    def set_dry_run(self, enabled: bool) -> None:
        if enabled:
            self._dry_run_event.set()
        else:
            self._dry_run_event.clear()

    # ── §2.2 last_operation ─────────────────────────────────

    @property
    def last_operation(self) -> dict | None:
        if self._last_operation is None:
            return None
        return {
            "template": self._last_operation.template,
            "original_pos": self._last_operation.original_pos,
            "safe_pos": self._last_operation.safe_pos,
            "duration_ms": self._last_operation.duration_ms,
            "confidence": self._last_operation.confidence,
            "success": self._last_operation.success,
            "dry_run": self._last_operation.dry_run,
            "timestamp": self._last_operation.timestamp,
        }

    def get_last_operation(self) -> dict | None:
        """获取上一次操作详情（§5.3）"""
        return self.last_operation

    # ── 内部记录 ──────────────────────────────────────────

    def _record_operation(
        self,
        template: str = "",
        original_pos: tuple = (0, 0),
        safe_pos: tuple = (0, 0),
        success: bool = True,
        confidence: float = 0.0,
    ) -> None:
        """记录操作到 _last_operation 和 monitor"""
        now = time.time()
        self._last_operation = LastOperation(
            template=template,
            original_pos=original_pos,
            safe_pos=safe_pos,
            duration_ms=0.0,
            confidence=confidence,
            success=success,
            dry_run=self.is_dry_run,
            timestamp=now,
        )
        # 记录到 monitor
        if self._monitor and hasattr(self._monitor, 'log'):
            self._monitor.log("INFO",
                             f"{'[沙盒] ' if self.is_dry_run else ''}"
                             f"操作: {template} "
                             f"坐标: {safe_pos} "
                             f"成功: {success}",
                             module="executor")

    # ── §5.3 核心操作 ─────────────────────────────────────

    def click_image(
        self,
        name: str,
        region: tuple[int, int, int, int] | None = None,
        timeout: float | None = None,
        stop_event: threading.Event | None = None,
        threshold: float | None = None,
    ) -> bool:
        """
        识图→偏移→点击全链路（§3.1 + §5.3）。

        timeout 控制重试超时（默认 0=单次尝试）。
        重试循环每轮开头调 recognizer.clear_cache() 确保重新截图。
        """
        start_time = time.time()

        while True:
            # 停止检查
            if stop_event and stop_event.is_set():
                return False

            # 超时检查
            if timeout is not None and timeout > 0:
                if time.time() - start_time > timeout:
                    return False

            # §3.1 清除缓存，确保重新截图
            try:
                self._recognizer.clear_cache()
            except Exception:
                pass

            # 安全注入
            self._anti_detect.wait_if_needed()
            self._anti_detect.maybe_long_pause(stop_event)

            # 识图
            try:
                match = self._recognizer.find_one(name, threshold=threshold, region=region)
            except Exception:
                if timeout is not None and timeout > 0:
                    self._anti_detect.sleep(0.5, 0.3, stop_event)
                    continue
                return False

            if match is None:
                # 未找到
                if timeout is not None and timeout > 0:
                    self._anti_detect.sleep(0.5, 0.3, stop_event)
                    continue
                return False

            # 安全偏移（§3.1 要求使用 random_offset_in_bounds）
            click_x, click_y = self._anti_detect.random_offset_in_bounds(
                match.center_x, match.center_y, match.width, match.height)

            # 走神检查
            self._anti_detect.maybe_long_pause(stop_event)

            # §4.4 沙盒模式
            if self._dry_run_event.is_set():
                self._record_operation(
                    template=name,
                    original_pos=(match.center_x, match.center_y),
                    safe_pos=(click_x, click_y),
                    success=True,
                    confidence=match.confidence if hasattr(match, 'confidence') else 0.0,
                )
                return True

            # 实际点击
            click_success = False
            if self._click_handler:
                try:
                    click_success = self._click_handler(click_x, click_y)
                except Exception:
                    click_success = False
            elif self._connection and hasattr(self._connection, 'click'):
                try:
                    self._connection.click(click_x, click_y)
                    click_success = True
                except Exception:
                    click_success = False

            if click_success:
                self._record_operation(
                    template=name,
                    original_pos=(match.center_x, match.center_y),
                    safe_pos=(click_x, click_y),
                    success=True,
                    confidence=match.confidence if hasattr(match, 'confidence') else 0.0,
                )
                self._bus.publish(Events.EXECUTOR_STEP_COMPLETED, source="executor",
                                 action="click_image", template=name)
                return True

            # 点击失败 → 重试
            if timeout is not None and timeout > 0:
                self._anti_detect.sleep(0.5, 0.3, stop_event)
                continue
            return False

    def click_position(self, x: int, y: int) -> None:
        """点击指定坐标（§5.3 click_point 的别名）
        以 10px 矩形做微小偏移，避免每次点击同一像素点。
        """
        self._anti_detect.wait_if_needed()
        # §5.3 要求 random_offset_in_bounds(cx, cy, 10, 10)
        ox, oy = self._anti_detect.random_offset_in_bounds(x, y, 10, 10)

        if self._dry_run_event.is_set():
            self._record_operation(template="click_position",
                                   original_pos=(x, y), safe_pos=(ox, oy))
            return

        if self._click_handler:
            self._click_handler(ox, oy)
        elif self._connection and hasattr(self._connection, 'click'):
            self._connection.click(ox, oy)

    # §5.3 兼容别名
    click_point = click_position

    # ── §5.4 swipe 滑动 ───────────────────────────────────

    def swipe(
        self,
        x1: int, y1: int,
        x2: int, y2: int,
        duration: float = 0.3,
    ) -> None:
        """
        滑动操作（§5.4 + §5.3）。

        调 anti_detect.generate_trajectory() 生成贝塞尔路径点，
        逐点执行路径点。duration 单位为秒。
        """
        self._anti_detect.wait_if_needed()
        trajectory = self._anti_detect.generate_trajectory(x1, y1, x2, y2, steps=10)

        if self._dry_run_event.is_set():
            self._record_operation(template="swipe",
                                   original_pos=(x1, y1), safe_pos=(x2, y2))
            return

        if not trajectory:
            trajectory = [(x1, y1), (x2, y2)]

        # 逐点执行路径
        segment_duration = duration / max(len(trajectory) - 1, 1)
        for i in range(len(trajectory) - 1):
            px, py = trajectory[i]
            nx, ny = trajectory[i + 1]
            if self._swipe_handler:
                self._swipe_handler(px, py, nx, ny, segment_duration)
            elif self._connection and hasattr(self._connection, 'swipe'):
                self._connection.swipe(px, py, nx, ny, segment_duration)

    # ── §5.3 场景检测 ─────────────────────────────────────

    def detect_scene(self, candidates: list[str], timeout: float | None = None) -> str | None:
        """
        遍历候选场景模板，返回最先匹配的场景名（§5.4 + §5.3）。

        支持 timeout 重复检测直到超时。
        命中后发布 scene_updated（去重）；全部候选均未匹配时发布 scene_unknown 事件（§5.5）。
        """
        start_time = time.time()
        while True:
            for c in candidates:
                if self._recognizer.exists(c):
                    self._publish_scene(c)
                    return c

            if timeout is not None and timeout > 0:
                if time.time() - start_time > timeout:
                    self._bus.publish(Events.SCENE_UNKNOWN, source="executor",
                                     candidates=candidates, timeout=timeout)
                    return None
                self._anti_detect.sleep(0.3, 0.1, None)
            else:
                self._bus.publish(Events.SCENE_UNKNOWN, source="executor",
                                 candidates=candidates)
                return None

    def probe_scene(self, candidates: list[str], timeout: float | None = None) -> str | None:
        """
        静默场景感知：遍历候选场景模板，命中返回场景名并发布 scene_updated；
        未命中返回 None（不发布 scene_unknown）。供场景感知步骤 scene_probe / 运行时定位。
        """
        start_time = time.time()
        while True:
            for c in candidates:
                if self._recognizer.exists(c):
                    self._publish_scene(c)
                    return c
            if timeout is not None and timeout > 0:
                if time.time() - start_time > timeout:
                    return None
                self._anti_detect.sleep(0.3, 0.1, None)
            else:
                return None

    def _publish_scene(self, scene: str) -> None:
        """场景感知命中 → 去重发布 scene_updated（07 订阅维护 current_scene/last_known_scene）。"""
        if scene and scene != self._last_scene:
            self._last_scene = scene
            try:
                self._bus.publish(Events.SCENE_UPDATED, source="executor", scene=scene)
            except Exception:
                pass

    def ensure_scene(self, name: str, timeout: float = 30.0) -> bool:
        """确保场景出现（§5.3）"""
        result = self._recognizer.wait(name, timeout=timeout)
        return result is not None

    def wait_any(
        self,
        names: list[str],
        timeout: float = 30.0,
        interval: float = 0.5,
        stop_event: threading.Event | None = None,
    ) -> tuple[str, Any, float] | None:
        """
        等待多个模板中任一出现（§3.2 + §5.3）。

        Returns:
            (模板名, MatchResult, waiting_time) 或 None
        """
        start_time = time.time()
        while True:
            if stop_event and stop_event.is_set():
                return None
            if time.time() - start_time > timeout:
                return None

            # 截一张图，遍历识别
            result = self._recognizer.wait_any(names, timeout=0, stop_event=stop_event)
            if result:
                template_name, match = result
                waiting_time = time.time() - start_time
                return (template_name, match, waiting_time)

            self._anti_detect.sleep(interval * 0.5, interval * 0.3, stop_event)

    def click_if_exists(self, name: str, threshold: float | None = None) -> bool:
        """存在则点击（§5.3 弹窗拦截用）"""
        if self._recognizer.exists(name, threshold=threshold):
            return self.click_image(name)
        return False

    # ── §5.3 休眠（可打断+沙盒跳过）──────────────────────

    def random_sleep(
        self, min_s: float = 1.0, max_s: float = 3.0,
        stop_event: threading.Event | None = None,
    ) -> bool:
        """
        可打断随机休眠（§5.3）。

        沙盒模式下直接返回 True（不执行休眠，§4.4）。
        """
        if self._dry_run_event.is_set():
            return True
        base = random.uniform(min_s, max_s)
        return self._anti_detect.sleep(base, 0.3, stop_event)

    # ── §5.3 其他操作 ─────────────────────────────────────

    def long_press(self, x: int, y: int, duration: float = 1.0) -> None:
        """长按操作（§5.3）"""
        if self._dry_run_event.is_set():
            return
        # ADB 长按手势：touch-down + wait + touch-up
        if self._connection and hasattr(self._connection, 'long_press'):
            self._connection.long_press(x, y, duration)
        else:
            self.click_position(x, y)
            time.sleep(duration)

    def input_text(self, text: str) -> None:
        """输入文本（§5.3）"""
        if self._dry_run_event.is_set():
            return
        if self._connection and hasattr(self._connection, 'input_text'):
            self._connection.input_text(text)

    def input_key(self, key: str) -> None:
        """按键操作 BACK/HOME/MENU（§5.3）"""
        if self._dry_run_event.is_set():
            return
        if self._connection and hasattr(self._connection, 'input_key'):
            self._connection.input_key(key)

    # ── 批量执行 ──────────────────────────────────────────

    def execute_batch(self, steps: list[dict[str, Any]]) -> list[bool]:
        """批量执行操作序列"""
        self._bus.publish(Events.EXECUTOR_BATCH_STARTED, source="executor", count=len(steps))
        results = []
        for step in steps:
            action = step.get("action", "")
            params = step.get("params", {})
            if action == "click_image":
                r = self.click_image(**params)
            elif action in ("click_position", "click_point"):
                self.click_position(**params)
                r = True
            elif action == "swipe":
                self.swipe(**params)
                r = True
            elif action == "wait":
                self._anti_detect.sleep(params.get("duration", 1.0), 0, None)
                r = True
            else:
                r = False
            results.append(r)
        self._bus.publish(Events.EXECUTOR_BATCH_COMPLETED, source="executor", count=len(results))
        return results
