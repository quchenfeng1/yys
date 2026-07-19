"""
行为档案（03-安全模块 子模块）

定义多档安全强度，供 AntiDetect 按需切换。
safe/normal/fast/debug 四档覆盖不同使用场景。

对应解耦文档：模块说明/03-安全模块.md
"""

from dataclasses import dataclass


@dataclass
class BehaviorProfile:
    """安全强度档案。"""

    name: str                    # 档案名
    click_offset_radius: int     # 点击随机偏移半径（像素）
    delay_jitter: float          # 延迟抖动系数
    long_pause_prob: float       # 走神暂停触发概率
    swipe_jitter: int            # 滑动抖动（ms）
    min_interval: float          # 最小操作间隔（秒）

    # ==================== 预设档案 ====================

    @classmethod
    def safe(cls) -> "BehaviorProfile":
        """最安全，最慢。长时间挂机推荐。"""
        return cls(
            name="safe",
            click_offset_radius=15,
            delay_jitter=1.0,
            long_pause_prob=0.15,
            swipe_jitter=200,
            min_interval=1.0,
        )

    @classmethod
    def normal(cls) -> "BehaviorProfile":
        """平衡（默认）。日常使用推荐。"""
        return cls(
            name="normal",
            click_offset_radius=10,
            delay_jitter=0.5,
            long_pause_prob=0.08,
            swipe_jitter=100,
            min_interval=0.8,
        )

    @classmethod
    def fast(cls) -> "BehaviorProfile":
        """快速，风险增加。刷材料短期使用。"""
        return cls(
            name="fast",
            click_offset_radius=5,
            delay_jitter=0.2,
            long_pause_prob=0.03,
            swipe_jitter=50,
            min_interval=0.5,
        )

    @classmethod
    def debug(cls) -> "BehaviorProfile":
        """调试，关闭安全处理。仅开发测试！"""
        return cls(
            name="debug",
            click_offset_radius=0,
            delay_jitter=0,
            long_pause_prob=0,
            swipe_jitter=0,
            min_interval=0,
        )

    # ==================== 工具方法 ====================

    @classmethod
    def get_profile(cls, name: str) -> "BehaviorProfile":
        """通过名称获取档案。"""
        profiles = {
            "safe": cls.safe,
            "normal": cls.normal,
            "fast": cls.fast,
            "debug": cls.debug,
        }
        factory = profiles.get(name, cls.normal)
        return factory()

    @classmethod
    def list_profiles(cls) -> list[str]:
        return ["safe", "normal", "fast", "debug"]
