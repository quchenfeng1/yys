"""
17-可视化构建模块：节点执行实现（P2）。

每个节点类型一个执行函数 execute_{type}(node, ctx) → NodeResult。
NodeResult.goto 指定从哪个输出端口继续（控制流分支）。
数据流：节点输出写入 ctx.data / ctx.vars，供后续分支/点击器引用。

节点执行全部走现有 Executor / Recognizer / OcrLocator（复用地基）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from visual import visual_schema as vs


@dataclass
class NodeResult:
    goto: str = "out"                 # 输出端口名（控制流去向）
    status: str = "ok"                # ok / end / error / interrupted
    data: dict = field(default_factory=dict)  # 数据流输出
    message: str = ""


@dataclass
class GraphContext:
    """图执行上下文（由 VisualTask 构造注入）"""
    executor: Any = None
    recognizer: Any = None
    ocr: Any = None
    anti_detect: Any = None
    monitor: Any = None
    stop_event: Any = None
    cycle_limit_event: Any = None
    task: dict = field(default_factory=dict)     # 可视化任务（teach 产物）
    assets_dir: str | Path = ""                  # 素材根（模板相对路径解析）
    screen_size: tuple = (1080, 1920)            # (w, h)
    dry_run: bool = False
    on_unknown: Callable | None = None           # 未知画面回调（示教）
    get_operation: Callable | None = None        # 通用操作加载器（4.26）
    param_values: dict = field(default_factory=dict)  # 参数上浮值（4.27）
    vars: dict = field(default_factory=dict)     # 任务变量
    data: dict = field(default_factory=dict)     # 节点数据流输出
    _screenshot: Any = None
    _shot_time: float = 0.0
    shot_ttl: float = 0.2

    # ── 截图 ──────────────────────────────────────────────
    def screenshot(self) -> np.ndarray:
        now = time.time()
        if self._screenshot is not None and now - self._shot_time < self.shot_ttl:
            return self._screenshot
        if self.executor is not None and hasattr(self.executor, "_recognizer"):
            try:
                img = self.executor._recognizer._get_screenshot()
                self._screenshot = img
                self._shot_time = time.time()
                return img
            except Exception:
                pass
        if self.recognizer is not None:
            try:
                img = self.recognizer._get_screenshot()
                self._screenshot = img
                self._shot_time = time.time()
                return img
            except Exception:
                pass
        if self._screenshot is not None:
            return self._screenshot
        raise RuntimeError("无可用截图来源")

    def clear_shot(self) -> None:
        self._screenshot = None

    # ── 帮助 ──────────────────────────────────────────────
    def sleep(self, seconds: float) -> bool:
        """可中断 sleep；返回是否被停止"""
        if self.stop_event is not None and self.stop_event.is_set():
            return True
        end = time.time() + seconds
        while time.time() < end:
            if self.stop_event is not None and self.stop_event.is_set():
                return True
            if self.cycle_limit_event is not None and self.cycle_limit_event.is_set():
                return True
            time.sleep(0.05)
        return False

    def stopped(self) -> bool:
        if self.stop_event is not None and self.stop_event.is_set():
            return True
        if self.cycle_limit_event is not None and self.cycle_limit_event.is_set():
            return True
        return False

    # ── 变量 ──────────────────────────────────────────────
    def get_var(self, name: str, default: Any = 0) -> Any:
        if name in self.vars:
            return self.vars[name]
        if name in self.data:
            return self.data[name]
        return default

    def set_var(self, name: str, value: Any) -> None:
        self.vars[name] = value

    def get_point(self, point_id: str) -> dict | None:
        return vs.find_point(self.task, point_id)

    def get_scene(self, scene_id: str) -> dict | None:
        return vs.find_scene(self.task, scene_id)

    def get_ocr_region(self, region_id: str) -> dict | None:
        return vs.find_ocr_region(self.task, region_id)


# ═══════════════════════════════════════════════════════════════
#  节点执行器
# ═══════════════════════════════════════════════════════════════

def _abs_point(ctx: GraphContext, point: dict) -> tuple[int, int]:
    """示教点 → 绝对坐标"""
    w, h = ctx.screen_size
    mode = point.get("mode", "relative")
    if mode == "relative":
        return vs.rel_to_abs(float(point.get("x", 0.5)),
                             float(point.get("y", 0.5)), w, h)
    return int(point.get("x", 0)), int(point.get("y", 0))


def _exec_clicker(node: dict, ctx: GraphContext) -> NodeResult:
    params = node.get("params", {})
    mode = params.get("mode", "固定点")
    # 随机点：屏幕内随机坐标点击（动画期间跳过用，不看画面）
    if mode == "随机点":
        import random
        w, h = ctx.screen_size
        x = random.randint(0, max(0, w - 1))
        y = random.randint(0, max(0, h - 1))
        if ctx.dry_run:
            _log(ctx, f"[dry] 随机点击 @ ({x},{y})")
        else:
            ctx.executor.click_position(x, y)
            _log(ctx, f"随机点击 @ ({x},{y})")
        return NodeResult(data={"point": (x, y)})
    # 固定点：示教点坐标
    point_id = params.get("point", "")
    point = ctx.get_point(point_id)
    if point is None:
        return NodeResult(status="error", message=f"示教点不存在: {point_id}")
    x, y = _abs_point(ctx, point)
    if ctx.dry_run:
        _log(ctx, f"[dry] 点击 {point.get('label', point_id)} @ ({x},{y})")
    else:
        ctx.executor.click_position(x, y)
        _log(ctx, f"点击 {point.get('label', point_id)} @ ({x},{y})")
    return NodeResult(data={"point": (x, y)})


def _exec_dragger(node: dict, ctx: GraphContext) -> NodeResult:
    params = node.get("params", {})
    direction = params.get("direction", "up")
    distance = float(params.get("distance", 0.6))
    duration = float(params.get("duration_ms", 600)) / 1000.0
    w, h = ctx.screen_size
    cx, cy = w // 2, h // 2
    dx = dy = 0
    if direction == "up":
        dx, dy = 0, -int(h * distance)
    elif direction == "down":
        dx, dy = 0, int(h * distance)
    elif direction == "left":
        dx, dy = -int(w * distance), 0
    elif direction == "right":
        dx, dy = int(w * distance), 0
    if ctx.dry_run:
        _log(ctx, f"[dry] 滑动 {direction} {distance}")
    else:
        ctx.executor.swipe(cx, cy, cx + dx, cy + dy, duration=duration)
        _log(ctx, f"滑动 {direction} {distance}")
    return NodeResult()


def _exec_wait(node: dict, ctx: GraphContext) -> NodeResult:
    seconds = float(node.get("params", {}).get("seconds", 1))
    if ctx.sleep(seconds):
        return NodeResult(status="interrupted", message="等待期间被停止")
    return NodeResult()


def _exec_set_var(node: dict, ctx: GraphContext) -> NodeResult:
    params = node.get("params", {})
    name = params.get("var_name", "")
    value = params.get("var_value", "")
    ctx.set_var(name, _coerce(value))
    return NodeResult(data={name: ctx.vars[name]})


def _exec_counter(node: dict, ctx: GraphContext) -> NodeResult:
    params = node.get("params", {})
    name = params.get("var_name", "")
    delta = int(params.get("delta", 1))
    cur = ctx.get_var(name, 0)
    try:
        cur = int(cur)
    except Exception:
        cur = 0
    ctx.set_var(name, cur + delta)
    return NodeResult(data={name: ctx.vars[name]})


def _exec_start(node: dict, ctx: GraphContext) -> NodeResult:
    return NodeResult()


def _exec_end(node: dict, ctx: GraphContext) -> NodeResult:
    return NodeResult(status="end", message="任务结束")


def _exec_scene_probe(node: dict, ctx: GraphContext) -> NodeResult:
    params = node.get("params", {})
    scene_id = params.get("scene", "")
    out_var = params.get("output_var", "")
    scene = ctx.get_scene(scene_id)
    if scene is None:
        return NodeResult(status="error", message=f"场景不存在: {scene_id}")
    timeout = float(params.get("timeout", 3))
    start = time.time()
    while True:
        if ctx.stopped():
            return NodeResult(status="interrupted")
        hit = _judge_scene(scene, ctx)
        if hit:
            _log(ctx, f"场景命中: {scene.get('name', scene_id)}")
            if out_var:
                ctx.set_var(out_var, "1")
            return NodeResult(data={"scene": scene_id})
        if timeout > 0 and time.time() - start > timeout:
            break
        ctx.sleep(0.3)
    # 未命中
    if out_var:
        ctx.set_var(out_var, "0")
    if ctx.on_unknown is not None:
        try:
            ctx.on_unknown(ctx.screenshot(), {"type": "scene", "scene": scene_id})
        except Exception:
            pass
    return NodeResult(goto="not_found", data={"scene": None})


def _exec_matcher(node: dict, ctx: GraphContext) -> NodeResult:
    params = node.get("params", {})
    template = params.get("template", "")
    threshold = float(params.get("threshold", 0.85))
    timeout = float(params.get("timeout", 3))
    if not template:
        return NodeResult(status="error", message="识图器未选择目标元素")
    start = time.time()
    while True:
        if ctx.stopped():
            return NodeResult(status="interrupted")
        match = _match_template(ctx, template, threshold)
        if match is not None:
            _log(ctx, f"识别命中: {template}")
            return NodeResult(data={
                "x": match[0], "y": match[1],
                "w": match[2], "h": match[3],
                "template": template,
            })
        if timeout > 0 and time.time() - start > timeout:
            break
        ctx.sleep(0.3)
    if ctx.on_unknown is not None:
        try:
            ctx.on_unknown(ctx.screenshot(), {"type": "element", "template": template})
        except Exception:
            pass
    return NodeResult(goto="miss", data={"template": template})


def _exec_ocr_reader(node: dict, ctx: GraphContext) -> NodeResult:
    params = node.get("params", {})
    region_id = params.get("region", "")
    keyword = params.get("keyword", "")
    out_var = params.get("output_var", "")
    region = ctx.get_ocr_region(region_id) if region_id else None
    if region is None:
        return NodeResult(status="error", message=f"OCR区域不存在: {region_id}")
    if ctx.ocr is None or not getattr(ctx.ocr, "is_ready", False):
        return NodeResult(status="error", message="OCR 引擎不可用")
    screen = ctx.screenshot()
    crop = _crop_region(screen, region, ctx)
    try:
        results = ctx.ocr.recognize(crop)
    except Exception as e:
        return NodeResult(status="error", message=f"OCR 失败: {e}")
    texts = [r.text for r in results]
    joined = "".join(texts)
    if out_var:
        ctx.set_var(out_var, joined)
    if keyword and keyword not in joined:
        return NodeResult(goto="miss", data={"texts": texts, "joined": joined})
    return NodeResult(data={"texts": texts, "joined": joined})


def _exec_branch(node: dict, ctx: GraphContext) -> NodeResult:
    params = node.get("params", {})
    data_source = params.get("data_source", "")
    op = params.get("op", ">=")
    value = params.get("value", "0")
    if data_source in ("存在", "不存在"):
        # 场景/元素存在性：data_source 字段存目标
        target = params.get("condition", "")
        if op == "存在":
            hit = _match_template(ctx, target, 0.85) is not None
        else:
            hit = not (_match_template(ctx, target, 0.85) is not None)
        return NodeResult(goto="true" if hit else "false")
    actual = ctx.get_var(data_source, _coerce(value))
    try:
        a = float(actual)
        b = float(_coerce(value))
    except Exception:
        a = str(actual)
        b = str(_coerce(value))
    hit = _compare(a, b, op)
    _log(ctx, f"分支 [{data_source}] {actual} {op} {value} → {'真' if hit else '假'}")
    return NodeResult(goto="true" if hit else "false")


def _exec_loop(node: dict, ctx: GraphContext) -> NodeResult:
    # 循环入口：初始化计数（由 graph_runner 维护），goto out 进入循环体
    return NodeResult()


def _exec_counter_loop_back(node: dict, ctx: GraphContext) -> NodeResult:
    return NodeResult(goto="loop_back")


def _exec_checker(node: dict, ctx: GraphContext) -> NodeResult:
    params = node.get("params", {})
    condition = params.get("condition", "")
    # 简化：condition 为 "变量 op 值" 或空（空=跳过）
    if not condition:
        return NodeResult()
    triggered = False
    if ">=" in condition or "<=" in condition or "==" in condition or "!=" in condition:
        import re
        m = re.match(r"([\w.]+)\s*(>=|<=|==|!=|>|<)\s*(.+)", condition)
        if m:
            name, op, val = m.group(1), m.group(2), m.group(3).strip()
            a = ctx.get_var(name, 0)
            try:
                a = float(a)
                val = float(_coerce(val))
            except Exception:
                pass
            triggered = _compare(a, val, op)
    if triggered:
        _log(ctx, f"检查器触发: {condition}")
        return NodeResult(goto="triggered")
    return NodeResult()


def _exec_refresher(node: dict, ctx: GraphContext) -> NodeResult:
    params = node.get("params", {})
    if params.get("swipe", True):
        _exec_dragger({"params": {"direction": "down", "distance": 0.6,
                                  "duration_ms": 600}}, ctx)
    return NodeResult()


def _exec_navigator(node: dict, ctx: GraphContext) -> NodeResult:
    params = node.get("params", {})
    action = params.get("action", "返回主界面")
    _log(ctx, f"导航: {action}")
    # 简化实现：返主/关弹窗依赖示教点（预留）；先记录日志
    return NodeResult()


def _exec_scroll_capture(node: dict, ctx: GraphContext) -> NodeResult:
    params = node.get("params", {})
    direction = params.get("direction", "up")
    steps = int(params.get("steps", 3))
    _log(ctx, f"滚动捕获 {direction} × {steps}（全景拼接 P3）")
    for _ in range(steps):
        if ctx.stopped():
            return NodeResult(status="interrupted")
        _exec_dragger({"params": {"direction": direction, "distance": 0.7,
                                  "duration_ms": 600}}, ctx)
        ctx.sleep(0.4)
    return NodeResult()


def _exec_operation(node: dict, ctx: GraphContext) -> NodeResult:
    """操作节点（4.26）：加载通用操作子图 → 绑定输入参数 → 内联递归执行"""
    params = node.get("params", {})
    op_name = params.get("operation", "")
    if not op_name:
        return NodeResult(status="error", message="操作节点未选择通用操作")
    op = ctx.get_operation(op_name) if ctx.get_operation else None
    if op is None:
        return NodeResult(status="error", message=f"通用操作不存在: {op_name}")
    sub_graph = op.get("graph", {})

    # 绑定输入参数（4.27 参数上浮：UI 配置区值 > 节点自身参数 > 默认值）
    input_values: dict[str, Any] = {}
    for inp in op.get("inputs", []):
        iname = inp["name"]
        val = params.get(f"input_{iname}")
        key = f"ops.{op_name}.{iname}"
        if key in (ctx.param_values or {}):
            val = ctx.param_values[key]
        if val is None or val == "":
            val = inp.get("default", "")
        input_values[iname] = val
        ctx.vars[f"op.{op_name}.{iname}"] = val

    # 递归执行子图（is_subgraph：子图 end 只结束子图，不结束整个任务）
    from visual.graph_runner import run_graph
    result = run_graph(sub_graph, ctx, is_subgraph=True)
    if result.status == "error":
        return NodeResult(status="error",
                          message=f"操作[{op_name}]失败: {result.error_message}")
    if result.status == "interrupted":
        return NodeResult(status="interrupted", message=f"操作[{op_name}]被中断")
    _log(ctx, f"操作完成: {op.get('display_name', op_name)}")
    return NodeResult(data={"operation": op_name, "inputs": input_values})


# ═══════════════════════════════════════════════════════════════
#  场景判定（SceneProbe，4.3/4.9）
# ═══════════════════════════════════════════════════════════════

def _judge_scene(scene: dict, ctx: GraphContext) -> bool:
    judgements = scene.get("judgements", [])
    if not judgements:
        return False
    logic = scene.get("logic", "and")
    results = [_judge_one(j, ctx) for j in judgements]
    if logic == "or":
        return any(results)
    return all(results)


def _judge_one(judgement: dict, ctx: GraphContext) -> bool:
    primitive = judgement.get("primitive", "template")
    try:
        if primitive == "template":
            return _judge_template(judgement, ctx)
        if primitive == "ocr_contains":
            return _judge_ocr(judgement, ctx)
        if primitive == "color_block":
            return _judge_color(judgement, ctx)
        if primitive == "edge_line":
            return _judge_edge(judgement, ctx)
    except Exception:
        return False
    return False


def _crop_region(screen: np.ndarray, region: dict, ctx: GraphContext) -> np.ndarray:
    """裁剪区域（relative → 绝对）"""
    w, h = ctx.screen_size
    r = region.get("region") or region.get("rect") or [0, 0, 1, 1]
    x, y, rw, rh = vs.region_to_abs(list(r), w, h)
    img_h, img_w = screen.shape[:2]
    x = max(0, min(x, img_w - 1))
    y = max(0, min(y, img_h - 1))
    rw = max(1, min(rw, img_w - x))
    rh = max(1, min(rh, img_h - y))
    return screen[y:y + rh, x:x + rw]


def _load_template(ctx: GraphContext, rel_path: str) -> np.ndarray | None:
    """从 assets 根加载模板图"""
    if not rel_path:
        return None
    base = Path(ctx.assets_dir) if ctx.assets_dir else Path(".")
    # 支持绝对路径与相对 assets 根
    p = Path(rel_path)
    if not p.is_absolute():
        p = base / rel_path
    if not p.exists():
        return None
    try:
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
        return img
    except Exception:
        return None


def _match_template(ctx: GraphContext, rel_path: str,
                    threshold: float) -> tuple | None:
    """模板匹配：返回 (x, y, w, h) 或 None"""
    tpl = _load_template(ctx, rel_path)
    if tpl is None:
        return None
    screen = ctx.screenshot()
    if screen is None:
        return None
    try:
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
        th, tw = tpl_gray.shape[:2]
        if th > screen_gray.shape[0] or tw > screen_gray.shape[1]:
            return None
        res = cv2.matchTemplate(screen_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val >= threshold:
            x, y = max_loc
            return (x, y, tw, th)
    except Exception:
        return None
    return None


def _judge_template(j: dict, ctx: GraphContext) -> bool:
    tpl = j.get("template", "")
    threshold = float(j.get("threshold", 0.85))
    hit = _match_template(ctx, tpl, threshold)
    if hit is not None:
        return True
    # 若指定 region，在区域内重试（模板整体匹配到 region 内）
    if j.get("region"):
        w, h = ctx.screen_size
        r = vs.region_to_abs(j["region"], w, h)
        screen = ctx.screenshot()
        if screen is not None and r:
            x, y, rw, rh = r
            crop = screen[y:y + rh, x:x + rw]
            old = ctx._screenshot
            ctx._screenshot = crop
            try:
                return _match_template(ctx, tpl, threshold) is not None
            finally:
                ctx._screenshot = old
    return False


def _judge_ocr(j: dict, ctx: GraphContext) -> bool:
    if ctx.ocr is None or not getattr(ctx.ocr, "is_ready", False):
        return False
    screen = ctx.screenshot()
    crop = _crop_region(screen, j, ctx)
    try:
        results = ctx.ocr.recognize(crop)
    except Exception:
        return False
    texts = [r.text for r in results]
    for kw in j.get("texts", []):
        if kw and kw in "".join(texts):
            return True
    return False


def _judge_color(j: dict, ctx: GraphContext) -> bool:
    screen = ctx.screenshot()
    crop = _crop_region(screen, j, ctx)
    if crop.size == 0:
        return False
    target = j.get("color", "#000000").lstrip("#")
    if len(target) == 6:
        tr, tg, tb = int(target[0:2], 16), int(target[2:4], 16), int(target[4:6], 16)
    else:
        return False
    h, w = crop.shape[:2]
    if h == 0 or w == 0:
        return False
    b, g, r = crop[h // 2, w // 2]
    # 主色近似（允许 40 容差）
    return abs(int(r) - tr) <= 40 and abs(int(g) - tg) <= 40 and abs(int(b) - tb) <= 40


def _judge_edge(j: dict, ctx: GraphContext) -> bool:
    # 预留：边缘线检测（P3）
    return False


# ═══════════════════════════════════════════════════════════════
#  工具
# ═══════════════════════════════════════════════════════════════

def _coerce(value: Any) -> Any:
    """文本值智能转换（数字/布尔/原样）"""
    if isinstance(value, (int, float, bool)):
        return value
    s = str(value).strip()
    if s.lower() in ("true", "是", "真"):
        return True
    if s.lower() in ("false", "否", "假"):
        return False
    try:
        if "." in s or "e" in s.lower():
            return float(s)
        return int(s)
    except Exception:
        return s


def _compare(a: Any, b: Any, op: str) -> bool:
    try:
        if op == ">=":
            return a >= b
        if op == "<=":
            return a <= b
        if op == "==":
            return a == b
        if op == "!=":
            return a != b
        if op == ">":
            return a > b
        if op == "<":
            return a < b
    except Exception:
        return False
    return False


def _log(ctx: GraphContext, message: str) -> None:
    if ctx.monitor is not None and hasattr(ctx.monitor, "info"):
        try:
            ctx.monitor.info(message, module="visual")
        except Exception:
            pass


# 注册表
_EXECUTORS: dict[str, Callable] = {
    "start": _exec_start,
    "end": _exec_end,
    "wait": _exec_wait,
    "set_var": _exec_set_var,
    "counter": _exec_counter,
    "clicker": _exec_clicker,
    "dragger": _exec_dragger,
    "scene_probe": _exec_scene_probe,
    "matcher": _exec_matcher,
    "ocr_reader": _exec_ocr_reader,
    "branch": _exec_branch,
    "loop": _exec_loop,
    "checker": _exec_checker,
    "refresher": _exec_refresher,
    "navigator": _exec_navigator,
    "scroll_capture": _exec_scroll_capture,
    "operation": _exec_operation,
}


def dispatch(node: dict, ctx: GraphContext) -> NodeResult:
    fn = _EXECUTORS.get(node.get("type", ""))
    if fn is None:
        return NodeResult(status="error", message=f"未知节点类型: {node.get('type')}")
    try:
        return fn(node, ctx)
    except Exception as e:
        return NodeResult(status="error", message=f"{node.get('name')}: {e}")
