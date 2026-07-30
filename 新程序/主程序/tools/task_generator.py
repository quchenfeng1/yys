"""
开发辅助工具：任务代码生成器。

根据任务描述自动生成 BaseTask 子类代码。
"""
from __future__ import annotations

from typing import Any


class TaskGenerator:
    """任务代码生成器"""

    TEMPLATE = '''"""
{module_doc}
"""
from __future__ import annotations

from typing import Any

from tasks.base.base_task import BaseTask
from tasks.base.task_result import TaskResult, TaskStatus


class {class_name}(BaseTask):
    """{class_doc}"""

    task_id = "{task_id}"

    def _build_graph(self):
        """构建步骤图"""
        from tasks.base.task_graph import TaskGraph
        graph = TaskGraph()
        # TODO: 添加步骤
        return graph

    def execute(self, context=None) -> TaskResult:
        """执行任务"""
        # TODO: 实现任务逻辑
        return TaskResult(
            task_id=self.task_id,
            status=TaskStatus.SUCCESS,
            reason="{task_id} 执行完成",
        )
'''

    @classmethod
    def generate(
        cls,
        task_id: str,
        class_name: str | None = None,
        module_doc: str = "",
        class_doc: str = "",
        **kwargs: Any,
    ) -> str:
        """生成任务代码"""
        if not class_name:
            class_name = "".join(word.capitalize() for word in task_id.split("_"))

        return cls.TEMPLATE.format(
            module_doc=module_doc or f"{task_id} 任务",
            class_name=class_name,
            class_doc=class_doc or f"{task_id} 任务实现",
            task_id=task_id,
        )

    @classmethod
    def generate_to_file(
        cls,
        task_id: str,
        output_dir: str,
        category: str = "common",
        **kwargs: Any,
    ) -> str:
        """生成任务代码并写入文件"""
        from pathlib import Path

        code = cls.generate(task_id, **kwargs)
        path = Path(output_dir) / category / f"{task_id}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")
        return str(path)
