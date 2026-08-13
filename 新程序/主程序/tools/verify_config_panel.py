"""验证：ConfigPanel 全局配置面板（子代理审计缺口 #2）。

链路：ConfigPanel.load_values → ConfigBridge.get → ConfigManager（读回显）
  → 用户改值 → save() → ConfigBridge.set("global.key", v) 逐字段原子写盘

覆盖：
  A. 字段注册完整（5 组 30+ 字段全部登记）
  B. load_values 回显（bridge 返回的值填充到控件）
  C. save() 逐字段 set（line/int/float/bool/choice 各类型取值的正确性）
  D. 保存状态反馈（成功/未连接）
  E. device.mock 提示需重启
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
    expect_sections = ["device.adb.host", "device.adb.port", "device.screenshot.method",
                       "device.mock", "image.template_threshold", "image.match_method",
                       "anti_detect.enabled", "anti_detect.min_interval",
                       "schedule.enabled", "schedule.timezone",
                       "log.level", "log.dir", "log.rotation"]
    check("A1 核心字段已注册", all(k in keys for k in expect_sections),
          f"缺 {[k for k in expect_sections if k not in keys]}")
    check("A2 字段数 >= 30", len(keys) >= 30, str(len(keys)))

    # ═══ B. load_values 回显 ═══
    print("\n[B] load_values 回显")
    bridge2 = FakeConfigBridge({
        "global.device.adb.host": "192.168.1.10",
        "global.device.adb.port": 5555,
        "global.device.mock": True,
        "global.image.template_threshold": 0.75,
        "global.image.match_method": "cv2.TM_CCORR_NORMED",
        "global.schedule.enabled": True,
        "global.log.level": "DEBUG",
        "global.anti_detect.min_interval": 2.5,
    })
    panel2 = ConfigPanel(param_bridge=SimpleNamespace(config=bridge2))
    # 逐个类型抽查回显
    def widget_of(key):
        for k, w, d in panel2._fields:
            if k == key:
                return w, d
        return None, None

    w, d = widget_of("device.adb.host")
    check("B1 line 回显", w is not None and w.text() == "192.168.1.10", str(w.text() if w else None))
    w, d = widget_of("device.adb.port")
    check("B2 int 回显", w.value() == 5555, str(w.value() if w else None))
    w, d = widget_of("device.mock")
    check("B3 bool 回显", w.isChecked() is True, str(w.isChecked() if w else None))
    w, d = widget_of("image.template_threshold")
    check("B4 float 回显", abs(w.value() - 0.75) < 0.001, str(w.value() if w else None))
    w, d = widget_of("image.match_method")
    check("B5 choice 回显", w.currentData() == "cv2.TM_CCORR_NORMED",
          str(w.currentData() if w else None))
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
    check("C2 保存内容含修改值", ("global.device.adb.host", "192.168.1.10")
          in panel2._bridge.sets, str(panel2._bridge.sets[:3]))
    # bool 类型取值正确
    check("C3 bool 保存为 True", ("global.device.mock", True) in panel2._bridge.sets,
          str([s for s in panel2._bridge.sets if "mock" in s[0]]))
    check("C4 choice 保存 data", ("global.image.match_method", "cv2.TM_CCORR_NORMED")
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
    bridge4 = FakeConfigBridge({"global.device.adb.port": 5037})
    panel4 = ConfigPanel(param_bridge=SimpleNamespace(config=bridge4))
    for k, w, d in panel4._fields:
        if k == "device.adb.port":
            w.setValue(5038)
            break
    panel4.save()
    check("E1 改端口 → 保存新值", ("global.device.adb.port", 5038) in bridge4.sets,
          str(bridge4.sets))

    print(f"\n🎉 ConfigPanel 全局配置面板验证 {PASS} 项通过"
          + ("" if FAIL == 0 else f"，失败 {FAIL} 项"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
