"""验证：ConfigPanel 全局配置面板（2026-08-16 精简后字段集）。

链路：ConfigPanel.load_values → ConfigBridge.get → ConfigManager（读回显）
  → 用户改值 → save() → ConfigBridge.set("global.key", v) 逐字段原子写盘

覆盖：
  A. 字段注册：核心字段在 / 已废弃字段（ADB地址、截屏、模拟器路径、
     匹配方法、行为画像、调度组）不在
  B. load_values 回显（line/int/float/bool/choice 各类型）
  C. save() 逐字段 set
  D. 保存状态反馈（成功/未连接）
  E. device.mock 提示需重启 + 修改后保存写回新值
"""
import os, sys
from pathlib import Path
from types import SimpleNamespace

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

PASS = 0
FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


class FakeConfigBridge:
    """记录 set 调用 + 提供 get 回显"""
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.sets = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.sets.append((key, value))
        self.values[key] = value


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from ui.panels.config_panel import ConfigPanel

    # ═══ A. 字段注册完整 ═══
    print("\n[A] 字段注册完整性")
    bridge = FakeConfigBridge()
    panel = ConfigPanel(param_bridge=SimpleNamespace(config=bridge))
    keys = [k for k, _, _ in panel._fields]
    expect_sections = ["device.mock", "image.template_threshold",
                       "image.ocr_enabled", "image.ocr_timeout",
                       "anti_detect.enabled", "anti_detect.min_interval",
                       "anti_detect.action_jitter", "anti_detect.random_fail_rate",
                       "log.level", "log.dir", "log.rotation"]
    check("A1 核心字段已注册", all(k in keys for k in expect_sections),
          f"缺 {[k for k in expect_sections if k not in keys]}")
    removed = ["device.adb.host", "device.adb.port", "device.adb.timeout",
               "device.screenshot.method", "device.screenshot.quality",
               "device.emulator_path", "device.emulator_name",
               "image.match_method", "anti_detect.mouse_simulation",
               "anti_detect.behavior_profile", "anti_detect.weekly_off_day",
               "schedule.enabled", "schedule.timezone", "schedule.crontab"]
    leaked = [k for k in removed if k in keys]
    check("A2 已废弃字段全部移除", not leaked, f"仍存在: {leaked}")
    check("A3 字段数合理", 8 <= len(keys) <= 20, str(len(keys)))

    # ═══ B. load_values 回显 ═══
    print("\n[B] load_values 回显")
    bridge2 = FakeConfigBridge({
        "global.device.mock": True,
        "global.image.template_threshold": 0.75,
        "global.image.ocr_timeout": 15,
        "global.image.ocr_use_gpu": True,
        "global.anti_detect.min_interval": 2.5,
        "global.log.level": "DEBUG",
        "global.log.dir": "mylogs",
    })
    panel2 = ConfigPanel(param_bridge=SimpleNamespace(config=bridge2))
    # 逐个类型抽查回显
    def widget_of(key):
        for k, w, d in panel2._fields:
            if k == key:
                return w, d
        return None, None

    w, d = widget_of("log.dir")
    check("B1 line 回显", w is not None and w.text() == "mylogs", str(w.text() if w else None))
    w, d = widget_of("image.ocr_timeout")
    check("B2 int 回显", w.value() == 15, str(w.value() if w else None))
    w, d = widget_of("device.mock")
    check("B3 bool 回显", w.isChecked() is True, str(w.isChecked() if w else None))
    w, d = widget_of("image.template_threshold")
    check("B4 float 回显", abs(w.value() - 0.75) < 0.001, str(w.value() if w else None))
    w, d = widget_of("image.ocr_use_gpu")
    check("B5 bool 回显2", w.isChecked() is True, str(w.isChecked() if w else None))
    w, d = widget_of("log.level")
    check("B6 choice 日志级别回显", w.currentData() == "DEBUG",
          str(w.currentData() if w else None))
    check("B7 加载状态", "已加载" in panel2._status_label.text(),
          panel2._status_label.text())

    # ═══ C. save() 逐字段 set ═══
    print("\n[C] save() 全量写回")
    panel2.save()
    saved_keys = [k for k, _ in panel2._bridge.sets]
    check("C1 全部字段 set 写回", len(panel2._bridge.sets) == len(panel2._fields),
          f"{len(panel2._bridge.sets)}/{len(panel2._fields)}")
    check("C2 保存内容含修改值", ("global.log.dir", "mylogs")
          in panel2._bridge.sets, str(panel2._bridge.sets[:3]))
    # bool 类型取值正确
    check("C3 bool 保存为 True", ("global.device.mock", True) in panel2._bridge.sets,
          str([s for s in panel2._bridge.sets if "mock" in s[0]]))
    check("C4 choice 保存 data", ("global.log.level", "DEBUG")
          in panel2._bridge.sets, "")
    check("C5 保存状态反馈含数量", "已保存" in panel2._status_label.text(),
          panel2._status_label.text())
    check("C6 device.mock=True → 提示需重启",
          "重启" in panel2._status_label.text(), panel2._status_label.text())

    # ═══ D. 未连接 → 状态提示 ═══
    print("\n[D] 未连接配置中心")
    panel3 = ConfigPanel(param_bridge=SimpleNamespace(config=None))
    panel3.save()
    check("D1 未连接 → 提示配置中心未连接",
          "未连接" in panel3._status_label.text(), panel3._status_label.text())

    # ═══ E. 修改后保存写回新值 ═══
    print("\n[E] 修改后保存")
    bridge4 = FakeConfigBridge({"global.log.rotation": "10 MB"})
    panel4 = ConfigPanel(param_bridge=SimpleNamespace(config=bridge4))
    for k, w, d in panel4._fields:
        if k == "log.rotation":
            w.setText("20 MB")
            break
    panel4.save()
    check("E1 改轮转 → 保存新值", ("global.log.rotation", "20 MB") in bridge4.sets,
          str(bridge4.sets))

    print(f"\n🎉 ConfigPanel 全局配置面板验证 {PASS} 项通过"
          + ("" if FAIL == 0 else f"，失败 {FAIL} 项"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
