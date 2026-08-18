"""
12-日志监控中心

异常截图管理器。
职责:
- 在关键时刻（错误/异常）自动截图保存
- 截图命名与归档
- 截图清理（按数量/时间）
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from core.event_bus import EventBus, get_global_bus
from core.events import Events


class SnapshotManager:
    """异常截图管理器"""

    def __init__(
        self,
        snapshot_dir: str | Path = "logs/snapshots",
        event_bus: EventBus | None = None,
        max_snapshots: int = 200,
        auto_clean: bool = True,
    ):
        self._dir = Path(snapshot_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._bus = event_bus or get_global_bus()
        self._lock = threading.Lock()
        self._max_snapshots = max_snapshots
        self._auto_clean = auto_clean
        self._count = 0

        # 截图保存回调（由 device 模块注入）
        self._capture_fn: Any = None

    def set_capture_fn(self, fn: Any) -> None:
        """设置截图获取函数"""
        self._capture_fn = fn

    def take_snapshot(
        self,
        reason: str = "manual",
        image: np.ndarray | None = None,
    ) -> str | None:
        """
        保存一张截图。

        Args:
            reason: 截图原因（error | manual | debug）
            image: 图片数据（None 则通过 capture_fn 获取）

        Returns:
            截图文件路径，失败返回 None
        """
        try:
            if image is None and self._capture_fn:
                image = self._capture_fn()

            if image is None:
                return None

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            with self._lock:
                self._count += 1
                fname = f"{timestamp}_{reason}_{self._count}.png"
                path = self._dir / fname

            # 保存图片（中文安全写入）
            from core.cv_io import imwrite as _cv_imwrite
            _cv_imwrite(str(path), image)

            # 清理
            if self._auto_clean:
                self._clean_old()

            self._bus.publish(Events.STATE_SNAPSHOT, path=str(path), reason=reason)
            return str(path)

        except Exception:
            return None

    def take_error_snapshot(self, error: str = "") -> str | None:
        """保存错误截图"""
        return self.take_snapshot(reason="error")

    # ── 管理 ──────────────────────────────────────────────────

    def list_snapshots(self) -> list[dict[str, Any]]:
        """列出所有截图"""
        snapshots = []
        for f in sorted(self._dir.glob("*.png"), reverse=True):
            snapshots.append({
                "path": str(f),
                "name": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
        return snapshots

    def delete_snapshot(self, name: str) -> bool:
        """删除指定截图"""
        path = self._dir / name
        if path.exists():
            path.unlink()
            return True
        return False

    def _clean_old(self) -> None:
        """清理超出上限的截图"""
        files = sorted(self._dir.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
        if len(files) > self._max_snapshots:
            for f in files[self._max_snapshots:]:
                try:
                    f.unlink()
                except Exception:
                    pass

    def clear_all(self) -> int:
        """清空所有截图"""
        count = 0
        for f in self._dir.glob("*.png"):
            try:
                f.unlink()
                count += 1
            except Exception:
                pass
        return count

    @property
    def count(self) -> int:
        return self._count

    @property
    def directory(self) -> str:
        return str(self._dir)
