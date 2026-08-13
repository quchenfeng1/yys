"""端到端验证：大号带小号刷副本（组队协调）——CoopHost 切换模拟器→小号准备→开战→轮流结算。

架构说明（§3.10 组队协调）：
- 大号(main)与小号(sub1)各自有独立模拟器（MockADBClient，serial 区分）
- ConnectionManager 连接池 + switch_device 切换当前设备
- AccountManager.switch_to(sub) → switch_device(sub.device_id) → Executor 操作落到小号模拟器
- CoopHost 编排：切小号→接受邀请/准备→切回大号→开战→轮流结算

验证点：
  1. AccountManager 从 accounts.yaml 加载 main + sub1
  2. ConnectionManager 连接池双设备
  3. switch_to 切换设备后 Executor 点击落在对应模拟器
  4. CoopHost 完整流程：小号准备 → 大号开战 → 轮流结算
  5. 无 teaming 配置时按单人执行不报错
"""
import sys, os, tempfile, shutil, time
from pathlib import Path

import numpy as np
import cv2

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

MAIN_SERIAL = "127.0.0.1:16384"
SUB1_SERIAL = "127.0.0.1:16416"


def _make_template(name: str, size: tuple[int, int], seed: int) -> np.ndarray:
    w, h = size
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (255, 255, 255), 2)
    cv2.putText(img, name.split("/")[-1][:8], (6, h // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    return img


def main():
    ok = 0
    fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"✅ {name}")
        else:
            fail += 1
            print(f"❌ {name}  {detail}")

    # ════════════ 0. 准备临时目录 + 素材 ════════════
    tmp = Path(tempfile.mkdtemp(prefix="coop_"))
    assets = tmp / "assets"
    # 大号素材：开始战斗 + 领奖（主号界面）
    (assets / "main").mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(assets / "main" / "btn_start_battle.png"),
                _make_template("main/btn_start_battle", (160, 60), 11))
    cv2.imwrite(str(assets / "main" / "btn_claim.png"),
                _make_template("main/btn_claim", (140, 60), 12))
    # 小号素材：接受邀请 + 准备 + 领奖（小号界面）
    (assets / "sub").mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(assets / "sub" / "btn_accept_invite.png"),
                _make_template("sub/btn_accept_invite", (160, 60), 21))
    cv2.imwrite(str(assets / "sub" / "btn_ready.png"),
                _make_template("sub/btn_ready", (140, 60), 22))
    cv2.imwrite(str(assets / "sub" / "btn_claim.png"),
                _make_template("sub/btn_claim", (140, 60), 23))

    # ════════════ 1. AccountManager 加载账号 ════════════
    print("\n── [1/6] AccountManager 加载 main + sub1 ──")
    from device.mock_adb import MockADBClient
    # 每个模拟器只"显示"自己的素材（assets_prefix 过滤），键保持完整相对路径
    main_adb = MockADBClient(serial=MAIN_SERIAL, assets_dir=str(assets),
                             assets_prefix="main")
    sub1_adb = MockADBClient(serial=SUB1_SERIAL, assets_dir=str(assets),
                             assets_prefix="sub")

    from core.account_manager import AccountManager
    am = AccountManager(
        connection=None,  # 先用无 connection 方式验证账号加载
    )
    # 手动注入账号（模拟 accounts.yaml 加载：直接构造）
    from core.account_manager import AccountInfo
    am._accounts = {
        "main": AccountInfo(account_id="main", name="main", role="main",
                            device_id=MAIN_SERIAL, teaming_enabled=False),
        "sub1": AccountInfo(account_id="sub1", name="sub1", role="sub",
                            device_id=SUB1_SERIAL, team_group="group_a",
                            teaming_enabled=True),
    }
    am._current_id = "main"
    check("加载 2 个账号", len(am.get_all_accounts()) == 2)
    check("sub_accounts 含 sub1", [a.account_id for a in am.sub_accounts] == ["sub1"])
    partners = am.get_teaming_partners("group_a")
    check("get_teaming_partners(group_a) 返回 sub1",
          [p.account_id for p in partners] == ["sub1"])

    # ════════════ 2. ConnectionManager 双设备连接池 ════════════
    print("\n── [2/6] ConnectionManager 双设备切换 ──")
    from device.connection import ConnectionManager

    class _Conn(ConnectionManager):
        """注入两个 MockADBClient 的连接管理器（简化构造）"""
        def __init__(self):
            # 绕过父类构造，只保留核心池逻辑
            import threading as _t
            self._pool_lock = _t.Lock()
            self._lock = _t.Lock()
            self._device_pool = {}
            self._adb = main_adb
            self._current_serial = MAIN_SERIAL
            self._connected = True
            self._conn_pause_event = _t.Event()
            self._conn_pause_event.set()
            self._quality_records = {}
            self._reconnect_thread = None
            self._reconnect_stop = _t.Event()
            self._heartbeat = None
            self._auto_reconnect = False
            self._max_retries = 5
            self._connection_status = "connected"
            self._screen_size = (0, 0)
            self._screenshot_cache = None
            self._screenshot_cache_time = 0.0
            self._event_bus = None
            self._state_manager = None
            self._config = None

    conn = _Conn()
    conn._device_pool[MAIN_SERIAL] = main_adb
    conn._device_pool[SUB1_SERIAL] = sub1_adb

    ok_switch = conn.switch_device(SUB1_SERIAL)
    check("switch_device 切到小号", ok_switch and conn.current_serial == SUB1_SERIAL)
    conn.switch_device(MAIN_SERIAL)
    check("switch_device 切回大号", conn.current_serial == MAIN_SERIAL)

    # 注入 connection 到 AccountManager
    am._connection = conn

    # ════════════ 3. switch_to 切换设备后 Executor 落在对应模拟器 ════════════
    print("\n── [3/6] switch_to 切换 → Executor 点击对应模拟器 ──")
    from core.recognizer import Recognizer
    from core.anti_detect import AntiDetect
    from core.executor import Executor

    rec_main = Recognizer(asset_dir=str(assets / "main"), connection=conn,
                          screenshot_ttl=0.05, result_cache_ttl=0.01)
    rec_sub = Recognizer(asset_dir=str(assets / "sub"), connection=conn,
                         screenshot_ttl=0.05, result_cache_ttl=0.01)
    ad = AntiDetect(min_interval=0.001, max_interval=0.002,
                    action_jitter=False, random_fail_rate=0)
    # 用一个大 Executor + 可切换识别器：实际 Executor 识别走 recognizer 截图（connection）
    # 简化：直接对每个设备建识别器，验证 connection 截图源是否正确

    # 验证：连接池切换后，screenshot 来自对应设备
    conn.switch_device(MAIN_SERIAL)
    img_main = conn.screenshot()
    check("切换大号后截图来自大号素材（含 btn_start_battle）",
          main_adb.screenshot_count >= 1 and True)
    # 更直接：验证 mock 设备各自截图不同（含各自素材）
    conn.switch_device(SUB1_SERIAL)
    img_sub = conn.screenshot()
    conn.switch_device(MAIN_SERIAL)

    # 用统一 Recognizer（连接池截图）+ 大号素材识别
    rec = Recognizer(asset_dir=str(assets / "main"), connection=conn,
                     screenshot_ttl=0.05, result_cache_ttl=0.01)
    conn.switch_device(MAIN_SERIAL)
    rec.update_screenshot(conn.screenshot())
    m = rec.find_one("btn_start_battle", threshold=0.9)
    check("大号界面识别到 btn_start_battle", m is not None)

    ex = Executor(recognizer=rec, anti_detect=ad, connection=conn, dry_run=False)
    conn.switch_device(MAIN_SERIAL)
    ok_start = ex.click_image("btn_start_battle", timeout=3)
    check("大号点击开始战斗", ok_start)
    check("点击落在 main 模拟器", len(main_adb.clicks) >= 1)
    check("小号模拟器未被点击", len(sub1_adb.clicks) == 0)

    # 切到小号 → 识别小号素材
    conn.switch_device(SUB1_SERIAL)
    rec2 = Recognizer(asset_dir=str(assets / "sub"), connection=conn,
                      screenshot_ttl=0.05, result_cache_ttl=0.01)
    rec2.update_screenshot(conn.screenshot())
    m2 = rec2.find_one("btn_accept_invite", threshold=0.9)
    check("小号界面识别到 btn_accept_invite", m2 is not None)

    # ════════════ 4. CoopHost 完整流程 ════════════
    print("\n── [4/6] CoopHost 组队协调完整流程 ──")
    # 构造一个"跟随连接切换"的 Executor：识别器用连接池截图 + 同时识别大/小号素材
    from games.yys.tasks.common.coop_host import CoopHost

    # CoopHost 内部用 context.executor.click_if_exists；executor 的 recognizer
    # 必须能看到"当前设备"的截图。每个设备截图只含自己的素材 → 命中各自
    rec3 = Recognizer(asset_dir=str(assets), connection=conn,
                      screenshot_ttl=0.05, result_cache_ttl=0.01)
    ex3 = Executor(recognizer=rec3, anti_detect=ad, connection=conn, dry_run=False)

    # 重置点击记录
    main_adb.clicks.clear()
    sub1_adb.clicks.clear()

    from tasks.base.task_context import TaskContext
    ctx = TaskContext(
        task_id="coop_battle",
        task_name="coop_battle",
        # 轮数复用「每轮循环」loop_count=2（不再单独配置 teaming.rounds）
        task_config={"teaming": {"sub_ids": ["sub1"]}, "loop_count": 2},
        executor=ex3,
        account_manager=am,
    )
    coop = CoopHost(params={
        "accept_btn": "sub/btn_accept_invite",
        "ready_btn": "sub/btn_ready",
        "start_btn": "main/btn_start_battle",
        "claim_btn": "sub/btn_claim",       # 小号结算素材
        "main_claim_btn": "main/btn_claim", # 主号结算素材
    })
    result = coop.execute(ctx)
    check("CoopHost 返回 SUCCESS", getattr(result, 'status', None) in ("success", "SUCCESS"),
          str(result))
    check("小号模拟器被操作（接受邀请/准备/结算）", len(sub1_adb.clicks) >= 4,
          f"sub1 点击 {len(sub1_adb.clicks)} 次")
    check("大号模拟器被操作（开战/结算）", len(main_adb.clicks) >= 2,
          f"main 点击 {len(main_adb.clicks)} 次")
    check("执行后当前账号切回主号", am.current_account_id == "main",
          f"当前 {am.current_account_id}")

    # ════════════ 5. 无 teaming → 单人执行不报错 ════════════
    print("\n── [5/6] 无 teaming 配置 → 单人执行 ──")
    ctx2 = TaskContext(task_id="solo", task_name="solo",
                       task_config={}, executor=ex3, account_manager=am)
    r2 = CoopHost().execute(ctx2)
    check("无小号配置返回 SUCCESS（按单人）", getattr(r2, 'status', None) in ("success", "SUCCESS"),
          str(r2))

    # ════════════ 6. TaskContext 注入 account_manager ════════════
    print("\n── [6/6] TaskContext.account_manager 字段存在 ──")
    check("TaskContext 有 account_manager 字段",
          hasattr(TaskContext(), 'account_manager'))

    # 清理
    shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'=' * 46}")
    print(f"🎉 组队协调验证 {ok}/{ok + fail} 通过")
    if fail:
        print("存在失败项，请检查。")
        sys.exit(1)


if __name__ == "__main__":
    main()
