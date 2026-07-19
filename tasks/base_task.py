"""
任务基类模块

所有任务（日常/常驻/活动/特殊）均继承自 BaseTask。
提供模板方法 execute()，统一执行流程：pre_check → setup → run → teardown → post_check

关键约束：
- name 必须与 assets/{name}/ 素材目录、config/coords/{name}.json 配置文件同名（三者绑定）
- run() 是唯一必须实现的钩子
- 任何设备操作必须通过 self.executor 调用（防封号守门）
"""

from abc import ABC, abstractmethod
from core.logger import get_logger

logger = get_logger("tasks.base")


class BaseTask(ABC):
    """任务基类，所有任务的根基类"""

    # ===== 类属性（子类必须定义）=====
    name: str = ""              # 任务唯一标识（与素材目录、配置文件同名）
    display_name: str = ""      # UI 显示名
    category: str = "daily"     # 分类: daily / permanent / event / special

    # ===== 可选类属性（有默认值）=====
    priority: int = 0           # 优先级（数字小先执行）

    def __init__(self, executor=None, recognizer=None, config=None):
        """
        Args:
            executor: 操作执行器（含防封号）
            recognizer: 图像识别器
            config: 任务配置字典
        """
        self.executor = executor
        self.recognizer = recognizer
        self.config = config or {}
        self._logger = get_logger(f"tasks.{self.name}")

    # ===== 生命周期钩子（子类按需覆写）=====

    def pre_check(self) -> bool:
        """前置检查：体力/次数/时间/有效期。返回 False 跳过本任务。"""
        return True

    def setup(self) -> bool:
        """前置准备：导航到目标场景、切换阵容。"""
        return True

    @abstractmethod
    def run(self) -> bool:
        """核心执行逻辑（必须实现）

        Returns:
            True 表示执行成功，False 表示失败
        """
        pass

    def teardown(self) -> bool:
        """收尾：回庭院、关弹窗。默认实现为空。"""
        return True

    def post_check(self) -> bool:
        """后置校验：确认任务完成。"""
        return True

    def on_error(self, error: Exception) -> bool:
        """异常处理

        Returns:
            True 表示已恢复，False 放弃本任务
        """
        self._logger.error(f"任务异常: {error}")
        return False

    # ===== 模板方法（请勿覆写）=====

    def execute(self) -> bool:
        """统一执行流程: pre_check → setup → run → teardown → post_check

        Returns:
            True 表示任务成功完成
        """
        self._logger.info(f"任务开始: {self.display_name}({self.name})")

        try:
            # 前置检查
            if not self.pre_check():
                self._logger.info(f"前置检查未通过，跳过任务: {self.name}")
                return False

            # 前置准备
            if not self.setup():
                self._logger.warning(f"前置准备失败: {self.name}")
                return False

            # 核心执行
            success = self.run()

            # 收尾
            self.teardown()

            # 后置校验
            if success:
                self.post_check()

            self._logger.info(f"任务结束: {self.name} ({'成功' if success else '失败'})")
            return success

        except Exception as e:
            self._logger.error(f"任务执行异常: {self.name} - {e}", exc_info=True)
            recovered = self.on_error(e)
            return False
