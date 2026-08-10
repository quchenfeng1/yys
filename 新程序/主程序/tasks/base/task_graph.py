"""
04-任务执行引擎

TaskGraph 步骤图引擎（DAG + 执行逻辑 + 错误恢复 + 熔断）。
对应设计书 §3.1/§4.1/§4.5/§4.7/§5.2/§5.3/§5.4/§5.5。
"""
from __future__ import annotations

import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from core.event_bus import get_global_bus
from core.events import Events
from core.exceptions import TaskError, TaskInterrupted
from tasks.base.task_result import TaskResult, TaskStatus
from tasks.base.task_step import StepResult, StepStatus


class EdgeType(str, Enum):
    """边类型（§5.2）"""
    NORMAL = "normal"       # 成功→下一步
    ERROR = "error"         # 失败→错误处理
    SKIP = "skip"           # 跳过→跳过处理
    CONDITIONAL = "conditional"  # 条件判断


@dataclass
class Edge:
    """步骤边（§5.2）"""
    from_step: str
    to_step: str
    edge_type: EdgeType = EdgeType.NORMAL
    condition: Callable[[Any, StepResult], bool] | None = None  # 仅 CONDITIONAL 使用


@dataclass
class GraphNode:
    """图节点"""
    step_id: str
    dependencies: list[str] = field(default_factory=list)
    step: Any = None  # TaskStep 实例
    metadata: dict[str, Any] = field(default_factory=dict)


class TaskGraph:
    """任务步骤图（DAG 执行引擎，§5.3）"""

    def __init__(self, max_fail_streak: int = 5):
        # 说明书 §2.3 要求属性名
        self._nodes: dict[str, GraphNode] = {}
        self._steps = self._nodes  # 说明书 §2.3 别名
        self._edges: dict[str, list[str]] = {}  # from_step -> [to_step]（依赖顺序）
        self._edge_defs: dict[str, list[Edge]] = {}  # from_step -> [Edge]（完整边定义）
        self._edges_typed = self._edge_defs  # 说明书 §2.3 别名
        self._entry_step: str = ""
        self._entry = self._entry_step  # 说明书 §2.3 别名
        self._bus = get_global_bus()

        # 熔断状态（§2.3）
        self._fail_streak: int = 0
        self._max_fail_streak: int = max_fail_streak
        self._start_time: float = 0.0

        # 运行时状态（§2.2 对外暴露）
        self.current_task: str = ""
        self.current_step: str = ""
        self.task_progress: str = ""  # 设计书要求 str 类型（如 "15/30"）
        self.step_result: StepResult | None = None

    # ── 构建 ──────────────────────────────────────────────────

    def add_step(self, name: str, step: Any, dependencies: list[str] | None = None) -> None:
        """添加步骤（§5.3）"""
        self._nodes[name] = GraphNode(step_id=name, step=step, dependencies=dependencies or [])
        for dep in (dependencies or []):
            self._edges.setdefault(dep, []).append(name)

    def add_edge(self, from_step: str, to_step: str,
                 edge_type: EdgeType = EdgeType.NORMAL,
                 condition: Callable[[Any, StepResult], bool] | None = None) -> None:
        """添加边（§5.3），condition 为可调用函数 (context, StepResult) -> bool"""
        edge = Edge(from_step=from_step, to_step=to_step,
                    edge_type=edge_type, condition=condition)
        self._edge_defs.setdefault(from_step, []).append(edge)

    def set_entry(self, name: str) -> None:
        """设置入口步骤（§5.3）"""
        self._entry_step = name

    # ── 执行 ──────────────────────────────────────────────────

    def run(self, context: Any = None) -> TaskResult:
        """
        执行步骤图（§5.3 run 方法 + §3.1 步骤循环）。

        寻边规则（§5.2）：
          优先匹配 StepResult.next_step（显式指定）；
          若为 None，依次检查当前步骤的所有出边：
            conditional → 评估 condition 函数
            skip       → 检查 StepResult.status==skip
            error      → 检查 status==fail
            normal     → 默认 fallback
          若无可匹配边，任务结束返回 success。
        """
        self.current_task = getattr(context, 'task_id', '') if context else ''
        self._start_time = time.time()
        self._fail_streak = 0
        self.step_result = None

        # 熔断阈值：优先 task_config.max_fail_streak（UI「失败容忍」配置），
        # 未配置时用构造默认（5）。此前该值从不注入，UI 配置不生效。
        try:
            _tc = getattr(context, 'task_config', None) or {}
            _mfs = _tc.get("max_fail_streak")
            if _mfs is not None:
                self._max_fail_streak = int(_mfs)
        except (TypeError, ValueError):
            pass
        results: list[StepResult] = []
        total = len(self._nodes)  # 提前定义，防止 while 不执行时 NameError

        # 从入口步骤开始
        current_step_id = self._entry_step
        if not current_step_id:
            # 无入口则拓扑序
            order = self.get_execution_order()
            current_step_id = order[0] if order else ""

        while current_step_id:
            # [步骤边界] 检查中断
            if self._check_interrupt(context):
                self._bus.publish(Events.EXECUTOR_STEP_FAILED, source="task_graph",
                                 step_id=current_step_id, error="任务被中断")
                break

            # [步骤边界] 检查超时
            if self._check_timeout(context):
                self._bus.publish(Events.EXECUTOR_STEP_FAILED, source="task_graph",
                                 step_id=current_step_id, error="任务超时")
                break

            self.current_step = current_step_id

            node = self._nodes.get(current_step_id)
            if not node or not node.step:
                break

            # 执行步骤
            step_result = self._execute_step(node.step, context)
            results.append(step_result)
            self.step_result = step_result

            # 更新进度字符串（步骤完成后，保证最终步骤显示正确进度）
            completed = len([r for r in results if r.status == StepStatus.SUCCESS])
            self.task_progress = f"{completed}/{total}"

            # [步骤边界] 失败 → 阶梯式错误恢复（§4.7 + §5.4）
            if step_result.status == StepStatus.FAIL:
                recovery = self._handle_error(context, current_step_id, step_result)
                if recovery is None:
                    # 熔断：连续失败超过阈值，跳过此任务
                    break
                if recovery.status == StepStatus.RETRY:
                    # 恢复成功 → 重试当前步骤
                    continue
                # 恢复失败 → 用 recovery 结果继续寻边
                step_result = recovery

            # 寻边：确定下一步
            next_step_id = self._resolve_next_step(current_step_id, step_result, context)
            if next_step_id is None:
                break  # 无下一步，任务结束
            current_step_id = next_step_id

        # 判断最终状态
        if self._check_interrupt(context):
            final_status = TaskStatus.ABORTED
        elif self._check_timeout(context):
            final_status = TaskStatus.TIMEOUT
        elif any(r.status == StepStatus.FAIL for r in results):
            final_status = TaskStatus.FAIL
        else:
            final_status = TaskStatus.SUCCESS

        return TaskResult(
            task_id=self.current_task,
            status=final_status,
            reason=f"完成 {len([r for r in results if r.status == StepStatus.SUCCESS])}/{total} 步",
            duration=time.time() - self._start_time,
        )

    def _resolve_next_step(self, from_step: str, result: StepResult, context: Any) -> str | None:
        """
        寻边规则（§5.2）。
        返回下一步骤名，None 表示结束。
        """
        # 1. 显式指定
        if result.next_step:
            return result.next_step

        edges = self._edge_defs.get(from_step, [])
        if not edges:
            # 无出边 → 检查是否有自然后继（拓扑序）
            successors = self._edges.get(from_step, [])
            return successors[0] if successors else None

        # 2. 按优先级检查各类型边
        # 先收集 conditional
        conditional_matches = [e for e in edges if e.edge_type == EdgeType.CONDITIONAL]
        for edge in conditional_matches:
            if edge.condition and edge.condition(context, result):
                return edge.to_step

        # skip 边
        if result.status == StepStatus.SKIP:
            for edge in edges:
                if edge.edge_type == EdgeType.SKIP:
                    return edge.to_step

        # error 边
        if result.status == StepStatus.FAIL:
            for edge in edges:
                if edge.edge_type == EdgeType.ERROR:
                    return edge.to_step

        # normal 边（默认 fallback，FAIL 状态不匹配 normal）
        if result.status != StepStatus.FAIL:
            for edge in edges:
                if edge.edge_type == EdgeType.NORMAL:
                    return edge.to_step

        return None

    def _probe_scene(self, context: Any, step: Any) -> None:
        """场景感知步骤（§4.9 scene_probe）：步骤执行前静默探测当前位置。

        仅当步骤声明 scene_probe 且执行器支持 probe_scene 时生效；
        素材缺失/异常/未声明 → 静默跳过，零影响。
        """
        probe = getattr(step, 'scene_probe', None)
        if not probe:
            return
        executor = getattr(context, 'executor', None) if context else None
        if executor is None or not hasattr(executor, 'probe_scene'):
            return
        try:
            executor.probe_scene(list(probe), timeout=0)
        except Exception:
            pass

    def _log(self, level: str, message: str, task: str = "") -> None:
        """模块级日志：发布 LOG_RECORD（UI 日志面板可见），兜底 print"""
        try:
            self._bus.publish(Events.LOG_RECORD, source="task_graph", level=level,
                              message=message, task=task, step=self.current_step)
        except Exception:
            print(f"[{level}] {message}")

    def _execute_step(self, step: Any, context: Any) -> StepResult:
        """执行单步（含重试，§5.3 + §5.4）。
        使用 step.run() 确保计时信息被正确设置。
        """
        # [场景感知] 步骤声明 scene_probe → 静默探测当前位置（§4.9，零影响）
        self._probe_scene(context, step)

        max_retries = getattr(step, 'retry_count', 0)
        step_id = getattr(step, 'step_id', '') or getattr(step, 'name', '')
        task_name = getattr(context, 'task_id', '') if context else ''
        self._log("info", f"[04-任务引擎] ▶ 步骤开始: {step_id}", task=task_name)
        for attempt in range(max(1, max_retries + 1)):
            try:
                # 使用 run() 而非 execute()，确保 step_id/duration 被设置
                result = step.run(context)

                _status = result.status.value if hasattr(result, 'status') else 'unknown'
                _msg = str(result.message) if getattr(result, 'message', '') else ''
                self._log("info",
                          f"[04-任务引擎] 步骤完成: {step_id} → {_status}"
                          f"{' · ' + _msg if _msg else ''}",
                          task=task_name)

                self._bus.publish(Events.EXECUTOR_STEP_COMPLETED, source="task_graph",
                                 step_id=result.step_id or getattr(step, 'step_id', ''),
                                 attempt=attempt,
                                 status=result.status.value if hasattr(result, 'status') else 'unknown')

                # run() 内已将异常转为 FAIL；据此判断是否重试
                if result.status == StepStatus.FAIL and attempt < max_retries:
                    self._bus.publish(Events.EXECUTOR_STEP_RETRY, source="task_graph",
                                     step_id=result.step_id or getattr(step, 'step_id', ''),
                                     attempt=attempt, error=result.message)
                    time.sleep(1)
                    continue

                if result.status == StepStatus.FAIL:
                    # 最后一次尝试失败后调用 cleanup
                    if hasattr(step, 'cleanup'):
                        try:
                            step.cleanup(context)
                        except Exception:
                            pass

                return result

            except TaskInterrupted:
                raise

            except Exception as e:
                # run() 理论上会捕获所有异常，此处为兜底
                if attempt < max_retries:
                    self._bus.publish(Events.EXECUTOR_STEP_RETRY, source="task_graph",
                                     step_id=getattr(step, 'step_id', ''),
                                     attempt=attempt, error=str(e))
                    time.sleep(1)
                    continue

                if hasattr(step, 'cleanup'):
                    try:
                        step.cleanup(context)
                    except Exception:
                        pass

                return StepResult(
                    step_id=getattr(step, 'step_id', ''),
                    status=StepStatus.FAIL,
                    message=str(e),
                )

        return StepResult(
            step_id=getattr(step, 'step_id', ''),
            status=StepStatus.FAIL,
            message="重试耗尽",
        )

    def _check_interrupt(self, context: Any) -> bool:
        """检查 stop_event（§5.3 _check_interrupt）"""
        if context and hasattr(context, 'stop_event') and context.stop_event:
            if context.stop_event.is_set():
                return True
        # 兼容旧版 BaseTask._interrupted
        if context and hasattr(context, 'task') and context.task:
            if getattr(context.task, '_interrupted', False):
                return True
        return False

    def _check_timeout(self, context: Any) -> bool:
        """检查任务级超时（§3.1 步骤边界检查）"""
        if not context or not hasattr(context, 'timeout') or not context.timeout:
            return False
        if not self._start_time:
            return False
        return (time.time() - self._start_time) > context.timeout

    def _handle_error(self, context: Any, step_id: str, result: StepResult) -> StepResult | None:
        """
        阶梯式错误恢复 + 熔断（§4.7 + §5.4）。

        调用路径：TaskGraph.run() 在 StepResult.status==FAIL 时调用。
        返回 StepResult 表示恢复后的结果，None 表示已熔断跳过。
        """
        self._fail_streak += 1
        self._bus.publish(Events.EXECUTOR_STEP_FAILED, source="task_graph",
                         step_id=step_id, error=result.message,
                         fail_streak=self._fail_streak)

        # ── 熔断检查 ──────────────────────────────────────────
        if self._fail_streak >= self._max_fail_streak:
            self._bus.publish(Events.EXECUTOR_STEP_FAILED, source="task_graph",
                             step_id=step_id,
                             error=f"连续失败{self._fail_streak}次，熔断跳过任务")
            return None

        # ── 阶梯式恢复 ────────────────────────────────────────
        executor = getattr(context, 'executor', None) if context else None

        try:
            if executor and hasattr(executor, 'detect_scene'):
                # 截图保存现场
                if hasattr(executor, 'screenshot'):
                    executor.screenshot()

                # 场景检测
                scene = executor.detect_scene(["courtyard", "battle", "popup", "login"])

                # 根据场景选择恢复路径
                if scene == "courtyard":
                    # 庭院 → 直接重试
                    return StepResult(
                        step_id=step_id,
                        status=StepStatus.RETRY,
                        message=f"场景=庭院，重试步骤 {step_id}",
                    )

                elif scene == "battle":
                    # 战斗中 → 等待结算 → 返回庭院
                    if hasattr(executor, 'wait_any'):
                        executor.wait_any(["victory", "defeat"], timeout=120)
                    if hasattr(executor, 'click_if_exists'):
                        executor.click_if_exists("confirm")
                    if hasattr(executor, 'ensure_scene'):
                        executor.ensure_scene("courtyard", timeout=30)
                    return StepResult(
                        step_id=step_id,
                        status=StepStatus.RETRY,
                        message=f"场景=战斗中，等待结算后重试",
                    )

                elif scene == "popup":
                    # 弹窗 → 关闭 → 重试
                    if hasattr(executor, 'click_if_exists'):
                        executor.click_if_exists("close_btn")
                    return StepResult(
                        step_id=step_id,
                        status=StepStatus.RETRY,
                        message=f"场景=弹窗，关闭后重试",
                    )

                elif scene == "login":
                    # 登录界面 → 游戏断开 → 标记不可恢复
                    return StepResult(
                        step_id=step_id,
                        status=StepStatus.FAIL,
                        message="游戏断开连接，登录界面",
                    )

            # ── 未知场景 → 保护模式（§5.4）────────────────────
            if executor:
                # 通用退出序列
                if hasattr(executor, 'click_if_exists'):
                    if executor.click_if_exists("close_btn"):
                        return StepResult(step_id=step_id, status=StepStatus.RETRY,
                                         message="保护模式：关闭弹窗后重试")
                if hasattr(executor, 'input_key'):
                    executor.input_key("BACK")
                    if hasattr(executor, 'ensure_scene'):
                        if executor.ensure_scene("courtyard", timeout=5):
                            return StepResult(step_id=step_id, status=StepStatus.RETRY,
                                             message="保护模式：返回庭院后重试")

            # 所有恢复尝试均失败
            return StepResult(
                step_id=step_id,
                status=StepStatus.FAIL,
                message=f"错误恢复失败 (fail_streak={self._fail_streak})",
            )

        except Exception as e:
            self._bus.publish(Events.EXECUTOR_STEP_FAILED, source="task_graph",
                             step_id=step_id, error=f"错误恢复异常: {e}")
            return StepResult(
                step_id=step_id,
                status=StepStatus.FAIL,
                message=f"错误恢复异常: {e}",
            )

    # ── 拓扑排序 ──────────────────────────────────────────────

    def get_execution_order(self) -> list[str]:
        """拓扑排序（用于依赖分析，run() 实际使用寻边驱动）"""
        in_degree = {nid: len(n.dependencies) for nid, n in self._nodes.items()}
        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
        if self._entry_step and self._entry_step not in queue:
            queue.appendleft(self._entry_step)

        result = []
        while queue:
            nid = queue.popleft()
            result.append(nid)
            for dep_id in self._edges.get(nid, []):
                in_degree[dep_id] -= 1
                if in_degree[dep_id] == 0:
                    queue.append(dep_id)

        if len(result) != len(self._nodes):
            raise TaskError("循环依赖")
        return result

    def get_dependents(self, step_id: str) -> list[str]:
        return self._edges.get(step_id, [])

    def get_dependencies(self, step_id: str) -> list[str]:
        node = self._nodes.get(step_id)
        return list(node.dependencies) if node else []

    @property
    def size(self) -> int:
        return len(self._nodes)

    def clear(self):
        self._nodes.clear()
        self._edges.clear()
        self._edge_defs.clear()
        self._fail_streak = 0
