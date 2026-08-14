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
    scene_loader: Callable | None = None         # 识别素材加载器（SceneStore.load）
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
        scene = vs.find_scene(self.task, scene_id)
        if scene is not None:
            return scene
        # 任务内无此场景 → 从识别素材库加载（跨任务复用）
        if self.scene_loader is not None:
            try:
                return self.scene_loader(scene_id)
            except Exception:
                return None
        return None

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
    # 识别坐标：点击上游识图器(matcher)输出的元素中心 + 随机偏移
    if mode == "识别坐标":
        try:
            cx = int(float(ctx.get_var("x", 0))) + int(float(ctx.get_var("w", 0))) // 2
            cy = int(float(ctx.get_var("y", 0))) + int(float(ctx.get_var("h", 0))) // 2
        except Exception:
            return NodeResult(status="error", message="识别坐标无效（上游识图器未命中）")
        off = int(float(params.get("offset", 0) or 0))
        if off:
            import random
            cx += random.randint(-off, off)
            cy += random.randint(-off, off)
        if ctx.dry_run:
            _log(ctx, f"[dry] 点击识别坐标 @ ({cx},{cy})")
        else:
            ctx.executor.click_position(cx, cy)
            _log(ctx, f"点击识别坐标 @ ({cx},{cy})")
        return NodeResult(data={"point": (cx, cy)})
    # 固定点：示教点坐标
    point_id = params.get("point", "")
    point = ctx.get_point(point_id)
    if point is None:
        return NodeResult(status="error", message=f"示教点不存在: {point_id}")
    # 区域点：框选的点击区域 → 区域内随机点击
    if point.get("region"):
        w, h = ctx.screen_size
        r = vs.region_to_abs(list(point["region"]), w, h)
        if r:
            import random
            x0, y0, rw, rh = r
            x = random.randint(int(x0), max(int(x0), int(x0 + rw) - 1))
            y = random.randint(int(y0), max(int(y0), int(y0 + rh) - 1))
            if ctx.dry_run:
                _log(ctx, f"[dry] 区域随机点击 {point.get('label', point_id)} @ ({x},{y})")
            else:
                ctx.executor.click_position(x, y)
                _log(ctx, f"区域随机点击 {point.get('label', point_id)} @ ({x},{y})")
            return NodeResult(data={"point": (x, y)})
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
    # 未设置的图像识别节点：触发示教（截图 + 阻断），等用户录入识别特征
    if not scene_id:
        if ctx.on_unknown is not None:
            try:
                ctx.on_unknown(ctx.screenshot(),
                               {"type": "scene_new", "node": node.get("id")})
            except Exception:
                pass
            # 示教恢复后：示教引擎可能已把识别素材 id 回填到本节点
            scene_id = node.get("params", {}).get("scene", "")
        if not scene_id:
            return NodeResult(status="error",
                              message="图像识别节点未设置识别图（示教后重试）")
    scene = ctx.get_scene(scene_id)
    if scene is None:
        return NodeResult(status="error", message=f"场景不存在: {scene_id}")
    # 判定次数：填 N = 最多进行 N 次截图判定（每次间隔 0.3s）
    max_attempts = int(params.get("timeout", 3))
    attempt = 0
    while True:
        if ctx.stopped():
            return NodeResult(status="interrupted")
        attempt += 1
        hit = _judge_scene(scene, ctx)
        if hit:
            _log(ctx, f"场景命中: {scene.get('name', scene_id)}")
            if out_var:
                ctx.set_var(out_var, "1")
            return NodeResult(data={"scene": scene_id})
        if max_attempts > 0 and attempt >= max_attempts:
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
    index = int(params.get("index", 0) or 0)
    threshold = float(params.get("threshold", 0.85))
    # 判定次数：填 N = 最多 N 次截图识别（每次间隔 0.3s）
    max_attempts = int(params.get("timeout", 3))
    region = params.get("region", "")  # 搜索区域 "x,y,w,h"(相对) 或空=全屏
    if not template:
        # 未设置目标元素 → 触发示教（截图 + 阻断），等用户圈出图标
        if ctx.on_unknown is not None:
            try:
                ctx.on_unknown(ctx.screenshot(),
                               {"type": "element_new", "node": node.get("id")})
            except Exception:
                pass
            # 示教恢复后：示教引擎可能已回填模板 + 区域
            template = node.get("params", {}).get("template", "")
            region = node.get("params", {}).get("region", region)
        if not template:
            return NodeResult(status="error",
                              message="识图器未设置目标元素（示教后重试）")
    attempt = 0
    while True:
        if ctx.stopped():
            return NodeResult(status="interrupted")
        attempt += 1
        match = _match_template(ctx, template, threshold, index=index,
                                region=region)
        if match is not None:
            _log(ctx, f"识别命中: {template}")
            return NodeResult(data={
                "x": match[0], "y": match[1],
                "w": match[2], "h": match[3],
                "template": template,
            })
        if max_attempts > 0 and attempt >= max_attempts:
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
        return NodeResult(status="error",
                          message="OCR 引擎不可用：请安装 paddleocr（pip install paddleocr）后重启程序")
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
    if op in ("存在", "不存在"):
        # 场景/元素存在性：condition 字段存目标（模板名）
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
    package = params.get("package", "")
    _log(ctx, f"导航: {action}")
    if action == "关闭弹窗":
        _press_key(ctx, "back", 1)
    elif action == "返回主界面":
        _press_key(ctx, "back", 3)
    elif action == "重启游戏":
        if not package:
            return NodeResult(status="error", message="重启游戏需填写游戏包名")
        if ctx.dry_run:
            _log(ctx, f"[dry] 重启游戏 {package}")
        elif ctx.executor is not None and hasattr(ctx.executor, "restart_app"):
            if not ctx.executor.restart_app(package):
                return NodeResult(status="error", message=f"重启游戏失败: {package}")
        else:
            return NodeResult(status="error", message="执行器不支持重启游戏")
    return NodeResult()


def _press_key(ctx: GraphContext, key: str, times: int) -> None:
    """模拟按键若干次（每次间隔 0.5s），dry_run 下仅记日志"""
    ex = ctx.executor
    for _ in range(times):
        if ctx.stopped():
            return
        if ctx.dry_run:
            _log(ctx, f"[dry] 按键 {key}")
        elif ex is not None and hasattr(ex, "press_key"):
            ex.press_key(key)
        ctx.sleep(0.5)


def _exec_scroll_capture(node: dict, ctx: GraphContext) -> NodeResult:
    params = node.get("params", {})
    direction = params.get("direction", "up")
    steps = int(params.get("steps", 3))
    _log(ctx, f"滚动捕获 {direction} × {steps}")
    frames: list = []
    for i in range(steps):
        if ctx.stopped():
            return NodeResult(status="interrupted")
        try:
            img = ctx.screenshot()
            if img is not None:
                frames.append(img)
        except Exception:
            pass
        if i < steps - 1:
            _exec_dragger({"params": {"direction": direction, "distance": 0.7,
                                      "duration_ms": 600}}, ctx)
            ctx.sleep(0.4)
    if not frames:
        return NodeResult(status="error", message="滚动捕获未能截取任何画面")
    # 拼接全景（纵向滚动纵向拼接 / 横向滚动横向拼接）
    if direction in ("up", "down"):
        pano = np.concatenate(frames, axis=0)
    else:
        pano = np.concatenate(frames, axis=1)
    # 保存全景到素材目录，供后续标注/识别
    out_dir = Path(ctx.assets_dir) if ctx.assets_dir else Path(".")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "panorama.png"
    try:
        cv2.imwrite(str(out_path), pano)
    except Exception as e:
        return NodeResult(status="error", message=f"全景保存失败: {e}")
    _log(ctx, f"全景已保存: {out_path} ({pano.shape[1]}x{pano.shape[0]})")
    return NodeResult(data={"panorama": str(out_path), "width": int(pano.shape[1]),
                            "height": int(pano.shape[0])})


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
    # v2 结构：红框(regions) + 蓝框(markers) + 精度(accuracy)
    if scene.get("regions"):
        return _judge_scene_v2(scene, ctx)
    # 旧结构：judgements + logic（向后兼容）
    judgements = scene.get("judgements", [])
    if not judgements:
        return False
    logic = scene.get("logic", "and")
    results = [_judge_one(j, ctx) for j in judgements]
    if logic == "or":
        return any(results)
    return all(results)


def _judge_scene_v2(scene: dict, ctx: GraphContext) -> bool:
    """v2 场景判定：遍历 红框(搜索范围)→蓝框(整体标识) 匹配，命中数 >= 精度 即通过。

    每个蓝框 = 一组独立遮罩块（连通域），整体匹配要求每个块都命中
    且相对位置对应。accuracy=0 表示全部蓝框命中。
    """
    regions = scene.get("regions", [])
    if not regions:
        return False
    accuracy = int(scene.get("accuracy", 0) or 0)
    total = 0
    hits = 0
    for region in regions:
        rr = region.get("region")  # 红框搜索范围 [x,y,w,h] 相对，None=全屏
        for marker in region.get("markers", []):
            total += 1
            if _match_marker(marker, ctx, region=rr):
                hits += 1
    need = accuracy if accuracy > 0 else total
    if need <= 0:
        return False
    return hits >= need


def _match_marker(marker: dict, ctx: GraphContext, region: Any = None) -> bool:
    """蓝框整体标识匹配：每个独立遮罩块都要在搜索区域（红框）内命中，
    且各块的相对位置与示教时对应。

    结构：marker.templates = [{template, dx, dy}]（dx/dy=相对第一块的像素偏移）；
    兼容旧结构 marker.template（单模板）。
    """
    thr = float(marker.get("threshold", 0.85))
    templates = marker.get("templates") or []
    if not templates:
        tpl = marker.get("template", "")
        if not tpl:
            return False
        return _match_template(ctx, tpl, thr, region=region) is not None
    # 第一块：在搜索区域（红框）内定位
    first = templates[0]
    m0 = _match_template(ctx, first.get("template", ""), thr, region=region)
    if m0 is None:
        return False
    x0, y0 = m0[0], m0[1]
    # 其余块：在相对偏移位置附近核对（位置对应，容差=块尺寸的一半）
    for t in templates[1:]:
        tpl = _load_template(ctx, t.get("template", ""))
        if tpl is None:
            return False
        th, tw = tpl.shape[0], tpl.shape[1]
        dx, dy = int(t.get("dx", 0)), int(t.get("dy", 0))
        cx = x0 + dx + tw // 2
        cy = y0 + dy + th // 2
        r = max(15, max(tw, th) // 2)
        near = [cx - r, cy - r, 2 * r + tw, 2 * r + th]  # 绝对像素搜索区
        if _match_template(ctx, t.get("template", ""), thr, region=near) is None:
            return False
    return True


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
    """从 assets 根加载模板图（保留 alpha 通道，供不规则遮罩匹配）"""
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
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                           cv2.IMREAD_UNCHANGED)
        return img
    except Exception:
        return None


def _parse_region(region: Any, screen: np.ndarray) -> tuple | None:
    """解析搜索区域（字符串 "x,y,w,h" 或列表）→ 绝对像素 (x, y, w, h)"""
    if isinstance(region, str):
        try:
            parts = [float(v) for v in region.replace("，", ",").split(",")]
            if len(parts) != 4:
                return None
            region = parts
        except Exception:
            return None
    if not isinstance(region, (list, tuple)) or len(region) != 4:
        return None
    h, w = screen.shape[:2]
    r = vs.region_to_abs(list(region), w, h)
    if r is None:
        return None
    x, y, rw, rh = r
    x = max(0, min(x, w - 1))
    y = max(0, min(y, h - 1))
    rw = max(1, min(rw, w - x))
    rh = max(1, min(rh, h - y))
    return (x, y, rw, rh)


def _match_template(ctx: GraphContext, rel_path: str,
                    threshold: float, index: int = 0,
                    region: Any = None) -> tuple | None:
    """模板匹配：返回 (x, y, w, h) 或 None；index>0 取第 N 个匹配（多实例）。

    region：搜索区域（相对 "x,y,w,h" 或列表），空=全屏；
    模板若带 alpha 通道（示教遮罩产物），alpha 作为匹配 mask（不规则图标）。
    """
    tpl = _load_template(ctx, rel_path)
    if tpl is None:
        return None
    # RGBA 模板 → alpha 作为匹配 mask，BGR 作为模板
    mask = None
    if tpl.ndim == 3 and tpl.shape[2] == 4:
        mask = tpl[:, :, 3]
        tpl = tpl[:, :, :3]
    screen = ctx.screenshot()
    if screen is None:
        return None
    try:
        # 搜索区域内匹配（坐标加回区域偏移）
        offset_x = offset_y = 0
        if region:
            r = _parse_region(region, screen)
            if r is None:
                return None
            rx, ry, rw, rh = r
            screen = screen[ry:ry + rh, rx:rx + rw]
            offset_x, offset_y = rx, ry
        screen_gray = None
        tpl_gray = None
        th, tw = tpl.shape[0], tpl.shape[1]
        if th > screen.shape[0] or tw > screen.shape[1]:
            return None
        if mask is not None:
            # 遮罩模板：彩色匹配（保留颜色信息；灰度会丢失颜色，彩色图标无法区分）
            res = cv2.matchTemplate(screen, tpl, cv2.TM_SQDIFF_NORMED, mask=mask)
            res = 1.0 - res  # 越大越好
        else:
            # 无遮罩模板：灰度匹配（兼容旧素材）
            screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
            tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
            # 低纹理模板（纯色块/低方差）用平方差匹配（归一化相关会除零→NaN）；
            # 有纹理模板用归一化相关（对光照更鲁棒）。
            low_texture = float(np.std(tpl_gray)) < 10.0
            if low_texture:
                res = cv2.matchTemplate(screen_gray, tpl_gray,
                                        cv2.TM_SQDIFF_NORMED)
                res = 1.0 - res
            else:
                res = cv2.matchTemplate(screen_gray, tpl_gray,
                                        cv2.TM_CCOEFF_NORMED)
        res = np.nan_to_num(res, nan=-1.0)
        if index <= 0:
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val >= threshold:
                x, y = max_loc
                return (x + offset_x, y + offset_y, tw, th)
            return None
        # 多实例：收集所有 >= threshold 的峰，按位置（先 y 后 x，从上到下从左到右）
        # 排序 + 非极大值抑制取第 index 个
        ys, xs = np.where(res >= threshold)
        if len(xs) == 0:
            return None
        order = sorted(range(len(xs)), key=lambda i: (int(ys[i]), int(xs[i])))
        picked: list[tuple[int, int]] = []
        for i in order:
            px, py = int(xs[i]), int(ys[i])
            # 标准 NMS：与所有已选实例均不重叠（|dx|>=tw 或 |dy|>=th）才保留
            if all(abs(px - ox) >= tw or abs(py - oy) >= th
                   for ox, oy in picked):
                picked.append((px, py))
                if len(picked) > index:
                    return (px + offset_x, py + offset_y, tw, th)
        return None
    except Exception:
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
        _log(ctx, "OCR 未就绪，ocr_contains 判定跳过（pip install paddleocr）")
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
    tol = int(j.get("tol", 40))
    h, w = crop.shape[:2]
    if h == 0 or w == 0:
        return False
    # 若指定 ratio：统计区域内与目标色接近的像素占比 >= ratio（主色占比模式）
    if j.get("ratio") is not None:
        b = crop[:, :, 0].astype(int)
        g = crop[:, :, 1].astype(int)
        r = crop[:, :, 2].astype(int)
        mask = (abs(r - tr) <= tol) & (abs(g - tg) <= tol) & (abs(b - tb) <= tol)
        return float(mask.mean()) >= float(j.get("ratio", 0.5))
    # 默认：中心点近似（兼容旧行为）
    b, g, r = crop[h // 2, w // 2]
    return abs(int(r) - tr) <= tol and abs(int(g) - tg) <= tol and abs(int(b) - tb) <= tol


def _judge_edge(j: dict, ctx: GraphContext) -> bool:
    """边缘线检测：区域内 Canny 边缘像素占比 >= threshold"""
    screen = ctx.screenshot()
    if screen is None:
        return False
    crop = _crop_region(screen, j, ctx)
    if crop.size == 0:
        return False
    try:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        ratio = float(edges.mean()) / 255.0
        return ratio >= float(j.get("threshold", 0.02))
    except Exception:
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
