"""综合诊断：加载真实 tasks.yaml 的 5 个任务，检查各任务的调度到期行为。

对每个任务：
  1. 初始 next_run / status（「未开始」判定）
  2. 模拟「到期」：把 next_run 设为过去（窗口内）→ build_schedule 是否判 DUE
  3. 模拟 mark_done 后：next_run 推进情况
  4. 识别"运行中不会自动到期"的任务（on_enter/trigger 设计语义）
"""
import os, sys, yaml
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from core.events import Events
from core.scheduler import Scheduler, ScheduleStatus


def to_ns(d):
    """dict → SimpleNamespace（递归）"""
    if isinstance(d, dict):
        return SimpleNamespace(**{k: to_ns(v) for k, v in d.items()})
    if isinstance(d, list):
        return [to_ns(x) for x in d]
    return d


def main():
    from core.event_bus import EventBus

    bus = EventBus()
    yaml_path = Path(_PROJ_ROOT) / "config" / "tasks.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    tasks = [to_ns(t) for t in data.get("tasks", [])]

    fake_cfg = SimpleNamespace(tasks_config=SimpleNamespace(tasks=tasks))
    sched = Scheduler(event_bus=bus, config=fake_cfg, state_manager=None, store=None)
    sched.load_tasks_from_config()

    now = datetime.now(sched._timezone)
    print(f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}  {sched._timezone}\n")

    print(f"{'任务':<20}{'类型':<10}{'初始next_run':<24}{'初始状态':<10}")
    for name in sched._tasks:
        cfg = sched._tasks[name]
        rtype = cfg.repeat.type if cfg.repeat else "?"
        nrt = sched._next_run.get(name)
        st = sched.task_status.get(name, ScheduleStatus.WAITING)
        nrt_s = nrt.strftime("%m-%d %H:%M") if nrt else "None(无)"
        print(f"{name:<20}{rtype:<10}{nrt_s:<24}{st.value:<10}")

    print("\n── 模拟「到期」（next_run → 过去 1 分钟，窗口内）──")
    for name in list(sched._tasks):
        cfg = sched._tasks[name]
        rtype = cfg.repeat.type if cfg.repeat else "?"
        if rtype in ("trigger", "on_enter", "once"):
            # 这类任务 next_run 恒 None，无法"到期"
            nrt = sched._next_run.get(name)
            if nrt is None:
                print(f"{name:<20}[{rtype:<8}] next_run=None → 不会自动到期"
                      f"（设计：需外部激活）")
                continue
        sched._next_run[name] = now - timedelta(minutes=1)
        sched.task_status[name] = ScheduleStatus.WAITING
        due = sched.build_schedule(publish=False)
        names = [t.name for t in due]
        flag = "✅ 自动到期" if name in names else "❌ 到期不被拾取!"
        print(f"{name:<20}[{rtype:<8}] next_run=过去1分钟 → DUE={name in names}  {flag}")

    print("\n── mark_done 后 next_run 推进 ──")
    for name in sched._tasks:
        cfg = sched._tasks[name]
        rtype = cfg.repeat.type if cfg.repeat else "?"
        if rtype in ("trigger", "on_enter", "once"):
            print(f"{name:<20}[{rtype:<8}] 执行后 next_run 清空 → 需外部激活（设计）")
            continue
        sched._next_run[name] = now - timedelta(minutes=1)
        sched.task_status[name] = ScheduleStatus.WAITING
        sched.mark_done(name, True)
        nrt = sched._next_run.get(name)
        st = sched.task_status.get(name)
        nrt_s = nrt.strftime("%m-%d %H:%M") if nrt else "None"
        print(f"{name:<20}[{rtype:<8}] mark_done后 status={st.value:<9} next_run={nrt_s}")


if __name__ == "__main__":
    main()
