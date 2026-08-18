"""诊断：设备连接 + 截图链路（capture_screen 完整路径）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2

from device.adb_client import ADBClient


def main():
    adb = ADBClient()
    print("[1] ADB 路径:", adb.adb_path)
    devices = adb.list_devices()
    print("[2] 设备列表:", devices)
    if not devices:
        print("    ❌ 无设备 — 模拟器可能关闭或 ADB 未连接")
        return 1
    serial = adb.get_first_device()
    adb.serial = serial
    print("[3] 使用设备:", serial)

    print("[4] echo 连通性:", adb.echo())
    try:
        w, h = adb.wm_size()
        print(f"[5] 分辨率: {w}x{h}")
    except Exception as e:
        print("[5] 分辨率获取失败:", e)

    print("[6] screencap 二进制截图…")
    t0 = time.time()
    try:
        data = adb.screencap()
        dt = time.time() - t0
        print(f"    bytes={len(data)} 耗时={dt:.2f}s")
        img = cv2.imdecode(__import__("numpy").frombuffer(
            data, dtype=__import__("numpy").uint8), cv2.IMREAD_COLOR)
        if img is None:
            print("    ❌ PNG 解码失败（数据可能被破坏）")
            Path("_diag_screencap.bin").write_bytes(data)
            print("    原始数据已存 _diag_screencap.bin，前 16 字节:",
                  data[:16].hex())
            return 1
        print(f"    ✅ 解码成功: {img.shape}")
    except Exception as e:
        print("    ❌ screencap 失败:", repr(e))
        return 1

    print("[7] exec-out 兼容路径（screenshot 方法）…")
    try:
        data2 = adb.screenshot()
        print(f"    bytes={len(data2)}")
    except Exception as e:
        print("    ⚠ 旧路径失败:", repr(e))

    print("\n✅ 设备截图链路正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
