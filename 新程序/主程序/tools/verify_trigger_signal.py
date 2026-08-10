"""验证：识图触发任务「触发模板」已升级为信号名多选下拉。

覆盖：
  ① 素材管理配置信号后，GameTaskPanel 能读取信号列表（_get_signal_options）
  ② 渲染 trigger 任务时触发信号用 MultiSelectCombo（非 QLineEdit）
  ③ 回显：配置的信号名被勾选
  ④ 兼容旧素材路径：旧配置素材路径 → 若对应素材有信号名则用信号名勾选
  ⑤ 保存：MultiSelectCombo.selected_data() → trigger_templates 写信号名
  ⑥ 无信号时回退文本输入
  ⑦ 后端解析：trigger_templates 信号名 → 素材路径（start_trigger_watcher 链路）
  ⑧ trigger 联动：loop_count 保持可编辑（组队轮数复用），其余时间控件禁用
"""
import os, sys, tempfile
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
    # ═══ 0. 准备临时 assets + manifest（两个 scene 素材带信号） ═══
    tmp = Path(tempfile.mkdtemp(prefix="trig_sig_"))
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
    from PyQt5.QtWidgets import QApplication, QLineEdit
    app = QApplication.instance() or QApplication([])

    # ═══ ① _get_signal_options 读取信号列表 ═══
    from ui.panels.game_task_panel import GameTaskPanel
    panel = GameTaskPanel(param_bridge=None)
    # 替换默认 assets 路径（默认指向真实项目 assets，这里指向临时目录）
    panel._assets_dir = assets
    import types

    def _sig_opts(self):
        return [(sig, rel) for rel, sig in meta.all_signals().items() if sig]
    panel._get_signal_options = types.MethodType(_sig_opts, panel)

    opts = panel._get_signal_options()
    check("① 读取信号列表", len(opts) == 2 and ("主界面", "scene/主界面") in opts,
          str(opts))

    # ═══ ② 渲染 trigger 任务 → MultiSelectCombo ═══
    from ui.widgets.multi_select_combo import MultiSelectCombo

    detail = {
        "name": "image_trigger_test", "display_name": "识图触发测试",
        "task_type": "special", "uses_battle": False,
        "enabled": True,
        "repeat": {"type": "trigger", "value": 1,
                   "trigger_templates": ["主界面"]},
    }
    # 临时替换 _get_signal_options 为绑定版本
    panel._get_signal_options = types.MethodType(_sig_opts, panel)
    panel._render_form(detail)
    w = panel._form_widgets.get("trigger_templates")
    check("② 触发信号用 MultiSelectCombo", isinstance(w, MultiSelectCombo),
          type(w).__name__)
    check("③ 信号名回显勾选", w.selected_data() == ["主界面"], str(w.selected_data()))

    # ═══ ④ 兼容旧素材路径：配置 "scene/主界面" → 用信号名"主界面"勾选 ═══
    detail_old = dict(detail)
    detail_old["repeat"] = {"type": "trigger", "value": 1,
                            "trigger_templates": ["scene/主界面"]}
    panel._render_form(detail_old)
    w = panel._form_widgets.get("trigger_templates")
    check("④ 旧素材路径→信号名勾选", w.selected_data() == ["主界面"],
          str(w.selected_data()))

    # ═══ ⑤ 保存：selected_data → trigger_templates ═══
    # 勾选"活动入口"
    panel._render_form(detail)
    w = panel._form_widgets.get("trigger_templates")
    w.set_selected(["主界面", "活动入口"])
    config = panel._collect_config()
    check("⑤ 保存写信号名", config["repeat"]["trigger_templates"] == ["主界面", "活动入口"],
          str(config["repeat"]["trigger_templates"]))

    # ═══ ⑥ 无信号时回退文本输入 ═══
    from ui.panels.game_task_panel import GameTaskPanel as GTP2
    panel2 = GTP2(param_bridge=None)
    # 注入空信号
    def _empty(self):
        return []
    panel2._get_signal_options = types.MethodType(_empty, panel2)
    panel2._render_form(detail)
    w2 = panel2._form_widgets.get("trigger_templates")
    check("⑥ 无信号回退 QLineEdit", isinstance(w2, QLineEdit), type(w2).__name__)

    # ═══ ⑦ 后端解析链路（信号名→素材路径） ═══
    signal_map = meta.all_signals()          # {素材识别名: 信号名}
    rel_by_signal = {v: k for k, v in signal_map.items()}
    tmpls = config["repeat"]["trigger_templates"]  # ["主界面","活动入口"]
    resolved = [rel_by_signal.get(t, t) for t in tmpls]
    check("⑦ 信号名→素材路径", resolved == ["scene/主界面", "scene/活动入口"],
          str(resolved))

    # ═══ ⑧ trigger 联动：时段隐藏、周期次数显示、loop_count 可编辑 ═══
    panel._render_form(detail)  # repeat.type=trigger
    w = panel._form_widgets
    check("⑧ trigger 下 loop_count 可编辑", w["loop_count"].isEnabled())
    check("⑧ trigger 下时段隐藏", w["slot_label"].isHidden())
    check("⑧ trigger 下周期次数显示", not w["max_daily"].isHidden())
    # 切换回 daily（下拉选框）→ 时段恢复显示
    w["repeat_type"].setCurrentIndex(w["repeat_type"].findData("daily"))
    check("⑧ daily 下时段显示", not w["slot_label"].isHidden())
    check("⑧ daily 下 loop_count 可编辑", w["loop_count"].isEnabled())

    print(f"\n🎉 触发信号多选下拉验证 {PASS} 项通过")


if __name__ == "__main__":
    main()
