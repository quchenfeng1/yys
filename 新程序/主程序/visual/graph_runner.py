"""
17-可视化构建模块：图执行器（P2，控制流 + 数据流 + 分支/循环）。

执行模型（4.14/4.19）：
1. 从 Start 节点沿 control 输出连线执行；
2. 分支/检查器/场景判定按条件选输出端口（true/false/out/not_found/miss/triggered）；
3. 循环：loop.out 连循环体起点，循环体末尾连回 loop.loop_back；循环结束后沿
   loop.done 继续；
4. 数据流：节点输出写入 ctx.data，供后续分支/点击器/OCR 引用。

安全：max_steps 防死循环；stop_event / cycle_limit_event 可中断。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from visual import visual_schema as vs
from visual.nodes import GraphContext, dispatch


@dataclass
class GraphRunResult:
    status: str = "success"      # success / error / interrupted / stopped
    reason: str = ""
    vars: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)
    error_message: str = ""


def _find_next(graph: dict, node_id: str, port: str) -> tuple[str | None, str | None]:
    """沿 (node_id, port) 输出端口找连线目标 → (next_id, in_port)"""
    for c in graph.get("connections", []):
        if c.get("out_node") == node_id and c.get("out_port") == port:
            return c.get("in_node"), c.get("in_port")
    return None, None


def _eval_until(condition: str, ctx: GraphContext) -> bool:
    """直到条件求值：'变量 op 值'（与分支同款比较）。

    值支持字面量（数字/文本）或变量引用（如 target 引用 vars['target']），
    便于循环次数由任务配置/变量动态驱动。
    """
    import re
    if not condition:
        return False
    m = re.match(r"([\w.]+)\s*(>=|<=|==|!=|>|<)\s*(.+)", condition)
    if not m:
        return False
    name, op, val = m.group(1), m.group(2), m.group(3).strip()
    a = ctx.get_var(name, 0)
    # 右值支持变量引用：值名存在于变量/数据流中时取其实际值
    if val in ctx.vars or val in ctx.data:
        val = ctx.get_var(val, val)
    try:
        a = float(a)
        val = float(val)
    except Exception:
        pass
    try:
        if op == ">=":
            return a >= val
        if op == "<=":
            return a <= val
        if op == "==":
            return a == val
        if op == "!=":
            return a != val
        if op == ">":
            return a > val
        if op == "<":
            return a < val
    except Exception:
        return False
    return False


def run_graph(graph: dict, ctx: GraphContext,
              max_steps: int = 100000, is_subgraph: bool = False) -> GraphRunResult:
    """执行整个节点图

    Args:
        graph: 节点图 dict
        ctx: 执行上下文
        max_steps: 防死循环最大步数
        is_subgraph: 是否为子图（operation 内联执行用）；子图 end 只结束子图
    """
    start = vs.find_node_by_type(graph, "start")
    if start is None:
        return GraphRunResult(status="error", error_message="图中缺少 Start 节点",
                              vars=ctx.vars, data=ctx.data)

    current_id: str | None = start["id"]
    loop_counters: dict[str, int] = {}
    step = 0

    while current_id:
        step += 1
        if step > max_steps:
            return GraphRunResult(status="error",
                                  error_message=f"执行步骤超限({max_steps})，疑似死循环",
                                  vars=ctx.vars, data=ctx.data)

        # 中断检查
        if ctx.stop_event is not None and ctx.stop_event.is_set():
            return GraphRunResult(status="interrupted", reason="收到停止信号",
                                  vars=ctx.vars, data=ctx.data)
        if ctx.cycle_limit_event is not None and ctx.cycle_limit_event.is_set():
            return GraphRunResult(status="interrupted", reason="活动循环次数达上限",
                                  vars=ctx.vars, data=ctx.data)

        node = vs.find_node(graph, current_id)
        if node is None:
            return GraphRunResult(status="error",
                                  error_message=f"节点不存在: {current_id}",
                                  vars=ctx.vars, data=ctx.data)

        # 每次从 in 端口进入 loop → 重置该循环计数。
        # （loop_back 路径在下方回跳逻辑处理，能到主循环顶部的 loop 必是从 in 进入，
        #   保证嵌套循环内层每轮都从 0 重新计数）
        if node.get("type") == "loop":
            loop_counters[node["id"]] = 0

        result = dispatch(node, ctx)

        # 数据流收集（节点输出 → ctx.data，供后续引用）
        if result.data:
            ctx.data.update(result.data)

        if result.status == "end":
            return GraphRunResult(status="success", reason=result.message or "任务结束",
                                  vars=ctx.vars, data=ctx.data)
        if result.status == "error":
            return GraphRunResult(status="error",
                                  error_message=result.message,
                                  vars=ctx.vars, data=ctx.data)
        if result.status == "interrupted":
            return GraphRunResult(status="interrupted", reason=result.message,
                                  vars=ctx.vars, data=ctx.data)

        goto = result.goto or "out"
        next_id, in_port = _find_next(graph, current_id, goto)

        # 循环回跳处理：目标是 loop 且进入端口为 loop_back。
        # 用 while 支持嵌套循环——内层 loop.done 连到外层 loop.loop_back 时，
        # 需要继续按外层 loop 的回跳逻辑处理（计数/条件判断），否则外层永不退出。
        while next_id is not None and in_port == "loop_back":
            next_node = vs.find_node(graph, next_id)
            if next_node is None or next_node.get("type") != "loop":
                break
            lid = next_id
            loop_counters[lid] = loop_counters.get(lid, 0) + 1
            params = next_node.get("params", {})
            mode = params.get("mode", "固定次数")
            max_count = int(params.get("count", 3))
            if mode == "直到条件":
                if _eval_until(params.get("condition", ""), ctx):
                    next_id, in_port = _find_next(graph, lid, "done")
                else:
                    next_id, in_port = _find_next(graph, lid, "out")
            elif loop_counters[lid] >= max_count:
                next_id, in_port = _find_next(graph, lid, "done")
            else:
                next_id, in_port = _find_next(graph, lid, "out")

        if next_id is None:
            # goto 端口无连线 → 图自然结束
            break
        current_id = next_id

    return GraphRunResult(status="success", reason="流程结束",
                          vars=ctx.vars, data=ctx.data)
