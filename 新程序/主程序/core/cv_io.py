"""
中文安全 OpenCV 图片读写（2026-08-15）。

cv2.imwrite / cv2.imread 在 Windows 上对含中文（非 ASCII）的路径
会静默失败（返回 False / None）。统一改用：
- imencode → tofile 写
- np.fromfile → imdecode 读
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def imwrite(path, img: np.ndarray) -> bool:
    """写图片（支持中文路径）。返回是否成功。"""
    if img is None:
        return False
    p = Path(path)
    ext = p.suffix.lower() or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    try:
        buf.tofile(str(p))
        return True
    except Exception:
        return False


def imread(path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
    """读图片（支持中文路径）。失败返回 None。"""
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = np.fromfile(str(p), dtype=np.uint8)
        return cv2.imdecode(data, flags)
    except Exception:
        return None
