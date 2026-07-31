"""
04-任务执行引擎

TaskRegistry 自动注册中心 + discover_tasks() 独立函数。
自动发现并注册所有 BaseTask 子类。
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Type

from tasks.base.base_task import BaseTask


def discover_tasks(package: str | None = None) -> dict[str, Type[BaseTask]]:
    """
    独立函数：扫描 tasks/ 下所有子目录的 .py 文件，
    排除 __init__.py 和 base/、common/，自动注册任务类。

    兼容两类入口：
      - BaseTask 子类（标准入口，key=task_id）
      - TaskStep 子类且声明 display_name（设计书入口，key=name）
        特化步骤（无 display_name）不会被注册为任务。

    Args:
        package: 扫描的包路径（默认扫描 tasks 下各分类目录）

    Returns:
        {task_id: task_class} 映射
    """
    from tasks.base.task_step import TaskStep
    discovered: dict[str, Type[BaseTask]] = {}

    if package:
        modules = _scan_package(package)
    else:
        # 只扫描具体任务目录，排除 base/（基类）和 common/（通用步骤）
        modules = []
        base = Path(__file__).parent
        for subdir in ["daily", "event", "permanent", "special"]:
            subpath = base / subdir
            if subpath.exists():
                modules.extend(_scan_package(f"tasks.{subdir}"))

    for module_name in modules:
        try:
            mod = importlib.import_module(module_name)
            for name, obj in inspect.getmembers(mod):
                if not inspect.isclass(obj) or inspect.isabstract(obj):
                    continue
                if issubclass(obj, BaseTask) and obj is not BaseTask:
                    # 标准入口：BaseTask 子类
                    task_id = getattr(obj, "task_id", None) or name
                    discovered[task_id] = obj
                elif (issubclass(obj, TaskStep) and obj is not TaskStep
                      and hasattr(obj, "display_name")):
                    # 设计书入口：TaskStep 子类 + display_name
                    # （特化步骤无 display_name，不会被误注册为任务）
                    task_id = getattr(obj, "name", None) or name
                    discovered[task_id] = obj
        except Exception:
            pass

    return discovered


def _scan_package(package: str) -> list[str]:
    """扫描包下的所有模块"""
    try:
        pkg = importlib.import_module(package)
        modules = []
        for _importer, modname, ispkg in pkgutil.walk_packages(
            pkg.__path__, prefix=f"{package}."
        ):
            if not ispkg:
                modules.append(modname)
        return modules
    except Exception:
        return []


class TaskRegistry:
    """任务注册中心"""

    def __init__(self, config=None, event_bus=None, state_manager=None):
        self._registry: dict[str, Type[BaseTask]] = {}
        self._categories: dict[str, list[str]] = {}  # category -> [task_id]
        self._scanned = False
        self._config = config
        self._event_bus = event_bus
        self._bus = self._event_bus  # 兼容别名
        self._state_mgr = state_manager
        self._state_manager = state_manager  # 说明书 §2.1 要求名

    # ── 注册 ──────────────────────────────────────────────────

    def register(self, task_class: Type[BaseTask]) -> None:
        """手动注册（§5.3），兼容 BaseTask 与设计书 TaskStep 入口类"""
        from tasks.base.task_step import TaskStep
        if issubclass(task_class, BaseTask) and task_class is not BaseTask:
            task_id = getattr(task_class, 'task_id', None) or task_class.__name__
        elif (issubclass(task_class, TaskStep) and task_class is not TaskStep
              and hasattr(task_class, 'display_name')):
            task_id = getattr(task_class, 'name', None) or task_class.__name__
        else:
            raise TypeError(
                f"{task_class} 不是可注册的任务类"
                "（BaseTask 子类，或声明了 display_name 的 TaskStep 子类）"
            )
        self._registry[task_id] = task_class
        category = getattr(task_class, 'category', 'common')
        self._categories.setdefault(category, []).append(task_id)

    def get(self, name: str) -> BaseTask:
        """
        获取任务实例（文档要求：每次返回新实例）。
        """
        if not self._scanned:
            self.scan()
        cls = self._registry.get(name)
        if not cls:
            raise KeyError(f"任务未注册: {name}")
        return cls(task_id=name)

    def get_all(self) -> list[BaseTask]:
        """获取所有任务实例"""
        return [self.get(tid) for tid in self._registry]

    def list_by_category(self, cat: str) -> list[BaseTask]:
        """按分类获取任务实例"""
        return [self.get(tid) for tid in self._categories.get(cat, [])]

    def get_dependency_graph(self) -> dict[str, list[str]]:
        """获取任务依赖图（UI 可视化用）"""
        graph = {}
        for tid, cls in self._registry.items():
            deps = getattr(cls, 'dependencies', [])
            graph[tid] = deps
        return graph

    # ── 自动扫描 ──────────────────────────────────────────────

    def scan(self, package: str | None = None) -> int:
        """
        自动扫描并注册所有 BaseTask 子类。
        使用 discover_tasks() 独立函数，排除 base/ 和 common/。

        Args:
            package: 扫描的包路径

        Returns:
            注册的任务数量
        """
        discovered = discover_tasks(package)
        for task_id, cls in discovered.items():
            self._registry[task_id] = cls
            category = getattr(cls, 'category', 'common')
            self._categories.setdefault(category, []).append(task_id)

        self._scanned = True
        return len(discovered)

    # ── 查询 ──────────────────────────────────────────────────

    def list_tasks(self) -> dict[str, str]:
        """列出所有注册的任务 {id: class_name}"""
        if not self._scanned:
            self.scan()
        return {tid: cls.__name__ for tid, cls in self._registry.items()}

    def __contains__(self, task_id: str) -> bool:
        return task_id in self._registry

    def __len__(self) -> int:
        return len(self._registry)

    def __repr__(self) -> str:
        return f"TaskRegistry({len(self)} tasks)"


# 全局默认实例
registry = TaskRegistry()
