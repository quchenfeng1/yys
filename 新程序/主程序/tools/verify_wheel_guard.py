"""输入框滚轮防护验证：数值/下拉不被滚轮改值，列表滚动不受影响。"""
import sys, os
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt5.QtCore import QPoint, QPointF, Qt, QEvent
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtWidgets import (QApplication, QSpinBox, QDoubleSpinBox, QComboBox,
                             QListWidget, QLineEdit)


def _wheel():
    return QWheelEvent(QPointF(10, 10), QPointF(10, 10),
                       QPoint(0, 0), QPoint(0, 120),
                       Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)


def main():
    app = QApplication(sys.argv)
    from ui.theme import disable_wheel_on_inputs
    disable_wheel_on_inputs(app)

    def _send(obj):
        """走 notify（真实滚轮路径，经过应用级事件过滤器）"""
        return app.notify(obj, _wheel())

    # ① QSpinBox 滚轮不改值
    sp = QSpinBox(); sp.setRange(0, 100); sp.setValue(42)
    _send(sp)
    assert sp.value() == 42, f"SpinBox 被滚轮改值: {sp.value()}"
    print("① PASS QSpinBox 滚轮不改值")

    # ② QDoubleSpinBox 滚轮不改值
    dsp = QDoubleSpinBox(); dsp.setRange(0, 100); dsp.setValue(12.5)
    _send(dsp)
    assert dsp.value() == 12.5, f"DoubleSpinBox 被改: {dsp.value()}"
    print("② PASS QDoubleSpinBox 滚轮不改值")

    # ③ QComboBox 滚轮不切换选项
    cb = QComboBox(); cb.addItems(["A", "B", "C"]); cb.setCurrentIndex(0)
    _send(cb)
    assert cb.currentIndex() == 0, f"ComboBox 被滚轮切换: {cb.currentIndex()}"
    print("③ PASS QComboBox 滚轮不切换选项")

    # ④ 列表/文本框滚轮不被拦截（不影响滚动）
    lw = QListWidget(); lw.addItems(["x", "y", "z"])
    le = QLineEdit("文本")
    guard = __import__("ui.theme", fromlist=["_WheelGuard"])._WheelGuard(app)
    assert guard.eventFilter(lw, _wheel()) is False, "列表滚轮不应被吞"
    assert guard.eventFilter(le, _wheel()) is False, "文本框滚轮不应被吞"
    print("④ PASS 列表/文本框滚轮正常（不误伤滚动）")

    print("\n🎉 输入框滚轮防护验证 4/4 通过")


if __name__ == "__main__":
    main()
