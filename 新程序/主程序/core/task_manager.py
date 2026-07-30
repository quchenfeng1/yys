"""
13-任务文件管理

TaskManager 任务文件管理器（§5.1 纯数据层）。
对应设计书 §2/§3/§4/§5/§6。

职责:
- 扫描 tasks/ 目录发现任务文件和通用模块
- 用 ast 模块解析 Python 源码提取元数据（不执行代码）
- 新建/删除/恢复任务文件
- 查找缺失素材

与 04-任务执行引擎 的区别：
- 04：运行时执行任务的引擎
- 13：开发时的任务文件管理
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════════
#  §5.2 TaskMeta 数据结构
# ═══════════════════════════════════════════════════════════════

@dataclass
class TaskMeta:
    """任务元数据（§5.2）"""
    filepath: str            # 文件绝对路径
    name: str                # 文件名（不含 .py，如 "soul_12"）
    display_name: str        # 显示名（如 "御魂12层"）
    description: str         # 功能描述
    category: str            # 分类（daily/permanent/event/special/common）
    module_name: str         # Python 模块名（如 "tasks.daily.soul_12"）


# ═══════════════════════════════════════════════════════════════
#  TaskManager
# ═══════════════════════════════════════════════════════════════

class TaskManager:
    """
    任务文件管理器（§5.3 方法定义）。

    纯数据层，不依赖 UI 框架。通过扫描 tasks/ 目录下的 .py 文件，
    使用 ast 模块安全提取元数据（不执行代码）。
    """

    def __init__(
        self,
        tasks_dir: str | Path | None = None,
        assets_dir: str | Path | None = None,
        config: Any = None,       # 兼容旧构造
        event_bus: Any = None,    # 兼容旧构造
    ):
        # §2.3 扫描目录配置
        project_root = self._find_project_root()
        self._tasks_dir = Path(tasks_dir) if tasks_dir else (project_root / "tasks")
        self._assets_dir = Path(assets_dir) if assets_dir else (project_root / "assets")

        # §2.3 扫描目录：daily/permanent/event/special
        self._scan_dirs: list[str] = ["daily", "permanent", "event", "special"]
        self._common_dir: str = "common"

        # §2.3 缓存
        self._cache: dict[str, TaskMeta] = {}
        self._cache_lock = threading.Lock()

        # 兼容旧属性
        self._config = config
        self._bus = event_bus

    @staticmethod
    def _find_project_root() -> Path:
        """向上查找包含 tasks/ 目录的根目录"""
        # 从当前文件位置向上查找
        current = Path(__file__).resolve().parent.parent  # 从 core/ 上到主程序目录
        if (current / "tasks").exists():
            return current
        # fallback: 当前工作目录
        return Path.cwd()

    # ═══════════════════════════════════════════════════════════
    #  §5.3 公开方法
    # ═══════════════════════════════════════════════════════════

    # ── 扫描 ──────────────────────────────────────────────

    def scan_all(self) -> list[TaskMeta]:
        """
        扫描全部任务和通用模块（§3.1 + §5.3）。

        清除并重建 _cache → 递归扫描 4 个分类目录 + common 目录
        → 对每个 .py 文件用 ast 提取元数据 → 缓存 → 返回全量列表。
        """
        results: list[TaskMeta] = []

        # 扫描分类目录
        for cat in self._scan_dirs:
            cat_dir = self._tasks_dir / cat
            if not cat_dir.exists():
                continue
            for py_file in sorted(cat_dir.rglob("*.py")):
                if py_file.name == "__init__.py":
                    continue
                meta = self._extract_meta(py_file, cat)
                if meta:
                    results.append(meta)

        # 扫描通用模块目录
        common_dir = self._tasks_dir / self._common_dir
        if common_dir.exists():
            for py_file in sorted(common_dir.rglob("*.py")):
                if py_file.name == "__init__.py":
                    continue
                meta = self._extract_meta(py_file, "common")
                if meta:
                    results.append(meta)

        # §2.3 更新缓存
        with self._cache_lock:
            self._cache.clear()
            for m in results:
                self._cache[m.name] = m

        return results

    def _extract_meta(self, py_file: Path, category: str) -> TaskMeta | None:
        """
        从 Python 文件提取元数据（§3.2）。

        使用 ast 安全解析，提取 display_name / description。
        优先级：display_name 类属性 > description 类属性 > docstring 第一行。
        不执行也不导入 .py 文件。
        """
        name = py_file.stem  # 文件名不含 .py
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, OSError):
            return None

        display_name = name
        description = ""

        # 提取模块级 docstring
        if (tree.body and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)):
            doc = tree.body[0].value.value.strip()
            description = doc.split("\n")[0] if doc else ""

        # 遍历类定义，提取 display_name / description 属性
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                if target.id == "display_name" and isinstance(item.value, ast.Constant):
                                    display_name = str(item.value.value)
                                elif target.id == "description" and isinstance(item.value, ast.Constant):
                                    if not description:
                                        description = str(item.value.value)

        # 构建模块名
        rel_path = py_file.relative_to(self._tasks_dir.parent) if self._tasks_dir.parent else py_file
        module_parts = list(rel_path.with_suffix("").parts)
        module_name = ".".join(module_parts)

        return TaskMeta(
            filepath=str(py_file),
            name=name,
            display_name=display_name or name,
            description=description or display_name or name,
            category=category,
            module_name=module_name,
        )

    # ── 查询（从缓存读取）─────────────────────────────────

    def get_all_tasks(self) -> list[TaskMeta]:
        """
        获取全部游戏任务列表（§5.3）。

        从 _cache 读取。若缓存为空则自动扫描。
        """
        if not self._cache:
            self.scan_all()
        with self._cache_lock:
            return [
                m for m in self._cache.values()
                if m.category in self._scan_dirs
            ]

    def get_tasks_by_category(self, category: str) -> list[TaskMeta]:
        """按分类获取任务列表（§5.3）"""
        return [m for m in self.get_all_tasks() if m.category == category]

    def get_generic_modules(self) -> list[TaskMeta]:
        """获取通用模块列表（§5.3）"""
        if not self._cache:
            self.scan_all()
        with self._cache_lock:
            return [m for m in self._cache.values() if m.category == "common"]

    def find_by_name(self, name: str) -> TaskMeta | None:
        """按文件名查找任务（§5.3）"""
        if not self._cache:
            self.scan_all()
        with self._cache_lock:
            return self._cache.get(name)

    def get_category_stats(self) -> dict[str, int]:
        """获取各分类的任务数量统计（§5.3）"""
        tasks = self.get_all_tasks()
        stats: dict[str, int] = {}
        for t in tasks:
            stats[t.category] = stats.get(t.category, 0) + 1
        return stats

    # ── 文件操作 ──────────────────────────────────────────

    def open_file(self, task_name_or_path: str) -> None:
        """
        用默认程序打开 .py 文件（§3.4 + §5.3）。

        参数为文件名或文件路径。
        """
        path = Path(task_name_or_path)
        if not path.exists():
            # 尝试按文件名查找
            meta = self.find_by_name(task_name_or_path)
            if meta:
                path = Path(meta.filepath)

        if not path.exists():
            raise FileNotFoundError(f"任务文件不存在: {task_name_or_path}")

        # 跨平台用默认程序打开
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)

    def new_task(self, category: str, name: str, display: str = "") -> str:
        """
        新建任务骨架文件（§3.3 + §5.3）。

        在 tasks/{category}/ 下生成 .py 文件，返回文件路径。
        """
        cat_dir = self._tasks_dir / category
        cat_dir.mkdir(parents=True, exist_ok=True)

        filepath = cat_dir / f"{name}.py"
        if filepath.exists():
            raise FileExistsError(f"任务文件已存在: {filepath}")

        display_name = display or name
        class_name = "".join(word.capitalize() for word in name.split("_"))

        skeleton = f'''"""
{category} 任务

{display_name} 自动执行。
"""
from __future__ import annotations

from typing import Any

from core.exceptions import TaskSkip
from tasks.base.base_task import BaseTask
from tasks.base.task_result import TaskResult, TaskStatus


class {class_name}(BaseTask):
    """ {display_name} """

    task_id = "{name}"
    display_name = "{display_name}"
    description = "{display_name}"

    def _build_graph(self):
        from tasks.base.task_graph import TaskGraph
        graph = TaskGraph()
        # TODO: 添加任务步骤
        return graph

    def execute(self, context=None) -> TaskResult:
        # TODO: 实现任务逻辑
        return TaskResult(
            task_id=self.task_id,
            status=TaskStatus.SUCCESS,
            reason="{display_name} 执行完成",
        )
'''
        filepath.write_text(skeleton, encoding="utf-8")

        # 清除缓存让下次扫描重新加载
        with self._cache_lock:
            self._cache.clear()

        return str(filepath)

    def delete_task(self, task_name: str) -> None:
        """
        安全删除任务（§3.4 + §5.3）。

        重命名为 .deleted 后缀，保留文件内容以便恢复。
        """
        meta = self.find_by_name(task_name)
        if not meta:
            raise FileNotFoundError(f"任务未找到: {task_name}")

        src = Path(meta.filepath)
        dst = src.with_suffix(".deleted")
        src.rename(dst)

        with self._cache_lock:
            self._cache.pop(task_name, None)

    def restore_task(self, task_name: str) -> None:
        """
        恢复已删除任务（§3.4 + §5.3）。

        将 .deleted 文件重命名回 .py，恢复任务到可用状态。
        """
        # 搜索 .deleted 文件
        for cat in self._scan_dirs + [self._common_dir]:
            cat_dir = self._tasks_dir / cat
            if not cat_dir.exists():
                continue
            deleted_file = cat_dir / f"{task_name}.deleted"
            if deleted_file.exists():
                restored = deleted_file.with_suffix(".py")
                deleted_file.rename(restored)
                with self._cache_lock:
                    self._cache.clear()
                return

        raise FileNotFoundError(f"未找到已删除的任务: {task_name}")

    # ── §5.3 find_missing_assets ──────────────────────────

    def find_missing_assets(self) -> list[str]:
        """
        查找缺失素材（§5.3 + §6.2）。

        遍历 tasks/ 下所有 .py 文件，正则匹配 click_image("xxx") 等
        模板引用名。与 assets/ 目录对比，返回缺失的素材名列表。

        调用方（UI 层）自行决定是否发布 assets_missing 事件。
        """
        # 收集 assets 目录中所有模板名（不含扩展名）
        existing_assets: set[str] = set()
        if self._assets_dir.exists():
            for ext in ("*.png", "*.jpg", "*.jpeg", "*.bmp"):
                for f in self._assets_dir.rglob(ext):
                    existing_assets.add(f.stem)

        # 正则匹配常见的模板引用模式
        patterns = [
            r'click_image\s*\(\s*["\']([^"\']+)["\']',
            r'find_one\s*\(\s*["\']([^"\']+)["\']',
            r'wait_any\s*\(\s*\[([^\]]+)\]',
            r'detect_scene\s*\(\s*\[([^\]]+)\]',
            r'ensure_scene\s*\(\s*["\']([^"\']+)["\']',
            r'click_if_exists\s*\(\s*["\']([^"\']+)["\']',
            r'image\s*=\s*["\']([^"\']+)["\']',
        ]

        referenced: set[str] = set()

        for py_file in self._tasks_dir.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
                for pat in patterns:
                    for match in re.finditer(pat, source):
                        if pat.startswith("wait_any") or pat.startswith("detect_scene"):
                            # 处理列表参数
                            inner = match.group(1)
                            parts = [p.strip().strip('"').strip("'") for p in inner.split(",")]
                            referenced.update(p for p in parts if p)
                        else:
                            referenced.add(match.group(1))
            except OSError:
                continue

        # 找出引用但 assets 目录中不存在的
        missing = [name for name in sorted(referenced) if name not in existing_assets]
        return missing

    # ═══════════════════════════════════════════════════════════
    #  兼容旧方法（配置 CRUD）
    # ═══════════════════════════════════════════════════════════

    def get_task(self, task_id: str) -> Any:
        """⚠️ 已弃用 — 配置项查询，保留兼容"""
        meta = self.find_by_name(task_id)
        if not meta:
            from core.exceptions import TaskNotFoundError
            raise TaskNotFoundError(f"任务未找到: {task_id}")
        return meta

    def list_tasks(self, category: str | None = None, **kw: Any) -> list[TaskMeta]:
        """列出任务（§5.3 get_tasks_by_category 的兼容别名）"""
        if category:
            return self.get_tasks_by_category(category)
        return self.get_all_tasks()

    def list_categories(self) -> list[str]:
        """列出所有任务分类"""
        return list(self.get_category_stats().keys())
