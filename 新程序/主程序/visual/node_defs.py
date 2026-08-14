"""
17-可视化构建模块：节点类型库（P2，元数据驱动，4.19）。

节点类型 = 通用原语（骨架零游戏内容，4.24）：
  感知：matcher / ocr_reader / scene_probe / scroll_capture
  操作：clicker / dragger / refresher / navigator / set_var
  逻辑：branch / loop / counter / checker
  控制：start / end

新增节点 = 新增一个 dict（params widget 由 UI 动态渲染）。
"""
from __future__ import annotations

from typing import Any

# ── 端口类型 ─────────────────────────────────────────────────
PORT_CONTROL = "control"   # 控制流（执行顺序）
PORT_SCENE = "scene"       # 场景判定结果（scene id）
PORT_TEXT = "text"         # OCR 文本
PORT_VALUE = "value"       # 数值/变量
PORT_POINT = "point"       # 坐标
PORT_IMAGE = "image"       # 截图


def _ctrl(port_name: str = "in") -> dict:
    return {"name": port_name, "port_type": PORT_CONTROL}


# ── 节点定义注册表 ───────────────────────────────────────────
NODE_DEFS: dict[str, dict] = {
    # ═══ 控制 ═══
    "start": {
        "type": "start", "label": "开始", "category": "控制",
        "inputs": [],
        "outputs": [_ctrl("out")],
        "params": [],
        "description": "任务入口（每个图一个）",
    },
    "end": {
        "type": "end", "label": "结束", "category": "控制",
        "inputs": [_ctrl("in")],
        "outputs": [],
        "params": [
            {"name": "finish_mode", "label": "结束方式", "widget": "combo",
             "options": ["结束任务", "返回主菜单"], "default": "结束任务"},
        ],
        "description": "任务结束",
    },
    # ═══ 感知 ═══
    "scene_probe": {
        "type": "scene_probe", "label": "场景判定", "category": "感知",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out"), _ctrl("not_found")],
        "params": [
            {"name": "scene", "label": "场景", "widget": "combo_scene", "default": ""},
            {"name": "timeout", "label": "超时(秒)", "widget": "spinbox", "default": 3,
             "min": 0, "max": 60},
            {"name": "output_var", "label": "输出变量", "widget": "text", "default": ""},
        ],
        "description": "判定当前界面=示教场景；命中写 1 / 未命中写 0 到输出变量；命中走 out，未命中走 not_found",
    },
    "matcher": {
        "type": "matcher", "label": "识图器", "category": "感知",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out"), _ctrl("miss")],
        "params": [
            {"name": "template", "label": "目标元素", "widget": "combo_element",
             "default": ""},
            {"name": "index", "label": "第几个(0=首个)", "widget": "spinbox",
             "default": 0, "min": 0, "max": 20},
            {"name": "threshold", "label": "阈值", "widget": "spinbox",
             "default": 0.85, "min": 0.0, "max": 1.0, "step": 0.01},
            {"name": "timeout", "label": "超时(秒)", "widget": "spinbox",
             "default": 3, "min": 0, "max": 60},
        ],
        "description": "识别某元素；命中走 out（输出坐标），未命中走 miss；index 选第 N 个同名匹配",
    },
    "ocr_reader": {
        "type": "ocr_reader", "label": "OCR读取", "category": "感知",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out"), _ctrl("miss")],
        "params": [
            {"name": "region", "label": "文字区域", "widget": "combo_ocr_region",
             "default": ""},
            {"name": "keyword", "label": "关键词", "widget": "text", "default": ""},
            {"name": "output_var", "label": "输出变量", "widget": "text", "default": ""},
        ],
        "description": "读取区域文字；含关键词走 out，否则 miss；文本存变量",
    },
    "scroll_capture": {
        "type": "scroll_capture", "label": "滚动捕获", "category": "感知",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "direction", "label": "方向", "widget": "combo",
             "options": ["up", "down", "left", "right"], "default": "up"},
            {"name": "steps", "label": "步数", "widget": "spinbox", "default": 3,
             "min": 1, "max": 20},
        ],
        "description": "滚动多屏并拼接全景（供后续标注/识别）",
    },
    # ═══ 操作 ═══
    "clicker": {
        "type": "clicker", "label": "点击器", "category": "操作",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "mode", "label": "点击方式", "widget": "combo",
             "options": ["固定点", "随机点", "识别坐标"], "default": "固定点"},
            {"name": "point", "label": "点击目标", "widget": "combo_point", "default": ""},
            {"name": "offset", "label": "偏移(px)", "widget": "spinbox", "default": 10,
             "min": 0, "max": 100},
        ],
        "description": "固定点：点示教点；随机点：屏幕随机；识别坐标：点击上游识图器输出的坐标中心",
    },
    "dragger": {
        "type": "dragger", "label": "拖拽器", "category": "操作",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "direction", "label": "方向", "widget": "combo",
             "options": ["up", "down", "left", "right"], "default": "up"},
            {"name": "distance", "label": "距离(0~1)", "widget": "spinbox",
             "default": 0.6, "min": 0.0, "max": 1.0, "step": 0.05},
            {"name": "duration_ms", "label": "时长(ms)", "widget": "spinbox",
             "default": 600, "min": 0, "max": 3000},
        ],
        "description": "滑动屏幕（方向+距离）",
    },
    "refresher": {
        "type": "refresher", "label": "刷新器", "category": "操作",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "swipe", "label": "下拉刷新", "widget": "checkbox", "default": True},
        ],
        "description": "刷新列表（下拉）",
    },
    "operation": {
        "type": "operation", "label": "操作", "category": "操作",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "operation", "label": "通用操作", "widget": "combo_operation",
             "default": ""},
        ],
        "description": "调用通用操作（可复用参数化子图，4.26）；选中操作后动态填充其输入参数",
    },
    "navigator": {
        "type": "navigator", "label": "导航器", "category": "操作",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "action", "label": "动作", "widget": "combo",
             "options": ["返回主界面", "关闭弹窗", "重启游戏"], "default": "返回主界面"},
            {"name": "package", "label": "游戏包名", "widget": "text", "default": ""},
        ],
        "description": "通用导航动作；重启游戏需填游戏包名",
    },
    "set_var": {
        "type": "set_var", "label": "变量设置", "category": "操作",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "var_name", "label": "变量名", "widget": "text", "default": ""},
            {"name": "var_value", "label": "值", "widget": "text", "default": ""},
        ],
        "description": "设置任务变量（文本/数字）",
    },
    "wait": {
        "type": "wait", "label": "等待", "category": "操作",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "seconds", "label": "秒数", "widget": "spinbox", "default": 1,
             "min": 0, "max": 60},
        ],
        "description": "等待固定秒数",
    },
    # ═══ 逻辑 ═══
    "branch": {
        "type": "branch", "label": "分支", "category": "逻辑",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("true"), _ctrl("false")],
        "params": [
            {"name": "condition", "label": "条件", "widget": "text", "default": ""},
            {"name": "op", "label": "比较", "widget": "combo",
             "options": [">=", "<=", "==", "!=", ">", "<", "存在", "不存在"],
             "default": ">="},
            {"name": "value", "label": "目标值", "widget": "text", "default": "0"},
            {"name": "data_source", "label": "数据源", "widget": "text", "default": ""},
        ],
        "description": "按条件走 true / false 两路；data_source 引用变量或 OCR 区域",
    },
    "loop": {
        "type": "loop", "label": "循环", "category": "逻辑",
        "inputs": [_ctrl("in"), _ctrl("loop_back")],
        "outputs": [_ctrl("out"), _ctrl("done")],
        "params": [
            {"name": "mode", "label": "模式", "widget": "combo",
             "options": ["固定次数", "直到条件"], "default": "固定次数"},
            {"name": "count", "label": "次数", "widget": "spinbox", "default": 3,
             "min": 1, "max": 999},
            {"name": "condition", "label": "条件(直到)", "widget": "text", "default": ""},
        ],
        "description": "out 连循环体起点，循环体末尾连回 loop_back；done 连循环结束后续",
    },
    "counter": {
        "type": "counter", "label": "计数器", "category": "逻辑",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "var_name", "label": "变量名", "widget": "text", "default": ""},
            {"name": "delta", "label": "增量", "widget": "spinbox", "default": 1,
             "min": -999, "max": 999},
        ],
        "description": "变量 += delta",
    },
    "checker": {
        "type": "checker", "label": "检查器", "category": "逻辑",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out"), _ctrl("triggered")],
        "params": [
            {"name": "condition", "label": "条件", "widget": "text", "default": ""},
            {"name": "action", "label": "处理动作", "widget": "combo",
             "options": ["返回主菜单", "等待", "跳过"], "default": "返回主菜单"},
        ],
        "description": "旁路拦截：条件成立走 triggered，否则 out",
    },
}


def get_node_def(node_type: str) -> dict | None:
    return NODE_DEFS.get(node_type)


def node_types() -> list[str]:
    return list(NODE_DEFS.keys())


def node_labels() -> dict[str, str]:
    return {t: d["label"] for t, d in NODE_DEFS.items()}


def categories() -> list[str]:
    """节点分类（节点库分组）"""
    cats: list[str] = []
    for d in NODE_DEFS.values():
        if d["category"] not in cats:
            cats.append(d["category"])
    return cats


def default_params(node_type: str) -> dict[str, Any]:
    """节点类型默认参数（UI 新建节点时填充）"""
    d = get_node_def(node_type)
    if not d:
        return {}
    out = {}
    for p in d.get("params", []):
        out[p["name"]] = p.get("default", "")
    return out


def validate_node(node: dict) -> list[str]:
    """校验节点：类型存在、必填参数齐全。返回错误列表（空=合法）。"""
    errors: list[str] = []
    ntype = node.get("type", "")
    d = get_node_def(ntype)
    if d is None:
        errors.append(f"未知节点类型: {ntype}")
        return errors
    for p in d.get("params", []):
        if p.get("required"):
            if not node.get("params", {}).get(p["name"]):
                errors.append(f"节点[{node.get('name', ntype)}] 缺少参数 {p['name']}")
    return errors
