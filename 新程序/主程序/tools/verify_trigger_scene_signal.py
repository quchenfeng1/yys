"""验证：场景信号链路 + 特殊条件触发（trigger）退役（2026-08-16 改写）。

素材库重构：scene/ 素材 → SceneStore（scenes/{id}.json，signal 字段，
regions[].markers[].templates[] 为特征块 PNG 相对路径）。
旧信号源（assets manifest / AssetMetaStore）已不维护。

1. SceneStore.signal_map：场景 → {特征块模板相对路径(去扩展名): 信号}
2. visual_bridge.signal_options：信号下拉源 [(信号, 场景id)]（信号管理面板/全局任务用）
3. RunController.set_signal_map：1:N 反向映射（信号→多模板）
4. 退役：GameTaskPanel 下拉移除 trigger + 触发信号控件移除 + 旧配置兼容
"""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from visual.scene_store import SceneStore            # noqa: E402
from ui.param_bridge.visual_bridge import VisualBridge  # noqa: E402
from ui.panels.game_task_panel import GameTaskPanel  # noqa: E402
from core.run_controller import RunController        # noqa: E402

ok = 0
fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"✅ {name}")
    else:
        fail += 1
        print(f"❌ {name}  {detail}")


def _scene(sid, sig, tpls):
    return {"id": sid, "name": sid, "signal": sig,
            "regions": [{"name": "红框1", "region": [0, 0, 1, 1],
                         "markers": [{"name": "蓝框A", "region": [0.1, 0.1, 0.2, 0.2],
                                      "templates": [{"template": t, "dx": 0, "dy": 0}
                                                    for t in tpls]}]}]}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="trig_sig_"))
    scenes_dir = tmp / "scenes"
    store = SceneStore([scenes_dir])
    store.save(_scene("主界面", "主界面",
                      ["visual/t1/scenes/主界面_1_100.png",
                       "visual/t1/scenes/主界面_2_100.png"]))
    store.save(_scene("活动入口", "活动入口", ["visual/t2/scenes/act_1_100.png"]))

    # 1. SceneStore.signal_map：每个特征块模板 → 信号
    sm = store.signal_map()
    check("signal_map 含 3 个特征块映射",
          sm == {"visual/t1/scenes/主界面_1_100": "主界面",
                 "visual/t1/scenes/主界面_2_100": "主界面",
                 "visual/t2/scenes/act_1_100": "活动入口"}, str(sm))
    opts = store.signal_options()
    check("signal_options 去重 [(信号, 场景id)]",
          dict(opts) == {"主界面": "主界面", "活动入口": "活动入口"}, str(opts))
    print("  ✅ SceneStore 信号映射/选项（多特征块 1:N）")

    # 1.5 空信号 = 非触发素材：signal_map/signal_options 均排除
    store.save(_scene("普通背景", "", ["visual/t3/scenes/bg_1_100.png"]))
    sm2 = store.signal_map()
    check("空信号场景不纳入信号映射",
          "visual/t3/scenes/bg_1_100" not in sm2, str(sm2))
    opts2 = store.signal_options()
    check("空信号场景不在下拉选项",
          "普通背景" not in dict(opts2), str(opts2))
    print("  ✅ 空信号 = 非触发素材（信号映射/下拉排除）")

    # 2. visual_bridge.signal_options
    vb = VisualBridge(scene_store=store)
    vopts = vb.signal_options()
    check("visual_bridge.signal_options", dict(vopts) == {"主界面": "主界面",
                                                          "活动入口": "活动入口"},
          str(vopts))
    print("  ✅ visual_bridge 触发信号下拉源")

    # 3. RunController.set_signal_map 1:N + 触发模板展开
    rc = RunController.__new__(RunController)
    rc._executor = None
    rc._signal_map = {}
    rc._rel_by_signal = {}
    rc.set_signal_map(store.signal_map())
    check("反向映射 1:N（信号→多模板）",
          rc._rel_by_signal.get("主界面") == [
              "visual/t1/scenes/主界面_1_100",
              "visual/t1/scenes/主界面_2_100"],
          str(rc._rel_by_signal))

    class FakeWatcher:
        def __init__(self):
            self.started = None

        def start(self, template_tasks=None, templates=None):
            self.started = (template_tasks, templates)

    rc._trigger_watcher = FakeWatcher()
    cfg_a = SimpleNamespace(
        name="t1",
        repeat=SimpleNamespace(type="trigger",
                               trigger_templates=["主界面", "scene/旧路径"]))
    cfg_b = SimpleNamespace(name="t2", repeat=SimpleNamespace(type="daily"))
    # 多对多：t3 也绑定「主界面」信号（同一模板 → 多个任务）
    cfg_c = SimpleNamespace(
        name="t3",
        repeat=SimpleNamespace(type="trigger",
                               trigger_templates=["主界面", "活动入口"]))
    rc._scheduler = SimpleNamespace(get_all_tasks=lambda: [cfg_a, cfg_b, cfg_c])
    rc.start_trigger_watcher()
    idx, tpls = rc._trigger_watcher.started
    check("多对多索引：同一特征块模板关联多任务",
          idx.get("visual/t1/scenes/主界面_1_100") == ["t1", "t3"],
          str(idx))
    check("旧路径模板进索引",
          idx.get("scene/旧路径") == ["t1"], str(idx))
    check("多信号任务出现在多个模板下",
          idx.get("visual/t2/scenes/act_1_100") == ["t3"], str(idx))
    check("模板全局去重（主界面两个特征块 + act + 旧路径 = 4）",
          sorted(tpls) == sorted(["visual/t1/scenes/主界面_1_100",
                                  "visual/t1/scenes/主界面_2_100",
                                  "visual/t2/scenes/act_1_100",
                                  "scene/旧路径"]), str(tpls))
    task_names = {n for names in idx.values() for n in names}
    check("非 trigger 任务不监控", task_names == {"t1", "t3"}, str(task_names))
    print("  ✅ RunController 触发收集：多对多索引 + 模板去重 + 信号展开")

    # 3.5 TriggerWatcher._scan_once：一次 match_any → 多任务各发一次事件
    from core.trigger_watcher import TriggerWatcher
    events: list[dict] = {}

    class FakeRecognizer:
        def match_any(self, names):
            # 只命中「主界面」的一个特征块
            return [("visual/t1/scenes/主界面_1_100", object())]

    class FakeBus:
        def publish(self, event, **kw):
            events[kw.get("task_name")] = kw.get("templates")

    tw = TriggerWatcher(recognizer=FakeRecognizer(), event_bus=FakeBus())
    tw.start({"visual/t1/scenes/主界面_1_100": ["t1", "t3"],
              "visual/t2/scenes/act_1_100": ["t3"]},
             ["visual/t1/scenes/主界面_1_100",
              "visual/t2/scenes/act_1_100"])
    tw._scan_once()
    check("一次扫描激活全部关联任务（t1、t3）",
          set(events) == {"t1", "t3"}, str(events))
    check("事件携带命中模板",
          events.get("t1") == ["visual/t1/scenes/主界面_1_100"], str(events))
    tw.stop()
    print("  ✅ TriggerWatcher 单轮扫描：全局模板一次匹配 → 索引反查多任务")

    # 4. GameTaskPanel 退役（2026-08-16）：信号下拉源保留，
    #    触发信号多选控件已移除，旧 trigger 配置兼容渲染/保存
    vb2 = VisualBridge(scene_store=store)
    panel = GameTaskPanel(visual_bridge=vb2)
    opts2 = panel._get_signal_options()
    check("面板信号下拉源保留（供其它模块复用）",
          dict(opts2) == {"主界面": "场景:主界面", "活动入口": "场景:活动入口"},
          str(opts2))
    detail = {"name": "t", "display_name": "t", "task_type": "special",
              "uses_battle": False, "enabled": True,
              "repeat": {"type": "trigger", "value": 1,
                         "trigger_templates": ["主界面"]}}
    panel._render_form(detail)
    check("退役：触发信号多选控件已移除",
          "trigger_templates" not in panel._form_widgets,
          str(panel._form_widgets.keys()))
    cb = panel._form_widgets["repeat_type"]
    check("退役：旧 trigger 配置回显已下线选项", cb.currentData() == "trigger",
          str(cb.currentData()))
    config = panel._collect_config()
    check("兼容：保存不丢旧 trigger_templates",
          config["repeat"]["type"] == "trigger"
          and config["repeat"]["trigger_templates"] == ["主界面"],
          str(config["repeat"]))
    print("  ✅ 面板退役：下拉移除 trigger + 触发信号控件移除 + 旧配置兼容")

    print(f"\n🎉 场景信号链路 + trigger 退役验证 {ok}/{ok + fail} 通过")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
