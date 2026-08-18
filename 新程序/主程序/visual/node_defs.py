"""
17-可视化构建模块：节点类型库（P2，元数据驱动，4.19）。

节点类型 = 通用原语（骨架零游戏内容，4.24）：
  感知：ocr_reader / scene_probe / scroll_capture
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
    "scene_trigger": {
        "type": "scene_trigger", "label": "信号触发器", "category": "控制",
        "inputs": [],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "scene", "label": "监听信号", "widget": "combo_signal", "default": ""},
        ],
        "description": "信号触发器：下拉列出本任务场景素材对应的信号（场景保存时的信号名），全局场景信号表命中该场景信号时被激活，从 out 开始执行场景内逻辑；不接受控制流连线进入",
    },
    # ═══ 变量 ═══
    "variable_group": {
        "type": "variable_group", "label": "变量组", "category": "变量",
        "inputs": [],
        "outputs": [],
        "params": [
            {"name": "group_name", "label": "变量组名", "widget": "text",
             "default": "变量组1"},
            {"name": "variables", "label": "变量定义", "widget": "button",
             "default": []},
        ],
        "description": "变量组（不参与执行流）：定义运行时变量（显示名/变量键/类型/默认值），\n点【详情】编辑；放置后在「变量配置」页可填写实际值，其它节点用 ${变量键} 引用",
    },
    "constant_group": {
        "type": "constant_group", "label": "常量组", "category": "变量",
        "inputs": [],
        "outputs": [],
        "params": [
            {"name": "group_name", "label": "常量组名", "widget": "text",
             "default": "常量组1"},
            {"name": "variables", "label": "常量定义", "widget": "button",
             "default": []},
        ],
        "description": "常量组（不参与执行流）：作者写死的常量（显示名/变量键/值），\n点【详情】编辑；运行时只读，其它节点用 ${变量键} 引用",
    },
    # ═══ 感知 ═══
    "scene_probe": {
        "type": "scene_probe", "label": "场景判定", "category": "感知",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out"), _ctrl("not_found")],
        "params": [
            {"name": "scene", "label": "场景素材", "widget": "combo_scene",
             "default": ""},
        ],
        "description": "场景判定：将截图器帧与本任务场景素材对比，命中→out(true)，未命中→not_found(false)；识别精度(特征值)由场景素材内数据决定（示教保存时录入）",
    },
    "screenshot": {
        "type": "screenshot", "label": "截图器", "category": "感知",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [],
        "description": "唯一截图权节点：截取当前屏幕写入帧缓存（prev=旧帧）；后续识图节点读帧缓存；操作节点执行后自动清帧",
    },
    "ocr_reader": {
        "type": "ocr_reader", "label": "OCR读取", "category": "感知",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out"), _ctrl("miss")],
        "params": [
            {"name": "template", "label": "OCR识别素材", "widget": "combo_ocr",
             "default": ""},
            {"name": "keyword", "label": "关键词", "widget": "text", "default": ""},
            {"name": "output_var", "label": "输出变量", "widget": "text", "default": ""},
        ],
        "description": "OCR读取：在红框区域内匹配蓝框遮罩图标，命中后按黄框相对位置裁剪截图并提取文字；含关键词走 out，否则 miss；文本存变量",
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
            {"name": "steps_var", "label": "步数引用", "widget": "text", "default": ""},
        ],
        "description": "滚动多屏并拼接全景（供后续标注/识别）；「步数引用」可引用变量",
    },
    "icon_count": {
        "type": "icon_count", "label": "图标计数", "category": "感知",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "template", "label": "操作识别素材", "widget": "combo_element",
             "default": ""},
            {"name": "output_var", "label": "数目输出变量", "widget": "text", "default": ""},
        ],
        "description": "图标计数：统计截图中特征比对通过（≥阈值）的图标个数（NMS 去重），数目写入输出变量，供分支/循环等节点判断；随机点击素材（只有红框）不支持计数",
    },
    # ═══ 操作 ═══
    "clicker": {
        "type": "clicker", "label": "点击器", "category": "操作",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out"), _ctrl("not_found")],
        "params": [
            {"name": "template", "label": "操作识别素材", "widget": "combo_element",
             "default": ""},
        ],
        "description": "点击器：正常操作识别素材=红框内识别遮罩图标，命中后在遮罩区域内随机点击；随机点击素材（只有红框）=不识别，直接在红框区域内随机点击；未命中走 not_found",
    },
    "dragger": {
        "type": "dragger", "label": "拖拽器", "category": "操作",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out"), _ctrl("not_found")],
        "params": [
            {"name": "template", "label": "操作识别素材（可选）", "widget": "combo_element",
             "default": ""},
            {"name": "direction", "label": "方向", "widget": "combo",
             "options": ["up", "down", "left", "right"], "default": "up"},
            {"name": "distance", "label": "距离(0~1)", "widget": "spinbox",
             "default": 0.6, "min": 0.0, "max": 1.0, "step": 0.05},
            {"name": "distance_var", "label": "距离引用", "widget": "text", "default": ""},
            {"name": "duration_ms", "label": "时长(ms)", "widget": "spinbox",
             "default": 600, "min": 0, "max": 3000},
            {"name": "duration_var", "label": "时长引用", "widget": "text", "default": ""},
        ],
        "description": "滑动屏幕：设置操作识别素材时从素材位置起滑（随机点击素材=红框内随机点；正常素材=遮罩内随机点，未命中走 not_found）；不设置素材时从屏幕中心起滑；「距离/时长引用」可引用变量",
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
    "compound": {
        "type": "compound", "label": "复合节点", "category": "通用",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "source", "label": "来源", "widget": "text", "default": ""},
        ],
        "description": "框选封装的多节点子图（或通用节点库导入）；执行时内联运行子图；不参与任务图节点库面板",
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
        "type": "wait", "label": "暂停", "category": "操作",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out"), _ctrl("timeout")],
        "params": [
            {"name": "seconds", "label": "暂停秒数", "widget": "spinbox", "default": 60,
             "min": 0, "max": 3600},
            {"name": "seconds_var", "label": "秒数引用", "widget": "text", "default": ""},
            {"name": "signal", "label": "等待信号(可空)", "widget": "text", "default": ""},
        ],
        "description": "暂停节点（2026-08-16 信号体系）：任务暂停等待；「等待信号」填任务信号名时收到该信号才恢复（out），否则等待该任务被调度激活；超过暂停秒数 → timeout 出口（接超时节点）；无信号时等价旧「等待」固定秒数",
    },
    # ═══ 信号（2026-08-16 信号体系）═══════
    "task_signal_out": {
        "type": "task_signal_out", "label": "任务信号输出", "category": "信号",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "signal", "label": "信号名", "widget": "text", "default": ""},
            {"name": "payload", "label": "参数(预留)", "widget": "text", "default": ""},
        ],
        "description": "任务信号输出（2026-08-16）：发出任务信号（精确匹配），发送后**不暂停**，继续向下执行直到暂停/结束节点；任务内或全局任务内均可使用",
    },
    "task_signal_in": {
        "type": "task_signal_in", "label": "任务信号接收", "category": "信号",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "signal", "label": "信号名", "widget": "text", "default": ""},
        ],
        "description": "任务信号接收（2026-08-16）：仅任务正在执行时生效；收到同名任务信号（含跨窗口）后从这里继续向下执行",
    },
    "scene_signal_in": {
        "type": "scene_signal_in", "label": "场景信号接收", "category": "信号",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "scene", "label": "场景素材", "widget": "combo_scene", "default": ""},
        ],
        "description": "场景信号接收（2026-08-16）：任务内场景识别器命中本场景时，图执行跳转到这里继续（每个任务的接收节点场景必须互不相同）",
    },
    "task_signal_trigger": {
        "type": "task_signal_trigger", "label": "任务信号触发器", "category": "信号",
        "inputs": [],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "signal", "label": "信号名", "widget": "text", "default": ""},
        ],
        "description": "任务信号触发器（2026-08-16）：图内存在此节点 = 该任务是触发任务（到期进待触发队列）；同名任务信号触发时被激活，从 out 接调度器分支",
    },
    "scheduler_ops": {
        "type": "scheduler_ops", "label": "调度器分支", "category": "信号",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("enqueue_pending"), _ctrl("enqueue_running"),
                    _ctrl("skip"), _ctrl("invalidate")],
        "params": [],
        "description": "调度器分支（2026-08-16，接在任务信号触发器后）：加入待执行队列 / 加入正在执行队列 / 跳过周期 / 任务失效（四个出口只接一个）",
    },
    "timeout": {
        "type": "timeout", "label": "超时节点", "category": "信号",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [],
        "description": "超时节点（2026-08-16）：暂停节点 timeout 出口接此节点；触发后任务判定异常，交由全局任务安全结束",
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
            {"name": "count_var", "label": "次数引用", "widget": "text", "default": ""},
            {"name": "condition", "label": "条件(直到)", "widget": "text", "default": ""},
        ],
        "description": "out 连循环体起点，循环体末尾连回 loop_back；done 连循环结束后续；「次数引用」填变量/参数键（如 loop_count），非空时覆盖固定次数",
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
    "param_process": {
        "type": "param_process", "label": "参数处理", "category": "逻辑",
        "inputs": [_ctrl("in")],
        "outputs": [_ctrl("out")],
        "params": [
            {"name": "var_name", "label": "变量名", "widget": "text", "default": ""},
            {"name": "op", "label": "运算符", "widget": "combo",
             "options": ["加", "减", "乘", "除以", "取余", "变化为", "取反"],
             "default": "加"},
            {"name": "value", "label": "运算值", "widget": "text", "default": ""},
        ],
        "description": "参数处理（2026-08-16）：只处理变量组中勾选「可调用」的变量——"
                       "加/减/乘/除以/取余（数字）、变化为（任意类型，文本需带引号如 '充足'）、"
                       "取反（bool，运算值留空）；值跨运行保留并在 UI 实时同步",
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
