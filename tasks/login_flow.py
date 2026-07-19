"""
登录流程任务模块

目标：从启动阴阳师开始，到稳定进入庭院主界面。

流程节点：
[1] 启动阴阳师 App（通过 ADB am start）
[2] 开屏动画 / 健康游戏公告 → 识别并点击跳过/确认
[3] 公告弹窗关闭（循环关闭直到无弹窗）
[4] 选区界面 → 识别并点击
[5] 点击"进入游戏"
[6] 等待庭院主界面出现（登录完成标志）

容错设计：
- 每个节点设置超时，超时则截图存档并重试
- 支持断点续登：若已在游戏内则跳过登录流程
- 登录失败超过 3 次则停止并告警
"""

import time
from pathlib import Path

from tasks.base_task import BaseTask
from core.exceptions import LoginFailedError
from core.logger import get_logger

logger = get_logger("tasks.login_flow")

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
SCREENSHOTS_DIR = PROJECT_ROOT / "screenshots"


class LoginFlow(BaseTask):
    """登录流程任务：启动游戏并进入庭院主界面"""

    name = "login_flow"
    display_name = "登录流程"
    category = "special"

    def __init__(self, executor=None, recognizer=None, config=None, adb_client=None,
                 app_package=None, app_activity=None):
        super().__init__(executor, recognizer, config)
        self.adb = adb_client
        self.app_package = app_package or "com.netease.onmyoji.wyzymnqsd_cps"
        self.app_activity = app_activity or "com.netease.onmyoji.Launcher"

        # 登录步骤配置（从 config/coords/login.json 加载）
        self._steps = self.config.get("steps", [])
        self._max_retries = 3

    def run(self) -> bool:
        """执行登录流程

        Returns:
            True 表示成功进入庭院
        """
        # 确保截图目录存在
        SCREENSHOTS_DIR.mkdir(exist_ok=True)

        # 检查是否已在游戏中（断点续登）
        if self._check_already_in_game():
            logger.info("已在游戏内，跳过登录流程")
            return True

        # 启动阴阳师 App
        logger.info("=" * 50)
        logger.info("开始登录流程")
        logger.info("=" * 50)

        if not self._launch_app():
            return False

        # 按步骤处理登录流程
        for attempt in range(self._max_retries):
            logger.info(f"登录尝试 {attempt + 1}/{self._max_retries}")

            try:
                success = self._process_login_steps()
                if success:
                    logger.info("登录流程完成，已进入庭院")
                    return True
            except LoginFailedError as e:
                logger.error(f"登录失败: {e}")
                # 截图存档
                self._save_error_screenshot(f"login_fail_attempt{attempt+1}")

            if attempt < self._max_retries - 1:
                logger.info("等待 5 秒后重试...")
                time.sleep(5)

        logger.error(f"登录失败超过 {self._max_retries} 次，停止尝试")
        return False

    def _check_already_in_game(self) -> bool:
        """检查是否已在游戏中（断点续登）

        通过识别庭院主界面标志图判断
        """
        if self.recognizer is None:
            return False

        # 检查是否有庭院标志图素材
        if not self.recognizer.has_template("scenes/courtyard/main"):
            return False

        # 快速检查一次
        result = self.recognizer.find("scenes/courtyard/main", threshold=0.7)
        if result:
            logger.info(f"检测到庭院主界面 (置信度={result.confidence:.3f})")
            return True

        return False

    def _launch_app(self) -> bool:
        """启动阴阳师 App"""
        if self.adb is None:
            logger.error("ADB 客户端未设置，无法启动 App")
            return False

        logger.info(f"启动阴阳师: {self.app_package}")

        # 先检查 App 是否已在运行
        if self.adb.is_app_running(self.app_package):
            logger.info("阴阳师已在运行，跳过启动")
            return True

        # 启动 App
        success = self.adb.launch_app(self.app_package, self.app_activity)
        if success:
            logger.info("阴阳师启动成功，等待加载...")
            time.sleep(5)  # 等待 App 加载
        else:
            logger.error("阴阳师启动失败")

        return success

    def _process_login_steps(self) -> bool:
        """按步骤处理登录流程

        根据 config/coords/login.json 中配置的 steps 依次处理。
        每个步骤识别对应图片并点击，带超时和循环处理。

        Returns:
            True 表示所有步骤完成
        Raises:
            LoginFailedError: 某步骤超时或失败
        """
        for step in self._steps:
            step_name = step.get("name", "unknown")
            image = step.get("image", "")
            timeout = step.get("timeout", 30)
            is_loop = step.get("loop", False)

            logger.info(f"--- 步骤: {step_name} (图片={image}, 超时={timeout}s, 循环={is_loop}) ---")

            if is_loop:
                # 循环步骤：反复点击直到不再出现（如关闭多个公告弹窗）
                self._handle_loop_step(image, step_name, timeout)
            else:
                # 普通步骤：等待图片出现并点击
                success = self._handle_single_step(image, step_name, timeout)
                if not success:
                    # 最后一个步骤（courtyard）允许不点击，只需检测到即可
                    if step_name == "courtyard":
                        # 庭院检测：如果是最后一步且前面都成功，可能已直接进入
                        result = self.recognizer.wait("scenes/courtyard/main", timeout=timeout)
                        if result:
                            logger.info(f"检测到庭院主界面 (置信度={result.confidence:.3f})")
                            return True
                        raise LoginFailedError(f"未检测到庭院主界面: {step_name}")
                    else:
                        raise LoginFailedError(f"步骤 {step_name} 失败：未找到图片 {image}")

        # 所有步骤完成
        return True

    def _handle_single_step(self, image: str, step_name: str, timeout: float) -> bool:
        """处理单个步骤：等待图片出现并点击

        Args:
            image: 模板图片名
            step_name: 步骤名
            timeout: 超时时间

        Returns:
            True 表示成功
        """
        if self.recognizer is None or self.executor is None:
            logger.error("识别器或执行器未设置")
            return False

        # 检查素材是否存在
        if not self.recognizer.has_template(image):
            logger.warning(f"素材不存在: {image}，跳过步骤 {step_name}")
            logger.info(f"请将对应截图放入 所需图片/ 文件夹（详见控制台输出的图片需求列表）")
            return False

        # 等待图片出现并点击
        success = self.executor.click_image(image, timeout=timeout)
        if success:
            logger.info(f"步骤 {step_name} 完成")
            # 点击后随机等待（界面加载）
            self.executor.random_sleep(1.0, 2.5)
        else:
            logger.warning(f"步骤 {step_name}: 未找到 {image}，尝试继续...")

        return success

    def _handle_loop_step(self, image: str, step_name: str, timeout: float):
        """处理循环步骤：反复点击直到不再出现（如关闭公告弹窗）

        Args:
            image: 模板图片名
            step_name: 步骤名
            timeout: 总超时时间
        """
        if self.recognizer is None or self.executor is None:
            return

        if not self.recognizer.has_template(image):
            logger.warning(f"素材不存在: {image}，跳过循环步骤 {step_name}")
            return

        start_time = time.time()
        click_count = 0
        max_loop = 10  # 最多循环 10 次，防止死循环

        while time.time() - start_time < timeout and click_count < max_loop:
            # 尝试点击（不等待，直接检测）
            if self.executor.click_if_exists(image):
                click_count += 1
                logger.info(f"循环步骤 {step_name}: 关闭第 {click_count} 个弹窗")
                self.executor.random_sleep(0.8, 1.5)
            else:
                # 没有更多弹窗了
                break

        logger.info(f"循环步骤 {step_name} 完成，共关闭 {click_count} 个弹窗")

    def _save_error_screenshot(self, tag: str = "error"):
        """错误时截图存档

        Args:
            tag: 截图标签
        """
        if self.adb is None:
            return

        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filepath = SCREENSHOTS_DIR / f"{tag}_{timestamp}.png"
            self.adb.screenshot()
            # 使用截图模块保存
            import cv2
            img = self.adb.screenshot()
            cv2.imwrite(str(filepath), img)
            logger.info(f"错误截图已保存: {filepath}")
        except Exception as e:
            logger.error(f"截图保存失败: {e}")
