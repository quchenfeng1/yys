"""
内联配置面板（v2.5 — 替代弹窗）

脚本配置子菜单全部在中间面板内联显示，不弹对话框。
已实现：模拟器连接 / 防封号参数 / 日志配置 / 识别参数 / 运行时段 / 配置导入导出
未实现：显示"功能尚未实现"占位
"""

import os
from PyQt5.QtCore import Qt, pyqtSignal, QTime
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QCheckBox,
    QFileDialog, QFormLayout, QScrollArea, QGroupBox, QTimeEdit,
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

        # 底部配置管理工具栏
        self._toolbar = ConfigToolbarWidget(self._config)
        layout.addWidget(self._toolbar)

    def show_config(self, key: str):
        """切换到指定配置面板。"""
        self._clear_stack()
        section = key.replace("config:", "")
        labels = {"emulator":"📡 模拟器连接","account":"👤 账号管理","priority":"📊 任务优先级",
                  "anti_detect":"🛡 防封号参数","runtime":"⏱ 运行时段","teams":"👥 阵容预设",
                  "log":"📝 日志配置","recognize":"🔍 识别参数"}
        self._title.setText(labels.get(section, "脚本配置"))

        if section == "emulator":
            self._current = EmulatorConfigWidget(self._config)
        elif section == "anti_detect":
            self._current = AntiDetectConfigWidget(self._config)
        elif section == "log":
            self._current = LogConfigWidget(self._config)
        elif section == "recognize":
            self._current = RecognizerConfigWidget(self._config)
        elif section == "runtime":
            self._current = RuntimeConfigWidget(self._config)
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

        # ── 心跳检测 ──
        form2 = QFormLayout(); form2.setSpacing(8)
        self._hb_interval = QSpinBox(); self._hb_interval.setRange(10, 300); self._hb_interval.setValue(30); self._hb_interval.setSuffix(" 秒")
        form2.addRow("心跳间隔:", self._hb_interval)
        ly.addLayout(form2)

        # ── App 配置 ──
        form3 = QFormLayout(); form3.setSpacing(8)
        self._app_pkg = QLineEdit(); self._app_pkg.setPlaceholderText("com.netease.onmyoji...")
        form3.addRow("App 包名:", self._app_pkg)
        self._app_act = QLineEdit(); self._app_act.setPlaceholderText("com.netease.onmyoji.Launcher")
        form3.addRow("启动 Activity:", self._app_act)
        ly.addLayout(form3)

        # ── 连接状态（只读）──
        self._status_label = QLabel("🔌 未测试"); self._status_label.setStyleSheet("color:#80868B;font-size:12px;")
        ly.addWidget(self._status_label)
        self._res_label = QLabel("📺 分辨率: —"); self._res_label.setStyleSheet("color:#80868B;font-size:12px;")
        ly.addWidget(self._res_label)
        self._quality_label = QLabel("📊 延迟: —"); self._quality_label.setStyleSheet("color:#80868B;font-size:12px;")
        ly.addWidget(self._quality_label)

        # ── 按钮行 ──
        btn_row = QHBoxLayout()
        test_btn = QPushButton("🔌 测试连接")
        test_btn.setStyleSheet("QPushButton{background:#34A853;color:white;font-weight:bold;border:none;border-radius:6px;padding:8px 16px;}QPushButton:hover{background:#2E7D32;}")
        test_btn.clicked.connect(self._test_connection)
        btn_row.addWidget(test_btn)
        reconnect_btn = QPushButton("🔄 重连")
        reconnect_btn.setStyleSheet("QPushButton{background:#F9AB00;color:white;font-weight:bold;border:none;border-radius:6px;padding:8px 16px;}QPushButton:hover{background:#E8A000;}")
        reconnect_btn.clicked.connect(self._reconnect)
        btn_row.addWidget(reconnect_btn)
        btn_row.addStretch()
        save = QPushButton("💾 保存配置"); save.setStyleSheet(STYLE_SAVE); save.clicked.connect(self._save)
        btn_row.addWidget(save)
        ly.addLayout(btn_row)
        ly.addStretch()

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
        self._hb_interval.setValue(self._cfg.get("emulator.heartbeat_interval",30))
        self._app_pkg.setText(self._cfg.get("app.package","com.netease.onmyoji.wyzymnqsd_cps"))
        self._app_act.setText(self._cfg.get("app.activity","com.netease.onmyoji.Launcher"))

    def _save(self):
        self._cfg.set("emulator.type",self._emu.currentData()); self._cfg.set("adb.port",self._port.value())
        self._cfg.set("adb.device_id",f"127.0.0.1:{self._port.value()}")
        p=self._adb.text().strip(); p and self._cfg.set("adb.path",p)
        self._cfg.set("emulator.path",self._emu_path.text().strip())
        self._cfg.set("emulator.auto_launch",self._auto.isChecked())
        self._cfg.set("emulator.heartbeat_interval",self._hb_interval.value())
        self._cfg.set("app.package",self._app_pkg.text().strip())
        self._cfg.set("app.activity",self._app_act.text().strip())
        if hasattr(self._cfg, 'save_global'):
            self._cfg.save_global()
        self._status_label.setText("💾 配置已保存"); self._status_label.setStyleSheet("color:#34A853;font-size:12px;")

    def _test_connection(self):
        """测试 ADB 连接并获取设备信息。"""
        try:
            from device.adb_client import ADBClient
            adb_path = self._adb.text().strip() or "adb"
            port = self._port.value()
            adb = ADBClient(device_id=f"127.0.0.1:{port}", adb_path=adb_path)
            if adb.is_connected():
                self._status_label.setText("🔌 已连接"); self._status_label.setStyleSheet("color:#34A853;font-size:12px;")
                w, h = adb.get_screen_size()
                self._res_label.setText(f"📺 分辨率: {w}×{h}")
                if {w, h} == {1280, 720}:
                    self._res_label.setStyleSheet("color:#34A853;font-size:12px;")
                else:
                    self._res_label.setStyleSheet("color:#F9AB00;font-size:12px;")
            else:
                self._status_label.setText("❌ 未连接"); self._status_label.setStyleSheet("color:#EA4335;font-size:12px;")
                self._res_label.setText("📺 分辨率: —")
        except Exception as e:
            self._status_label.setText(f"❌ 连接失败: {e}"); self._status_label.setStyleSheet("color:#EA4335;font-size:11px;")

    def _reconnect(self):
        """断开后重新连接。"""
        self._status_label.setText("🔄 重连中..."); self._status_label.setStyleSheet("color:#F9AB00;font-size:12px;")
        self._test_connection()


# ===== 防封号参数面板 =====

# 行为档案预设值
PROFILES = {
    "SAFE":   {"offset": 18, "jitter": 1.5, "interval": 1.2, "pause": 0.12, "runtime": 6,  "actions": 1500},
    "NORMAL": {"offset": 12, "jitter": 0.6, "interval": 0.8, "pause": 0.05, "runtime": 8,  "actions": 2000},
    "FAST":   {"offset": 8,  "jitter": 0.3, "interval": 0.4, "pause": 0.02, "runtime": 12, "actions": 4000},
    "DEBUG":  {"offset": 0,  "jitter": 0.0, "interval": 0.0, "pause": 0.00, "runtime": 24, "actions": 99999},
}

class AntiDetectConfigWidget(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._cfg = config; self._build(); self._load()

    def _build(self):
        ly = QVBoxLayout(self); ly.setSpacing(12)
        title = QLabel("防封号参数设置"); title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        title.setStyleSheet("color:#1A1A2E;"); ly.addWidget(title)

        # ── 行为档案预设 ──
        g0 = QGroupBox("行为档案预设")
        f0 = QFormLayout(g0); f0.setSpacing(8)
        self._profile = QComboBox()
        self._profile.addItems(["NORMAL (推荐)", "SAFE (最安全)", "FAST (快速)", "DEBUG (调试)"])
        self._profile.setCurrentIndex(0)
        self._profile.currentIndexChanged.connect(self._apply_profile)
        f0.addRow("档案:", self._profile)
        ly.addWidget(g0)

        # ── 点击 ──
        g1 = QGroupBox("点击安全")
        f1 = QFormLayout(g1); f1.setSpacing(8)
        self._off = QSpinBox(); self._off.setRange(0,50); self._off.setSuffix(" px")
        f1.addRow("偏移半径:", self._off)
        ly.addWidget(g1)

        # ── 间隔 ──
        g2 = QGroupBox("操作间隔")
        f2 = QFormLayout(g2); f2.setSpacing(8)
        self._dly = QDoubleSpinBox(); self._dly.setRange(0,3); self._dly.setSingleStep(0.1); self._dly.setSuffix(" s")
        f2.addRow("延迟抖动:", self._dly)
        self._intv = QDoubleSpinBox(); self._intv.setRange(0,5); self._intv.setSingleStep(0.1); self._intv.setSuffix(" s")
        f2.addRow("最小间隔:", self._intv)
        self._pse = QDoubleSpinBox(); self._pse.setRange(0,1); self._pse.setSingleStep(0.01)
        f2.addRow("走神概率:", self._pse)
        ly.addWidget(g2)

        # ── 运行限制 ──
        g3 = QGroupBox("运行限制")
        f3 = QFormLayout(g3); f3.setSpacing(8)
        self._run = QSpinBox(); self._run.setRange(1,24); self._run.setSuffix(" 小时")
        f3.addRow("每日时长上限:", self._run)
        self._act = QSpinBox(); self._act.setRange(100,100000); self._act.setSingleStep(100); self._act.setSuffix(" 次")
        f3.addRow("每日操作上限:", self._act)
        ly.addWidget(g3)

        # ── 运行状态（只读）──
        self._status_label = QLabel("📊 今日操作: —  |  运行时长: —")
        self._status_label.setStyleSheet("color:#5F6368;font-size:11px;padding:4px 0;")
        ly.addWidget(self._status_label)

        # ── 按钮 ──
        btn_row = QHBoxLayout()
        save = QPushButton("💾 保存配置"); save.setStyleSheet(STYLE_SAVE); save.clicked.connect(self._save)
        btn_row.addStretch(); btn_row.addWidget(save)
        ly.addLayout(btn_row); ly.addStretch()

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
        if hasattr(self._cfg, 'save_global'): self._cfg.save_global()

    def _apply_profile(self, idx):
        """一键应用行为档案预设值。"""
        names = ["NORMAL", "SAFE", "FAST", "DEBUG"]
        name = names[idx] if idx < len(names) else "NORMAL"
        p = PROFILES.get(name, PROFILES["NORMAL"])
        self._off.setValue(p["offset"])
        self._dly.setValue(p["jitter"])
        self._intv.setValue(p["interval"])
        self._pse.setValue(p["pause"])
        self._run.setValue(p["runtime"])
        self._act.setValue(p["actions"])


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
        self._cfg.set("run.screenshot_on_error",self._ss.isChecked())
        if hasattr(self._cfg, 'save_global'): self._cfg.save_global()


# ===== 图像识别参数面板 =====

class RecognizerConfigWidget(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._cfg = config; self._build(); self._load()

    def _build(self):
        ly = QVBoxLayout(self); ly.setSpacing(12)
        title = QLabel("图像识别设置"); title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        title.setStyleSheet("color:#1A1A2E;"); ly.addWidget(title)

        g1 = QGroupBox("模板匹配")
        f1 = QFormLayout(g1); f1.setSpacing(8)
        self._threshold = QDoubleSpinBox(); self._threshold.setRange(0.5, 1.0); self._threshold.setSingleStep(0.05)
        f1.addRow("默认阈值:", self._threshold)
        self._grayscale = QCheckBox("灰度匹配（推荐）"); self._grayscale.setChecked(True)
        f1.addRow("", self._grayscale)
        self._multiscale = QCheckBox("多尺度匹配（缩放偏差时启用）")
        f1.addRow("", self._multiscale)
        ly.addWidget(g1)

        g2 = QGroupBox("OCR 文字定位（预留）")
        f2 = QFormLayout(g2); f2.setSpacing(8)
        self._ocr_enabled = QCheckBox("启用 OCR")
        f2.addRow("", self._ocr_enabled)
        self._ocr_lang = QComboBox(); self._ocr_lang.addItems(["chi_sim", "eng"])
        f2.addRow("语言:", self._ocr_lang)
        ly.addWidget(g2)

        g3 = QGroupBox("识别缓存")
        f3 = QFormLayout(g3); f3.setSpacing(8)
        self._cache_ttl = QDoubleSpinBox(); self._cache_ttl.setRange(0.1, 10.0); self._cache_ttl.setSingleStep(0.1); self._cache_ttl.setSuffix(" 秒")
        f3.addRow("结果缓存:", self._cache_ttl)
        ly.addWidget(g3)

        btn_row = QHBoxLayout()
        self._reload_btn = QPushButton("重载素材")
        self._reload_btn.setStyleSheet("QPushButton{background:#F9AB00;color:white;font-weight:bold;border:none;border-radius:6px;padding:8px 16px;}QPushButton:hover{background:#E8A000;}")
        self._reload_btn.clicked.connect(self._reload_templates)
        btn_row.addWidget(self._reload_btn)
        btn_row.addStretch()
        save = QPushButton("保存配置"); save.setStyleSheet(STYLE_SAVE); save.clicked.connect(self._save)
        btn_row.addWidget(save)
        ly.addLayout(btn_row); ly.addStretch()

    def _load(self):
        self._threshold.setValue(self._cfg.get("recognize.threshold", 0.8))
        self._grayscale.setChecked(self._cfg.get("recognize.grayscale", True))
        self._multiscale.setChecked(self._cfg.get("recognize.multiscale", False))
        self._ocr_enabled.setChecked(self._cfg.get("recognize.ocr_enabled", False))
        idx = self._ocr_lang.findText(self._cfg.get("recognize.ocr_lang", "chi_sim"))
        if idx >= 0: self._ocr_lang.setCurrentIndex(idx)
        self._cache_ttl.setValue(self._cfg.get("recognize.cache_ttl", 1.0))

    def _save(self):
        self._cfg.set("recognize.threshold", self._threshold.value())
        self._cfg.set("recognize.grayscale", self._grayscale.isChecked())
        self._cfg.set("recognize.multiscale", self._multiscale.isChecked())
        self._cfg.set("recognize.ocr_enabled", self._ocr_enabled.isChecked())
        self._cfg.set("recognize.ocr_lang", self._ocr_lang.currentText())
        self._cfg.set("recognize.cache_ttl", self._cache_ttl.value())
        if hasattr(self._cfg, 'save_global'): self._cfg.save_global()

    def _reload_templates(self):
        try:
            from core.recognizer import Recognizer
            r = Recognizer(lambda: None)
            r.reload()
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, "素材重载", f"已重载 {len(r.list_templates())} 张素材")
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "重载失败", str(e))


class RuntimeConfigWidget(QWidget):
    """⏱ 运行时段配置 — 每日运行窗口 + 定时启停。"""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._cfg = config; self._build(); self._load()

    def _build(self):
        ly = QVBoxLayout(self); ly.setSpacing(12)
        title = QLabel("⏱ 运行时段设置"); title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        title.setStyleSheet("color:#1A1A2E;"); ly.addWidget(title)

        g1 = QGroupBox("每日运行窗口")
        f1 = QFormLayout(g1); f1.setSpacing(8)
        row_start = QHBoxLayout()
        self._win_start = QTimeEdit(); self._win_start.setDisplayFormat("HH:mm")
        row_start.addWidget(self._win_start)
        row_start.addWidget(QLabel("~"))
        self._win_end = QTimeEdit(); self._win_end.setDisplayFormat("HH:mm")
        row_start.addWidget(self._win_end)
        row_start.addStretch()
        f1.addRow("运行时段:", row_start)
        ly.addWidget(g1)

        g2 = QGroupBox("定时启停（如主窗口未运行时生效）")
        f2 = QFormLayout(g2); f2.setSpacing(8)
        self._sched_start = QCheckBox("定时启动脚本")
        f2.addRow("", self._sched_start)
        row_start2 = QHBoxLayout()
        self._start_time = QTimeEdit(); self._start_time.setDisplayFormat("HH:mm")
        row_start2.addWidget(QLabel("启动时间:"))
        row_start2.addWidget(self._start_time)
        row_start2.addStretch()
        f2.addRow("", row_start2)

        self._sched_stop = QCheckBox("定时停止脚本")
        f2.addRow("", self._sched_stop)
        row_stop = QHBoxLayout()
        self._stop_time = QTimeEdit(); self._stop_time.setDisplayFormat("HH:mm")
        row_stop.addWidget(QLabel("停止时间:"))
        row_stop.addWidget(self._stop_time)
        row_stop.addStretch()
        f2.addRow("", row_stop)
        ly.addWidget(g2)

        g3 = QGroupBox("超时与容错")
        f3 = QFormLayout(g3); f3.setSpacing(8)
        self._task_timeout = QSpinBox(); self._task_timeout.setRange(10, 3600); self._task_timeout.setSuffix(" 秒")
        f3.addRow("单任务超时:", self._task_timeout)
        self._max_restarts = QSpinBox(); self._max_restarts.setRange(0, 100); self._max_restarts.setSuffix(" 次/天")
        f3.addRow("最大重启次数:", self._max_restarts)
        ly.addWidget(g3)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save = QPushButton("保存配置"); save.setStyleSheet(STYLE_SAVE); save.clicked.connect(self._save)
        btn_row.addWidget(save)
        ly.addLayout(btn_row); ly.addStretch()

    def _load(self):
        self._win_start.setTime(QTime.fromString(
            self._cfg.get("global.run_window_start", "08:00"), "HH:mm"))
        self._win_end.setTime(QTime.fromString(
            self._cfg.get("global.run_window_end", "23:00"), "HH:mm"))
        self._sched_start.setChecked(
            self._cfg.get("global.scheduled_start_enabled", False))
        self._start_time.setTime(QTime.fromString(
            self._cfg.get("global.scheduled_start_time", "06:00"), "HH:mm"))
        self._sched_stop.setChecked(
            self._cfg.get("global.scheduled_stop_enabled", False))
        self._stop_time.setTime(QTime.fromString(
            self._cfg.get("global.scheduled_stop_time", "23:00"), "HH:mm"))
        self._task_timeout.setValue(
            self._cfg.get("global.task_timeout", 300))
        self._max_restarts.setValue(
            self._cfg.get("global.max_restarts_per_day", 10))

    def _save(self):
        self._cfg.set("global.run_window_start",
                      self._win_start.time().toString("HH:mm"))
        self._cfg.set("global.run_window_end",
                      self._win_end.time().toString("HH:mm"))
        self._cfg.set("global.scheduled_start_enabled",
                      self._sched_start.isChecked())
        self._cfg.set("global.scheduled_start_time",
                      self._start_time.time().toString("HH:mm"))
        self._cfg.set("global.scheduled_stop_enabled",
                      self._sched_stop.isChecked())
        self._cfg.set("global.scheduled_stop_time",
                      self._stop_time.time().toString("HH:mm"))
        self._cfg.set("global.task_timeout", self._task_timeout.value())
        self._cfg.set("global.max_restarts_per_day", self._max_restarts.value())
        if hasattr(self._cfg, 'save_global'): self._cfg.save_global()


class ConfigToolbarWidget(QWidget):
    """配置管理工具栏 — 导入/导出/热重载/校验。"""

    exported = pyqtSignal(str)
    imported = pyqtSignal(str)
    validated = pyqtSignal(list)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._cfg = config; self._build()

    def _build(self):
        ly = QHBoxLayout(self); ly.setContentsMargins(0, 4, 0, 4); ly.setSpacing(8)

        self._export_btn = QPushButton("📥 导出配置")
        self._export_btn.setStyleSheet(STYLE_SAVE)
        self._export_btn.clicked.connect(self._export)
        ly.addWidget(self._export_btn)

        self._import_btn = QPushButton("📤 导入配置")
        self._import_btn.setStyleSheet(STYLE_SAVE)
        self._import_btn.clicked.connect(self._import)
        ly.addWidget(self._import_btn)

        self._reload_btn = QPushButton("🔄 热重载")
        self._reload_btn.clicked.connect(self._reload)
        ly.addWidget(self._reload_btn)

        self._validate_btn = QPushButton("✅ 校验配置")
        self._validate_btn.clicked.connect(self._validate)
        ly.addWidget(self._validate_btn)

        ly.addStretch()
        self._status = QLabel("")
        self._status.setStyleSheet("color:#6B7280;font-size:12px;")
        ly.addWidget(self._status)

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出配置", "config_backup.zip", "ZIP (*.zip)")
        if path:
            try:
                self._cfg.export_config(path)
                self._status.setText(f"已导出 → {os.path.basename(path)}")
                self.exported.emit(path)
            except Exception as e:
                QMessageBox.warning(self, "导出失败", str(e))

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入配置", "", "ZIP (*.zip)")
        if path:
            reply = QMessageBox.question(self, "确认导入",
                f"将从 {os.path.basename(path)} 恢复配置，当前配置将被覆盖。继续？",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    self._cfg.import_config(path)
                    self._cfg.reload()
                    self._status.setText(f"已导入 → {os.path.basename(path)}")
                    self.imported.emit(path)
                except Exception as e:
                    QMessageBox.warning(self, "导入失败", str(e))

    def _reload(self):
        try:
            self._cfg.reload()
            self._status.setText("配置已热重载")
        except Exception as e:
            QMessageBox.warning(self, "重载失败", str(e))

    def _validate(self):
        try:
            errors = self._cfg.validate()
            if errors:
                QMessageBox.warning(self, "配置校验",
                    f"发现 {len(errors)} 个问题：\n" + "\n".join(f"• {e}" for e in errors[:20]))
            else:
                QMessageBox.information(self, "配置校验", "所有配置项校验通过 ✓")
            self._status.setText(f"校验完成 — {'通过' if not errors else f'{len(errors)}个问题'}")
            self.validated.emit(errors)
        except Exception as e:
            QMessageBox.warning(self, "校验失败", str(e))
