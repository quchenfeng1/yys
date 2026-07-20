"""
验证测试 — 特殊任务任务
"""

# ==================== ① 模块声明（必填） ====================
display_name = "验证测试"
description = "验证测试 — 战斗任务"
task_type = "battle"

# 能力声明（按需启用，UI 据此显示配置区）
uses_battle = True
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
    g = TaskGraph("test_verify")

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
class TestVerifyTask(TaskStep):
    """验证测试。"""
    name = "test_verify"
    display_name = display_name
    description = description
    is_generic = False
    timeout = timeout

    def execute(self, context: TaskContext) -> StepResult:
        graph = build_graph(context)
        success = graph.run(context)
        return (
            StepResult.success("验证测试 完成")
            if success else StepResult.fail("验证测试 失败")
        )
