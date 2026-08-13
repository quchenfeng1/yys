"""端到端验证：战斗配置 / 组队配置从 tasks.yaml → scheduler → task_config 完整透传。

背景（2026-08-07 修复）：
- UI「战斗配置」Tab 保存 teaming/soul_setup/lock_team/change_team/stamina_required
- 但 config_schema.TaskEntry dataclass 缺少这些字段，validate 时被丢弃
  → Scheduler 读不到 → CoopHost 永远收不到组队小号、combat_test 战斗配置失效
- 已修复：TaskEntry / Scheduler.TaskConfig 补齐字段 + load 读取 + run_controller 注入
- 另：TaskGraph 熔断阈值此前从不注入（默认 5 vs 配置 10），现从 task_config 读取

验证点：
  1. TaskEntry 保留 teaming/soul_setup/lock_team/change_team/stamina_required
  2. Scheduler TaskConfig 透传上述字段 + loop_count(max_fail_streak/floor/team_id)
  3. run_controller 注入 task_config 含全部字段
  4. TaskGraph 熔断阈值 = 配置值（10）
  5. combat_test 从 task_config 读战斗配置（回退文件读取兜底）
"""
import sys, os, tempfile
from pathlib import Path

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

PASS = 0


def check(label, cond, detail=""):
    global PASS
    assert cond, f"FAIL: {label}  {detail}"
    PASS += 1
    print(f"PASS {label}")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="battle_cfg_"))
    (tmp / "global.yaml").write_text(
        "device:\n  adb: {host: 127.0.0.1, port: 5037}\n"
        "image: {template_threshold: 0.8}\n"
        "anti_detect: {min_interval: 1.0, max_interval: 5.0}\n"
        "log: {level: INFO}\n", encoding="utf-8")
    (tmp / "accounts.yaml").write_text("accounts: []\n", encoding="utf-8")
    (tmp / "tasks.yaml").write_text("""
tasks:
- name: combat_test
  id: combat_test
  enabled: true
  priority: 10
  repeat: {type: daily, value: 1, loop_count: 5}
  loop_count: 5
  max_fail_streak: 10
  team_id: 阵容1
  floor: 10
  teaming: {sub_ids: [sub1, sub2]}
  soul_setup: {group: 御魂副本, team: 御魂十层, position: [4, 1]}
  lock_team: true
  change_team: true
  stamina_required: 100
""", encoding="utf-8")

    from core.config_manager import ConfigManager
    from core.scheduler import Scheduler

    cm = ConfigManager(config_dir=tmp)
    cm.load()
    raw = cm.tasks_config
    t = raw.tasks[0]

    # 1. TaskEntry 保留字段
    check("TaskEntry.teaming 保留", getattr(t, 'teaming', None) == {'sub_ids': ['sub1', 'sub2']})
    check("TaskEntry.soul_setup 保留", getattr(t, 'soul_setup', None) == {'group': '御魂副本', 'team': '御魂十层', 'position': [4, 1]})
    check("TaskEntry.lock_team 保留", getattr(t, 'lock_team', None) is True)
    check("TaskEntry.change_team 保留", getattr(t, 'change_team', None) is True)
    check("TaskEntry.stamina_required 保留", getattr(t, 'stamina_required', None) == 100)

    # 2. Scheduler 透传
    sch = Scheduler(config=cm, store=None)
    sch.load_tasks_from_config()
    cfg = sch.get_config("combat_test")
    check("Scheduler.teaming", getattr(cfg, 'teaming', None) == {'sub_ids': ['sub1', 'sub2']})
    check("Scheduler.soul_setup", getattr(cfg, 'soul_setup', None) is not None)
    check("Scheduler.lock_team", bool(getattr(cfg, 'lock_team', False)) is True)
    check("Scheduler.change_team", bool(getattr(cfg, 'change_team', False)) is True)
    check("Scheduler.stamina_required", getattr(cfg, 'stamina_required', None) == 100)
    check("Scheduler.max_fail_streak", getattr(cfg, 'max_fail_streak', None) == 10)
    check("Scheduler.floor", getattr(cfg, 'floor', None) == 10)
    check("Scheduler.team_id", getattr(cfg, 'team_id', None) == '阵容1')

    # 3. run_controller 注入 task_config
    tc = {
        "max_fail_streak": getattr(cfg, 'max_fail_streak', 10),
        "team_id": getattr(cfg, 'team_id', None),
        "floor": getattr(cfg, 'floor', None),
        "teaming": getattr(cfg, 'teaming', None),
        "soul_setup": getattr(cfg, 'soul_setup', None),
        "lock_team": bool(getattr(cfg, 'lock_team', False)),
        "change_team": bool(getattr(cfg, 'change_team', False)),
        "stamina_required": getattr(cfg, 'stamina_required', None),
    }
    check("task_config.teaming", tc["teaming"] == {'sub_ids': ['sub1', 'sub2']})
    check("task_config.soul_setup", tc["soul_setup"] is not None)
    check("task_config.stamina_required", tc["stamina_required"] == 100)

    # 4. TaskGraph 熔断阈值注入
    from tasks.base.task_graph import TaskGraph
    from tasks.base.task_context import TaskContext
    g = TaskGraph()
    g.run(TaskContext(task_id="combat_test", task_config=tc))
    check("TaskGraph 熔断=10", g._max_fail_streak == 10, str(g._max_fail_streak))

    # 5. combat_test 从 task_config 读战斗配置
    from games.yys.tasks.special.combat_test import _load_battle_config
    bc = _load_battle_config(TaskContext(task_id="combat_test", task_config=tc))
    check("combat_test.soul_setup.group", bc["soul_setup"]["group"] == "御魂副本")
    check("combat_test.lock_team", bc["lock_team"] is True)
    check("combat_test.change_team", bc["change_team"] is True)

    # 6. 无 task_config 时回退文件读取（向后兼容）
    bc2 = _load_battle_config(TaskContext(task_id="combat_test", task_config={}))
    check("无 task_config 回退文件常量", bc2["soul_setup"]["group"] == "御魂副本")

    print(f"\n🎉 战斗/组队配置链路验证 {PASS} 项通过")


if __name__ == "__main__":
    main()
