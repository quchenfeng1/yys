"""验证：可视化任务 × 游戏任务整合（2026-08-16）。

覆盖：
1. 可视化任务保存 → tasks.yaml 注册调度条目（幂等，不覆盖已有配置）
2. TaskBridge.get_task_metas 合并可视化任务（task_type=visual_task）
3. get_task_detail 可视化任务补显示名/分类
4. 游戏任务面板：可视化任务渲染变量配置/常量展示 Tab（按组名分组）
5. 面板保存 → 变量配置写回可视化任务 param_values
6. 执行配置分组：时间调度 + 其他（无循环次数/战斗配置）
"""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from PyQt5.QtWidgets import QApplication, QTabWidget

app = QApplication(sys.argv)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.param_bridge.task_bridge import TaskBridge        # noqa: E402
from ui.param_bridge.visual_bridge import VisualBridge    # noqa: E402
from ui.panels.game_task_panel import GameTaskPanel       # noqa: E402
from visual.rule_store import VisualTaskStore             # noqa: E402


class FakeConfig:
    """记录 update_task 调用的假 ConfigManager"""

    def __init__(self, existing: dict | None = None):
        self._tasks: dict = dict(existing or {})
        self.updates: list = []

    def get_task_config(self, name):
        return self._tasks.get(name)

    def update_task(self, name, **kw):
        self.updates.append((name, dict(kw)))
        self._tasks.setdefault(name, {}).update(kw)


def _var_graph_task(name="视觉日常"):
    return {
        "name": name, "display_name": "视觉日常", "category": "daily",
        "param_values": {},
        "graph": {"nodes": [
            {"type": "start", "id": "s1"},
            {"type": "variable_group", "id": "v1", "params": {
                "group_name": "循环参数",
                "variables": [{"key": "loop_count", "label": "循环次数",
                               "type": "int", "default": 3}]}},
            {"type": "variable_group", "id": "v2", "params": {
                "group_name": "等待参数",
                "variables": [{"key": "wait_sec", "label": "等待秒数",
                               "type": "int", "default": 1}]}},
            {"type": "constant_group", "id": "c1", "params": {
                "group_name": "固定配置",
                "variables": [{"key": "team_id", "label": "阵容",
                               "type": "text", "value": "阵容1"}]}},
        ]},
    }


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="vis_task_"))

    # 1. 可视化任务保存 → tasks.yaml 注册条目（幂等）
    vstore = VisualTaskStore(tmp / "visual_tasks")
    cfg = FakeConfig()
    vb = VisualBridge(store=vstore, config=cfg)
    vb.save_task(_var_graph_task())
    assert cfg.updates and cfg.updates[0][0] == "视觉日常", cfg.updates
    assert cfg.updates[0][1].get("enabled") is True
    assert cfg.updates[0][1].get("category") == "daily"
    # 已存在 → 不再覆盖
    cfg2 = FakeConfig(existing={"视觉日常": {"enabled": False, "priority": 99}})
    vb2 = VisualBridge(store=vstore, config=cfg2)
    vb2.save_task(_var_graph_task())
    assert cfg2.updates == [], cfg2.updates
    assert cfg2.get_task_config("视觉日常")["priority"] == 99, \
        "已有配置不能被覆盖"
    print("  ✅ 可视化任务保存 → tasks.yaml 注册条目（幂等不覆盖）")

    # 2. TaskBridge.get_task_metas 合并可视化任务
    class FakeInst:
        task_id = "视觉日常"
        _definition = _var_graph_task()

    class FakeRegistry:
        def get_all(self):
            return [FakeInst()]

        def get(self, name):
            return FakeInst()

    tb = TaskBridge(registry=FakeRegistry(), file_manager=None, config=None)
    metas = tb.get_task_metas()
    vmeta = [m for m in metas if m["name"] == "视觉日常"]
    assert vmeta and vmeta[0]["task_type"] == "visual_task"
    assert vmeta[0]["is_visual"] is True
    assert vmeta[0]["display_name"] == "视觉日常"
    print("  ✅ get_task_metas 合并可视化任务（visual_task 标记）")

    # 3. get_task_detail 可视化任务补显示名/分类
    class FakeScheduler:
        def get_next_run_time(self, n):
            return None

    tb2 = TaskBridge(registry=FakeRegistry(), file_manager=None,
                     config=None, scheduler=FakeScheduler())
    detail = tb2.get_task_detail("视觉日常")
    assert detail.get("display_name") == "视觉日常", detail
    assert detail.get("is_visual") is True, detail
    assert detail.get("task_type") == "visual_task", detail
    print("  ✅ get_task_detail 可视化任务补显示名/is_visual")

    # 4/5/6. 游戏任务面板：变量配置/常量展示 + 保存写回
    saved_params: dict = {}
    vb3 = VisualBridge(store=VisualTaskStore(tmp / "visual_tasks"),
                       config=FakeConfig())

    def _fake_save(task):
        saved_params["param_values"] = task.get("param_values")

    vb3.save_task = _fake_save  # 截获写回
    vb3.get_task = lambda n: _var_graph_task(n)
    vb3.load_task = lambda n: _var_graph_task(n)

    panel = GameTaskPanel(param_bridge=SimpleNamespace(
        task=SimpleNamespace(
            get_task_detail=lambda n: {
                "name": "视觉日常", "display_name": "视觉日常",
                "task_type": "visual_task", "is_visual": True,
                "enabled": True, "repeat": {"type": "daily", "value": 1},
                "priority": 10, "time_start": "06:00", "time_end": "23:59",
                "next_run_time": "",
            },
            get_next_run_time=lambda n: "",
            get_cycle_progress=lambda n: (0, None),
            save_task_config=lambda n, c: None,
            reload_scheduler=lambda n=None: None,
            update_next_run=lambda n, dt: None,
        ),
        run=SimpleNamespace(reset_task_cycle=lambda n: None),
    ), visual_bridge=vb3)
    panel._render_form({
        "name": "视觉日常", "display_name": "视觉日常",
        "task_type": "visual_task", "is_visual": True,
        "enabled": True, "repeat": {"type": "daily", "value": 1},
        "priority": 10, "time_start": "06:00", "time_end": "23:59",
    })
    panel._current_name = "视觉日常"  # _save 依赖当前选中任务名
    # 执行配置无循环次数/战斗控件
    assert "loop_count" not in panel._form_widgets
    assert "soul_group" not in panel._form_widgets
    # 变量配置按组名分组：两个变量组 + 一个常量组
    assert set(panel._var_inputs) == {"loop_count", "wait_sec"}, \
        list(panel._var_inputs)
    assert panel._var_inputs["loop_count"].value() == 3  # 默认值
    panel._var_inputs["loop_count"].setValue(7)
    panel._var_inputs["wait_sec"].setValue(2)
    # 保存 → param_values 写回可视化任务
    panel._save()
    assert saved_params.get("param_values") == {"loop_count": 7, "wait_sec": 2}, \
        saved_params
    print("  ✅ 面板变量配置 Tab 分组渲染 + 保存写回 param_values")

    print("\n🎉 verify_visual_in_game_task 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
