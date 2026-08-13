"""
通用模块：CoopHost 组队主机（创建队伍→邀请→开战→轮流结算）。

大号带队刷副本的协调器：
- 从 task_config.teaming（或 params）读取组队小号列表（sub_ids 或 team_group）
- 依次切换小号模拟器，让每个小号完成"接受邀请/准备"（CoopJoin）
- 切回主号 → 点击开始战斗
- 轮流结算：每轮战斗结束后，逐个切换小号执行结算/领奖（CoopPassive），再切回主号

素材名全部可配置（params），默认使用约定名（btn_accept_invite / btn_ready /
btn_start_battle / btn_claim），与 run_controller._on_coordinate_action 一致。
"""
from __future__ import annotations

import time
from typing import Any

from tasks.base.task_step import TaskStep, StepResult, StepStatus


def _log(ctx, msg: str) -> None:
    """输出到 UI 日志面板（无总线时兜底 print）"""
    try:
        from core.event_bus import get_global_bus
        from core.events import Events
        get_global_bus().publish(Events.LOG_RECORD, source="tasks",
                                 level="info", message=msg)
    except Exception:
        print(f"[info] {msg}")


class CoopHost(TaskStep):
    """组队队长（主号带队）：协调大号 + 小号完成"准备→开战→轮流结算"循环。

    当前仅支持主号带队（大号创建队伍，小号接受邀请+准备），不支持小号带队。
    组队轮数复用「每轮循环」（task_config.loop_count），不单独配置。

    用法（在任务 _build_graph 中作为主号的步骤引用）：
        g.add_step("coop", CoopHost(params={
            "accept_btn": "tasks/_shared/btn_accept_invite",  # 小号接受邀请素材
            "ready_btn": "tasks/_shared/btn_ready",           # 小号准备素材
            "start_btn": "tasks/_shared/btn_start_battle",    # 大号开战素材
            "claim_btn": "tasks/_shared/btn_claim",           # 小号结算/领奖素材
            "main_claim_btn": "tasks/_shared/btn_claim",      # 主号结算素材（默认同 claim_btn）
            "wait_timeout": 120,                              # 等待小号加入超时
        }))
        轮数来自 task_config.loop_count（每轮循环），也可用 params.rounds 显式覆盖。
    """

    is_generic = True

    def execute(self, context: Any = None) -> StepResult:
        # 需要切换设备 → 必须注入 account_manager
        am = getattr(context, 'account_manager', None)
        ex = getattr(context, 'executor', None)
        if am is None or ex is None:
            _log(context, "CoopHost: 缺少 account_manager/executor，跳过组队协调")
            return StepResult.success("无组队能力，按单人执行")

        # 素材名（params 优先，默认约定名）
        accept_btn = self.params.get("accept_btn", "btn_accept_invite")
        ready_btn = self.params.get("ready_btn", "btn_ready")
        start_btn = self.params.get("start_btn", "btn_start_battle")
        claim_btn = self.params.get("claim_btn", "btn_claim")
        # 主号结算素材：可独立配置（真实场景主/小号结算按钮可能不同素材）
        main_claim_btn = self.params.get("main_claim_btn") or claim_btn
        wait_timeout = float(self.params.get("wait_timeout", 120))

        # 读取组队小号列表：params.sub_ids 优先，其次 task_config.teaming
        sub_ids = self.params.get("sub_ids") or []
        teaming_cfg = (context.task_config or {}).get("teaming") or {}
        if not sub_ids and teaming_cfg:
            sub_ids = teaming_cfg.get("sub_ids") or []
            if not sub_ids and teaming_cfg.get("group"):
                try:
                    partners = am.get_teaming_partners(teaming_cfg["group"])
                    sub_ids = [p.account_id for p in partners]
                except Exception:
                    sub_ids = []
        # 轮数 = 每次触发打几轮。复用「每轮循环」(loop_count)，不单独配置：
        # params.rounds 优先 → teaming.rounds（旧配置兼容）→ task_config.loop_count → 1
        cfg_loop = 1
        try:
            cfg_loop = int((context.task_config or {}).get("loop_count") or 1)
        except (TypeError, ValueError):
            cfg_loop = 1
        rounds = int(self.params.get("rounds", teaming_cfg.get("rounds", cfg_loop)))
        if not sub_ids:
            _log(context, "CoopHost: 未配置组队小号（teaming.sub_ids/group 为空），按单人执行")
            return StepResult.success("未配置小号，单人刷本")

        main_id = None
        try:
            cur = am.get_current()
            main_id = cur.account_id if cur else None
        except Exception:
            pass

        _log(context, f"CoopHost: 组队 {len(sub_ids)} 个小号 → {sub_ids}")

        # ── 阶段1：小号准备（接受邀请/准备） ──
        for sub_id in sub_ids:
            try:
                if not am.switch_to(sub_id):
                    _log(context, f"CoopHost: 切换小号 {sub_id} 失败，跳过")
                    continue
                time.sleep(0.5)
                # 小号：接受邀请 → 准备
                ex.click_if_exists(accept_btn, threshold=0.8)
                ex.click_if_exists(ready_btn, threshold=0.8)
                _log(context, f"CoopHost: 小号 {sub_id} 已接受邀请并准备")
            except Exception as e:
                _log(context, f"CoopHost: 小号 {sub_id} 准备异常: {e}")

        # ── 切回主号 → 开始战斗 ──
        if main_id:
            try:
                am.switch_to(main_id)
            except Exception:
                pass
        ex.click_if_exists(start_btn, threshold=0.8)
        _log(context, "CoopHost: 主号已点击开始战斗")

        # ── 阶段2：轮流结算（每轮：主号结算 → 切小号结算 → 切回） ──
        for r in range(1, rounds + 1):
            if self.check_interrupt(context):
                return StepResult(status=StepStatus.SKIP, message="被中断")
            _log(context, f"CoopHost: 第 {r}/{rounds} 轮结算")
            # 主号结算（用主号自己的结算素材）
            ex.click_if_exists(main_claim_btn, threshold=0.8)
            time.sleep(1.0)
            # 依次小号结算
            for sub_id in sub_ids:
                try:
                    if not am.switch_to(sub_id):
                        continue
                    time.sleep(0.5)
                    ex.click_if_exists(claim_btn, threshold=0.8)
                    _log(context, f"CoopHost: 小号 {sub_id} 第 {r} 轮结算完成")
                except Exception:
                    continue
            # 切回主号
            if main_id:
                try:
                    am.switch_to(main_id)
                except Exception:
                    pass

        return StepResult.success(f"组队完成：{len(sub_ids)} 个小号 × {rounds} 轮")
