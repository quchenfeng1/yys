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

try:
    import yaml  # 写 tasks.yaml 默认调度条目（_append_tasks_yaml）
except ImportError:  # pragma: no cover
    yaml = None


# ═══════════════════════════════════════════════════════════════
#  §5.2 TaskMeta 数据结构
# ═══════════════════════════════════════════════════════════════

@dataclass
class TaskMeta:
    """任务元数据（§5.2 + 设计书 §2 模块声明）"""
    filepath: str            # 文件绝对路径
    name: str                # 文件名（不含 .py，如 "soul_12"）
    display_name: str        # 显示名（如 "御魂12层"）
    description: str         # 功能描述
    category: str            # 分类（daily/permanent/event/special/common）
    module_name: str         # Python 模块名（如 "tasks.daily.soul_12"）
    # ── 设计书 §2 模块级声明（UI 动态配置区依据） ──────────
    task_type: str = "event_task"   # "battle" | "event_task"
    uses_battle: bool = False       # → UI 显示战斗配置区
    uses_team: bool = False         # → UI 显示阵容配置
    uses_soul: bool = False         # → UI 显示御魂配置
    uses_stamina: bool = False      # → UI 显示体力门槛
    loop_count: int = 1             # 每轮循环次数
    timeout: int = 300              # 任务总超时（秒）


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
        从 Python 文件提取元数据（§3.2 + 设计书 §4.3）。

        使用 ast 安全解析，提取模块级声明（display_name/description/task_type/
        uses_*/loop_count/timeout）与类属性 display_name/description。
        优先级：模块级变量 > 类属性 > docstring 第一行。
        不执行也不导入 .py 文件。
        """
        name = py_file.stem  # 文件名不含 .py
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, OSError):
            return None

        # 模块级 docstring 第一行（fallback description）
        docline = ""
        if (tree.body and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)):
            doc = tree.body[0].value.value.strip()
            docline = doc.split("\n")[0] if doc else ""

        # 设计书 §2：模块级声明（模块顶层 Assign → Name）
        mod_vals: dict[str, Any] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                        mod_vals[target.id] = node.value.value

        display_name = str(mod_vals.get("display_name") or name)
        description = str(mod_vals.get("description") or docline or display_name)

        # 类属性 display_name/description（fallback，优先级低于模块级）
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                if target.id == "display_name" and isinstance(item.value, ast.Constant):
                                    if "display_name" not in mod_vals:
                                        display_name = str(item.value.value)
                                elif target.id == "description" and isinstance(item.value, ast.Constant):
                                    if "description" not in mod_vals and not description:
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
            task_type=str(mod_vals.get("task_type", "event_task")),
            uses_battle=bool(mod_vals.get("uses_battle", False)),
            uses_team=bool(mod_vals.get("uses_team", False)),
            uses_soul=bool(mod_vals.get("uses_soul", False)),
            uses_stamina=bool(mod_vals.get("uses_stamina", False)),
            loop_count=int(mod_vals.get("loop_count", 1) or 1),
            timeout=int(mod_vals.get("timeout", 300) or 300),
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

    def get_meta(self, name: str) -> TaskMeta | None:
        """按文件名获取任务元数据（§5.3，从缓存读取）"""
        if not self._cache:
            self.scan_all()
        with self._cache_lock:
            return self._cache.get(name)

    @property
    def all_tasks(self) -> list[TaskMeta]:
        """说明书 §2.2 要求的只读属性"""
        return self.get_all_tasks()

    def get_tasks_by_category(self, category: str) -> list[TaskMeta]:
        """按分类获取任务列表（§5.3）"""
        return [m for m in self.get_all_tasks() if m.category == category]

    def get_generic_modules(self) -> list[TaskMeta]:
        """获取通用模块列表（§5.3）"""
        if not self._cache:
            self.scan_all()
        with self._cache_lock:
            return [m for m in self._cache.values() if m.category == "common"]

    @property
    def generic_modules(self) -> list[TaskMeta]:
        """说明书 §2.2 要求的只读属性"""
        return self.get_generic_modules()

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

    def new_task(self, category: str, name: str, display: str = "",
                 task_type: str = "event_task") -> str:
        """
        新建任务骨架文件（§3.3 + §5.3）。

        task_type（core/task_template.py）：
          event_task  非战斗任务 → tasks/{category}/，tasks.yaml 写默认调度（repeat=daily）
          battle      战斗任务   → tasks/{category}/，tasks.yaml 写调度 + 作战配置
          generic     通用任务   → tasks/common/，不写 tasks.yaml（无调度，供其他任务引用）
          trigger     触发任务   → tasks/{category}/，tasks.yaml 写 trigger 规则 + 空触发模板

        返回文件路径。
        """
        from core.task_template import generate as gen_template

        # 通用任务固定放 common/ 目录（不注册为独立任务）
        if task_type == "generic":
            cat_dir = self._tasks_dir / self._common_dir
            category = "common"
        else:
            cat_dir = self._tasks_dir / category
        cat_dir.mkdir(parents=True, exist_ok=True)

        filepath = cat_dir / f"{name}.py"
        if filepath.exists():
            raise FileExistsError(f"任务文件已存在: {filepath}")

        display_name = display or name
        code = gen_template(task_type, name, display_name, category)
        filepath.write_text(code, encoding="utf-8")

        # 非通用任务：tasks.yaml 追加默认调度条目（时间调度/作战配置）
        if task_type != "generic":
            self._append_tasks_yaml(task_type, name, display_name, category)

        # 创建任务图片文件夹（asset_catalog 约定：专属/共享/识图）
        try:
            from core.asset_catalog import AssetCatalog
            catalog = AssetCatalog(self._assets_dir)
            catalog.ensure_scene_dir()
            if task_type == "generic":
                catalog.ensure_shared_dir()
            else:
                catalog.ensure_task_dir(name)
        except Exception:
            pass

        # 清除缓存让下次扫描重新加载
        with self._cache_lock:
            self._cache.clear()

        return str(filepath)

    def _append_tasks_yaml(self, task_type: str, name: str, display: str,
                           category: str) -> None:
        """在 config/tasks.yaml 追加任务默认调度条目（原子写盘，失败不阻断）。"""
        from core.task_template import build_yaml_entry
        entry = build_yaml_entry(task_type, name, display, category)
        if entry is None:
            return
        if yaml is None:
            return
        try:
            p = Path(self._tasks_dir).parent / "config" / "tasks.yaml"
            data = {}
            if p.exists():
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                data = {}
            tasks = data.setdefault("tasks", [])
            if tasks is None:  # "tasks:" 空列表解析为 None
                tasks = data["tasks"] = []
            # 已存在同名任务 → 不重复追加
            if any(t and t.get("name") == name for t in tasks):
                return
            tasks.append(entry)
            tmp = p.with_suffix(".yaml.tmp")
            tmp.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False,
                               default_flow_style=False),
                encoding="utf-8")
            os.replace(tmp, p)
        except Exception:
            pass

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

        改进：
        - 跳过注释行（行首 # 或行内 # 后的内容），避免注释里的引用误报
        - 规范化路径匹配：引用完整路径（如 common/ui/close_btn）与
          assets 相对路径或文件名 stem 均可匹配

        调用方（UI 层）自行决定是否发布 assets_missing 事件。
        """
        # 收集 assets 目录中所有模板（相对路径不含扩展名 + 文件名 stem）
        existing_paths: set[str] = set()
        existing_stems: set[str] = set()
        if self._assets_dir.exists():
            for ext in ("*.png", "*.jpg", "*.jpeg", "*.bmp"):
                for f in self._assets_dir.rglob(ext):
                    rel = f.relative_to(self._assets_dir).with_suffix("")
                    existing_paths.add(str(rel).replace("\\", "/"))
                    existing_stems.add(f.stem)

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
                # 逐行处理并剔除注释（行首 # 或行内 # 之后的内容）
                code_lines = []
                for line in source.split("\n"):
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        continue
                    # 截断行内注释（# 前后有空格）
                    hash_idx = line.find(" #")
                    code_lines.append(line[:hash_idx] if hash_idx >= 0 else line)
                clean_source = "\n".join(code_lines)

                for pat in patterns:
                    for match in re.finditer(pat, clean_source):
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
        # 匹配规则：引用完整路径命中 或 引用路径末尾组件命中素材文件名
        def _is_missing(ref: str) -> bool:
            if ref in existing_paths:
                return False
            last = ref.split("/")[-1]
            if last in existing_stems:
                return False
            return True

        missing = [name for name in sorted(referenced) if _is_missing(name)]
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
