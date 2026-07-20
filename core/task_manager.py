"""
任务管理器（v2.4 新增 — 脚本任务可视化管理系统）

扫描 tasks/ 目录发现所有任务和通用模块，解析 Python 文件中的
docstring 和类属性作为元数据，供 UI 面板展示。

职责：
  - 扫描四类任务目录（daily/permanent/event/special）发现任务
  - 扫描通用模块目录（tasks/common/）发现可复用模块
  - 解析每个文件的名称、功能描述、分类、是否可独立执行
  - 提供打开文件、新建任务、删除任务功能

设计原则：
  - 纯数据层：不涉及 UI，只提供数据和操作接口
  - 文件驱动：任务元数据直接来自 Python 源码，无需额外配置文件
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from core.event_bus import event_bus

# ==================== 数据模型 ====================

@dataclass
class TaskModule:
    """任务或通用模块的元数据。"""
    name: str                      # 文件名（不含 .py），如 "sign_in"
    display_name: str = ""         # 显示名，如 "每日签到"
    description: str = ""          # 功能描述（来自 docstring）
    category: str = ""             # daily / permanent / event / special / common
    task_type: str = ""            # battle(战斗任务) / event_task(事件任务) / ""(通用模块)
    filepath: str = ""             # 完整文件路径
    can_execute: bool = True       # 是否可独立执行（通用模块=False）
    is_generic: bool = False       # 是否为通用模块
    enabled: bool = False          # 是否在 tasks.yaml 中启用
    # ── 模块声明（决定 UI 配置区）──
    uses_battle: bool = False      # 是否包含战斗
    uses_team: bool = False        # 是否需要阵容调整
    uses_soul: bool = False        # 是否需要御魂配置
    uses_stamina: bool = False     # 是否需要体力检查
    loop_count: int = 1            # 默认循环次数
    timeout: int = 300             # 任务总超时（秒）


# ==================== 任务扫描器 ====================

class TaskManager:
    """任务管理器。扫描、解析、管理任务文件。"""

    CATEGORY_LABELS = {
        "daily": "日常任务",
        "permanent": "常驻任务",
        "event": "活动任务",
        "special": "特殊任务",
        "common": "通用任务模块",
    }

    CATEGORY_ICONS = {
        "daily": "📅",
        "permanent": "⚔",
        "event": "🎪",
        "special": "⭐",
        "common": "🔧",
    }

    TASK_TYPE_LABELS = {
        "battle": "战斗任务",
        "event_task": "事件任务",
    }

    TASK_TYPE_ICONS = {
        "battle": "⚔",
        "event_task": "📋",
    }

    def __init__(self, project_root: Path = None):
        self._root = project_root or Path(__file__).parent.parent
        self._tasks_dir = self._root / "tasks"
        self._tasks: list[TaskModule] = []
        self._generic_modules: list[TaskModule] = []

    # ==================== 扫描 ====================

    def scan_all(self):
        """扫描全部任务和通用模块。"""
        self._tasks = []
        self._generic_modules = []

        # 扫描四类任务
        for cat in ["daily", "permanent", "event", "special"]:
            cat_dir = self._tasks_dir / cat
            if cat_dir.exists():
                for f in sorted(cat_dir.glob("*.py")):
                    if f.name.startswith("_") or f.name.startswith("base_"):
                        continue
                    mod = self._parse_file(f, cat, can_execute=True, is_generic=False)
                    self._tasks.append(mod)

        # 扫描通用模块
        common_dir = self._tasks_dir / "common"
        if common_dir.exists():
            for f in sorted(common_dir.glob("*.py")):
                if f.name.startswith("_"):
                    continue
                mod = self._parse_file(f, "common", can_execute=False, is_generic=True)
                self._generic_modules.append(mod)

    # ==================== 解析 ====================

    def _parse_file(self, filepath: Path, category: str,
                    can_execute: bool, is_generic: bool) -> TaskModule:
        """解析一个 Python 文件，提取元数据。"""
        name = filepath.stem
        display_name = name.replace("_", " ").title()
        description = ""
        tt = "event_task"  # 默认事件任务

        try:
            content = filepath.read_text(encoding="utf-8")
            # 提取 docstring 第一行作为功能描述
            desc = self._extract_docstring(content)
            if desc:
                description = desc

            # 尝试提取 display_name（类属性或模块级变量）
            dn = self._extract_display_name(content)
            if dn:
                display_name = dn

            # 尝试提取 description（更详细的功能说明）
            dd = self._extract_description(content)
            if dd:
                description = dd

            # 尝试提取 task_type（战斗任务/事件任务）
            tt = self._extract_task_type(content)
            if not tt:
                # 默认：非通用模块按 category 推断
                tt = "battle" if category in ("permanent",) else "event_task"

            # ★ 提取模块能力声明（uses_* / loop_count / timeout）
            uses_battle = self._extract_bool(content, "uses_battle")
            uses_team = self._extract_bool(content, "uses_team")
            uses_soul = self._extract_bool(content, "uses_soul")
            uses_stamina = self._extract_bool(content, "uses_stamina")
            loop_count = self._extract_int(content, "loop_count", 1)
            timeout = self._extract_int(content, "timeout", 300)

        except Exception:
            pass

        return TaskModule(
            name=name,
            display_name=display_name,
            description=description,
            category=category,
            task_type=tt if not is_generic else "",
            filepath=str(filepath),
            can_execute=can_execute,
            is_generic=is_generic,
            uses_battle=uses_battle,
            uses_team=uses_team,
            uses_soul=uses_soul,
            uses_stamina=uses_stamina,
            loop_count=loop_count,
            timeout=timeout,
        )

    @staticmethod
    def _extract_docstring(content: str) -> str:
        """提取模块级 docstring 的第一行。"""
        # 匹配 """...""" 或 '''...'''
        m = re.search(r'^\s*"""\s*(.+?)(?:\n|["]{3})', content, re.DOTALL)
        if not m:
            m = re.search(r"^\s*'''\s*(.+?)(?:\n|[']{3})", content, re.DOTALL)
        if m:
            return m.group(1).strip()
        return ""

    @staticmethod
    def _extract_display_name(content: str) -> str:
        """提取类属性 display_name 或 name 变量。"""
        for pattern in [
            r'display_name\s*=\s*["\'](.+?)["\']',
            r'display_name\s*:\s*str\s*=\s*["\'](.+?)["\']',
        ]:
            m = re.search(pattern, content)
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def _extract_description(content: str) -> str:
        """提取 description 类属性。"""
        for pattern in [
            r'description\s*=\s*["\'](.+?)["\']',
            r'description\s*:\s*str\s*=\s*["\'](.+?)["\']',
        ]:
            m = re.search(pattern, content)
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def _extract_task_type(content: str) -> str:
        """提取 task_type 模块级变量（battle / event_task）。"""
        for pattern in [
            r'task_type\s*=\s*["\'](.+?)["\']',
            r'task_type\s*:\s*str\s*=\s*["\'](.+?)["\']',
        ]:
            m = re.search(pattern, content)
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def _extract_bool(content: str, var_name: str) -> bool:
        """提取模块级 bool 变量（如 uses_battle = True）。"""
        for pat in [
            rf'{var_name}\s*=\s*True',
            rf'{var_name}\s*:\s*bool\s*=\s*True',
        ]:
            if re.search(pat, content):
                return True
        return False

    @staticmethod
    def _extract_int(content: str, var_name: str, default: int = 0) -> int:
        """提取模块级 int 变量（如 loop_count = 10）。"""
        for pat in [
            rf'{var_name}\s*=\s*(\d+)',
            rf'{var_name}\s*:\s*int\s*=\s*(\d+)',
        ]:
            m = re.search(pat, content)
            if m:
                return int(m.group(1))
        return default

    # ==================== 查询 ====================

    def get_all_tasks(self) -> list[TaskModule]:
        """获取全部游戏任务。"""
        return self._tasks

    def get_tasks_by_category(self, category: str) -> list[TaskModule]:
        """获取指定分类的任务。"""
        return [t for t in self._tasks if t.category == category]

    def get_generic_modules(self) -> list[TaskModule]:
        """获取全部通用模块。"""
        return self._generic_modules

    def find_by_name(self, name: str) -> Optional[TaskModule]:
        """按文件名查找。"""
        for t in self._tasks + self._generic_modules:
            if t.name == name:
                return t
        return None

    def get_category_stats(self) -> dict:
        """获取各分类的任务数量。"""
        stats = {}
        for t in self._tasks:
            stats[t.category] = stats.get(t.category, 0) + 1
        return stats

    # ==================== 操作 ====================

    def open_file(self, module: TaskModule) -> bool:
        """用系统默认程序打开文件（通常是 VSCode）。"""
        path = Path(module.filepath)
        if not path.exists():
            return False
        try:
            if sys.platform == "win32":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
            return True
        except Exception:
            return False

    def new_task(self, category: str, name: str,
                 display_name: str = "", task_type: str = "event_task") -> Optional[Path]:
        """在指定分类下创建新任务文件（含 uses_* 能力声明骨架）。"""
        if category not in self.CATEGORY_LABELS:
            return None

        filename = name.replace(" ", "_").lower() + ".py"
        filepath = self._tasks_dir / category / filename

        if filepath.exists():
            return None  # 已存在

        display = display_name or name
        ttype_label = self.TASK_TYPE_LABELS.get(task_type, "事件任务")
        is_battle = "True" if task_type == "battle" else "False"
        template = f'''"""
{display} — {self.CATEGORY_LABELS.get(category, category)}任务
"""

# ==================== ① 模块声明（必填） ====================
display_name = "{display}"
description = "{display} — {ttype_label}"
task_type = "{task_type}"

# 能力声明（按需启用，UI 据此显示配置区）
uses_battle = {is_battle}
uses_team = False
uses_soul = False
uses_stamina = False
loop_count = 1
timeout = 300

# ==================== ② 导入依赖 ====================
from tasks.base.task_step import TaskStep, StepResult
from tasks.base.task_context import TaskContext
from tasks.base.task_graph import TaskGraph

# 通用模块（按需取消注释）
from tasks.common.close_popup    import ClosePopup
from tasks.common.return_hall    import ReturnHall
# from tasks.common.battle_loop   import BattleLoop
# from tasks.common.select_team   import SelectTeam
# from tasks.common.check_stamina import CheckStamina


# ==================== ③ 特化步骤（可选） ====================


# ==================== ④ 构建 TaskGraph ====================
def build_graph(context: TaskContext) -> TaskGraph:
    g = TaskGraph("{name}")

    # SETUP 阶段（执行一次）
    g.add_step("close_popup", ClosePopup())

    # LOOP 阶段（循环 N 次）
    # g.add_step("battle", BattleLoop(times=context.task_config.get("loop_count", 1)))

    # TEARDOWN 阶段（执行一次）
    g.add_step("go_home", ReturnHall())

    # 连线
    g.set_entry("close_popup")
    g.add_edge("close_popup", "go_home")
    g.set_error_branch("go_home")
    return g


# ==================== ⑤ 入口类 ====================
class {name.title().replace("_", "")}Task(TaskStep):
    """{display}。"""
    name = "{name}"
    display_name = display_name
    description = description
    is_generic = False
    timeout = timeout

    def execute(self, context: TaskContext) -> StepResult:
        graph = build_graph(context)
        success = graph.run(context)
        return (
            StepResult.success("{display} 完成")
            if success else StepResult.fail("{display} 失败")
        )
'''

        filepath.write_text(template, encoding="utf-8")
        event_bus.publish("task_file_created", name=name, category=category)
        return filepath

    def delete_task(self, module: TaskModule) -> bool:
        """删除任务文件（移至回收站逻辑：重命名为 .deleted）。"""
        path = Path(module.filepath)
        if not path.exists():
            return False
        deleted_path = path.with_suffix(".py.deleted")
        path.rename(deleted_path)
        event_bus.publish("task_file_deleted", name=module.name, category=module.category)
        return True
