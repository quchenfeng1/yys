"""
任务自动注册模块

职责：自动扫描 tasks/ 下四个子目录（daily/permanent/event/special），
导入所有模块，收集 BaseTask 子类，按 name 建立注册表。
新增任务只需放文件到对应目录，无需手动注册。
"""

import importlib
import pkgutil
from pathlib import Path

from tasks.base_task import BaseTask
from core.logger import get_logger

logger = get_logger("tasks.registry")

# 任务分类与对应的子包名
TASK_CATEGORIES = {
    "daily": "tasks.daily",
    "permanent": "tasks.permanent",
    "event": "tasks.event",
    "special": "tasks.special",
}


def discover_tasks() -> dict:
    """扫描所有任务目录，发现并注册 BaseTask 子类

    Returns:
        {task_name: task_class} 注册表
    """
    tasks = {}

    for category, package_name in TASK_CATEGORIES.items():
        try:
            package = importlib.import_module(package_name)
        except ImportError:
            logger.warning(f"无法导入任务包: {package_name}")
            continue

        # 扫描包内所有模块
        package_path = Path(package.__file__).parent
        for importer, modname, ispkg in pkgutil.iter_modules([str(package_path)]):
            if modname.startswith("_"):
                continue

            full_module_name = f"{package_name}.{modname}"
            try:
                module = importlib.import_module(full_module_name)
            except Exception as e:
                logger.error(f"导入任务模块失败: {full_module_name} - {e}")
                continue

            # 收集模块中的 BaseTask 子类
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type)
                    and issubclass(attr, BaseTask)
                    and attr is not BaseTask
                    and getattr(attr, "name", "")):

                    task_name = attr.name
                    if task_name in tasks:
                        logger.warning(f"任务名冲突: {task_name} (在 {full_module_name} 中重复定义)")
                    tasks[task_name] = attr
                    logger.debug(f"发现任务: {task_name} ({category}) <- {full_module_name}")

    logger.info(f"任务扫描完成，共发现 {len(tasks)} 个任务: {list(tasks.keys())}")
    return tasks
