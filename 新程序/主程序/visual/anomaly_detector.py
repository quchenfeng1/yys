"""
异常判定引擎（2026-08-16 信号体系）。

判定公式（设计 v5/v7）：
- 重复键 =（节点 id, 场景信号）：同一节点连续触发场景识别器且识别出相同信号
  → 计数累加；节点 id 或场景信号变化 → 该节点计数重置
- 时间窗口：window 秒内连续识别到同一场景信号 count 次 → 也判异常（跨节点滑动）
- 识别不到（信号为空串）同样参与计数（页面卡死/黑屏场景）

阈值：global.yaml anomaly.count（默认 5）/ anomaly.window（默认 30 秒）。
"""
from __future__ import annotations

import time


class AnomalyDetector:
    """异常判定引擎（每任务执行一个实例）。"""

    def __init__(self, count: int = 5, window: int = 30):
        self.count = max(1, int(count))
        self.window = max(1, int(window))
        self._node_keys: dict[tuple[str, str], tuple[int, float]] = {}
        self._signal_win: dict[str, tuple[int, float]] = {}

    def check(self, node_id: str, signal: str = "") -> bool:
        """记录一次识别并判定是否异常。返回 True=异常。"""
        now = time.time()
        sig = str(signal or "")
        anomaly = False

        # ① 每节点连续计数：键相同 → 累加；变化 → 重置
        key = (str(node_id or ""), sig)
        prev = self._node_keys.get(key)
        cnt = (prev[0] + 1) if prev is not None else 1
        self._node_keys[key] = (cnt, now)
        if cnt >= self.count:
            anomaly = True

        # ② 时间窗口内同信号连续计数（跨节点滑动窗口）
        win = self._signal_win.get(sig)
        wcnt = (win[0] + 1) if (win is not None and now - win[1] <= self.window) else 1
        self._signal_win[sig] = (wcnt, now)
        if wcnt >= self.count:
            anomaly = True

        return anomaly

    def reset(self) -> None:
        self._node_keys.clear()
        self._signal_win.clear()
