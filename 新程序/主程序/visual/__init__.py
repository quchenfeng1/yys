"""
17-可视化构建模块（visual 子包）。

高内聚独立子包：数据结构 / 节点库 / 图执行器 / 可视化任务运行时 / 存储 /
示教引擎。对外只暴露少量接口，通过 EventBus 与主程序解耦。

可选加载：不进入可视化构建时零占用（惰性 import）。
"""
from visual.visual_schema import (
    default_task, load_task, save_task, normalize_task,
    new_node, new_connection, default_graph,
    find_node, find_node_by_type,
    add_scene, add_point, add_ocr_region,
    find_scene, find_point, find_ocr_region,
)
from visual.node_defs import NODE_DEFS, get_node_def, default_params
from visual.visual_task import VisualTask
from visual.rule_store import VisualTaskStore

__all__ = [
    "default_task", "load_task", "save_task", "normalize_task",
    "new_node", "new_connection", "default_graph",
    "find_node", "find_node_by_type",
    "add_scene", "add_point", "add_ocr_region",
    "find_scene", "find_point", "find_ocr_region",
    "NODE_DEFS", "get_node_def", "default_params",
    "VisualTask", "VisualTaskStore",
]
