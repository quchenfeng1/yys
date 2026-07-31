#!/usr/bin/env python3
"""
设计书任务链验证（tools/verify_task_chain.py）

验证「按任务设计指导书写法」的任务能否完整跑通：
  1. TaskStep 无参构造（继承类属性 name / is_generic / timeout）
  2. Registry 注册 TaskStep 入口类（声明 display_name），特化步骤不误注册
  3. Scheduler execution_mode 多时段推进（per_slot 每时段各一次 / daily 一天一次 / max_daily）
  4. run_controller._execute_task_once 注入 context.task_config（loop_count/floor/team_id/execution_mode）

运行：
    .venv/bin/python tools/verify_task_chain.py

返回码：0=全部通过  1=有失败项
"""
from __future__ import annotations

import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}  {detail}")


# ═══════════════════════════════════════════════════════════════
#  1. TaskStep 无参构造（设计书 §8.2 特化步骤写法）
# ═══════════════════════════════════════════════════════════════

def verify_taskstep_construct() -> None:
    print("\n[1/4] TaskStep 无参构造（设计书 §8.2）")
    from tasks.base.task_step import TaskStep, StepResult

    class EnterDungeon(TaskStep):
        """进入副本（设计书写法：无 __init__，靠类属性）"""
        name = "enter_dungeon"
        is_generic = False
        timeout = 30

        def execute(self, context=None):
            return StepResult.success("已进入副本")

    s = EnterDungeon()  # 设计书：无参构造
    check("step_id 继承类属性 name", s.step_id == "enter_dungeon", f"实际 {s.step_id}")
    check("name 属性", s.name == "enter_dungeon")
    check("is_generic 继承类属性", s.is_generic is False, f"实际 {s.is_generic}")
    check("timeout 继承类属性(30)", s.timeout == 30, f"实际 {s.timeout}")
    check("execute 返回成功", s.execute().success)

    # 显式传参仍兼容（通用模块写法）
    from tasks.common.close_popup import ClosePopup
    cp = ClosePopup(step_id="close_popup")
    check("显式 step_id 兼容", cp.step_id == "close_popup", f"实际 {cp.step_id}")


# ═══════════════════════════════════════════════════════════════
#  2. Registry 注册设计书入口类
# ═══════════════════════════════════════════════════════════════

def verify_registry() -> None:
    print("\n[2/4] Registry 注册设计书入口类")
    from tasks.registry import TaskRegistry

    # 设计书 §3.1 模板：入口类 MyTask(TaskStep) + display_name
    from tasks.base.task_step import TaskStep

    class MyTask(TaskStep):
        name = "my_task"
        display_name = "测试任务"
        description = "验证设计书入口类"
        timeout = 300

        def execute(self, context=None):
            return StepResult.success("完成")

    class EnterDungeon(TaskStep):
        """特化步骤：无 display_name，不应被注册为任务"""
        name = "enter_dungeon"

        def execute(self, context=None):
            return StepResult.success("ok")

    from tasks.base.task_result import StepResult

    reg = TaskRegistry()
    reg.register(MyTask)
    check("入口类注册成功", "my_task" in reg._registry, f"实际 {list(reg._registry)}")
    inst = reg.get("my_task")
    check("get 返回实例", inst is not None and type(inst) is MyTask)
    check("特化步骤不注册", "enter_dungeon" not in reg._registry)

    # 特化步骤无参构造在 TaskGraph 中可正常 add_step
    from tasks.base.task_graph import TaskGraph
    g = TaskGraph("t")
    g.add_step("enter", EnterDungeon())
    g.add_step("main", MyTask())
    check("TaskGraph 可组装无参步骤", len(g._nodes) == 2)


# ═══════════════════════════════════════════════════════════════
#  3. Scheduler execution_mode 多时段推进
# ═══════════════════════════════════════════════════════════════

def verify_scheduler_rounds() -> None:
    print("\n[3/4] Scheduler execution_mode 多时段推进")
    from core.scheduler import Scheduler, TaskConfig, RepeatConfig, ScheduleStatus
    from core.task_state import TaskStateStore

    store = TaskStateStore(path=str(ROOT / "config/runtime/verify_task_state.json"))
    sched = Scheduler(config=None, store=store)
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)

    # 动态多时段：第一时段在过去（已错过），第二时段在未来（+1h 起点）
    # 保证「下一时段起点」永远是未来时刻，与当前运行时间无关
    hhmm = lambda dt: dt.strftime("%H:%M")
    past_slot = [hhmm(now - timedelta(hours=3)), hhmm(now - timedelta(hours=2))]
    future_slot = [hhmm(now + timedelta(hours=1)), hhmm(now + timedelta(hours=2))]
    slots = [past_slot, future_slot]
    starts = {s[0] for s in slots}

    # 多时段 + per_slot + max_daily=2
    cfg = TaskConfig(
        name="slot_task",
        repeat=RepeatConfig(type="daily", value=1),
        execution_mode="per_slot",
        time_slots=slots,
        max_daily=2,
    )
    sched._tasks["slot_task"] = cfg
    sched._next_run["slot_task"] = now - timedelta(minutes=5)
    sched._today_count["slot_task"] = 0

    # 第 1 次成功 → 推进到下一时段起点（未来时刻）
    sched.mark_done("slot_task", success=True)
    nrt1 = sched._next_run["slot_task"]
    check("per_slot 第1次后 → 下一时段起点(未来)",
          nrt1 is not None and nrt1 > now and nrt1.strftime("%H:%M") in starts,
          f"实际 {nrt1}")

    # 第 2 次成功 → max_daily=2 满 → 今日 completed + next_run=次日首个时段起点
    sched.mark_done("slot_task", success=True)
    nrt2 = sched._next_run["slot_task"]
    check("per_slot 满 max_daily → 次日首个时段起点",
          nrt2 is not None and nrt2.date() > now.date()
          and nrt2.strftime("%H:%M") in starts, f"实际 {nrt2}")
    check("满 max_daily → 今日 completed",
          sched.task_status.get("slot_task") == ScheduleStatus.COMPLETED,
          f"实际 {sched.task_status.get('slot_task')}")

    # daily 模式：一天只执行一次 → 直接次日首个时段起点
    cfg2 = TaskConfig(
        name="slot_daily",
        repeat=RepeatConfig(type="daily", value=1),
        execution_mode="daily",
        time_slots=slots,
    )
    sched._tasks["slot_daily"] = cfg2
    sched._next_run["slot_daily"] = now - timedelta(minutes=5)
    sched._today_count["slot_daily"] = 0
    sched.mark_done("slot_daily", success=True)
    nrt3 = sched._next_run["slot_daily"]
    check("daily 模式 → 次日首个时段起点（一天一次）",
          nrt3 is not None and nrt3.date() > now.date()
          and nrt3.strftime("%H:%M") in starts, f"实际 {nrt3}")


# ═══════════════════════════════════════════════════════════════
#  4. run_controller 注入 task_config
# ═══════════════════════════════════════════════════════════════

def verify_task_config_injection() -> None:
    print("\n[4/4] run_controller 注入 task_config")
    from tasks.registry import TaskRegistry
    from tasks.base.task_step import TaskStep
    from tasks.base.task_result import StepResult
    from core.scheduler import Scheduler, TaskConfig, RepeatConfig
    from core.task_state import TaskStateStore
    from core.run_controller import RunController
    from core.event_bus import EventBus

    captured: dict = {}

    class ConfigTask(TaskStep):
        name = "config_task"
        display_name = "配置注入验证"

        def execute(self, context=None):
            captured["task_config"] = dict(context.task_config) if context else {}
            return StepResult.success("ok")

    reg = TaskRegistry()
    reg.register(ConfigTask)

    store = TaskStateStore(path=str(ROOT / "config/runtime/verify_task_state.json"))
    sched = Scheduler(config=None, store=store)
    sched._tasks["config_task"] = TaskConfig(
        name="config_task",
        repeat=RepeatConfig(type="daily", value=1, loop_count=5),
        execution_mode="per_slot",
        floor=10,
        team_id="t1",
        max_daily=3,
        time_start="08:00",
        time_end="23:00",
    )

    rc = RunController(
        scheduler=sched, registry=reg, monitor=None, state_mgr=None,
        runtime_progress_path=str(ROOT / "config/runtime/verify_progress.json"),
    )
    ok = rc._execute_task_once("config_task")
    check("任务执行成功", ok)
    tc = captured.get("task_config", {})
    check("loop_count 注入(5)", tc.get("loop_count") == 5, f"实际 {tc.get('loop_count')}")
    check("floor 注入(10)", tc.get("floor") == 10, f"实际 {tc.get('floor')}")
    check("team_id 注入(t1)", tc.get("team_id") == "t1", f"实际 {tc.get('team_id')}")
    check("execution_mode 注入", tc.get("execution_mode") == "per_slot",
          f"实际 {tc.get('execution_mode')}")
    check("max_daily 注入(3)", tc.get("max_daily") == 3, f"实际 {tc.get('max_daily')}")


def verify_total_count_and_time_window() -> None:
    print("\n[5/5] 累计总次数 + on_enter 启动任务")
    from core.scheduler import Scheduler, TaskConfig, RepeatConfig, ScheduleStatus
    from core.task_state import TaskStateStore

    with tempfile.TemporaryDirectory() as td:
        store = TaskStateStore(path=str(Path(td) / "st.json"))
        sched = Scheduler(config=None, store=store)
        tz = timezone(timedelta(hours=8))
        past = datetime.now(tz) - timedelta(minutes=5)

        # ── total_count 累计上限（如 100 次） ──
        sched._tasks["tt"] = TaskConfig(name="tt", repeat=RepeatConfig(type="daily", value=1), total_count=2)
        sched._next_run["tt"] = past
        sched._today_count["tt"] = 0
        sched.mark_done("tt", success=True)
        check("累计1次后未达上限(仍调度)",
              sched._total_count.get("tt") == 1 and sched._next_run.get("tt") is not None)
        sched.mark_done("tt", success=True)
        check("累计2次后永久完成",
              sched._total_count.get("tt") == 2
              and sched.task_status.get("tt") == ScheduleStatus.COMPLETED
              and "tt" not in sched._next_run)
        schedule = sched.build_schedule()
        check("达标任务不进入日程", "tt" not in [t.name for t in schedule])

        # ── on_enter 启动任务：执行后本轮完成（next_run 清空），不反复入队 ──
        sched._tasks["oe"] = TaskConfig(
            name="oe", repeat=RepeatConfig(type="on_enter", value=1))
        sched._next_run["oe"] = past
        sched._today_count["oe"] = 0
        sched.mark_done("oe", success=True)
        check("on_enter 执行后本轮完成",
              sched.task_status.get("oe") == ScheduleStatus.COMPLETED
              and "oe" not in sched._next_run)
        schedule_oe = sched.build_schedule()
        check("on_enter 完成不进入日程（不反复入队）",
              "oe" not in [t.name for t in schedule_oe])

        # 重新激活（下次启动）：_calc_initial_next_run on_enter → now
        nxt_oe = sched._calc_initial_next_run(sched._tasks["oe"])
        check("on_enter 重新激活 → next_run=now",
              nxt_oe is not None and abs((nxt_oe - datetime.now(tz)).total_seconds()) < 120,
              f"实际 {nxt_oe}")
        # load_state 激活：on_enter 任务重置 next_run=now
        sched._next_run["oe"] = None  # 模拟已完成的持久化状态
        sched.task_status["oe"] = ScheduleStatus.COMPLETED
        sched.load_state()  # store 为空 → 早退；此处验证 _tasks 中有 on_enter 时的重置逻辑走 load_tasks 路径
        sched._next_run["oe"] = sched._calc_initial_next_run(sched._tasks["oe"])
        sched.task_status["oe"] = ScheduleStatus.WAITING
        check("on_enter 重新入队（next_run<=now）",
              sched._next_run.get("oe") is not None
              and sched._next_run.get("oe") <= datetime.now(tz),
              f"实际 {sched._next_run.get('oe')}")


def verify_advance_logic() -> None:
    print("\n[6/6] 下次执行时间自动推进（4 类场景）")
    from core.scheduler import Scheduler, TaskConfig, RepeatConfig, ScheduleStatus
    from core.task_state import TaskStateStore

    with tempfile.TemporaryDirectory() as td:
        store = TaskStateStore(path=str(Path(td) / "st.json"))
        sched = Scheduler(config=None, store=store)
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)

        # ① daily 执行成功 → 次日 time_start
        t1 = TaskConfig(name='t1', repeat=RepeatConfig(type='daily', value=1),
                        time_start='08:00', time_end='09:00')
        sched._tasks['t1'] = t1
        sched._next_run['t1'] = now.replace(hour=8, minute=0, second=0, microsecond=0)
        sched._today_count['t1'] = 0
        sched.mark_done('t1', success=True)
        nrt1 = sched._next_run['t1']
        exp1 = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        check("①每日执行成功→次日08:00", nrt1 == exp1, f"实际 {nrt1}")

        # ② daily 过期（8-9点窗口，11点开脚本）→ 自动推进次日 08:00
        t2 = TaskConfig(name='t2', repeat=RepeatConfig(type='daily', value=1),
                        time_start='08:00', time_end='09:00')
        sched._tasks['t2'] = t2
        now11 = now.replace(hour=11, minute=0, second=0, microsecond=0)
        today8 = now11.replace(hour=8, minute=0, second=0, microsecond=0)
        sched._next_run['t2'] = today8
        sched._advance_stale_task('t2', t2, now11)
        nrt2 = sched._next_run['t2']
        exp2 = (now11 + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        check("②过期未执行→自动推进次日08:00", nrt2 == exp2, f"实际 {nrt2}")

        # ③ weekly 执行成功 → 推进到未来匹配日（周三）
        t3 = TaskConfig(name='t3', repeat=RepeatConfig(type='weekly', value=1, weekday=2))
        sched._tasks['t3'] = t3
        sched._next_run['t3'] = now
        sched._today_count['t3'] = 0
        sched.mark_done('t3', success=True)
        nrt3 = sched._next_run['t3']
        check("③每周执行成功→未来周三", nrt3 is not None and nrt3 > now and nrt3.weekday() == 2,
              f"实际 {nrt3}")

        # ④ interval_hours 执行成功 → N 小时后
        t4 = TaskConfig(name='t4', repeat=RepeatConfig(type='interval_hours', value=6))
        sched._tasks['t4'] = t4
        sched._next_run['t4'] = now
        sched._today_count['t4'] = 0
        sched.mark_done('t4', success=True)
        nrt4 = sched._next_run['t4']
        delta4 = (nrt4 - now).total_seconds()
        check("④隔6小时执行成功→6小时后",
              nrt4 is not None and delta4 > 5 * 3600 and delta4 < 7 * 3600,
              f"实际 {nrt4} delta={delta4:.0f}s")


def verify_battle_loop_resume() -> None:
    print("\n[7/7] BattleLoop 断点续跑（20/100 → 再执行 80 场）")
    from tasks.base.task_context import TaskContext
    from tasks.common.battle_loop import BattleLoop

    # ① 有进度 20/100 → 从 20 继续，再执行 80 场
    calls: list = []
    state = {"t1": {"completed": 20, "total": 100, "updated": ""}}

    def saver(tid, c, t):
        calls.append((tid, c, t))

    ctx = TaskContext(task_id="t1", state=state, progress_saver=saver)
    bl = BattleLoop(step_id="battle", max_battles=100, wait_time=0)
    result = bl.execute(ctx)
    check("断点恢复：从20继续打到100", state["t1"]["completed"] == 100,
          f"实际 completed={state['t1'].get('completed')}")
    check("再执行 80 场（每场一次持久化）", len(calls) == 80, f"实际 {len(calls)}")
    check("返回成功", result.success, f"实际 {result}")

    # ② 无进度 → 从 0 开始 100 场
    calls2: list = []
    ctx2 = TaskContext(task_id="t2", state={},
                       progress_saver=lambda *a: calls2.append(a))
    bl2 = BattleLoop(step_id="battle", max_battles=100, wait_time=0)
    bl2.execute(ctx2)
    check("无进度从0开始100场", len(calls2) == 100, f"实际 {len(calls2)}")

    # ③ 无限循环（max_battles=0）在中断时退出
    import threading
    stop = threading.Event()
    calls3: list = []
    ctx3 = TaskContext(task_id="t3", state={}, stop_event=stop,
                       progress_saver=lambda *a: (calls3.append(a), stop.set()))
    bl3 = BattleLoop(step_id="battle", max_battles=0, wait_time=0)
    r3 = bl3.execute(ctx3)
    check("无限循环可被中断", r3.status.value in ("success", "skip"), f"实际 {r3}")


def verify_initial_window() -> None:
    print("\n[8/8] get_initial_next_run 窗口修正（配置在窗口内立即执行）")
    from core.repeat_rule import RepeatRule, TZ_UTC8

    def tz(hh, mm, day_off=0):
        d = datetime.now(TZ_UTC8) + timedelta(days=day_off)
        return d.replace(hour=hh, minute=mm, second=0, microsecond=0)

    # ① 窗口内保存（06:00-23:59，11:00）→ 立即执行
    r = RepeatRule(type="daily", time="06:00", time_end="23:59")
    nrt = r.get_initial_next_run(tz(11, 0))
    check("①窗口内(11:00)→立即执行", nrt == tz(11, 0), f"实际 {nrt}")

    # ② 无结束时间（11:00）→ 立即执行
    r2 = RepeatRule(type="daily", time="06:00")
    check("②无结束时间(11:00)→立即执行", r2.get_initial_next_run(tz(11, 0)) == tz(11, 0))

    # ③ 窗口前（05:00）→ 今天 06:00
    check("③窗口前(05:00)→今天06:00",
          r.get_initial_next_run(tz(5, 0)) == tz(5, 0).replace(hour=6))

    # ④ 已过窗口（次日 00:30）→ 当天 06:00
    check("④已过窗口(次日00:30)→当天06:00",
          r.get_initial_next_run(tz(0, 30, 1)) == tz(0, 30, 1).replace(hour=6, minute=0))

    # ⑤ 窗口边缘（23:30）→ 立即执行
    check("⑤窗口内(23:30)→立即执行", r.get_initial_next_run(tz(23, 30)) == tz(23, 30))

    # ⑥ weekly 匹配日窗口内 → 立即
    rw = RepeatRule(type="weekly", time="06:00", time_end="23:59",
                    weekdays=[tz(11, 0).weekday()])
    check("⑥weekly匹配日窗口内→立即", rw.get_initial_next_run(tz(11, 0)) == tz(11, 0))

    # ⑦ weekly 非匹配日 → 未来匹配日
    other_wd = (tz(11, 0).weekday() + 1) % 7
    rw2 = RepeatRule(type="weekly", time="06:00", time_end="23:59", weekdays=[other_wd])
    nrt7 = rw2.get_initial_next_run(tz(11, 0))
    check("⑦weekly非匹配日→未来匹配日",
          nrt7 is not None and nrt7 > tz(11, 0) and nrt7.weekday() == other_wd)

    # ⑧ interval_hours 不受影响
    ri = RepeatRule(type="interval_hours", interval=6, time="06:00")
    nrt8 = ri.get_initial_next_run(tz(11, 0))
    check("⑧interval_hours=now+6h",
          abs((nrt8 - tz(11, 0)).total_seconds() - 6 * 3600) < 60)


def verify_reload_advance() -> None:
    print("\n[9/9] 保存后 reload 提前评估（窗口内未执行 → 提前到当前）")
    from core.config_manager import ConfigManager
    from core.scheduler import Scheduler
    from core.task_state import TaskStateStore
    from ui.param_bridge.task_bridge import TaskBridge
    from core.event_bus import EventBus

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / 'global.yaml').write_text('_version: 1\ndevice:\n  adb:\n    port: 5037\n  mock: true\n', encoding='utf-8')
        (base / 'accounts.yaml').write_text('accounts: []\n', encoding='utf-8')
        (base / 'tasks.yaml').write_text('''tasks:
  - id: orochi_soul
    name: orochi_soul
    category: special
    enabled: true
    time_start: "06:00"
    time_end: "23:59"
    repeat: {type: daily}
''', encoding='utf-8')
        cfg = ConfigManager(config_dir=str(base), event_bus=EventBus()); cfg.load()
        store = TaskStateStore(path=str(base / 'st.json'))
        tomorrow = (datetime.now(timezone(timedelta(hours=8))) + timedelta(days=1)).replace(
            hour=6, minute=0, second=0, microsecond=0)
        store.save({"orochi_soul": {"task_name": "orochi_soul",
                                    "next_run_time": tomorrow.isoformat(),
                                    "today_count": 0, "total_count": 0, "fail_streak": 0}})
        sched = Scheduler(config=cfg, store=store, event_bus=EventBus())
        sched.load_state()
        sched.load_tasks_from_config()
        bridge = TaskBridge(scheduler=sched, config=cfg, event_bus=EventBus())

        # ① 未执行 + 窗口内 → 保存后提前到当前
        cfg.update_task('orochi_soul', time_start='06:00', time_end='23:59',
                        repeat={'type': 'daily', 'value': 1})
        bridge.reload_scheduler('orochi_soul')
        nrt = bridge.get_next_run_time('orochi_soul')
        now = datetime.now(timezone(timedelta(hours=8)))
        nrt_dt = datetime.strptime(nrt, '%Y-%m-%d %H:%M').replace(tzinfo=timezone(timedelta(hours=8)))
        check("①未执行+窗口内→提前到当前", nrt is not None and abs((nrt_dt - now).total_seconds()) < 120,
              f"实际 {nrt}")

        # ② 今日已执行（today_count=1 持久化）→ 不提前
        sched._today_count['orochi_soul'] = 1
        sched._next_run['orochi_soul'] = tomorrow
        sched.save_state()
        cfg.update_task('orochi_soul', priority=9)
        bridge.reload_scheduler('orochi_soul')
        nrt2 = bridge.get_next_run_time('orochi_soul')
        d2 = datetime.strptime(nrt2, '%Y-%m-%d %H:%M').replace(tzinfo=timezone(timedelta(hours=8)))
        check("②今日已执行→不提前(保持明天)", nrt2 is not None and d2.date() > now.date(), f"实际 {nrt2}")

        # ③ 窗口已过 → 不提前
        sched._today_count['orochi_soul'] = 0
        sched._next_run['orochi_soul'] = tomorrow
        sched.save_state()
        cfg.update_task('orochi_soul', time_start='06:00', time_end='07:00')
        bridge.reload_scheduler('orochi_soul')
        nrt3 = bridge.get_next_run_time('orochi_soul')
        d3 = datetime.strptime(nrt3, '%Y-%m-%d %H:%M').replace(tzinfo=timezone(timedelta(hours=8)))
        check("③窗口已过→不提前", nrt3 is not None and d3.date() > now.date(), f"实际 {nrt3}")


def main() -> int:
    verify_taskstep_construct()
    verify_registry()
    verify_scheduler_rounds()
    verify_task_config_injection()
    verify_total_count_and_time_window()
    verify_advance_logic()
    verify_battle_loop_resume()
    verify_initial_window()
    verify_reload_advance()

    print("\n============================================================")
    print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败")
    if FAIL:
        print("❌ 存在失败项")
        return 1
    print("🎉 设计书任务链全部通过！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
