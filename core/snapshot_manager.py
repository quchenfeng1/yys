"""
异常截图管理器（12-日志与监控模块 子模块）

出错时自动截图+保存上下文 JSON。
"""

import os
import json
from datetime import datetime


class SnapshotManager:
    """异常截图管理器。"""

    def __init__(self, config):
        self._base_dir = config.get("global.run.screenshot_dir", "logs/snapshots")
        self._enabled = config.get("global.run.screenshot_on_error", True)

    def capture(self, task_name: str, step_name: str,
                error: Exception, screenshot=None):
        """保存异常截图与上下文。"""
        if not self._enabled:
            return

        today = datetime.now().strftime("%Y-%m-%d")
        ts = datetime.now().strftime("%H%M%S")
        dir_path = os.path.join(self._base_dir, today)
        os.makedirs(dir_path, exist_ok=True)

        filename_base = f"{task_name}_{step_name}_{ts}"

        # 保存上下文 JSON
        context = {
            "task": task_name,
            "step": step_name,
            "error": str(error),
            "error_type": type(error).__name__,
            "timestamp": datetime.now().isoformat(),
        }
        ctx_path = os.path.join(dir_path, f"{filename_base}.json")
        with open(ctx_path, "w", encoding="utf-8") as f:
            json.dump(context, f, ensure_ascii=False, indent=2, default=str)

        # 保存截图（如有）
        if screenshot is not None:
            import cv2
            img_path = os.path.join(dir_path, f"{filename_base}.png")
            cv2.imwrite(img_path, screenshot)
