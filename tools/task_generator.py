"""
任务脚手架生成器

一键生成新任务的全套文件（任务类 + 配置模板 + 素材目录）。
"""

import os
import sys

TEMPLATE_DAILY = '''"""
{display_name} — 日常任务

纯领奖无战斗。
"""

from tasks.base.task_step import TaskStep, StepResult
from tasks.base.task_context import TaskContext


class {class_name}(TaskStep):
    """{display_name}。"""
    name = "{task_name}"
    is_generic = False
    timeout = 30

    def execute(self, context: TaskContext) -> StepResult:
        executor = context.executor

        # TODO: 实现 {display_name} 的逻辑
        # 1. 进入入口
        # 2. 领取奖励
        # 3. 关闭弹窗

        return StepResult.success("{display_name} 完成")
'''

TEMPLATE_PERMANENT = '''"""
{display_name} — 常驻副本

有战斗逻辑的常驻副本任务。
"""

from tasks.base.task_graph import TaskGraph
from tasks.base.task_context import TaskContext


class {class_name}:
    """{display_name}。"""
    name = "{task_name}"
    display_name = "{display_name}"
    category = "permanent"

    def build_graph(self) -> TaskGraph:
        g = TaskGraph(task_name=self.name)

        # TODO: 添加特化步骤
        # g.add_step("enter", Enter{task_name_camel}())
        # 通用步骤复用 tasks/common/

        g.set_entry("enter")
        return g

    def execute(self) -> bool:
        from tasks.base.task_context import TaskContext
        context = TaskContext(task_name=self.name)
        return self.build_graph().run(context)
'''

CONFIG_TEMPLATE = '''{{
  "entry_path": [],
  "floor": 0,
  "times": 1,
  "team_id": "",
  "ensure_team_before_enter": true,
  "lock_team_after_select": true,
  "settle_images": ["common/battle/victory", "common/battle/defeat"]
}}
'''


def generate_task(task_type: str, task_name: str, display_name: str):
    """生成新任务的全套文件。

    Args:
        task_type: daily / permanent / event / special
        task_name: 任务标识（小写下划线，如 yuhun）
        display_name: UI 显示名（中文，如 御魂副本）
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(base_dir)

    # 1. 创建任务文件
    tasks_dir = os.path.join(project_root, "tasks", task_type)
    os.makedirs(tasks_dir, exist_ok=True)

    class_name = "".join(w.capitalize() for w in task_name.split("_")) + "Task"
    task_name_camel = "".join(w.capitalize() for w in task_name.split("_"))

    template = TEMPLATE_DAILY if task_type == "daily" else TEMPLATE_PERMANENT
    content = template.format(
        display_name=display_name,
        class_name=class_name,
        task_name=task_name,
        task_name_camel=task_name_camel,
    )

    task_file = os.path.join(tasks_dir, f"{task_name}.py")
    with open(task_file, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ 已创建任务文件: {task_file}")

    # 2. 创建配置模板
    coords_dir = os.path.join(project_root, "config", "coords")
    os.makedirs(coords_dir, exist_ok=True)
    config_file = os.path.join(coords_dir, f"{task_name}.json")
    if not os.path.exists(config_file):
        with open(config_file, "w", encoding="utf-8") as f:
            f.write(CONFIG_TEMPLATE)
        print(f"✅ 已创建配置模板: {config_file}")

    # 3. 创建素材目录
    category = task_type if task_type != "permanent" else "permanent"
    if task_type == "daily":
        category = "daily"
    elif task_type in ("event", "special"):
        pass  # category = task_type

    assets_dir = os.path.join(project_root, "assets", "tasks", category, task_name)
    os.makedirs(assets_dir, exist_ok=True)
    readme = os.path.join(assets_dir, "README.md")
    if not os.path.exists(readme):
        with open(readme, "w", encoding="utf-8") as f:
            f.write(f"# {display_name} 素材\n\n待截图：\n- entry.png: 入口按钮\n")
    print(f"✅ 已创建素材目录: {assets_dir}")

    print(f"\n🎉 {display_name}（{task_name}）生成完毕！")
    print(f"   下一步：① 截图填充素材 → ② 填配置 → ③ 实现 execute() 逻辑")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("用法: python task_generator.py new --type <daily|permanent|event|special> --name <name> --display <显示名>")
        print("示例: python task_generator.py new --type permanent --name yuling --display 御灵")
        sys.exit(1)

    # 简单解析
    args = sys.argv[1:]
    task_type = args[args.index("--type") + 1] if "--type" in args else "daily"
    task_name = args[args.index("--name") + 1] if "--name" in args else "new_task"
    display_name = args[args.index("--display") + 1] if "--display" in args else task_name

    generate_task(task_type, task_name, display_name)
