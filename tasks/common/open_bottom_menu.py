"""
主界面识别（通用模块）

判断当前页面是否为主界面，是则展开底部菜单栏。
验证"识别-个人名片"和"按钮-打开式神录"同时存在即放行。

逻辑流程：
  1. 寻找「识别-个人名片」→ 确认为主界面
  2. 寻找「按钮-打开底部菜单」→ 存在则点击展开
  3. 否则寻找「按钮-打开式神录」→ 判断菜单是否已展开
  4. 两者同时存在 → 放行（success）
"""

display_name = "主界面识别"
description = "识别个人名片确认主页→展开底部菜单→验证式神录按钮可见即放行"

from tasks.base.task_step import TaskStep, StepResult
from tasks.base.task_context import TaskContext


class OpenBottomMenu(TaskStep):
    """主界面识别：确认主页并展开底部菜单，验证式神录可见。"""
    name = "open_bottom_menu"
    is_generic = True
    timeout = 15

    def execute(self, context: TaskContext) -> StepResult:
        rec = context.recognizer
        exe = context.executor

        # ── 第1步：确认当前页面为主界面 ──
        main_icon = rec.find("主界面/识别-个人名片")
        if main_icon is None:
            return StepResult.fail("未找到「识别-个人名片」，当前不在主界面")

        # ── 第2步：尝试展开底部菜单 ──
        open_btn = rec.find("主界面/按钮-打开底部菜单")
        if open_btn is not None:
            # 找到展开按钮，点击它
            exe.click_if_exists("主界面/按钮-打开底部菜单")
        else:
            # 没找到展开按钮，检查式神录按钮是否已可见
            pass  # 继续第3步统一验证

        # ── 第3步：最终验证 —— 个人名片 + 式神录 同时可见 ──
        card = rec.find("主界面/识别-个人名片")
        shikigami = rec.find("主界面/按钮-打开式神录")

        if card is not None and shikigami is not None:
            return StepResult.success("主界面识别通过，底部菜单已展开")
        elif card is None:
            return StepResult.fail("「识别-个人名片」消失，已离开主界面")
        else:
            return StepResult.fail("「按钮-打开式神录」不可见，底部菜单未展开")
