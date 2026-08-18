# -*- coding: utf-8 -*-
"""
信号体系 UI 三件套冒烟测试（2026-08-16）：
- SignalManagerPanel：三 Tab 表格 + 自定义信号增删
- AnomalyTasksPanel：异常任务列表 + 处理跳转信号
- VisualBuilderPanel：全局任务 Tab + open_task_and_select 红框定位
- menu_tree / ui_settings：菜单与显隐项接线
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication, QLabel, QTableWidget, QPushButton, QMessageBox  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)
# offscreen 环境下 QMessageBox 静态弹窗可能崩溃，测试中替换为无操作
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)


class FakeStore:
    def save(self, task):
        self.saved = task
        return True


class FakeBridge:
    def __init__(self):
        self._store = FakeStore()
        self.current_game = "yys"
        self._assets_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "_tmp_assets")
        os.makedirs(self._assets_dir, exist_ok=True)
        self._saved_global = None

    def get_ocr(self):
        return None

    def capture_screen(self):
        return None

    def icon_items(self, game_id=None):
        return ["btn_ok", "btn_battle"]

    def scene_list(self):
        return [{"id": "scene_courtyard", "name": "庭院"},
                {"id": "scene_battle", "name": "战斗"}]

    def ocr_items(self, game_id=None):
        return ["ocr_gold"]

    def signal_options(self):
        return [("sig_a", "信号A"), ("sig_b", "信号B")]

    def compound_list(self, game_id=None):
        return []

    def load_compound(self, name, game_id=None):
        return None

    def save_compound(self, node_def, game_id=None):
        pass

    def delete_compound(self, name, game_id=None):
        return True

    def global_task_load(self):
        return {}

    def global_task_save(self, task):
        self._saved_global = task
        return True

    def load_task(self, name):
        return {"name": name, "game": "yys", "kind": "task",
                "graph": {"nodes": [
                    {"id": "n1", "type": "scene_probe", "name": "场景判定",
                     "params": {}, "pos": [0, 0]}], "connections": []}}


def _find_buttons(widget):
    return widget.findChildren(QPushButton)


def main():
    checks = []
    print("STEP A", flush=True)

    # ── A. 信号管理面板 ──────────────────────────────
    from ui.panels.signal_manager_panel import SignalManagerPanel
    sp = SignalManagerPanel(
        scene_provider=lambda: [{"scene_id": "scene_a", "signal": "sig_a"}],
        trigger_provider=lambda: [{"task": "t1", "signal": "sig_t"}],
        task_provider=lambda: [{"task": "t1", "signal": "sig_x"}],
        custom_provider=lambda: ["custom_1"],
        add_custom_cb=lambda n: True,
        remove_custom_cb=lambda n: True,
    )
    sp.refresh()
    tables = sp.findChildren(QTableWidget)
    checks.append(("A1 三 Tab 表格", len(tables) == 3))
    checks.append(("A2 场景表格行数", tables[0].rowCount() == 1))
    checks.append(("A3 触发表格行数", tables[1].rowCount() == 1))
    checks.append(("A4 任务表格行数", tables[2].rowCount() == 1))
    checks.append(("A5 自定义列表", sp.list_custom.count() == 1))
    print("STEP B", flush=True)

    # ── B. 异常任务面板 ──────────────────────────────
    from ui.panels.anomaly_tasks_panel import AnomalyTasksPanel
    got = {}
    ap = AnomalyTasksPanel(
        abnormal_provider=lambda: ["t1"],
        list_provider=lambda t: [
            {"id": "a1", "time": "2026-08-16 12:00", "reason": "场景异常",
             "node_id": "n1", "signal": "sig_a", "handled": False},
        ],
        mark_handled_cb=lambda aid: True,
        confirm_fixed_cb=lambda t: True,
        unresolved_cb=lambda t: 0,
    )
    ap.handle_requested.connect(lambda t, n: got.update(task=t, node=n))
    ap.task_list.setCurrentRow(0)
    checks.append(("B1 履历行数", ap.table.rowCount() >= 1))
    # 点「处理」按钮（履历表第 0 行操作列）→ handle_requested 信号
    btn = ap.table.cellWidget(0, 5)
    if btn is not None:
        btn.click()
    checks.append(("B2 处理跳转信号", got.get("task") == "t1" and got.get("node") == "n1"))
    checks.append(("B3 确认修复按钮存在",
                   any("已修复" in b.text() for b in ap.findChildren(QPushButton))))
    print("STEP C", flush=True)

    # ── C. 可视化构建：全局任务 Tab + 跳转定位 ────────
    from ui.visual_builder.visual_builder_panel import VisualBuilderPanel
    fb = FakeBridge()
    vb = VisualBuilderPanel(fb)
    texts = [vb._right_tabs.tabText(i) for i in range(vb._right_tabs.count())]
    checks.append(("C1 全局任务 Tab", "全局任务" in texts))
    checks.append(("C2 Tab 总数=5", vb._right_tabs.count() == 5))
    # 保存全局任务
    vb._save_global_task()
    checks.append(("C3 全局任务保存", fb._saved_global is not None))
    # 异常跳转：打开任务并红框定位
    vb.open_task_and_select("t1", "n1")
    checks.append(("C4 跳转打开任务", vb._current_task.get("name") == "t1"))
    checks.append(("C5 异常节点高亮", vb._canvas._hl_node_id == "n1"))
    checks.append(("C6 编排 Tab 前置", vb._right_tabs.currentIndex() == 0))
    print("STEP D", flush=True)

    # ── D. 菜单与设置接线 ────────────────────────────
    from ui.panels.menu_tree import _MENU_ORDER, _MENU_LABEL, _MENU_ICON
    checks.append(("D1 菜单顺序含信号", "signals" in _MENU_ORDER))
    checks.append(("D2 菜单顺序含异常", "anomalies" in _MENU_ORDER))
    checks.append(("D3 菜单在设置前", _MENU_ORDER.index("signals") <
                   _MENU_ORDER.index("config")))
    checks.append(("D4 标签", _MENU_LABEL["signals"] == "信号管理"
                   and _MENU_LABEL["anomalies"] == "异常任务"))
    checks.append(("D5 图标", _MENU_ICON["signals"] and _MENU_ICON["anomalies"]))
    from ui.panels.ui_settings_panel import _PANEL_TOGGLE_ITEMS
    keys = [k for k, _, _ in _PANEL_TOGGLE_ITEMS]
    checks.append(("D6 设置显隐项", "signals" in keys and "anomalies" in keys))

    fails = [f"{name}: {v}" for name, v in checks if not v]
    print(f"TOTAL {len(checks)}/{len(checks) - len(fails)}")
    if fails:
        print("FAILS:")
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("🎉 信号体系 UI 三件套冒烟全部通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
