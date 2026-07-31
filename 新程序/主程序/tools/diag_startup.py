"""启动链路诊断（临时）：跑 bootstrap.start()，检查 scheduler 状态与三个问题"""
import os, sys, traceback
from pathlib import Path

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt5.QtWidgets import QApplication


def main():
    app = QApplication(sys.argv)

    from core.bootstrap import ApplicationBootstrap
    bootstrap = ApplicationBootstrap(root_dir=Path(_PROJ_ROOT))
    try:
        ok = bootstrap.start()
        print(f"bootstrap.start() → {ok}")
    except Exception:
        traceback.print_exc()
        return

    sched = bootstrap.get("scheduler")
    if sched is None:
        print("scheduler 未初始化")
        return

    print("\n── ① 已加载任务（get_all_tasks）──")
    for c in sched.get_all_tasks():
        rep = getattr(c.repeat, 'type', '?') if c.repeat else '?'
        print(f"  {c.name}: enabled={c.enabled} repeat={rep} "
              f"next_run={sched.get_next_run_time(c.name)}")

    print("\n── ② 调度到期（build_schedule DUE）──")
    sch = sched.build_schedule(publish=False)
    if sch:
        for t in sch:
            print(f"  DUE: {t.name} next_run={t.next_run}")
    else:
        print("  （无到期任务）")

    print("\n── ③ next_run / task_status 全表 ──")
    for name in sched._tasks:
        nrt = sched._next_run.get(name)
        print(f"  {name}: _next_run={nrt} status={sched.task_status.get(name)} "
              f"today_count={sched._today_count.get(name)}")

    print("\n── ④ 已失效（get_invalid_tasks）──")
    inv = sched.get_invalid_tasks()
    if inv:
        for i in inv:
            print(f"  {i}")
    else:
        print("  （无）")

    print("\n── ⑤ 未开始（get_upcoming）──")
    up = sched.get_upcoming()
    if up:
        for u in up:
            print(f"  {u}")
    else:
        print("  （无）")

    print("\n── ⑥ TaskBridge 已失效（含禁用/待配置）──")
    bridge = bootstrap.get("bridge")
    if bridge and hasattr(bridge, 'task') and hasattr(bridge.task, 'get_invalid_tasks'):
        inv2 = bridge.task.get_invalid_tasks()
        if inv2:
            for i in inv2:
                print(f"  {i}")
        else:
            print("  （无）")
    else:
        print("  bridge.task.get_invalid_tasks 不可用")

    # 关闭
    try:
        bootstrap.shutdown()
    except Exception:
        pass


if __name__ == "__main__":
    main()
