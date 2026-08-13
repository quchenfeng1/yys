#!/usr/bin/env python3
"""
模拟设备模式冒烟测试（tools/smoke_mock.py）

无 GUI、无真实模拟器，验证「点击启动 → 连接建立 → 日志输出」的完整链路：
  1. global.yaml 读取 device.mock=true
  2. ConnectionManager 注入 MockADBClient 后 connect() 成功
  3. Mock 截图可解码（合成图含素材模板）
  4. RunController._start_run() 触发"设备连接成功"日志（走 Monitor → LOG_RECORD）

运行：
    .venv/bin/python tools/smoke_mock.py

返回码：0=通过  1=失败
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.event_bus import EventBus
from core.events import Events
from core.config_manager import ConfigManager
from core.state_manager import StateManager
from core.monitor import Monitor
from device.mock_adb import MockADBClient
from device.connection import ConnectionManager
from core.run_controller import RunController


def main() -> int:
    failed = False

    # ── 1. 配置读取 ──────────────────────────────────────────
    cfg = ConfigManager(
        config_dir=str(ROOT / "config"),
        game_tasks_yaml=str(ROOT / "games/yys/tasks.yaml"),
        game_coords_dir=str(ROOT / "games/yys/coords"),
    )
    cfg.load()
    mock_enabled = bool(cfg.global_config.device.mock)
    print(f"[1] device.mock = {mock_enabled}")
    if not mock_enabled:
        print("    [FAIL] 未启用模拟设备模式")
        failed = True

    # ── 2. 事件总线 + 状态 + 日志收集 ──────────────────────
    bus = EventBus()
    sm = StateManager(event_bus=bus)

    logs: list[dict] = []
    bus.subscribe(Events.LOG_RECORD, lambda **kw: logs.append(kw))
    bus.subscribe(Events.CONNECTION_RESTORED,
                  lambda **kw: logs.append({"__event__": "CONNECTION_RESTORED", **kw}))

    mon = Monitor(
        event_bus=bus,
        config=cfg,
        connection=None,
        log_dir=str(ROOT / "logs"),
        snapshot_dir=str(ROOT / "logs/snapshots"),
    )

    # ── 3. 连接（模拟） ─────────────────────────────────────
    mock = MockADBClient(assets_dir=str(ROOT / "games/yys/assets"))
    conn = ConnectionManager(adb_client=mock, config=cfg, event_bus=bus, state_manager=sm)

    ok = conn.connect()
    print(f"[2] connect() = {ok} | is_connected = {conn.is_connected()} "
          f"| serial = {conn.current_serial}")
    if not (ok and conn.is_connected()):
        print("    [FAIL] 连接未建立")
        failed = True

    # 截图可解码
    img_bytes = mock.screencap()
    img = cv2.imdecode(np.frombuffer(img_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    print(f"[3] screencap 解码 = {img.shape} | 素材模板数 = {len(mock.template_positions)}")
    if img is None or img.size == 0:
        print("    [FAIL] 截图解码失败")
        failed = True

    # ── 4. RunController 启动链 ─────────────────────────────
    rc = RunController(
        scheduler=None,
        connection=conn,
        config=cfg,
        state_mgr=sm,
        executor=None,
        recognizer=None,
        anti_detect=None,
        event_bus=bus,
        monitor=mon,
        account_mgr=None,
        runtime_progress_path=str(ROOT / "games/yys/runtime/smoke_progress.json"),
    )

    logs.clear()
    rc._start_run()
    time.sleep(0.8)  # 等待 Monitor 异步日志

    print("\n[4] _start_run 日志输出:")
    for e in logs:
        if e.get("__event__"):
            print(f"    [事件] {e['__event__']}")
        else:
            print(f"    [{e.get('module','')}] {e.get('level','')}: {e.get('message','')}")

    msgs = [e.get("message", "") for e in logs]
    if not any("设备连接成功" in m for m in msgs):
        print("    [FAIL] 缺少「设备连接成功」日志")
        failed = True
    if not any("运行已启动" in m for m in msgs):
        print("    [FAIL] 缺少「运行已启动」日志")
        failed = True

    print()
    if failed:
        print("❌ 冒烟测试失败")
        return 1
    print("✅ 模拟设备连接链冒烟测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
