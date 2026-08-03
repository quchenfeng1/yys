"""任务模板生成器验证：四种任务类型模板 + tasks.yaml 调度条目自动写入。"""
import sys, os, tempfile
from pathlib import Path

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)


def _compile_ok(code: str, name: str) -> bool:
    try:
        compile(code, f"{name}.py", "exec")
        return True
    except SyntaxError as e:
        print(f"  ⚠️ 语法错误 {name}: {e}")
        return False


def main():
    print("── [A] core/task_template.generate 四种类型 ──")
    from core.task_template import generate, build_yaml_entry, TASK_TYPES

    samples = {
        "event_task": ("my_event", "我的非战斗", "daily"),
        "battle": ("my_battle", "我的战斗", "special"),
        "generic": ("my_generic", "我的通用", "common"),
        "trigger": ("my_trigger", "我的触发", "special"),
    }
    for ttype, (name, display, cat) in samples.items():
        code = generate(ttype, name, display, cat)
        assert _compile_ok(code, name), f"{ttype} 模板语法错误"
        # 关键内容检查
        if ttype == "battle":
            assert "uses_battle = True" in code and "_load_battle_config" in code, "战斗模板应含战斗配置"
        elif ttype == "generic":
            assert "is_generic = True" in code and "params" in code, "通用模板应含 params"
        elif ttype == "trigger":
            assert "trigger" in code.lower(), "触发模板应含 trigger 说明"
        else:
            assert "uses_battle = False" in code, "非战斗模板 uses_battle 应为 False"
    print("① PASS 四种类型模板生成 + 语法编译通过")

    # build_yaml_entry
    e_battle = build_yaml_entry("battle", "my_battle", "我的战斗", "special")
    assert e_battle["repeat"]["type"] == "daily"
    assert e_battle.get("soul_setup") and e_battle.get("lock_team") is True
    e_trigger = build_yaml_entry("trigger", "my_trigger", "我的触发", "special")
    assert e_trigger["repeat"]["type"] == "trigger"
    assert e_trigger["time_start"] is None and e_trigger["time_end"] is None
    e_event = build_yaml_entry("event_task", "my_event", "我的非战斗", "daily")
    assert e_event["repeat"]["type"] == "daily" and e_event.get("soul_setup") is None
    assert build_yaml_entry("generic", "x", "y", "common") is None
    print("② PASS build_yaml_entry 正确（battle 含作战配置 / trigger 无时段 / generic 为 None）")

    print("\n── [B] TaskManager.new_task 实际创建 + tasks.yaml 写入 ──")
    from core.task_manager import TaskManager
    tmp = Path(tempfile.mkdtemp(prefix="task_tmpl_"))
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "tasks.yaml").write_text("tasks:\n", encoding="utf-8")
    mgr = TaskManager(tasks_dir=tmp / "tasks", assets_dir=tmp / "assets")

    # 战斗任务 → special/，tasks.yaml 追加调度 + 作战配置
    p1 = mgr.new_task("special", "new_battle", "新战斗", task_type="battle")
    assert (tmp / "tasks" / "special" / "new_battle.py").exists(), "战斗任务应创建在 special/"
    assert _compile_ok(Path(p1).read_text(encoding="utf-8"), "new_battle")

    # 非战斗任务 → daily/，tasks.yaml 追加 daily 调度
    p2 = mgr.new_task("daily", "new_event", "新非战斗", task_type="event_task")
    assert (tmp / "tasks" / "daily" / "new_event.py").exists()

    # 通用任务 → common/，不写 tasks.yaml
    p3 = mgr.new_task("common", "new_generic", "新通用", task_type="generic")
    assert (tmp / "tasks" / "common" / "new_generic.py").exists(), "通用任务应创建在 common/"
    assert "is_generic = True" in Path(p3).read_text(encoding="utf-8")

    # 触发任务 → special/，tasks.yaml 追加 trigger 规则
    p4 = mgr.new_task("special", "new_trigger", "新触发", task_type="trigger")
    assert (tmp / "tasks" / "special" / "new_trigger.py").exists()

    import yaml
    data = yaml.safe_load((tmp / "config" / "tasks.yaml").read_text(encoding="utf-8"))
    tasks = data["tasks"]
    names = [t["name"] for t in tasks]
    assert "new_battle" in names and "new_event" in names and "new_trigger" in names
    assert "new_generic" not in names, "通用任务不应写入 tasks.yaml"
    battle_entry = next(t for t in tasks if t["name"] == "new_battle")
    assert battle_entry["repeat"]["type"] == "daily" and "soul_setup" in battle_entry
    trigger_entry = next(t for t in tasks if t["name"] == "new_trigger")
    assert trigger_entry["repeat"]["type"] == "trigger"
    print("③ PASS new_task 四类任务创建正确（generic 在 common/ 且不入 yaml，battle/trigger 调度正确）")

    # 再次创建同名 → 抛错 + yaml 不重复
    try:
        mgr.new_task("daily", "new_event", "重复", task_type="event_task")
        raise AssertionError("同名任务应抛 FileExistsError")
    except FileExistsError:
        pass
    data2 = yaml.safe_load((tmp / "config" / "tasks.yaml").read_text(encoding="utf-8"))
    assert sum(1 for t in data2["tasks"] if t["name"] == "new_event") == 1, "yaml 不应重复"
    print("④ PASS 同名任务拒绝创建 + tasks.yaml 不重复追加")

    print("\n🎉 任务模板生成器验证 4/4 通过")


if __name__ == "__main__":
    main()
