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
    on_unknown: Callable | None = None           # 未知画面回调（已停用：识别失败直接走 miss/not_found）
    on_node: Callable | None = None              # 节点执行通知（画布红框高亮当前节点）
    on_result: Callable | None = None            # 节点执行结果 (node_id, status)（进度跟踪，2026-08-16）
    publish_image: Callable | None = None        # (node_id, png_bytes) 截图器帧 → 节点预览（仅测试运行注入）
    get_compound: Callable | None = None         # 通用节点加载器（CompoundStore.load）
    scene_loader: Callable | None = None         # 识别素材加载器（SceneStore.load）
    scene_lister: Callable | None = None         # 识别素材清单（SceneStore.list，场景信号表用）
    param_values: dict = field(default_factory=dict)  # 参数上浮值（4.27）
    callable_store: Any = None                   # CallableVarStore（可调用变量持久化，2026-08-16）
    task_id: str = ""                            # 任务 id（可调用变量存储键）
    on_callable_changed: Callable | None = None  # (key, value) 可调用变量被参数处理改变（UI 同步用）
    vars: dict = field(default_factory=dict)     # 任务变量
    data: dict = field(default_factory=dict)     # 节点数据流输出
    _screenshot: Any = None
    _shot_time: float = 0.0
    shot_ttl: float = 0.2
    frame: Any = None            # 截图器输出的当前帧（唯一截图产物，2026-08-15）
    # ── 信号体系回调（2026-08-16，VisualTask/RunController 注入）──
    signal_emit: Callable | None = None      # (name, payload) 发布任务信号
    scene_fallback: Callable | None = None   # (node_id, goto) → {"jump_to"} / {"abnormal"} / None（未接线出口兑底）
    on_wait: Callable | None = None          # (task_id, signal, seconds, node_id) 暂停注册（RunController 编排）
    scheduler_op: Callable | None = None     # (op, task_id) 调度器操作（pending/running/skip/invalidate）
    resume_wait: bool = False                # 恢复执行：从暂停节点继续（out/timeout 由 data['wait_outcome'] 决定）

    # ── 截图 ──────────────────────────────────────────────
    def _raw_screenshot(self) -> np.ndarray:
        """底层截图（TTL 缓存）：真正触屏截图的入口"""
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

    def screenshot(self) -> np.ndarray:
        """识图节点读帧：帧缓存有值用帧；无帧 fallback 自行截图（旧任务兼容）"""
        if self.frame is not None:
            return self.frame
        return self._raw_screenshot()

    def capture_frame(self) -> np.ndarray:
        """截图器专用：截一帧写入帧缓存。"""
        img = self._raw_screenshot()
        self.frame = img
        return img

    def clear_frame(self) -> None:
        """操作节点执行后：清当前帧（强制下次识图前先过截图器）"""
        self.frame = None

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


def _resolve_region_ref(value: Any, ctx: GraphContext) -> Any:
    """区域外部输入解析（2026-08-15）：变量引用 → 字面量 "x,y,w,h" → None(全图)。

    优先顺序：外部输入（变量/数据流）> 节点配置（字面量）> 全图搜索。
    变量引用目的：循环每轮识别区域不同，由 set_var 更新。
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # 变量 / 数据流引用（循环输出传入）
    if s in ctx.vars:
        return _resolve_region_ref(ctx.vars[s], ctx)
    if s in ctx.data:
        return _resolve_region_ref(ctx.data[s], ctx)
    # 字面量区域
    try:
        parts = [float(v) for v in s.replace("，", ",").split(",")]
        if len(parts) == 4:
            return parts
    except Exception:
        pass
    return None   # 无法解析 → 全图


def _icon_meta(ctx: GraphContext, rel_path: str) -> dict:
    """图标素材元数据（旧式：PNG 旁同名 .json）：{region: [x,y,w,h] 红框搜索区域}"""
    import json
    if not rel_path:
        return {}
    base = Path(ctx.assets_dir) if ctx.assets_dir else Path(".")
    p = Path(rel_path)
    if not p.is_absolute():
        p = base / rel_path
    meta = p.with_suffix(".json")
    if meta.exists():
        try:
            return json.loads(meta.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


def _icon_entry(ctx: GraphContext, rel_path: str) -> dict:
    """图标素材条目解析（2026-08-15）：图标素材与场景素材同规格，
    json 条目为主文件（image/region/threshold），PNG 只是图片数据。

    - .json 条目 → {image: 图片相对路径, region: 红框搜索区域, threshold}
    - 旧式 .png → 读 PNG 旁同名 .json 的 region 元数据（兼容旧任务）
    返回 dict；解析失败返回 {}。
    """
    import json
    if not rel_path:
        return {}
    base = Path(ctx.assets_dir) if ctx.assets_dir else Path(".")
    p = Path(rel_path)
    if not p.is_absolute():
        p = base / rel_path
    if p.suffix.lower() == ".json":
        try:
            data = json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
        image = data.get("image") or data.get("template") or ""
        if not image:
            return {}
        img = Path(image)
        img_path = img if img.is_absolute() else p.parent / img
        if img_path.exists():
            try:
                image_rel = img_path.relative_to(base).as_posix()
            except Exception:
                image_rel = str(img_path)
        else:
            # 条目里写相对 assets 根的图片路径（旧格式）
            image_rel = image
        return {"image": image_rel,
                "region": data.get("region") or None,
                "threshold": float(data.get("threshold") or 0.85),
                "ocr_box": data.get("ocr_box") or None,
                "mode": data.get("mode") or None,
                "exclusions": _parse_exclusions(base, p, data.get("exclusions"))}
    # 旧式：PNG + 旁同名 .json 元数据（threshold=None 表示不覆盖节点阈值）
    meta = _icon_meta(ctx, rel_path)
    return {"image": rel_path,
            "region": meta.get("region") or None,
            "threshold": None,
            "ocr_box": None,
            "mode": None,
            "exclusions": []}


def _random_point_in_mask(ctx: GraphContext, rel_path: str,
                          match: tuple) -> tuple[int, int] | None:
    """在图标遮罩（alpha>0 的像素=点击范围）内随机取一点。

    match = (mx, my, w, h[, score]) 匹配位置（绝对像素）；
    返回绝对随机点击坐标。
    """
    import random
    tpl = _load_template(ctx, rel_path)
    if tpl is None:
        return None
    alpha = None
    if tpl.ndim == 3 and tpl.shape[2] == 4:
        alpha = tpl[:, :, 3]
    if alpha is None:
        # 无 alpha（旧素材）：整个图标区域随机
        mx, my = int(match[0]), int(match[1])
        mw, mh = int(match[2]), int(match[3])
        return (random.randint(mx, mx + mw - 1),
                random.randint(my, my + mh - 1))
    ys, xs = np.nonzero(alpha > 0)
    if len(ys) == 0:
        return None
    i = random.randint(0, len(ys) - 1)
    return (int(match[0] + xs[i]), int(match[1] + ys[i]))


def _random_point_in_region(ctx: GraphContext,
                            region: Any) -> tuple[int, int] | None:
    """在红框区域（相对坐标 [x,y,w,h]）内随机取一点。

    随机点击素材（mode=region_click）用：不识别，直接红框内随机点。
    region 为空 = 全屏随机。
    """
    import random
    w, h = ctx.screen_size
    x0, y0, x1, y1 = 0, 0, w - 1, h - 1
    if region:
        try:
            rx, ry, rw, rh = (float(v) for v in region)
            x0 = max(0, min(w - 1, int(rx * w)))
            y0 = max(0, min(h - 1, int(ry * h)))
            x1 = max(x0, min(w - 1, int((rx + rw) * w)))
            y1 = max(y0, min(h - 1, int((ry + rh) * h)))
        except Exception:
            return None
    return (random.randint(x0, x1), random.randint(y0, y1))


def _exec_clicker(node: dict, ctx: GraphContext) -> NodeResult:
    """点击器（2026-08-15 遮罩随机点击 / 随机点击素材 / 排除素材）：
    - 正常操作识别素材：红框内多实例匹配，候选按分数降序，逐个检查排除素材
      （命中任一排除特征跳过），点第一个未被排除实例的遮罩内随机点
    - 随机点击素材（只有红框）：不识别，红框内随机点击
    未命中或全部被排除 → not_found。"""
    params = node.get("params", {})
    template = params.get("template", "")
    if not template:
        return NodeResult(status="error",
                          message="点击器未设置操作识别素材")
    # 操作识别素材 = 条目 json（或旧式 PNG）→ 图片 + 红框搜索区域 + 阈值
    entry = _icon_entry(ctx, template)
    image = entry.get("image") or template
    region = entry.get("region") or None
    th = entry.get("threshold") or 0.85
    if entry.get("mode") == "region_click":
        # 随机点击素材：只有红框，无需识别 → 红框内随机点
        pt = _random_point_in_region(ctx, region)
        if pt is None:
            return NodeResult(status="error",
                              message=f"随机点击区域无效: {template}")
        px, py = pt
        if ctx.dry_run:
            _log(ctx, f"[dry] 区域随机点击 {template} @ ({px},{py})")
        else:
            ctx.executor.click_position(px, py)
            _log(ctx, f"区域随机点击 {template} @ ({px},{py})")
        return NodeResult(data={"point": (px, py), "template": template,
                                "mode": "region_click"})
    # 多实例匹配：候选按分数降序（保持原"最高分优先"语义），逐个排除检查
    candidates = _match_all_templates(ctx, image, th, region=region)
    if not candidates:
        return NodeResult(goto="not_found", data={"template": template})
    candidates.sort(key=lambda m: m[4], reverse=True)
    excluded = 0
    for m in candidates:
        if _exclusions_hit(ctx, entry.get("exclusions"),
                           m[0], m[1], m[2], m[3]):
            excluded += 1
            _log(ctx, f"跳过被排除实例 {template} @ ({m[0]},{m[1]}) "
                      f"score={m[4]:.2f}")
            continue
        # 遮罩覆盖的所有区域 = 点击区，随机点击一个点
        pt = _random_point_in_mask(ctx, image, m)
        if pt is None:
            return NodeResult(status="error",
                              message=f"图标遮罩无效: {template}")
        px, py = pt
        if ctx.dry_run:
            _log(ctx, f"[dry] 遮罩随机点击 {template} @ ({px},{py})")
        else:
            ctx.executor.click_position(px, py)
            _log(ctx, f"遮罩随机点击 {template} @ ({px},{py})")
        return NodeResult(data={"point": (px, py), "template": template,
                                "excluded": excluded})
    # 全部候选被排除
    _log(ctx, f"点击器 {template}: {excluded} 个实例全部被排除")
    return NodeResult(goto="not_found", data={"template": template,
                                             "excluded": excluded})


def _exec_dragger(node: dict, ctx: GraphContext) -> NodeResult:
    """拖拽器（2026-08-15 起支持识别素材起点）：
    - 设置了操作识别素材：
        · 随机点击素材（只有红框）→ 红框内随机点作为拖拽起点（不识别）
        · 正常素材 → 识别遮罩，命中后遮罩内随机点作为拖拽起点
        未命中 → not_found（不阻断流程）
    - 未设置素材：保持旧行为，从屏幕中心起滑。
    """
    params = node.get("params", {})
    direction = params.get("direction", "up")
    distance = _var_num(params, ctx, "distance", "distance_var", 0.6)
    duration = _var_num(params, ctx, "duration_ms", "duration_var", 600) / 1000.0
    template = params.get("template", "")
    start: tuple[int, int] | None = None
    if template:
        entry = _icon_entry(ctx, template)
        image = entry.get("image") or template
        region = entry.get("region") or None
        if entry.get("mode") == "region_click":
            start = _random_point_in_region(ctx, region)
        else:
            m = _match_template(ctx, image,
                                entry.get("threshold") or 0.85,
                                region=region)
            if m is not None:
                start = _random_point_in_mask(ctx, image, m)
        if start is None:
            return NodeResult(goto="not_found",
                              data={"template": template})
    w, h = ctx.screen_size
    cx, cy = start if start is not None else (w // 2, h // 2)
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
        _log(ctx, f"[dry] 滑动 {direction} {distance}"
                  + (f"（起点素材 {template}）" if template else ""))
    else:
        ctx.executor.swipe(cx, cy, cx + dx, cy + dy, duration=duration)
        _log(ctx, f"滑动 {direction} {distance} 起点=({cx},{cy})"
                  + (f"（素材 {template}）" if template else ""))
    if template:
        return NodeResult(data={"start": (cx, cy),
                                "end": (cx + dx, cy + dy),
                                "template": template})
    return NodeResult()


def _var_num(params: dict, ctx: GraphContext, name: str,
             var_name: str, default: float) -> float:
    """数字参数值：优先 var_name 引用（变量键或 ${键}替换后的数值字符串），
    失败回退固定参数。"""
    v = params.get(name, default)
    ref = str(params.get(var_name, "") or "").strip()
    if ref:
        got = ctx.get_var(ref, None)
        if got is None or str(got).strip() in ("", "None"):
            # ${key} 在 resolve 后已变成数值字符串（如 "3"）
            try:
                got = float(ref)
            except Exception:
                got = None
        if got is not None:
            try:
                v = float(got)
            except Exception:
                pass
    try:
        return float(v)
    except Exception:
        return float(default)


def _exec_wait(node: dict, ctx: GraphContext) -> NodeResult:
    """暂停节点（2026-08-16 信号体系）：

    - 未注入 on_wait（示教/测试运行）→ 兼容旧「等待」：固定 sleep 后 out
    - 注入 on_wait（正式运行）：
      首次进入 → 注册暂停（RunController 记录快照）→ 返回 paused（非阻塞挂起）
      恢复执行（ctx.resume_wait=True）→ 按 data['wait_outcome'] 走 out（信号唤醒）
      或 timeout（超时）
    """
    params = node.get("params", {}) or {}
    seconds = _var_num(params, ctx, "seconds", "seconds_var", 60)
    signal = str(params.get("signal", "") or "")
    if ctx.on_wait is None:
        if ctx.sleep(float(seconds)):
            return NodeResult(status="interrupted", message="等待期间被停止")
        return NodeResult()
    if ctx.resume_wait:
        outcome = str(ctx.data.get("wait_outcome") or "resume")
        if outcome == "timeout":
            _log(ctx, f"暂停超时: {ctx.task_id}")
            return NodeResult(goto="timeout")
        _log(ctx, f"暂停恢复: {ctx.task_id}" + (f" (信号 {signal})" if signal else ""))
        return NodeResult()
    # 首次进入：注册暂停 → 非阻塞挂起（快照由 RunController 保存）
    try:
        ctx.on_wait(ctx.task_id, signal, float(seconds), node.get("id", ""))
    except Exception:
        pass
    ctx.data["_pause_node_id"] = node.get("id", "")
    ctx.data["_pause_signal"] = signal
    ctx.data["_pause_seconds"] = seconds
    _log(ctx, f"任务暂停: {ctx.task_id}" + (f" (等信号 {signal})" if signal else ""))
    return NodeResult(status="paused")


def _exec_task_signal_out(node: dict, ctx: GraphContext) -> NodeResult:
    """任务信号输出（2026-08-16）：发出信号后不暂停，继续向下执行。"""
    params = node.get("params", {}) or {}
    signal = str(params.get("signal", "") or "")
    if not signal:
        return NodeResult(status="error", message="任务信号输出未设置信号名")
    payload = params.get("payload") or ""
    if ctx.signal_emit is not None:
        try:
            ctx.signal_emit(signal, payload)
        except Exception:
            pass
    _log(ctx, f"任务信号输出: [{signal}]" + (f" payload={payload}" if payload else ""))
    return NodeResult(data={"task_signal": signal})


def _exec_task_signal_in(node: dict, ctx: GraphContext) -> NodeResult:
    """任务信号接收（2026-08-16）：仅任务正在执行时生效；执行到这里=恢复点，直接通过。"""
    params = node.get("params", {}) or {}
    signal = str(params.get("signal", "") or "")
    _log(ctx, f"任务信号接收点: [{signal or '(未设置)'}]")
    return NodeResult(data={"task_signal": signal})


def _exec_scene_signal_in(node: dict, ctx: GraphContext) -> NodeResult:
    """场景信号接收（2026-08-16）：任务内场景识别器命中后图执行跳转到这里，直接通过。"""
    scene_id = str(node.get("params", {}).get("scene", "") or "")
    _log(ctx, f"场景信号接收: [{scene_id}]")
    return NodeResult(data={"scene_signal": scene_id})


def _exec_task_signal_trigger(node: dict, ctx: GraphContext) -> NodeResult:
    """任务信号触发器（2026-08-16）：图内存在此节点 = 该任务是触发任务；
    同名任务信号触发时被激活，从 out 接调度器分支。"""
    signal = str(node.get("params", {}).get("signal", "") or "")
    if not signal:
        return NodeResult(status="error", message="任务信号触发器未设置信号名")
    _log(ctx, f"⚡ 任务信号触发器激活: [{signal}]")
    return NodeResult(data={"triggered_signal": signal})


def _exec_scheduler_ops(node: dict, ctx: GraphContext) -> NodeResult:
    """调度器分支（2026-08-16）：四个出口只接一个（按图内连线决定），
    执行对应调度器操作并从该出口继续。"""
    graph = ctx.task.get("graph", {}) or {}
    ports = ["enqueue_pending", "enqueue_running", "skip", "invalidate"]
    connected = []
    for c in graph.get("connections", []):
        if c.get("out_node") == node.get("id") and c.get("out_port") in ports:
            connected.append(c.get("out_port"))
    connected = [p for p in ports if p in connected]
    if not connected:
        return NodeResult(status="error", message="调度器分支未连接任何出口")
    port = connected[0]
    op_map = {"enqueue_pending": "pending", "enqueue_running": "running",
              "skip": "skip", "invalidate": "invalidate"}
    if ctx.scheduler_op is not None:
        try:
            ctx.scheduler_op(op_map[port], ctx.task_id)
        except Exception:
            pass
    _log(ctx, f"调度器分支: {port}（{ctx.task_id}）")
    return NodeResult(goto=port, data={"scheduler_op": port})


def _exec_timeout(node: dict, ctx: GraphContext) -> NodeResult:
    """超时节点（2026-08-16）：暂停超时走到这里 → 判定异常，交由全局任务安全结束。"""
    _log(ctx, "⏰ 暂停超时：任务判定异常，转全局任务安全结束")
    return NodeResult(status="abnormal", message="等待超时",
                      data={"abnormal_reason": "wait_timeout"})


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


# ── 可调用变量（2026-08-16）─────────────────────────────────

def _parse_callable_value(raw: str):
    """运算值解析：带引号→text；true/false→bool；空→None；数字→int/float；其余→原字符串"""
    s = (raw or "").strip()
    if not s:
        return None
    if len(s) >= 2 and s[0] in ("'", '"') and s[-1] == s[0]:
        return s[1:-1]
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        if "." in s or "e" in low:
            return float(s)
        return int(s)
    except Exception:
        return s


def _coerce_by_type(v, vtype: str):
    """按声明类型规整（跨运行从 json 读回的可能是字符串）"""
    if vtype == "int":
        return int(float(v))
    if vtype == "float":
        return float(v)
    if vtype == "bool":
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("1", "true", "yes", "是")
    return "" if v is None else str(v)


def _exec_param_process(node: dict, ctx: GraphContext) -> NodeResult:
    """参数处理（2026-08-16）：只允许处理「可调用」变量。

    运算符：加/减/乘/除以/取余（数字）、变化为（任意类型）、取反（bool）。
    值跨运行保留（callable_store）+ 事件同步 UI（on_callable_changed）。
    """
    params = node.get("params", {}) or {}
    name = str(params.get("var_name", "") or "").strip()
    op = params.get("op", "加")
    if not name:
        return NodeResult(status="error", message="参数处理：未设置变量名")
    callables = vs.callable_var_defs((ctx.task or {}).get("graph", {}))
    if name not in callables:
        return NodeResult(status="error",
                          message=f"参数处理：变量「{name}」未在变量组中勾选「可调用」")
    vtype = callables[name]["type"]
    val = _parse_callable_value(params.get("value", ""))

    cur = ctx.get_var(name, None)
    if cur is None:
        cur = callables[name].get("default")
    try:
        cur = _coerce_by_type(cur, vtype)
    except Exception:
        cur = None

    result: Any = None
    if op in ("加", "减", "乘", "除以", "取余"):
        try:
            a = float(cur) if cur is not None else 0.0
            b = float(val) if val is not None else 0.0
        except Exception:
            return NodeResult(
                status="error",
                message=f"参数处理：{op} 需要数字（当前值 {cur!r} / 运算值 {val!r}）")
        if op == "加":
            result = a + b
        elif op == "减":
            result = a - b
        elif op == "乘":
            result = a * b
        elif op == "除以":
            if b == 0:
                return NodeResult(status="error", message="参数处理：除以 0")
            result = a / b
        else:  # 取余
            if int(b) == 0:
                return NodeResult(status="error", message="参数处理：取余 0")
            result = a % b
        if vtype == "int":
            result = int(result)
        else:
            result = float(result)
    elif op == "变化为":
        if val is None:
            return NodeResult(status="error", message="参数处理：变化为需要运算值")
        result = val
        if vtype == "int":
            try:
                result = int(float(result))
            except Exception:
                return NodeResult(status="error",
                                  message=f"参数处理：{result!r} 不是 int 类型")
        elif vtype == "float":
            try:
                result = float(result)
            except Exception:
                return NodeResult(status="error",
                                  message=f"参数处理：{result!r} 不是 float 类型")
        elif vtype == "bool":
            if not isinstance(result, bool):
                return NodeResult(
                    status="error",
                    message=f"参数处理：{result!r} 不是 bool（请用 true/false）")
        else:  # text
            if isinstance(result, bool):
                return NodeResult(
                    status="error",
                    message="参数处理：text 类型运算值需带引号（如 '充足'）")
            result = str(result)
    elif op == "取反":
        if vtype != "bool":
            return NodeResult(status="error", message="参数处理：取反只支持 bool 类型")
        result = not bool(cur)
    else:
        return NodeResult(status="error", message=f"参数处理：未知运算符「{op}」")

    ctx.set_var(name, result)
    if ctx.callable_store is not None and hasattr(ctx.callable_store, "update"):
        try:
            ctx.callable_store.update(name, result)
        except Exception:
            pass
    if ctx.on_callable_changed is not None:
        try:
            ctx.on_callable_changed(name, result)
        except Exception:
            pass
    _log(ctx, f"参数处理: {name} {op} → {result}")
    return NodeResult(data={name: result})


def _exec_start(node: dict, ctx: GraphContext) -> NodeResult:
    return NodeResult()


def _exec_end(node: dict, ctx: GraphContext) -> NodeResult:
    return NodeResult(status="end", message="任务结束")


def _exec_scene_probe(node: dict, ctx: GraphContext) -> NodeResult:
    """场景判定（2026-08-15）：将截图器帧与本任务场景素材对比。

    命中 → out（true）；未命中 → not_found（false）继续往下。
    识别精度（特征值）由场景素材内的 accuracy 决定（示教保存时录入）。
    """
    params = node.get("params", {})
    scene_id = params.get("scene", "")
    out_var = params.get("output_var", "")
    if not scene_id:
        return NodeResult(status="error",
                          message="场景判定未设置场景素材")
    scene = ctx.get_scene(scene_id)
    if scene is None:
        return NodeResult(status="error", message=f"场景素材不存在: {scene_id}")
    if ctx.stopped():
        return NodeResult(status="interrupted")
    hit = _judge_scene(scene, ctx)
    if out_var:
        ctx.set_var(out_var, "1" if hit else "0")
    if hit:
        sig = scene.get("signal") or scene_id
        _log(ctx, f"场景命中: {scene.get('name', scene_id)} (信号: {sig})")
        # 场景判定成功输出场景信号（供信号触发器/分支引用）
        ctx.data["scene_signal"] = sig
        ctx.data["scene_id"] = scene_id
        return NodeResult(data={"scene": scene_id, "signal": sig})
    # 未命中 → not_found 直接继续（不再阻断等示教）
    return NodeResult(goto="not_found", data={"scene": None})


def query_signal_table(ctx: GraphContext) -> str:
    """全局场景信号表（任务外置配置，2026-08-15）：一次截图多分类识别。

    命中 → 返回场景 id（写 ctx.data['scene_signal']/['scene_score']，
           连续同场景计数累计在 ctx.data['_streak_*']）；
    全无命中 → 返回 ""（清空信号与 streak）。
    连续 retry_limit 次识别出同一场景 → raise RuntimeError（调用方转 error）。
    """
    st = (ctx.task.get("settings", {}) or {}).get("signal_table", {}) or {}
    scene_ids = [str(s).strip() for s in st.get("scenes", []) if str(s).strip()]
    if not scene_ids and ctx.scene_lister is not None:
        try:
            scene_ids = [s.get("id", "") for s in ctx.scene_lister()]
        except Exception:
            scene_ids = []
    if not scene_ids:
        raise RuntimeError("场景信号表无可用场景（scenes 为空且场景库无场景）")
    retry_limit = int(st.get("retry_limit", 5) or 0)

    best_id, best_score = "", 0.0
    best_signal = ""
    for sid in scene_ids:
        scene = ctx.get_scene(sid)
        if scene is None:
            continue
        hit, score = _judge_scene_score(scene, ctx)
        if hit and score > best_score:
            best_id, best_score = sid, score
            best_signal = scene.get("signal") or sid

    if not best_id:
        # 全无命中：异常画面（脱离任务，由调用方接示教）
        ctx.data["scene_signal"] = None
        ctx.data["_streak_scene"] = ""
        ctx.data["_streak_count"] = 0
        return ""

    # 连续同一场景重试保护（场景切换后自动清零）
    last = ctx.data.get("_streak_scene", "")
    count = int(ctx.data.get("_streak_count", 0) or 0)
    count = count + 1 if best_id == last else 1
    ctx.data["_streak_scene"] = best_id
    ctx.data["_streak_count"] = count
    if retry_limit > 0 and count >= retry_limit:
        raise RuntimeError(
            f"连续 {count} 次识别出同一场景 [{best_id}]，疑似卡死")
    ctx.data["scene_signal"] = best_signal
    ctx.data["scene_id"] = best_id
    ctx.data["scene_score"] = best_score
    _log(ctx, f"场景信号: {best_signal} (score={best_score:.2f}, streak={count})")
    return best_id


def _exec_scene_trigger(node: dict, ctx: GraphContext) -> NodeResult:
    """信号触发器（2026-08-15）：监听场景 id，被全局场景信号表命中后激活，
    从 out 开始执行场景内逻辑。只被信号激活，不接受控制流连线进入。"""
    scene_id = node.get("params", {}).get("scene", "")
    if not scene_id:
        return NodeResult(status="error", message="信号触发器未设置监听场景")
    _log(ctx, f"🔔 信号触发器激活: [{scene_id}]")
    return NodeResult(data={"active_scene": scene_id})



def _exec_icon_count(node: dict, ctx: GraphContext) -> NodeResult:
    """图标计数（2026-08-15）：统计截图中特征比对通过（≥阈值）的图标个数。

    多实例匹配（NMS 去重）→ 数目写入输出变量（供分支/循环判断）+
    data.count。随机点击素材（mode=region_click）无特征模板，不支持计数。
    """
    params = node.get("params", {}) or {}
    template = params.get("template", "")
    out_var = params.get("output_var", "")
    if not template:
        return NodeResult(status="error",
                          message="图标计数未设置操作识别素材")
    entry = _icon_entry(ctx, template)
    if entry.get("mode") == "region_click":
        return NodeResult(status="error",
                          message=f"随机点击素材不支持计数: {template}")
    image = entry.get("image") or template
    region = entry.get("region") or None
    th = entry.get("threshold") or 0.85
    matches = _match_all_templates(ctx, image, th, region=region)
    count = len(matches)
    if out_var:
        ctx.set_var(out_var, count)
    _log(ctx, f"图标计数 {template}: 命中 {count} 个")
    return NodeResult(data={"count": count, "template": template,
                            "matches": [list(m[:4]) for m in matches]})


def _exec_ocr_reader(node: dict, ctx: GraphContext) -> NodeResult:
    """OCR读取（2026-08-15）：OCR 识别素材 = 红框搜索区域 + 蓝框遮罩标识
    + 黄框文字位置（相对蓝框匹配点）。

    蓝框遮罩在红框区域内匹配成功后，按黄框相对偏移裁剪截图 → OCR 提取文字；
    含关键词走 out，否则 miss；文本存输出变量。
    """
    params = node.get("params", {})
    template = params.get("template", "")
    keyword = params.get("keyword", "")
    out_var = params.get("output_var", "")
    if not template:
        return NodeResult(status="error",
                          message="OCR读取未设置OCR识别素材")
    entry = _icon_entry(ctx, template)
    image = entry.get("image") or template
    if not image:
        return NodeResult(status="error",
                          message=f"OCR识别素材无效: {template}")
    ocr_box = entry.get("ocr_box")
    if not ocr_box or len(ocr_box) != 4:
        return NodeResult(status="error",
                          message=f"OCR识别素材缺少黄框文字位置: {template}")
    if ctx.ocr is None:
        return NodeResult(status="error",
                          message="OCR 引擎不可用：请安装 paddleocr（pip install paddleocr）后重启程序")
    # 懒加载：首次使用才初始化 paddle 引擎（可能需下载模型，耗时较长）
    if not getattr(ctx.ocr, "is_ready", False):
        try:
            ctx.ocr.initialize()
        except Exception as e:
            return NodeResult(status="error",
                              message=f"OCR 引擎初始化失败: {e}")
    # 蓝框遮罩在红框区域内匹配（匹配点=遮罩裁剪左上角）
    m = _match_template(ctx, image, entry.get("threshold") or 0.85,
                        region=entry.get("region") or None)
    if m is None:
        return NodeResult(goto="miss", data={"template": template})
    # 黄框位置 = 匹配点 + 相对像素偏移；裁剪 → OCR
    screen = ctx.screenshot()
    H, W = screen.shape[:2]
    dx, dy, dw, dh = (int(round(float(v))) for v in ocr_box)
    x0 = max(0, min(W - 1, int(m[0]) + dx))
    y0 = max(0, min(H - 1, int(m[1]) + dy))
    x1 = max(x0 + 1, min(W, x0 + max(1, dw)))
    y1 = max(y0 + 1, min(H, y0 + max(1, dh)))
    crop = screen[y0:y1, x0:x1]
    try:
        results = ctx.ocr.recognize(crop)
    except Exception as e:
        return NodeResult(status="error", message=f"OCR 失败: {e}")
    texts = [r.text for r in results]
    joined = "".join(texts)
    if out_var:
        ctx.set_var(out_var, joined)
    _log(ctx, f"OCR 区域[{x0},{y0},{x1 - x0}x{y1 - y0}] "
              f"识别文本: {joined!r}")
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


def _exec_screenshot(node: dict, ctx: GraphContext) -> NodeResult:
    """截图器（2026-08-15）：唯一截图权节点，截一帧写入帧缓存（prev=旧帧）。

    测试运行时会同步把该帧发到截图器节点上直接预览（ComfyUI 预览节点风格）；
    正式任务不注入 publish_image → 零额外开销。
    """
    try:
        img = ctx.capture_frame()
    except Exception as e:
        return NodeResult(status="error", message=f"截图失败: {e}")
    if img is not None and ctx.publish_image is not None:
        try:
            ok, buf = cv2.imencode(".png", img)
            if ok:
                ctx.publish_image(node.get("id"), buf.tobytes())
        except Exception:
            pass
    h, w = img.shape[:2]
    _log(ctx, f"截图 {w}x{h} → 帧缓存")
    return NodeResult(data={"width": w, "height": h})


def _exec_compound(node: dict, ctx: GraphContext) -> NodeResult:
    """复合节点（2026-08-15）：内联执行子图（框选封装片段 / 通用节点库导入）。

    子图优先取节点内嵌 subgraph；无内嵌时按 params.source 从通用节点库加载。
    """
    params = node.get("params", {})
    source = params.get("source", "")
    sub = node.get("subgraph")
    if not sub and source and ctx.get_compound is not None:
        try:
            loaded = ctx.get_compound(source)
            sub = loaded.get("subgraph") if loaded else None
        except Exception:
            sub = None
    if not sub or not sub.get("nodes"):
        return NodeResult(status="error",
                          message=f"复合节点子图缺失: {source or node.get('name')}")
    from visual.graph_runner import run_graph
    result = run_graph(sub, ctx, is_subgraph=True,
                       entry_id=sub.get("entry_id"))
    if result.status == "error":
        return NodeResult(status="error",
                          message=f"复合节点[{source or node.get('name')}]失败: "
                                  f"{result.error_message}")
    if result.status == "interrupted":
        return NodeResult(status="interrupted",
                          message=f"复合节点[{source}]被中断")
    _log(ctx, f"复合节点完成: {source or node.get('name')}")
    return NodeResult(data={"compound": source or node.get("name", "")})


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
    params = node.get("params", {}) or {}
    direction = params.get("direction", "up")
    steps = int(_var_num(params, ctx, "steps", "steps_var", 3))
    _log(ctx, f"滚动捕获 {direction} × {steps}")
    frames: list = []
    for i in range(steps):
        if ctx.stopped():
            return NodeResult(status="interrupted")
        try:
            img = ctx.frame if ctx.frame is not None else ctx.screenshot()
            if img is not None:
                frames.append(img)
        except Exception:
            pass
        if i < steps - 1:
            _exec_dragger({"params": {"direction": direction, "distance": 0.7,
                                      "duration_ms": 600}}, ctx)
            # 拖动后画面已变：清帧缓存，强制下一步实时截图
            # （否则前面截图器节点留下的旧帧会被每步重复拼接）
            ctx.clear_frame()
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
        from core.cv_io import imwrite as _cv_imwrite
        if not _cv_imwrite(str(out_path), pano):
            return NodeResult(status="error", message="全景保存失败（图片写入错误）")
    except Exception as e:
        return NodeResult(status="error", message=f"全景保存失败: {e}")
    _log(ctx, f"全景已保存: {out_path} ({pano.shape[1]}x{pano.shape[0]})")
    return NodeResult(data={"panorama": str(out_path), "width": int(pano.shape[1]),
                            "height": int(pano.shape[0])})


# ═══════════════════════════════════════════════════════════════
#  场景判定（SceneProbe，4.3/4.9）
# ═══════════════════════════════════════════════════════════════

def _judge_scene(scene: dict, ctx: GraphContext) -> bool:
    hit, _ = _judge_scene_score(scene, ctx)
    return hit


def _judge_scene_score(scene: dict, ctx: GraphContext) -> tuple[bool, float]:
    """场景判定 + 匹配分数（场景信号表多分类取最高分用）。

    命中 → (True, 0~1 平均匹配分数)；未命中 → (False, 0.0)。
    v2 结构（regions）与旧结构（judgements + logic）统一入口。
    """
    if scene.get("regions"):
        return _judge_scene_v2_score(scene, ctx)
    judgements = scene.get("judgements", [])
    if not judgements:
        return False, 0.0
    logic = scene.get("logic", "and")
    results = [_judge_one_score(j, ctx) for j in judgements]
    scores = [s for h, s in results if h]
    if not scores:
        return False, 0.0
    if logic == "or":
        return True, max(scores)
    if len(scores) != len(results):
        return False, 0.0
    return True, sum(scores) / len(scores)


def _judge_scene_v2(scene: dict, ctx: GraphContext) -> bool:
    hit, _ = _judge_scene_v2_score(scene, ctx)
    return hit


def _judge_scene_v2_score(scene: dict, ctx: GraphContext) -> tuple[bool, float]:
    """v2 场景判定 + 分数：遍历 红框(搜索范围)→蓝框(整体标识) 匹配，
    命中数 >= 精度即通过；分数 = 命中蓝框的平均分。

    每个蓝框 = 一组独立遮罩块（连通域），整体匹配要求每个块都命中
    且相对位置对应。accuracy=0 表示全部蓝框命中。
    """
    regions = scene.get("regions", [])
    if not regions:
        return False, 0.0
    accuracy = int(scene.get("accuracy", 0) or 0)
    total = 0
    hits = 0
    scores: list[float] = []
    for region in regions:
        rr = region.get("region")  # 红框搜索范围 [x,y,w,h] 相对，None=全屏
        for marker in region.get("markers", []):
            total += 1
            hit, score = _match_marker_score(marker, ctx, region=rr)
            if hit:
                hits += 1
                scores.append(score)
    need = accuracy if accuracy > 0 else total
    if need <= 0 or hits < need or not scores:
        return False, 0.0
    return True, sum(scores) / len(scores)


def _match_marker(marker: dict, ctx: GraphContext, region: Any = None) -> bool:
    hit, _ = _match_marker_score(marker, ctx, region=region)
    return hit


def _match_marker_score(marker: dict, ctx: GraphContext,
                        region: Any = None) -> tuple[bool, float]:
    """蓝框整体标识匹配 + 分数：每个独立遮罩块都要在搜索区域（红框）内命中，
    且各块的相对位置与示教时对应；分数 = 各块匹配分数平均。

    结构：marker.templates = [{template, dx, dy}]（dx/dy=相对第一块的像素偏移）；
    兼容旧结构 marker.template（单模板）。
    """
    thr = float(marker.get("threshold", 0.85))
    templates = marker.get("templates") or []
    if not templates:
        tpl = marker.get("template", "")
        if not tpl:
            return False, 0.0
        m = _match_template_score(ctx, tpl, thr, region=region)
        return (True, m[4]) if m is not None else (False, 0.0)
    # 第一块：在搜索区域（红框）内定位
    first = templates[0]
    m0 = _match_template_score(ctx, first.get("template", ""), thr, region=region)
    if m0 is None:
        return False, 0.0
    # 排除素材（2026-08-15）：蓝框级排除，主块命中后检查排除特征，
    # 命中任一 → 该标识不通过
    if _exclusions_hit(ctx, marker.get("exclusions"),
                       m0[0], m0[1], m0[2], m0[3]):
        return False, 0.0
    x0, y0 = m0[0], m0[1]
    score = float(m0[4])
    n = 1
    # 其余块：在相对偏移位置附近核对（位置对应，容差=块尺寸的一半）
    for t in templates[1:]:
        tpl = _load_template(ctx, t.get("template", ""))
        if tpl is None:
            return False, 0.0
        th, tw = tpl.shape[0], tpl.shape[1]
        dx, dy = int(t.get("dx", 0)), int(t.get("dy", 0))
        cx = x0 + dx + tw // 2
        cy = y0 + dy + th // 2
        r = max(15, max(tw, th) // 2)
        near = [cx - r, cy - r, 2 * r + tw, 2 * r + th]  # 绝对像素搜索区
        m = _match_template_score(ctx, t.get("template", ""), thr, region=near)
        if m is None:
            return False, 0.0
        score += float(m[4])
        n += 1
    return True, score / n


def _judge_one(judgement: dict, ctx: GraphContext) -> bool:
    hit, _ = _judge_one_score(judgement, ctx)
    return hit


def _judge_one_score(judgement: dict, ctx: GraphContext) -> tuple[bool, float]:
    """旧结构 judgement 判定 + 分数（template 有真实匹配分，其余 1.0/0.0）"""
    primitive = judgement.get("primitive", "template")
    try:
        if primitive == "template":
            return _judge_template_score(judgement, ctx)
        if primitive == "ocr_contains":
            hit = _judge_ocr(judgement, ctx)
            return hit, (1.0 if hit else 0.0)
        if primitive == "color_block":
            hit = _judge_color(judgement, ctx)
            return hit, (1.0 if hit else 0.0)
        if primitive == "edge_line":
            hit = _judge_edge(judgement, ctx)
            return hit, (1.0 if hit else 0.0)
    except Exception:
        return False, 0.0
    return False, 0.0


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


def _parse_exclusions(base: Path, entry_path: Path, raw) -> list[dict]:
    """解析排除素材列表：image 文件名 → 相对 assets 根的路径。

    image 与条目 json 同目录（排除 PNG 保存处），运行时经 assets 根加载。
    """
    out: list[dict] = []
    for ex in raw or []:
        if not isinstance(ex, dict):
            continue
        eimg = ex.get("image") or ""
        if not eimg:
            continue
        ep = Path(eimg)
        ep_path = ep if ep.is_absolute() else entry_path.parent / ep
        if ep_path.exists():
            try:
                erel = ep_path.relative_to(base).as_posix()
            except Exception:
                erel = str(ep_path)
        else:
            erel = eimg
        out.append({"image": erel,
                    "region": ex.get("region") or None,
                    "threshold": float(ex.get("threshold") or 0.85)})
    return out


def _exclusions_hit(ctx: GraphContext, exclusions: list[dict],
                    mx: int, my: int, mw: int, mh: int) -> bool:
    """排除素材判定（2026-08-15）：在主图标匹配框 (mx,my,mw,mh) 内逐个搜索
    排除特征（region 相对图标框，命中任一即排除）。

    exclusions: [{image, region(相对图标框 [x,y,w,h] 或 None=整框), threshold}]

    ⚠️ 判定阈值下限 0.92：纯色模板在灰背景上 TM_SQDIFF_NORMED 归一化分数
    会到 0.86+（假命中），真特征约 1.0——0.92 才能区分"真有特征"与背景噪音。
    """
    for ex in exclusions or []:
        if not isinstance(ex, dict):
            continue
        img = ex.get("image") or ""
        if not img:
            continue
        thr = max(0.92, float(ex.get("threshold") or 0.85))
        reg = ex.get("region")
        if reg:
            try:
                rx, ry, rw, rh = (float(v) for v in reg)
                area = [mx + int(rx * mw), my + int(ry * mh),
                        max(1, int(rw * mw)), max(1, int(rh * mh))]
            except Exception:
                area = [mx, my, mw, mh]
        else:
            area = [mx, my, mw, mh]
        m = _match_template_score(ctx, img, 0.0, region=area)
        if m is not None and float(m[4]) >= thr:
            return True
    return False


def _match_template(ctx: GraphContext, rel_path: str,
                    threshold: float, index: int = 0,
                    region: Any = None) -> tuple | None:
    """模板匹配（兼容旧接口）：返回 (x, y, w, h) 或 None"""
    m = _match_template_score(ctx, rel_path, threshold, index=index,
                              region=region)
    if m is None:
        return None
    return m[:4]


def _match_all_templates(ctx: GraphContext, rel_path: str,
                         threshold: float,
                         region: Any = None) -> list[tuple]:
    """匹配所有 ≥threshold 的实例（NMS 去重，2026-08-15 图标计数用）。

    返回 [(x, y, w, h, score), ...]（绝对屏幕坐标，从上到下从左到右排序）。
    """
    tpl = _load_template(ctx, rel_path)
    if tpl is None:
        return []
    mask = None
    if tpl.ndim == 3 and tpl.shape[2] == 4:
        mask = tpl[:, :, 3]
        tpl = tpl[:, :, :3]
    screen = ctx.screenshot()
    if screen is None:
        return []
    try:
        offset_x = offset_y = 0
        if region:
            r = _parse_region(region, screen)
            if r is None:
                return []
            rx, ry, rw, rh = r
            screen = screen[ry:ry + rh, rx:rx + rw]
            offset_x, offset_y = rx, ry
        th, tw = tpl.shape[0], tpl.shape[1]
        if th > screen.shape[0] or tw > screen.shape[1]:
            return []
        if mask is not None:
            res = cv2.matchTemplate(screen, tpl, cv2.TM_SQDIFF_NORMED,
                                    mask=mask)
            res = 1.0 - res
        else:
            screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
            tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
            low_texture = float(np.std(tpl_gray)) < 10.0
            if low_texture:
                res = cv2.matchTemplate(screen_gray, tpl_gray,
                                        cv2.TM_SQDIFF_NORMED)
                res = 1.0 - res
            else:
                res = cv2.matchTemplate(screen_gray, tpl_gray,
                                        cv2.TM_CCOEFF_NORMED)
        res = np.nan_to_num(res, nan=-1.0)
        ys, xs = np.where(res >= threshold)
        if len(xs) == 0:
            return []
        # 按分数降序做 NMS：高分真峰值先保留，抑制其低分邻域，
        # 避免低分邻居先保留导致真峰值被挤掉（mask 匹配下 SQDIFF 分数
        # 会向邻域扩散）
        if len(xs) > 3000:
            # 性能保护：低阈值下灰背景全像素都是候选（数万），
            # NMS O(n×picked) 会卡死——截断到分数最高的前 3000 个
            order = sorted(range(len(xs)),
                           key=lambda i: float(res[ys[i], xs[i]]),
                           reverse=True)[:3000]
        else:
            order = sorted(range(len(xs)),
                           key=lambda i: float(res[ys[i], xs[i]]),
                           reverse=True)
        picked: list[tuple[int, int]] = []
        out: list[tuple] = []
        for i in order:
            px, py = int(xs[i]), int(ys[i])
            # 标准 NMS：与所有已选实例均不重叠（|dx|>=tw 或 |dy|>=th）才保留
            if all(abs(px - ox) >= tw or abs(py - oy) >= th
                   for ox, oy in picked):
                picked.append((px, py))
                out.append((px + offset_x, py + offset_y, tw, th,
                            float(res[py, px])))
        # 输出按位置（从上到下从左到右）排序，保持遍历直观
        out.sort(key=lambda m: (m[1], m[0]))
        return out
    except Exception:
        return []


def _match_template_score(ctx: GraphContext, rel_path: str,
                          threshold: float, index: int = 0,
                          region: Any = None) -> tuple | None:
    """模板匹配：返回 (x, y, w, h, score) 或 None；index>0 取第 N 个匹配（多实例）。

    score = 匹配相似度（0~1，越大越像），供场景信号表多分类取最高分。

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
                return (x + offset_x, y + offset_y, tw, th, float(max_val))
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
                    return (px + offset_x, py + offset_y, tw, th,
                            float(res[py, px]))
        return None
    except Exception:
        return None


def _judge_template(j: dict, ctx: GraphContext) -> bool:
    hit, _ = _judge_template_score(j, ctx)
    return hit


def _judge_template_score(j: dict, ctx: GraphContext) -> tuple[bool, float]:
    """旧结构 template judgement 判定 + 匹配分数"""
    tpl = j.get("template", "")
    threshold = float(j.get("threshold", 0.85))
    m = _match_template_score(ctx, tpl, threshold)
    if m is not None:
        return True, float(m[4])
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
                m = _match_template_score(ctx, tpl, threshold)
                return (True, float(m[4])) if m is not None else (False, 0.0)
            finally:
                ctx._screenshot = old
    return False, 0.0


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
    "param_process": _exec_param_process,
    "clicker": _exec_clicker,
    "dragger": _exec_dragger,
    "scene_probe": _exec_scene_probe,
    "scene_trigger": _exec_scene_trigger,
    "screenshot": _exec_screenshot,
    "ocr_reader": _exec_ocr_reader,
    "icon_count": _exec_icon_count,
    "branch": _exec_branch,
    "loop": _exec_loop,
    "checker": _exec_checker,
    "refresher": _exec_refresher,
    "navigator": _exec_navigator,
    "scroll_capture": _exec_scroll_capture,
    "compound": _exec_compound,
    # ── 信号体系（2026-08-16）──
    "task_signal_out": _exec_task_signal_out,
    "task_signal_in": _exec_task_signal_in,
    "scene_signal_in": _exec_scene_signal_in,
    "task_signal_trigger": _exec_task_signal_trigger,
    "scheduler_ops": _exec_scheduler_ops,
    "timeout": _exec_timeout,
}


# 操作节点（执行后画面已变 → 自动清帧，强制下次识图前先过截图器）
_ACTION_NODES = {"clicker", "dragger", "navigator", "refresher",
                 "scroll_capture", "compound"}


def dispatch(node: dict, ctx: GraphContext) -> NodeResult:
    fn = _EXECUTORS.get(node.get("type", ""))
    if fn is None:
        return NodeResult(status="error", message=f"未知节点类型: {node.get('type')}")
    try:
        result = fn(node, ctx)
        # 操作节点执行后清帧（画面已变，防止识图读到操作前的旧帧）
        if node.get("type") in _ACTION_NODES:
            ctx.clear_frame()
        return result
    except Exception as e:
        return NodeResult(status="error", message=f"{node.get('name')}: {e}")
