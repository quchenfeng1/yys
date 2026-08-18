"""验证：识图触发任务 UI 退役（2026-08-16 改写）。

旧「触发模板信号名多选下拉」已下线（新体系 = 图内任务信号触发器节点）：

  ① 下拉不再提供 trigger 类型（新任务无法创建）
  ② 渲染旧 trigger 配置 → 无 MultiSelectCombo / 无 QLineEdit 触发控件
  ③ 保存兼容：旧 trigger_templates 不丢失
  ④ visual_bridge.signal_options 仍可用（信号管理面板/全局任务画布使用）
  ⑤ 旧后端解析（信号名→素材路径）代码保留（Executor.wait_signal 等使用）
"""
import os, sys, tempfile
from pathlib import Path

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PASS = 0


def check(label, cond, detail=""):
    global PASS
    assert cond, f"FAIL: {label}  {detail}"
    PASS += 1
    print(f"PASS {label}")


def main():
    # ═══ 0. 准备临时 assets + manifest（两个 scene 素材带信号） ═══
    tmp = Path(tempfile.mkdtemp(prefix="trig_retire_"))
    assets = tmp / "assets"
    scene = assets / "scene"
    scene.mkdir(parents=True, exist_ok=True)
    (scene / "主界面.png").write_bytes(b"fake")
    (scene / "活动入口.png").write_bytes(b"fake")

    from core.asset_meta import AssetMetaStore
    meta = AssetMetaStore(assets)
    meta.set_image_meta("scene/主界面.png", tags=["主界面"], signal="主界面")
    meta.set_image_meta("scene/活动入口.png", tags=["活动"], signal="活动入口")

    # ═══ 先建 QApplication（QWidget 前置条件） ═══
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from ui.panels.game_task_panel import GameTaskPanel

    detail = {
        "name": "image_trigger_test", "display_name": "识图触发测试",
        "task_type": "special", "uses_battle": False,
        "enabled": True,
        "repeat": {"type": "trigger", "value": 1,
                   "trigger_templates": ["主界面"]},
    }

    # ═══ ① 下拉不再提供 trigger 类型 ═══
    panel = GameTaskPanel(param_bridge=None)
    panel._render_form(dict(detail, repeat={"type": "daily"}))
    cb = panel._form_widgets["repeat_type"]
    check("① 下拉无 trigger 选项",
          cb.findData("trigger") < 0 and all(cb.itemData(i) != "trigger"
                                             for i in range(cb.count())),
          str([cb.itemData(i) for i in range(cb.count())]))

    # ═══ ② 渲染旧 trigger 配置 → 无触发信号控件 ═══
    panel._render_form(detail)
    check("② 无 trigger_templates 控件",
          "trigger_templates" not in panel._form_widgets,
          str(panel._form_widgets.keys()))
    check("② 旧配置回显已下线选项",
          panel._form_widgets["repeat_type"].currentData() == "trigger",
          str(panel._form_widgets["repeat_type"].currentData()))

    # ═══ ③ 保存兼容：旧 trigger_templates 不丢失 ═══
    config = panel._collect_config()
    check("③ 保存保留旧 trigger_templates",
          config["repeat"]["type"] == "trigger"
          and config["repeat"]["trigger_templates"] == ["主界面"],
          str(config["repeat"]))

    # ═══ ④ visual_bridge.signal_options 仍可用 ═══
    from visual.scene_store import SceneStore
    scenes_dir = tmp / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    store = SceneStore([scenes_dir])
    store.save({"id": "主界面", "name": "主界面", "signal": "主界面",
                "regions": [{"name": "红框1", "region": [0, 0, 1, 1],
                             "markers": [{"name": "蓝框A",
                                          "region": [0.1, 0.1, 0.2, 0.2],
                                          "templates": [{"template": "t.png",
                                                         "dx": 0, "dy": 0}]}]}]})
    from ui.param_bridge.visual_bridge import VisualBridge
    vb = VisualBridge(scene_store=store)
    vopts = vb.signal_options()
    check("④ signal_options 可用（信号面板/全局任务）",
          dict(vopts) == {"主界面": "主界面"}, str(vopts))

    # ═══ ⑤ 旧后端解析代码保留（信号名→素材路径） ═══
    signal_map = meta.all_signals()          # {素材识别名: 信号名}
    rel_by_signal = {v: k for k, v in signal_map.items()}
    tmpls = ["主界面", "活动入口"]
    resolved = [rel_by_signal.get(t, t) for t in tmpls]
    check("⑤ 信号名→素材路径解析保留",
          resolved == ["scene/主界面", "scene/活动入口"], str(resolved))

    print(f"\n🎉 识图触发 UI 退役验证 {PASS} 项通过")


if __name__ == "__main__":
    main()
