"""
任务模板生成器（Task Template Generator）

独立模块（不依赖调度/运行核心）：
- 按任务类型生成 .py 骨架代码（非战斗/战斗/通用/触发）
- 生成 tasks.yaml 默认调度条目（通用任务除外）
- 纯文本生成，无文件副作用（文件写入由 13-任务文件管理 调用方负责）

任务类型：
  event_task  非战斗任务：无作战配置，带时间调度（repeat）
  battle      战斗任务：带作战配置（御魂/锁定/换队），带时间调度
  generic     通用任务：无调度配置，作为 TaskStep 被其他游戏任务引用
  trigger     触发任务：无时间调度，由外部触发（手动按钮/识图/其他任务事件）

设计原则：模板只给"骨架 + 注释指引"，运行期调度/战斗配置均从 tasks.yaml 读取
（05/14 模块机制），不把配置写死在代码里，避免耦合。
"""
from __future__ import annotations

# ── 任务类型常量 ────────────────────────────────────────────

TASK_TYPES = ("event_task", "battle", "generic", "trigger")

TASK_TYPE_LABELS = {
    "event_task": "非战斗任务",
    "battle": "战斗任务",
    "generic": "通用任务",
    "trigger": "触发任务",
}

# ── 占位符（避免 format 大括号转义）────────────────────────

_N = "__NAME__"        # 任务名（文件名，不含 .py）
_D = "__DISPLAY__"     # 显示名
_C = "__CATEGORY__"    # 分类（daily/permanent/event/special/common）
_K = "__CLASS__"       # 类名（大驼峰）

# ── 非战斗任务模板 ──────────────────────────────────────────

_TEMPLATE_EVENT = """\"\"\"{_D} 任务（非战斗）

{_C} 分类。时间调度（repeat）已在 tasks.yaml 自动写入默认条目，运行期由 05-时间调度模块读取；
在下方只写"何时点击什么按钮"的执行逻辑即可。

素材（图片）约定（core/asset_catalog.py）：
  本任务专属图片 → assets/tasks/{_N}/，代码引用 "tasks/{_N}/xxx"
  通用共享图片 → assets/tasks/_shared/，引用 "tasks/_shared/xxx"
  识图（场景确认）素材 → assets/scene/，scene_probe 引用 "scene/xxx"
\"\"\"
from __future__ import annotations

from typing import Any

from tasks.base.base_task import BaseTask
from tasks.base.task_graph import TaskGraph
from tasks.base.task_step import StepResult, TaskStep

# ── 模块级声明（UI 配置表单依据，13-任务文件管理 §2.2）──────
display_name = "{_D}"
description = "{_D}"
task_type = "event_task"     # "battle" | "event_task"
uses_battle = False          # 非战斗任务：不需要作战配置
uses_team = False            # 需要阵容配置 → 改 True
uses_soul = False            # 需要御魂配置 → 改 True
uses_stamina = False         # 需要体力门槛 → 改 True
loop_count = 1               # 每轮循环次数
timeout = 300                # 任务总超时（秒）


class StepOne(TaskStep):
    \"\"\"步骤1 示例：点击目标 → 14-执行器（02识图→03防封→01设备点击）\"\"\"
    is_generic = False
    timeout = 20

    def execute(self, context=None):
        # TODO: 在这里写"何时点击什么按钮"的逻辑，例：
        # context.executor.click_image("common/ui/xxx", timeout=5,
        #                             stop_event=getattr(context, 'stop_event', None))
        return StepResult.success("步骤1完成")


class {_K}(BaseTask):
    \"\"\" {_D} \"\"\"

    task_id = "{_N}"
    display_name = "{_D}"
    description = "{_D}"

    def _build_graph(self) -> TaskGraph:
        \"\"\"声明步骤图（§5.3）：在这里串联你的步骤\"\"\"
        graph = TaskGraph()
        # 例：
        # from tasks.common.close_popup import ClosePopup
        # graph.add_step("step1", StepOne())
        # graph.add_step("close", ClosePopup())
        # graph.set_entry("step1")
        # graph.add_edge("step1", "close")
        return graph
"""

# ── 战斗任务模板 ────────────────────────────────────────────

_TEMPLATE_BATTLE = """\"\"\"{_D} 任务（战斗）

{_C} 分类。战斗配置（御魂/锁定/换队）从 tasks.yaml 读取（_load_battle_config），
时间调度（repeat）已在 tasks.yaml 自动写入；只写"何时点击什么按钮"的执行逻辑即可。

素材（图片）约定（core/asset_catalog.py）：
  本任务专属图片 → assets/tasks/{_N}/，代码引用 "tasks/{_N}/xxx"
  战斗通用图片 → assets/tasks/_shared/，引用 "tasks/_shared/xxx"
  识图（场景确认）素材 → assets/scene/，scene_probe 引用 "scene/xxx"
\"\"\"
from __future__ import annotations

from pathlib import Path
from typing import Any

from tasks.base.base_task import BaseTask
from tasks.base.task_graph import TaskGraph
from tasks.base.task_step import StepResult, TaskStep

# ── 模块级声明（UI 显示战斗配置 Tab）────────────────────────
display_name = "{_D}"
description = "{_D}"
task_type = "battle"
uses_battle = True           # 战斗任务：UI 显示战斗配置 Tab
uses_team = True
uses_soul = True
uses_stamina = True
loop_count = 1
timeout = 600

# ── 战斗配置默认值（运行期从 tasks.yaml 读取，失败回退此常量）──
SOUL_SETUP = {{"group": "御魂副本", "team": "御魂十层", "position": [4, 1]}}
LOCK_TEAM = True
CHANGE_TEAM = True


def _load_battle_config() -> dict:
    \"\"\"从 config/tasks.yaml 读取本任务的战斗配置，失败回退模块常量。\"\"\"
    default = {{"soul_setup": SOUL_SETUP, "lock_team": LOCK_TEAM, "change_team": CHANGE_TEAM}}
    try:
        import yaml
        p = Path(__file__).resolve().parents[2] / "config" / "tasks.yaml"
        if p.exists():
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
            tasks = data.get("tasks", []) if isinstance(data, dict) else []
            for t in tasks:
                if t and t.get("name") == "{_N}":
                    return {{
                        "soul_setup": t.get("soul_setup", SOUL_SETUP),
                        "lock_team": t.get("lock_team", LOCK_TEAM),
                        "change_team": t.get("change_team", CHANGE_TEAM),
                    }}
    except Exception:
        pass
    return default


class EnterBattle(TaskStep):
    \"\"\"步骤1 进入副本 → 点击入口（14→02→03→01）\"\"\"
    is_generic = False
    timeout = 20

    def execute(self, context=None):
        # TODO: 点击副本入口，例：
        # context.executor.click_image("battle/xxx/entry", timeout=5,
        #                             stop_event=getattr(context, 'stop_event', None))
        return StepResult.success("进入副本完成")


class BattleLoop(TaskStep):
    \"\"\"步骤2 战斗循环 → 可引用通用模块 tasks/common/battle_loop.py\"\"\"
    is_generic = False
    timeout = 600

    def execute(self, context=None):
        # TODO: 或引用通用模块：
        # from tasks.common.battle_loop import BattleLoop
        return StepResult.success("战斗完成")


class {_K}(BaseTask):
    \"\"\" {_D} \"\"\"

    task_id = "{_N}"
    display_name = "{_D}"
    description = "{_D}"

    def _build_graph(self) -> TaskGraph:
        graph = TaskGraph()
        # 注入战斗配置 + 串联通用模块（例）：
        # from tasks.common.soul_configure import SoulConfigure
        # from tasks.common.pre_battle_prep import PreBattlePrep
        # cfg = _load_battle_config()
        # graph.add_step("soul", SoulConfigure(params=cfg["soul_setup"]))
        # graph.add_step("prep", PreBattlePrep(params={{'lock_team': cfg['lock_team'],
        #                                               'change_team': cfg['change_team']}}))
        # graph.add_step("battle", BattleLoop())
        # graph.set_entry("soul")
        # graph.add_edge("soul", "prep")
        # graph.add_edge("prep", "battle")
        return graph
"""

# ── 通用任务模板（common，无调度）───────────────────────────

_TEMPLATE_GENERIC = """\"\"\"通用任务：{_D}

通用模块（common）——不单独执行，被其他游戏任务引用为其一部分。
无调度配置（不需要在 tasks.yaml 注册）。

素材（图片）约定（core/asset_catalog.py）：通用模块共享图片 → assets/tasks/_shared/，
代码引用 "tasks/_shared/xxx"。
\"\"\"
from __future__ import annotations

from typing import Any

from tasks.base.task_step import StepResult, TaskStep


class {_K}(TaskStep):
    \"\"\" {_D}（通用步骤，可被任务引用） \"\"\"
    is_generic = True          # 通用模块标记：不注册为独立任务
    timeout = 20

    def __init__(self, params: dict | None = None, **kwargs):
        super().__init__(**kwargs)
        self.params = params or {{}}

    def execute(self, context=None):
        # TODO: 通用逻辑，可读取 self.params 传参，例：
        # group = self.params.get("group")
        # context.executor.click_image("common/ui/xxx", timeout=5,
        #                             stop_event=getattr(context, 'stop_event', None))
        return StepResult.success("{_D}完成")
"""

# ── 触发任务模板（trigger）──────────────────────────────────

_TEMPLATE_TRIGGER = """\"\"\"{_D} 任务（特殊条件触发 trigger）

触发方式（说明书 02 §3.6 + 05 §3.1）：
  ① 手动：UI 队列面板「⚡触发」按钮
  ② 识图：TriggerWatcher 识别到 trigger_templates 中任一模板图自动触发
  ③ 其他任务：发布 trigger_detected(task_name=...) 事件触发
执行后进入已失效「[等待下次触发]」，需再次触发。

素材（图片）约定（core/asset_catalog.py）：
  本任务专属图片（含触发模板图）→ assets/tasks/{_N}/，引用 "tasks/{_N}/xxx"
  识图（场景确认）素材 → assets/scene/，scene_probe 引用 "scene/xxx"
\"\"\"
from __future__ import annotations

from typing import Any

from tasks.base.base_task import BaseTask
from tasks.base.task_graph import TaskGraph
from tasks.base.task_step import StepResult, TaskStep

# ── 模块级声明 ──────────────────────────────────────────────
display_name = "{_D}"
description = "{_D}"
task_type = "event_task"
uses_battle = False
loop_count = 1
timeout = 300

# ── 触发配置：在 UI 配置表单「触发模板」填写 trigger_templates ──
# 识别到这些图片之一 → 自动触发执行；也可在代码/其他任务里发布
# trigger_detected 事件自定义触发条件


class StepOne(TaskStep):
    \"\"\"步骤1 示例：触发后要执行的逻辑\"\"\"
    is_generic = False
    timeout = 20

    def execute(self, context=None):
        # TODO: 触发后执行的动作，例：
        # context.executor.click_image("common/ui/xxx", timeout=5,
        #                             stop_event=getattr(context, 'stop_event', None))
        return StepResult.success("步骤1完成")


class {_K}(BaseTask):
    \"\"\" {_D} \"\"\"

    task_id = "{_N}"
    display_name = "{_D}"
    description = "{_D}"

    def _build_graph(self) -> TaskGraph:
        graph = TaskGraph()
        # graph.add_step("step1", StepOne())
        # graph.set_entry("step1")
        return graph
"""

_TEMPLATES = {
    "event_task": _TEMPLATE_EVENT,
    "battle": _TEMPLATE_BATTLE,
    "generic": _TEMPLATE_GENERIC,
    "trigger": _TEMPLATE_TRIGGER,
}


# ── 公开 API ────────────────────────────────────────────────

def generate(task_type: str, name: str, display: str, category: str) -> str:
    """按任务类型生成 .py 骨架代码。

    Args:
        task_type: event_task / battle / generic / trigger
        name: 任务文件名（不含 .py）
        display: 显示名
        category: 分类（generic 建议传 "common"）

    Raises:
        ValueError: task_type 不支持
    """
    if task_type not in _TEMPLATES:
        raise ValueError(f"不支持的任务类型: {task_type}，可选: {list(_TEMPLATES)}")
    tmpl = _TEMPLATES[task_type]
    class_name = "".join(w.capitalize() for w in name.split("_"))
    return tmpl.format(_N=name, _D=display, _C=category, _K=class_name)


def build_yaml_entry(task_type: str, name: str, display: str, category: str) -> dict | None:
    """生成 tasks.yaml 默认调度条目。

    generic 返回 None（通用任务不需要调度配置）。
    战斗任务附带作战配置字段；触发任务为 trigger 规则 + 空触发模板。
    """
    if task_type == "generic":
        return None

    entry = {
        "name": name,
        "id": name,
        "display_name": display,
        "category": category,
        "enabled": True,
        "priority": 10,
        "time_start": "06:00",
        "time_end": "23:59",
        "max_daily": None,
        "active_range": None,
        "total_count": None,
        "execution_mode": "daily",
        "loop_count": 1,
        "time_slots": None,
    }

    if task_type == "trigger":
        # 触发任务：无时间窗口、无执行模式（外部触发）
        entry["time_start"] = None
        entry["time_end"] = None
        entry.pop("execution_mode", None)
        entry["repeat"] = {"type": "trigger", "value": 1, "trigger_templates": []}
    elif task_type == "battle":
        # 战斗任务：时间调度 + 作战配置（UI 战斗配置 Tab 可编辑）
        entry["repeat"] = {"type": "daily", "value": 1, "loop_count": 1}
        entry.update({
            "team_id": "阵容1",
            "floor": 10,
            "max_fail_streak": 10,
            "soul_setup": {"group": "御魂副本", "team": "御魂十层", "position": [4, 1]},
            "lock_team": True,
            "change_team": True,
            "stamina_required": 0,
        })
    else:
        # 非战斗任务：时间调度（默认每日）
        entry["repeat"] = {"type": "daily", "value": 1, "loop_count": 1}

    return entry
