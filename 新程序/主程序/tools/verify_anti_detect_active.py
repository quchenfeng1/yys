"""
验证：防封策略是否真正生效（2026-08-16 确认 + 修复启用开关）。

覆盖：
  A. wait_if_needed 间隔落在 [min,max]（随机采样）
  B. enabled=False → debug 档案（零偏移/零走神/零漂移）
  C. random_offset_in_bounds 偏移在矩形内且随机
  D. 滑动轨迹起终点正确且轨迹随机
  E. should_random_fail 失败率 0/1 边界
  F. Executor.click_position 链路：间隔 + ±5px 随机偏移；关闭→原坐标
  G. 可视化点击器/拖拽器随机点：红框区域内随机、遮罩 alpha 内随机
  H. bootstrap 真实接线：global.yaml 的 min/max/jitter/失败率/enabled 注入
运行：QT_QPA_PLATFORM=offscreen python -X utf8 tools/verify_anti_detect_active.py
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core.anti_detect as admod
from core.anti_detect import AntiDetect

results: list[tuple[str, bool]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond)))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


class _PatchSleep:
    """临时接管 time.sleep 收集休眠时长"""

    def __init__(self):
        self.slept: list[float] = []
        self._orig = admod.time.sleep

    def __enter__(self):
        admod.time.sleep = self.slept.append
        return self

    def __exit__(self, *a):
        admod.time.sleep = self._orig


# ── A. 间隔生效（min/max）────────────────────────────
ad = AntiDetect(min_interval=0.3, max_interval=0.5,
                action_jitter=False, random_fail_rate=0.0, enabled=True)
waits: list[float] = []
with _PatchSleep() as p:
    for _ in range(10):
        ad._last_action_time = time.time() - 0.05
        ad.wait_if_needed()
    waits = list(p.slept)
# wait = interval - 0.05，interval∈[0.3,0.5] → wait∈[0.25,0.45]
check("A1 间隔落在 min~max", bool(waits)
      and all(0.25 - 1e-6 <= w <= 0.45 + 1e-6 for w in waits), str(waits[:3]))
check("A2 间隔随机", len(set(round(w, 4) for w in waits)) >= 5, str(waits[:3]))

# ── B. enabled=False → debug 档案 ─────────────────────
ad_off = AntiDetect(min_interval=0.0, max_interval=0.0,
                    action_jitter=False, random_fail_rate=0.0, enabled=False)
check("B1 关闭→debug档案", ad_off.current_profile == "debug",
      ad_off.current_profile)
check("B2 关闭→零偏移", ad_off.random_offset(100, 100) == (100, 100))
with _PatchSleep() as p:
    ad_off.maybe_long_pause()
    check("B3 关闭→无走神停顿", not p.slept, str(p.slept))

# ── C. 偏移随机性 ────────────────────────────────────
ad2 = AntiDetect(min_interval=0.05, max_interval=0.05,
                 action_jitter=False, random_fail_rate=0.0, enabled=True)
pts = [ad2.random_offset_in_bounds(100, 100, 20, 20) for _ in range(50)]
check("C1 偏移都在矩形内",
      all(90 <= x <= 109 and 90 <= y <= 109 for x, y in pts))
check("C2 偏移随机", len(set(pts)) >= 5, str(set(pts)))

# ── D. 滑动轨迹 ──────────────────────────────────────
t1 = ad2.generate_trajectory(0, 0, 300, 300, steps=10)
t2 = ad2.generate_trajectory(0, 0, 300, 300, steps=10)
check("D1 轨迹起终点正确", t1[0] == (0, 0) and t1[-1] == (300, 300))
check("D2 轨迹随机", t1 != t2)

# ── E. 随机失败率 ────────────────────────────────────
adf0 = AntiDetect(min_interval=0.05, max_interval=0.05,
                  action_jitter=False, random_fail_rate=0.0, enabled=True)
check("E1 失败率0→永不失败", all(not adf0.should_random_fail() for _ in range(50)))
adf1 = AntiDetect(min_interval=0.05, max_interval=0.05,
                  action_jitter=False, random_fail_rate=1.0, enabled=True)
check("E2 失败率1→必失败", all(adf1.should_random_fail() for _ in range(50)))

# ── F. Executor.click_position 链路 ──────────────────
from core.executor import Executor


class FakeConn:
    def __init__(self):
        self.clicks: list[tuple[int, int]] = []

    def click(self, x, y):
        self.clicks.append((x, y))


conn = FakeConn()
ad3 = AntiDetect(min_interval=0.05, max_interval=0.05,
                 action_jitter=False, random_fail_rate=0.0, enabled=True)
with _PatchSleep() as p:
    ex = Executor(recognizer=None, anti_detect=ad3, connection=conn,
                  monitor=None, config=None, event_bus=None)
    for _ in range(5):
        ex.click_position(100, 100)
    slept = list(p.slept)
check("F1 点击落在±5px内",
      all(95 <= x <= 104 and 95 <= y <= 104 for x, y in conn.clicks),
      str(conn.clicks))
check("F2 点击点随机", len(set(conn.clicks)) >= 2, str(conn.clicks))
check("F3 点击前有间隔等待", len(slept) >= 1, str(slept[:3]))

conn2 = FakeConn()
ad_off2 = AntiDetect(min_interval=0.0, max_interval=0.0,
                     action_jitter=False, random_fail_rate=0.0, enabled=False)
ex2 = Executor(recognizer=None, anti_detect=ad_off2, connection=conn2,
               monitor=None, config=None, event_bus=None)
ex2.click_position(100, 100)
check("F4 关闭防封→点原坐标", conn2.clicks == [(100, 100)], str(conn2.clicks))

# ── G. 可视化节点随机点 ──────────────────────────────
import numpy as np
import visual.nodes as nodes


class FakeCtx:
    screen_size = (1000, 800)


ctx = FakeCtx()
pts_r = [nodes._random_point_in_region(ctx, [0, 0, 0.5, 0.5]) for _ in range(30)]
check("G1 红框随机点在区域内",
      all(0 <= x <= 499 and 0 <= y <= 399 for x, y in pts_r), str(pts_r[0]))
check("G2 红框随机点随机", len(set(pts_r)) >= 10, str(len(set(pts_r))))

tpl = np.zeros((20, 20, 4), np.uint8)
tpl[5:15, 5:15, 3] = 255  # alpha 方块
_real_load = nodes._load_template
nodes._load_template = lambda c, rel: tpl
try:
    pts_m = [nodes._random_point_in_mask(ctx, "x.png", (100, 100, 20, 20))
             for _ in range(30)]
finally:
    nodes._load_template = _real_load
check("G3 遮罩随机点在alpha内",
      all(tpl[p[1] - 100, p[0] - 100, 3] > 0 for p in pts_m), str(pts_m[0]))
check("G4 遮罩随机点随机", len(set(pts_m)) >= 5, str(len(set(pts_m))))

# ── H. bootstrap 真实接线 ─────────────────────────────
import yaml
from core.bootstrap import ApplicationBootstrap
# bootstrap._init_ui 会创建 MainWindow + qt-material 主题，
# 必须先有 QApplication（否则 offscreen 下 0xC0000409）
from PyQt5.QtWidgets import QApplication
_app = QApplication.instance() or QApplication(sys.argv)

g = yaml.safe_load((ROOT / "config" / "global.yaml").read_text(encoding="utf-8"))
adc = g.get("anti_detect", {})
b = ApplicationBootstrap(root_dir=ROOT)
ok = b.start()
check("H1 bootstrap 启动", ok)
if ok:
    try:
        adb = b.get("anti_detect")
        check("H2 min_interval 注入",
              abs(adb._min_interval - adc.get("min_interval", 1.0)) < 1e-9)
        check("H3 max_interval 注入",
              abs(adb._max_interval - adc.get("max_interval", 5.0)) < 1e-9)
        check("H4 action_jitter 注入",
              adb._action_jitter == adc.get("action_jitter", True))
        check("H5 random_fail_rate 注入",
              abs(adb._random_fail_rate - adc.get("random_fail_rate", 0.02)) < 1e-9)
        check("H6 enabled 注入", adb.is_enabled == adc.get("enabled", True))
    finally:
        b.shutdown()
else:
    for n in ("H2", "H3", "H4", "H5", "H6"):
        check(n, False, "bootstrap 未启动")

# ── 收尾 ─────────────────────────────────────────────
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QEvent
for w in QApplication.topLevelWidgets():
    try:
        w.hide()
        w.deleteLater()
    except Exception:
        pass
QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
QApplication.processEvents()

passed = sum(1 for _, ok in results if ok)
print(f"TOTAL {passed}/{len(results)}")
sys.stdout.flush()
os._exit(0 if passed == len(results) else 1)
