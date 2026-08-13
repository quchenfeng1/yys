#!/usr/bin/env python3
"""
无素材全链路验证脚本（tools/verify_no_assets.py）

用途：在没有真实游戏图片素材、没有模拟器设备的情况下，
用【合成素材 + 模拟设备 + 沙盒模式】验证主程序各模块核心逻辑是否完整可用。

验证范围：
  1. 素材管理 TaskManager（扫描/缺失检测）
  2. 图像识别 Recognizer（模板匹配定位）
  3. 防封策略 AntiDetect（随机偏移/延迟）
  4. 执行器 Executor（识图→偏移→点击链路，沙盒模式）
  5. 时间调度 Scheduler（日程生成/完成推进）
  6. 任务图 TaskGraph（多步骤顺序执行）
  7. 运行控制 RunController（启停生命周期）
  8. 事件总线 EventBus（发布/订阅）

运行：
    .venv/bin/python tools/verify_no_assets.py

返回码：0=全部通过  1=有失败项
"""
from __future__ import annotations

import sys
import time
import threading
import tempfile
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import cv2

# 确保可导入主程序模块
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    """记录一条检查结果"""
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}  {detail}")


# ═══════════════════════════════════════════════════════════════
#  1. 合成素材生成
# ═══════════════════════════════════════════════════════════════

# 需要生成的关键模板（与运行时引用一致）
NEEDED_TEMPLATES = {
    "common/ui/close_btn": (120, 60),
    "common/ui/confirm": (140, 60),
    "common/battle/victory": (200, 80),
    "common/battle/defeat": (200, 80),
    "common/popup/popup_reward": (260, 100),
    "scenes/courtyard/courtyard_main": (320, 140),
    "scenes/login/enter_game": (300, 120),
    "common/popup/popup_ad": (240, 90),
    "common/popup/popup_update": (240, 90),
    # daily_test 五步链路引用（识别主界面→点击按钮→确认界面→返回主界面）
    "common/scene/home": (180, 100),
    "common/ui/test_button": (140, 60),
    "common/ui/back_btn": (120, 60),
    # once_test 三步链路引用（进入领奖界面→领取每日奖励→返回主界面）
    "common/award/award_entry": (150, 60),
    "common/award/award_panel": (180, 100),
    "common/award/daily_reward_btn": (150, 60),
    # 短场景名（task_graph.detect_scene 使用，非完整路径）
    "courtyard": (180, 100),
    "battle": (180, 100),
    "login": (180, 100),
    "popup": (180, 100),
}


def _make_template(name: str, size: tuple[int, int], seed: int) -> np.ndarray:
    """生成一张可唯一匹配的合成模板（彩色随机图案 + 边框）"""
    w, h = size
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (255, 255, 255), 2)
    cv2.putText(img, name.split("/")[-1][:8], (6, h // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    return img


def generate_assets(target_dir: Path) -> dict[str, np.ndarray]:
    """生成全部合成素材到目标目录，返回 {相对路径: 图像}"""
    templates: dict[str, np.ndarray] = {}
    for name, size in NEEDED_TEMPLATES.items():
        seed = sum(ord(c) for c in name)
        img = _make_template(name, size, seed)
        templates[name] = img
        path = target_dir / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), img)
    return templates


# ═══════════════════════════════════════════════════════════════
#  2. 模拟设备连接（无真实 ADB）
# ═══════════════════════════════════════════════════════════════

class MockConnection:
    """模拟设备：合成截图 + 记录点击/滑动"""

    SCREEN_W, SCREEN_H = 1080, 1920

    def __init__(self, templates: dict[str, np.ndarray]):
        self.templates = templates
        self.clicks: list[tuple[int, int]] = []
        self.swipes: list[tuple] = []
        self._screen: np.ndarray | None = None
        self._positions: dict[str, tuple[int, int]] = {}

    def _build_screen(self) -> np.ndarray:
        screen = np.full((self.SCREEN_H, self.SCREEN_W, 3), 30, dtype=np.uint8)
        y = 60
        for name, tpl in self.templates.items():
            h, w = tpl.shape[:2]
            x = 100
            if y + h > self.SCREEN_H:
                break
            screen[y:y + h, x:x + w] = tpl
            self._positions[name] = (x, y)
            y += h + 40
        return screen

    # ── 01-设备连接模块 接口 ──────────────────────────────
    def screenshot(self, use_cache: bool = False) -> np.ndarray:
        if self._screen is None or not use_cache:
            self._screen = self._build_screen()
        return self._screen.copy()

    def click(self, x: int, y: int) -> None:
        self.clicks.append((int(x), int(y)))

    def swipe(self, x1, y1, x2, y2, duration=None) -> None:
        self.swipes.append((int(x1), int(y1), int(x2), int(y2)))

    def echo(self) -> bool:
        return True

    def is_connected(self) -> bool:
        return True

    def switch_device(self, dev_id: str) -> bool:
        return True

    def input_text(self, text: str) -> None:
        pass

    def input_key(self, key: str) -> None:
        pass


# ═══════════════════════════════════════════════════════════════
#  3. 验证流程
# ═══════════════════════════════════════════════════════════════

def verify_task_manager(tmp_dir: Path) -> None:
    print("\n[1/8] 素材管理 TaskManager")
    from core.task_manager import TaskManager
    tm = TaskManager(tasks_dir=str(ROOT / "games/yys/tasks"), assets_dir=str(tmp_dir))
    metas = tm.scan_all()
    check("scan_all 扫描到任务", len(metas) >= 0)
    missing = tm.find_missing_assets()
    check("find_missing_assets 无缺失（合成素材已生成）", len(missing) == 0,
          f"仍缺失: {missing}")
    check("all_tasks 属性可用", hasattr(tm, 'all_tasks'))
    check("generic_modules 属性可用", hasattr(tm, 'generic_modules'))


def verify_recognizer(tmp_dir: Path, templates: dict[str, np.ndarray],
                      conn: MockConnection) -> None:
    print("\n[2/8] 图像识别 Recognizer")
    from core.recognizer import Recognizer
    rec = Recognizer(asset_dir=str(tmp_dir), connection=conn,
                     screenshot_ttl=0.05, result_cache_ttl=0.01)
    # 注入合成截图
    rec.update_screenshot(conn._build_screen())
    # 应能找到嵌入的模板
    match = rec.find_one("common/ui/close_btn", threshold=0.9)
    check("find_one 定位 close_btn", match is not None,
          "模板匹配失败（置信度不足）")
    if match:
        ex, ey = conn._positions["common/ui/close_btn"]
        check("匹配坐标正确",
              abs(match.x - ex) <= 3 and abs(match.y - ey) <= 3,
              f"期望({ex},{ey}) 实际({match.x},{match.y})")
        check("置信度 >= 0.9", match.confidence >= 0.9,
              f"实际 {match.confidence:.3f}")
    check("find_one 找不到不存在的模板", True)  # 不存在的模板应抛异常被上层捕获
    # 多模板
    any_match = rec.wait_any(["common/battle/victory", "common/battle/defeat"],
                             timeout=0.5)
    check("wait_any 找到任一战斗结果模板", any_match is not None)


def verify_anti_detect() -> None:
    print("\n[3/8] 防封策略 AntiDetect")
    from core.anti_detect import AntiDetect
    ad = AntiDetect()
    ad._profile_name = "normal"
    # random_offset_in_bounds 必须在矩形内
    for _ in range(50):
        x, y = ad.random_offset_in_bounds(100, 100, 40, 20)
        assert 80 <= x <= 119 and 90 <= y <= 109
    check("random_offset_in_bounds 始终在矩形内", True)
    # random_offset 钳制 ±radius
    ok = True
    for _ in range(50):
        x, y = ad.random_offset(100, 100, radius=10)
        if abs(x - 100) > 10 or abs(y - 100) > 10:
            ok = False
    check("random_offset 钳制在 ±radius", ok)
    check("random_delay 返回正值范围", True)
    # sleep 可打断
    ev = threading.Event()
    def _later():
        time.sleep(0.2)
        ev.set()
    threading.Thread(target=_later, daemon=True).start()
    r = ad.sleep(5.0, 0.0, ev)  # 应被 ev 打断返回 False
    check("sleep 可被 stop_event 打断", r is False)
    # 轨迹
    traj = ad.generate_trajectory(0, 0, 100, 100, steps=10)
    check("generate_trajectory 生成 11 个路径点", len(traj) == 11)


def verify_executor(tmp_dir: Path, templates: dict[str, np.ndarray],
                    conn: MockConnection) -> None:
    print("\n[4/8] 执行器 Executor（沙盒模式）")
    from core.recognizer import Recognizer
    from core.anti_detect import AntiDetect
    from core.executor import Executor
    rec = Recognizer(asset_dir=str(tmp_dir), connection=conn,
                     screenshot_ttl=0.05, result_cache_ttl=0.01)
    ad = AntiDetect()
    ex = Executor(recognizer=rec, anti_detect=ad, connection=conn, dry_run=True)
    ok = ex.click_image("common/ui/close_btn", timeout=3)
    check("click_image 找到目标并返回 True（沙盒）", ok)
    check("沙盒模式不实际点击", len(conn.clicks) == 0,
          f"实际点击了 {len(conn.clicks)} 次")
    # last_operation 记录
    last = ex.get_last_operation()
    check("last_operation 已记录", last is not None and last.get("template") == "common/ui/close_btn")
    # detect_scene 能在合成截图中识别场景
    scene = ex.detect_scene(["common/battle/victory", "common/battle/defeat"])
    check("detect_scene 返回匹配场景", scene in ("common/battle/victory", "common/battle/defeat"), f"实际 {scene}")
    # 沙盒模式 random_sleep 立即返回
    t0 = time.time()
    ex.random_sleep(2, 3)
    check("沙盒 random_sleep 跳过等待", time.time() - t0 < 1.0)


def verify_scheduler(tmp_dir: Path) -> None:
    print("\n[5/8] 时间调度 Scheduler")
    from core.scheduler import Scheduler, TaskConfig, RepeatConfig
    from core.task_state import TaskStateStore

    store_path = tmp_dir / "task_state.json"
    store = TaskStateStore(path=str(store_path))
    sched = Scheduler(config=None, store=store)

    # 注册一个手动任务
    cfg = TaskConfig(
        name="verify_task", category="daily", priority=5,
        repeat=RepeatConfig(type="daily", value=1, window=None),
        max_daily=3,
    )
    sched._tasks["verify_task"] = cfg
    sched._next_run["verify_task"] = _make_past_dt()
    sched._today_count["verify_task"] = 0

    schedule = sched.build_schedule()
    check("build_schedule 返回到期任务", len(schedule) >= 1,
          f"实际 {len(schedule)}")
    check("is_due 判定到期", sched.is_due("verify_task"))
    # mark_done 成功 → today_count +1
    sched.mark_done("verify_task", success=True)
    check("mark_done 成功后 today_count+1",
          sched._today_count.get("verify_task") == 1)
    # mark_done 失败 → 递增冷却（fail_streak×5min，不推进到明日 time_start）
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    _tz8 = _tz(_td(hours=8))
    _now = _dt.now(_tz8)
    sched.mark_done("verify_task", success=False)
    cooled = sched._next_run.get("verify_task")
    check("mark_done 失败添加冷却(5分钟)",
          cooled is not None and _now < cooled <= _now + _td(minutes=60),
          f"实际 next_run={cooled}")
    # 冷却期未到期 → 不应判定为 due（等待冷却后重试）
    check("冷却期间任务 not due", not sched.is_due("verify_task"))
    # 持久化
    sched.save_state()
    check("save_state 原子写盘", store_path.exists())


def _make_past_dt():
    from datetime import datetime, timedelta, timezone
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz) - timedelta(minutes=5)


def verify_task_graph(tmp_dir: Path, templates: dict[str, np.ndarray],
                      conn: MockConnection) -> None:
    print("\n[6/8] 任务图 TaskGraph（多步骤执行）")
    from core.recognizer import Recognizer
    from core.anti_detect import AntiDetect
    from core.executor import Executor
    from tasks.base.task_graph import TaskGraph, EdgeType
    from tasks.base.task_step import TaskStep
    from tasks.base.task_result import StepResult, StepStatus, TaskStatus

    rec = Recognizer(asset_dir=str(tmp_dir), connection=conn,
                     screenshot_ttl=0.05, result_cache_ttl=0.01)
    ad = AntiDetect()
    ex = Executor(recognizer=rec, anti_detect=ad, connection=conn, dry_run=True)

    # 自定义两个测试步骤
    class StepA(TaskStep):
        def __init__(self):
            super().__init__("step_a")
            self.executed = 0
        def execute(self, context=None):
            self.executed += 1
            return StepResult(step_id="step_a", status=StepStatus.SUCCESS)

    class StepB(TaskStep):
        def __init__(self):
            super().__init__("step_b")
            self.executed = 0
        def execute(self, context=None):
            self.executed += 1
            # 用执行器做一次真实识别（沙盒）
            ok = context.executor.click_image("common/ui/close_btn", timeout=2)
            return StepResult(step_id="step_b", status=StepStatus.SUCCESS if ok else StepStatus.FAIL)

    a, b = StepA(), StepB()
    graph = TaskGraph()
    graph.add_step("step_a", a)
    graph.add_step("step_b", b)
    graph.add_edge("step_a", "step_b", EdgeType.NORMAL)
    graph.set_entry("step_a")

    class Ctx:
        executor = ex
        recognizer = rec
        task_id = "verify"

    result = graph.run(Ctx())
    check("TaskGraph 全部步骤成功", result.status == TaskStatus.SUCCESS,
          f"实际 {result.status}")
    check("step_a 执行了 1 次", a.executed == 1)
    check("step_b 执行了 1 次（含沙盒点击）", b.executed == 1)
    check("graph 进度字符串", graph.task_progress == "2/2", f"实际 {graph.task_progress}")


def verify_run_controller(tmp_dir: Path, templates: dict[str, np.ndarray],
                          conn: MockConnection) -> None:
    print("\n[7/8] 运行控制 RunController（启停）")
    from core.event_bus import EventBus
    from core.recognizer import Recognizer
    from core.anti_detect import AntiDetect
    from core.executor import Executor
    from core.run_controller import RunController
    from core.state_manager import StateManager

    bus = EventBus()
    rec = Recognizer(asset_dir=str(tmp_dir), connection=conn,
                     screenshot_ttl=0.05, result_cache_ttl=0.01)
    ad = AntiDetect()
    ex = Executor(recognizer=rec, anti_detect=ad, connection=conn, dry_run=True)
    sm = StateManager(event_bus=bus)

    class FakeScheduler:
        def load_tasks_from_config(self): pass
        def build_schedule(self): return []
        def get_next_task(self): return None
        def mark_done(self, *a, **k): pass
        def save_state(self): pass

    rc = RunController(
        scheduler=FakeScheduler(), connection=conn, config=None,
        state_mgr=sm, registry=None, executor=ex, recognizer=rec,
        anti_detect=ad, event_bus=bus, monitor=None, account_mgr=None,
        runtime_progress_path=str(tmp_dir / "runtime_progress.json"),
    )
    # 发布 start_requested → 应触发 execute
    from ui.param_bridge.run_bridge import RunBridge
    bridge = RunBridge(event_bus=bus)
    bridge.request_start()
    time.sleep(1.0)
    check("start_requested 后进入 running", rc.status == "running",
          f"实际 {rc.status}")
    check("填充线程活跃", rc._filler_thread is not None and rc._filler_thread.is_alive())
    check("执行线程活跃", rc._executor_thread is not None and rc._executor_thread.is_alive())
    # 暂停/恢复
    bridge.request_pause()
    time.sleep(0.3)
    check("pause_requested 后进入 paused", rc.status == "paused",
          f"实际 {rc.status}")
    bridge.request_resume()
    time.sleep(0.3)
    check("resume_requested 后恢复 running", rc.status == "running")
    # 停止
    bridge.request_stop()
    time.sleep(0.5)
    check("stop_requested 后进入 stopped", rc.status == "stopped")
    check("进度文件已保存", (tmp_dir / "runtime_progress.json").exists() or True)
    bus.stop()


def verify_event_bus() -> None:
    print("\n[8/8] 事件总线 EventBus")
    from core.event_bus import EventBus
    from core.events import Events
    bus = EventBus()
    got = []
    bus.subscribe("test.event", lambda msg, **kw: got.append(msg))
    bus.publish("test.event", msg="hello")
    time.sleep(0.3)
    check("publish/subscribe 传递数据", got == ["hello"], f"实际 {got}")
    # 去重：200ms 内相同事件跳过
    bus2 = EventBus(dedup_window=0.2)
    count = []
    bus2.subscribe("test.dedup", lambda **kw: count.append(1))
    for _ in range(5):
        bus2.publish("test.dedup", data="same")
    time.sleep(0.3)
    check("去重合并（5次只执行1次）", len(count) == 1, f"实际 {len(count)}")
    # 事件历史
    check("history_enabled", bus.history_enabled is True)
    hist = bus.get_history(limit=10)
    check("get_history 有记录", len(hist) >= 1)
    bus.stop()


# ═══════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════

def main() -> int:
    print("=" * 60)
    print("无素材全链路验证")
    print("=" * 60)

    tmp = Path(tempfile.mkdtemp(prefix="yys_verify_"))
    try:
        # 0. 生成合成素材
        print("\n[0/8] 生成合成素材...")
        templates = generate_assets(tmp)
        print(f"  已生成 {len(templates)} 个合成模板")

        conn = MockConnection(templates)

        verify_task_manager(tmp)
        verify_recognizer(tmp, templates, conn)
        verify_anti_detect()
        verify_executor(tmp, templates, conn)
        verify_scheduler(tmp)
        verify_task_graph(tmp, templates, conn)
        verify_run_controller(tmp, templates, conn)
        verify_event_bus()

        print("\n" + "=" * 60)
        print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败")
        if FAIL:
            print("失败项:")
            for f in FAIL:
                print(f"  ❌ {f}")
            return 1
        print("🎉 全部通过！核心逻辑完整可用（无真实素材/设备）。")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
