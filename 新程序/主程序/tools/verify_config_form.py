#!/usr/bin/env python3
"""
配置表单链路验证（tools/verify_config_form.py）

无 GUI 验证「游戏任务面板」背后的核心链路（设计书 §4）：
  1. TaskManager 解析模块级声明（task_type/uses_battle/loop_count/timeout）
  2. ConfigManager.update_task 写 tasks.yaml（列表结构，validate 通过，读回一致）
  3. TaskBridge.get_task_detail 合并声明 + 配置
  4. TaskBridge.save_task_config 保存后 get_task_config 读回

运行：
    .venv/bin/python tools/verify_config_form.py

返回码：0=全部通过  1=有失败项
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}  {detail}")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def verify_task_manager(tmp_tasks: Path) -> None:
    print("\n[1/4] TaskManager 解析模块级声明（设计书 §2）")
    from core.task_manager import TaskManager

    # 设计书模板：模块级声明
    write(tmp_tasks / "special" / "orochi_soul.py", '''"""御魂副本-八岐大蛇第十层"""
display_name = "御魂副本-八岐大蛇"
description = "自动刷御魂八岐大蛇第十层"
task_type = "battle"

uses_battle = True
uses_team = True
uses_soul = True
uses_stamina = True
loop_count = 10
timeout = 900
''')
    write(tmp_tasks / "special" / "__init__.py", "")

    tm = TaskManager(tasks_dir=str(tmp_tasks), assets_dir=str(tmp_tasks.parent / "assets"))
    metas = tm.scan_all()
    m = tm.get_meta("orochi_soul")
    check("扫描到任务", m is not None)
    if m:
        check("display_name 解析", m.display_name == "御魂副本-八岐大蛇", f"实际 {m.display_name}")
        check("task_type 解析", m.task_type == "battle", f"实际 {m.task_type}")
        check("uses_battle 解析", m.uses_battle is True, f"实际 {m.uses_battle}")
        check("uses_team 解析", m.uses_team is True)
        check("uses_soul 解析", m.uses_soul is True)
        check("uses_stamina 解析", m.uses_stamina is True)
        check("loop_count 解析(10)", m.loop_count == 10, f"实际 {m.loop_count}")
        check("timeout 解析(900)", m.timeout == 900, f"实际 {m.timeout}")


def verify_config_update(tmp_cfg: Path) -> None:
    print("\n[2/4] ConfigManager.update_task（列表结构写盘）")
    from core.config_manager import ConfigManager

    write(tmp_cfg / "global.yaml", "_version: 1\ndevice:\n  adb:\n    port: 5037\n  mock: true\n")
    write(tmp_cfg / "accounts.yaml", "accounts: []\n")
    write(tmp_cfg / "tasks.yaml", "tasks: []\n")

    cfg = ConfigManager(config_dir=str(tmp_cfg))
    cfg.load()

    cfg.update_task("orochi_soul", priority=5, max_daily=50, time_start="08:00",
                    time_end="23:00", execution_mode="per_slot",
                    time_slots=[["10:00", "12:00"], ["14:00", "16:00"]])
    # validate 必须通过（列表结构）
    errors = cfg.validate()
    check("update_task 后 validate 通过", not errors, f"实际 {errors}")

    # 读回
    tc = cfg.get_task_config("orochi_soul")
    check("get_task_config 读回", tc is not None)
    if tc:
        check("priority 读回(5)", tc.get("priority") == 5, f"实际 {tc.get('priority')}")
        check("max_daily 读回(50)", tc.get("max_daily") == 50)
        check("execution_mode 读回", tc.get("execution_mode") == "per_slot")
        check("time_slots 读回", tc.get("time_slots") == [["10:00", "12:00"], ["14:00", "16:00"]])

    # 再更新不覆盖已存在条目
    cfg.update_task("orochi_soul", time_end="22:00")
    tc2 = cfg.get_task_config("orochi_soul")
    check("二次更新保留旧字段(priority=5)", tc2.get("priority") == 5)
    check("二次更新生效(time_end=22:00)", tc2.get("time_end") == "22:00")


def verify_task_bridge(tmp_tasks: Path, tmp_cfg: Path) -> None:
    print("\n[3/4] TaskBridge.get_task_detail（声明 + 配置合并）")
    from core.config_manager import ConfigManager
    from core.task_manager import TaskManager
    from core.event_bus import EventBus
    from ui.param_bridge.task_bridge import TaskBridge

    cfg = ConfigManager(config_dir=str(tmp_cfg))
    cfg.load()
    tm = TaskManager(tasks_dir=str(tmp_tasks), assets_dir=str(tmp_tasks.parent / "assets"))
    tm.scan_all()

    bridge = TaskBridge(registry=None, scheduler=None, task_manager=None,
                        config=cfg, file_manager=tm, event_bus=EventBus())

    metas = bridge.get_task_metas()
    check("get_task_metas 返回元数据", any(m["name"] == "orochi_soul" for m in metas))
    m = next((x for x in metas if x["name"] == "orochi_soul"), None)
    if m:
        check("meta 含 uses_battle", m["uses_battle"] is True)

    detail = bridge.get_task_detail("orochi_soul")
    check("detail 含 display_name", detail.get("display_name") == "御魂副本-八岐大蛇")
    check("detail 含 uses_battle", detail.get("uses_battle") is True)
    check("detail 合并 tasks.yaml(priority=5)", detail.get("priority") == 5)


def verify_save(tmp_cfg: Path) -> None:
    print("\n[4/4] TaskBridge.save_task_config（保存后读回）")
    from core.config_manager import ConfigManager
    from core.task_manager import TaskManager
    from core.event_bus import EventBus
    from ui.param_bridge.task_bridge import TaskBridge

    cfg = ConfigManager(config_dir=str(tmp_cfg))
    cfg.load()
    tm = TaskManager(tasks_dir=str(tmp_cfg.parent / "tasks"), assets_dir=str(tmp_cfg.parent / "assets"))
    bridge = TaskBridge(config=cfg, file_manager=tm, event_bus=EventBus())

    bridge.save_task_config("orochi_soul", {
        "enabled": True, "priority": 3, "time_start": "09:00", "time_end": "21:00",
        "max_daily": 20, "repeat": {"type": "daily", "value": 1},
        "execution_mode": "per_slot",
        "loop_count": 2, "team_id": "阵容1", "max_fail_streak": 3,
    })
    tc = cfg.get_task_config("orochi_soul")
    check("保存后读回 priority=3", tc.get("priority") == 3, f"实际 {tc.get('priority')}")
    check("保存后读回 team_id", tc.get("team_id") == "阵容1")
    check("保存后读回 execution_mode", tc.get("execution_mode") == "per_slot")
    check("保存后 validate 通过", not cfg.validate())


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        tmp_tasks = base / "tasks"
        tmp_cfg = base / "config"
        verify_task_manager(tmp_tasks)
        verify_config_update(tmp_cfg)
        verify_task_bridge(tmp_tasks, tmp_cfg)
        verify_save(tmp_cfg)

    print("\n============================================================")
    print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败")
    if FAIL:
        print("❌ 存在失败项")
        return 1
    print("🎉 配置表单链路全部通过！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
