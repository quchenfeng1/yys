"""qt-material + qtawesome 集成验证（离屏截图）。"""
import sys, os
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt5.QtWidgets import QApplication, QWidget, QHBoxLayout, QVBoxLayout, \
    QPushButton, QComboBox, QCheckBox, QSpinBox, QGroupBox, QFormLayout, QLabel
from PyQt5.QtCore import Qt


def main():
    app = QApplication(sys.argv)

    # ① qt-material 主题
    from qt_material import apply_stylesheet
    apply_stylesheet(app, theme='light_blue.xml')
    print("① qt-material 主题应用成功")

    # ② qtawesome 图标
    import qtawesome as qta
    icon = qta.icon('fa5s.check-circle', color='#4a90d9')
    print("② qtawesome 图标生成成功:", not icon.isNull())

    # 组合 demo
    win = QWidget()
    win.setWindowTitle("Material 预览")
    win.resize(700, 480)
    lay = QVBoxLayout(win)
    lay.setContentsMargins(20, 20, 20, 20)

    gb = QGroupBox("Material 控件 Demo")
    form = QFormLayout(gb)
    cb = QComboBox(); cb.addItems(["选项A", "选项B", "选项C"])
    ch = QCheckBox("勾选状态"); ch.setChecked(True)
    sp = QSpinBox(); sp.setRange(0, 100); sp.setValue(42)
    btn = QPushButton("主按钮")
    btn.setIcon(qta.icon('fa5s.play', color='#ffffff'))
    form.addRow("下拉:", cb)
    form.addRow("复选:", ch)
    form.addRow("数值:", sp)
    form.addRow("按钮:", btn)
    lay.addWidget(gb)
    lay.addStretch()

    win.show()
    app.processEvents()
    out = os.path.join(_PROJ_ROOT, "ui_material_preview.png")
    win.grab().save(out)
    print(f"预览已保存: {out}")


if __name__ == "__main__":
    main()
