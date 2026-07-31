"""重复入队修复验证（临时）：模拟填充/执行线程竞争，确认执行中的任务不再被再次入队"""
import os, sys
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from collections import deque
from core.run_controller import RunController
from core.event_bus import EventBus


class FakeScheduler:
    """模拟调度器：任务到期，直到 mark_done 后才不再到期"""
    def __init__(self):
        self.done = False
        self.mark_done_calls = 0

    def build_schedule(self):
        return []

    def get_next_task(self):
        return "daily_test" if not self.done else None

    def mark_done(self, name, success):
        self.mark_done_calls += 1
        self.done = True


def main():
    bus = EventBus()
    sched = FakeScheduler()
    rc = RunController(scheduler=sched, event_bus=bus)
    rc.current_task = None

    def filler_once():
        """模拟填充线程单轮（与 _filler_loop 相同的去重逻辑）"""
        next_task = sched.get_next_task()
        if not next_task:
            return False
        with rc._queue_lock:
            if next_task in rc._task_queue or next_task == rc.current_task:
                return False  # 已在队列 或 正在执行 → 不入队
            rc._task_queue.append(next_task)
            return True

    # ① 初始：任务到期 → 入队
    assert filler_once() is True, "首次应入队"
    assert list(rc._task_queue) == ["daily_test"], f"got {list(rc._task_queue)}"
    print("① PASS 首次到期 → 入队")

    # ② 执行线程：popleft 出队 + 锁内设置 current_task
    with rc._queue_lock:
        t = rc._task_queue.popleft()
        if t:
            rc.current_task = t
    assert rc.current_task == "daily_test"
    assert len(rc._task_queue) == 0
    print("② PASS 出队执行中（current_task=daily_test，队列已空）")

    # ③ 执行中，填充线程再来一轮 → 修复后应【不入队】
    assert filler_once() is False, "执行中的任务不应被重复入队（BUG 修复点）"
    assert len(rc._task_queue) == 0, f"不应有重复入队, got {list(rc._task_queue)}"
    print("③ PASS 执行中任务不被重复入队（修复生效）")

    # ④ 执行完成：mark_done（next_run 推进）→ current_task=None → 不再到期
    rc._scheduler.mark_done("daily_test", True)
    rc.current_task = None
    assert filler_once() is False, "mark_done 后不应再到期"
    assert rc._scheduler.mark_done_calls == 1
    print("④ PASS mark_done 后任务不再到期，全程仅执行一次")

    print("\n🎉 重复入队修复验证 4/4 通过")


if __name__ == "__main__":
    main()
