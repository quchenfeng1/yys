"""
内联配置面板（v2.5 — 替代弹窗）

脚本配置子菜单全部在中间面板内联显示，不弹对话框。
已实现：模拟器连接 / 防封号参数 / 日志配置
未实现：显示"功能尚未实现"占位
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QCheckBox,
    QFileDialog, QFormLayout, QScrollArea,
)

EMULATOR_TYPES = {"ldplayer":"雷电模拟器","mumu":"MuMu模拟器","nox":"夜神模拟器"}
EMULATOR_DEFAULT_PORTS = {"ldplayer":5555,"mumu":16384,"nox":62001}

STYLE_SAVE = """
    QPushButton { background: #1A73E8; color: white; font-weight: bold;
    border: none; border-radius: 6px; padding: 8px 20px; }
    QPushButton:hover { background: #1557B0; }
"""
STYLE_BOX = """
    QGroupBox { font-weight: bold; color: #1A1A2E; border: 1px solid #E8ECF0;
    border-radius: 8px; margin-top: 12px; padding: 16px 12px 12px 12px; }
    QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
"""


class ConfigPanel(QWidget):
    """脚本配置面板 — 根据 key 显示对应的内联配置。"""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self._current = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        self._title = QLabel("脚本配置")
        self._title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        self._title.setStyleSheet("color: #1A1A2E; padding: 4px 0;")
        layout.addWidget(self._title)

        # 滚动区域承载内容
        self._stack = QWidget()
        self._stack_layout = QVBoxLayout(self._stack)
        self._stack_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._stack)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        layout.addWidget(scroll, stretch=1)

    def show_config(self, key: str):
        """切换到指定配置面板。"""
        self._clear_stack()
        section = key.replace("config:", "")
        labels = {"emulator":"📡 模拟器连接","account":"👤 账号管理","priority":"📊 任务优先级",
                  "anti_detect":"🛡 防封号参数","runtime":"⏱ 运行时段","teams":"👥 阵容预设","log":"📝 日志配置"}
        self._title.setText(labels.get(section, "脚本配置"))

        if section == "emulator":
            self._current = EmulatorConfigWidget(self._config)
        elif section == "anti_detect":
            self._current = AntiDetectConfigWidget(self._config)
        elif section == "log":
            self._current = LogConfigWidget(self._config)
        else:
            self._current = self._placeholder(labels.get(section, section))
        self._stack_layout.addWidget(self._current)

    def _placeholder(self, name: str) -> QLabel:
        lbl = QLabel(f"「{name}」功能尚未实现")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color:#9CA3AF;font-size:16px;padding:60px;")
        return lbl

    def _clear_stack(self):
        while self._stack_layout.count():
            w = self._stack_layout.takeAt(0).widget()
            if w: w.deleteLater()


# ===== 模拟器连接面板 =====

class EmulatorConfigWidget(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._cfg = config; self._build(); self._load()

    def _build(self):
        ly = QVBoxLayout(self); ly.setSpacing(12)
        title = QLabel("模拟器连接设置"); title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        title.setStyleSheet("color:#1A1A2E;"); ly.addWidget(title)

        form = QFormLayout(); form.setSpacing(10)
        self._emu = QComboBox()
        for k,v in EMULATOR_TYPES.items(): self._emu.addItem(v,k)
        self._emu.currentIndexChanged.connect(lambda:self._port.setValue(EMULATOR_DEFAULT_PORTS.get(self._emu.currentData(),5555)))
        form.addRow("模拟器类型:", self._emu)
        self._port = QSpinBox(); self._port.setRange(1,65535); form.addRow("ADB 端口:", self._port)

        self._adb = QLineEdit(); self._adb.setPlaceholderText("留空自动检测"); ly.addWidget(self._row("ADB 路径:", self._adb, "浏览...", self._browse_adb))
        self._emu_path = QLineEdit(); self._emu_path.setPlaceholderText("留空自动检测"); ly.addWidget(self._row("模拟器路径:", self._emu_path, "浏览...", self._browse_emu))

        self._auto = QCheckBox("模拟器未运行时自动启动"); self._auto.setChecked(True); form.addRow("", self._auto)
        ly.addLayout(form)

        save = QPushButton("💾 保存配置"); save.setStyleSheet(STYLE_SAVE); save.clicked.connect(self._save)
        ly.addWidget(save); ly.addStretch()

    def _row(self, label, edit, btn_text, callback):
        w = QWidget(); r = QHBoxLayout(w); r.setContentsMargins(0,0,0,0)
        r.addWidget(QLabel(label)); r.addWidget(edit); b=QPushButton(btn_text); b.clicked.connect(callback); r.addWidget(b)
        return w

    def _browse_adb(self):
        p,_=QFileDialog.getOpenFileName(self,"选择 adb.exe","","可执行文件 (*.exe)"); p and self._adb.setText(p)
    def _browse_emu(self):
        p,_=QFileDialog.getOpenFileName(self,"选择模拟器程序","","可执行文件 (*.exe)"); p and self._emu_path.setText(p)

    def _load(self):
        t = self._cfg.get("emulator.type","mumu"); idx=self._emu.findData(t); idx>=0 and self._emu.setCurrentIndex(idx)
        self._port.setValue(self._cfg.get("adb.port",16384)); self._adb.setText(self._cfg.get("adb.path",""))
        self._emu_path.setText(self._cfg.get("emulator.path","")); self._auto.setChecked(self._cfg.get("emulator.auto_launch",True))

    def _save(self):
        self._cfg.set("emulator.type",self._emu.currentData()); self._cfg.set("adb.port",self._port.value())
        self._cfg.set("adb.device_id",f"127.0.0.1:{self._port.value()}")
        p=self._adb.text().strip(); p and self._cfg.set("adb.path",p)
        self._cfg.set("emulator.path",self._emu_path.text().strip())
        self._cfg.set("emulator.auto_launch",self._auto.isChecked()); self._cfg.save_global()


# ===== 防封号参数面板 =====

class AntiDetectConfigWidget(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._cfg = config; self._build(); self._load()

    def _build(self):
        ly = QVBoxLayout(self); ly.setSpacing(12)
        title = QLabel("防封号参数设置"); title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        title.setStyleSheet("color:#1A1A2E;"); ly.addWidget(title)

        form = QFormLayout(); form.setSpacing(10)
        self._off = QSpinBox(); self._off.setRange(0,50); form.addRow("点击偏移半径 (px):", self._off)
        self._dly = QDoubleSpinBox(); self._dly.setRange(0,3); self._dly.setSingleStep(0.1); form.addRow("延迟抖动系数:", self._dly)
        self._intv = QDoubleSpinBox(); self._intv.setRange(0,5); self._intv.setSingleStep(0.1); form.addRow("最小操作间隔 (s):", self._intv)
        self._pse = QDoubleSpinBox(); self._pse.setRange(0,1); self._pse.setSingleStep(0.01); form.addRow("走神概率:", self._pse)
        self._run = QSpinBox(); self._run.setRange(1,24); form.addRow("每日运行上限 (h):", self._run)
        self._act = QSpinBox(); self._act.setRange(100,100000); self._act.setSingleStep(100); form.addRow("每日操作上限 (次):", self._act)
        ly.addLayout(form)

        save = QPushButton("💾 保存配置"); save.setStyleSheet(STYLE_SAVE); save.clicked.connect(self._save)
        ly.addWidget(save); ly.addStretch()

    def _load(self):
        self._off.setValue(self._cfg.get("anti_detect.click_offset_radius",12))
        self._dly.setValue(self._cfg.get("anti_detect.delay_jitter",0.6))
        self._intv.setValue(self._cfg.get("anti_detect.min_interval",0.8))
        self._pse.setValue(self._cfg.get("anti_detect.long_pause_prob",0.05))
        self._run.setValue(self._cfg.get("anti_detect.max_daily_runtime",8))
        self._act.setValue(self._cfg.get("anti_detect.max_daily_actions",2000))

    def _save(self):
        self._cfg.set("anti_detect.click_offset_radius",self._off.value())
        self._cfg.set("anti_detect.delay_jitter",self._dly.value())
        self._cfg.set("anti_detect.min_interval",self._intv.value())
        self._cfg.set("anti_detect.long_pause_prob",self._pse.value())
        self._cfg.set("anti_detect.max_daily_runtime",self._run.value())
        self._cfg.set("anti_detect.max_daily_actions",self._act.value())
        self._cfg.save_global()


# ===== 日志配置面板 =====

class LogConfigWidget(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._cfg = config; self._build(); self._load()

    def _build(self):
        ly = QVBoxLayout(self); ly.setSpacing(12)
        title = QLabel("日志与截图设置"); title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        title.setStyleSheet("color:#1A1A2E;"); ly.addWidget(title)

        form = QFormLayout(); form.setSpacing(10)
        self._lvl = QComboBox(); self._lvl.addItems(["DEBUG","INFO","WARNING","ERROR"]); form.addRow("日志级别:", self._lvl)
        self._ss = QCheckBox("异常时自动截图"); form.addRow("", self._ss)
        ly.addLayout(form)

        save = QPushButton("💾 保存配置"); save.setStyleSheet(STYLE_SAVE); save.clicked.connect(self._save)
        ly.addWidget(save); ly.addStretch()

    def _load(self):
        idx=self._lvl.findText(self._cfg.get("run.log_level","INFO")); idx>=0 and self._lvl.setCurrentIndex(idx)
        self._ss.setChecked(self._cfg.get("run.screenshot_on_error",True))

    def _save(self):
        self._cfg.set("run.log_level",self._lvl.currentText())
        self._cfg.set("run.screenshot_on_error",self._ss.isChecked()); self._cfg.save_global()
