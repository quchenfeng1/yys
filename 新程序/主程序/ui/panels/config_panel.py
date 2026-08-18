"""
UI 子面板：ConfigPanel 全局配置面板（06-配置管理中心 的可编辑表单）。

按《06-配置管理中心》§4.7 + config_schema 字段：
- device（仅「模拟设备模式」；地址/连接由「模拟器管理」统一承载）
- image（模板阈值/OCR）
- anti_detect（防封）
- log（日志）

2026-08-16 精简：移除无后端消费者的字段——
ADB 主机/端口/超时/重试、截图方式/质量/缩放/缓存、模拟器路径/名称、
匹配方法、鼠标模拟/行为画像/每周休息日、调度组（schedule.*）。

读写经 ParamBridge.config（ConfigBridge）→ ConfigManager，保存即原子写盘。
"""
from __future__ import annotations

from typing import Any

from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

LOG_LEVELS = ["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]


class ConfigPanel(QWidget):
    """全局配置面板（可编辑，保存写回 global.yaml）"""

    def __init__(self, param_bridge: Any = None, parent=None):
        super().__init__(parent)
        self._bridge = getattr(param_bridge, 'config', None) if param_bridge else None
        # (key, widget, dtype)  dtype: str/int/float/bool/choice
        self._fields: list[tuple[str, Any, str]] = []
        self._setup_ui()
        self.load_values()

    # ── UI 构建 ──────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(QLabel("全局配置（保存后写回 global.yaml）"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self._form_layout = QVBoxLayout(container)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_save = QPushButton("💾 保存全部配置")
        btn_save.clicked.connect(self.save)
        btn_reload = QPushButton("↻ 重新加载")
        btn_reload.clicked.connect(self.load_values)
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_reload)
        root.addLayout(btn_row)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color:#4CAF50;")
        root.addWidget(self._status_label)

        # ── 设备组（2026-08-16 精简）──────────────────
        # ADB 地址/端口/截图/模拟器路径等已由「模拟器管理」统一承载，
        # 仅保留真正被后端消费的 device.mock。
        from ui.theme import panel_group
        g_dev, dev_content = panel_group("设备 (device)")
        f_dev = QFormLayout()
        dev_content.addLayout(f_dev)
        cb_mock = self._add_field(f_dev, "device.mock", "模拟设备模式(无真实模拟器)", "bool", False)
        cb_mock.setToolTip("开启后无需真实 ADB 设备即可运行（需重启生效）")
        hint_dev = QLabel("模拟器地址与连接由左侧「模拟器管理」统一配置，无需在此设置")
        hint_dev.setStyleSheet("color:#8a94a6; font-size:12px;")
        dev_content.addWidget(hint_dev)
        self._form_layout.addWidget(g_dev)

        # ── 识别组 ──────────────────────────────────────
        g_img, img_content = panel_group("图像识别 (image)")
        f_img = QFormLayout()
        img_content.addLayout(f_img)
        self._add_field(f_img, "image.template_threshold", "模板匹配阈值", "float", 0.8, 0.0, 1.0, 0.05)
        self._add_field(f_img, "image.ocr_enabled", "启用 OCR", "bool", True)
        self._add_field(f_img, "image.ocr_timeout", "OCR 超时(秒)", "int", 10, 1, 120)
        self._add_field(f_img, "image.ocr_use_gpu", "OCR 使用 GPU", "bool", False)
        self._form_layout.addWidget(g_img)

        # ── 防封组 ──────────────────────────────────────
        g_ad, ad_content = panel_group("防封策略 (anti_detect)")
        f_ad = QFormLayout()
        ad_content.addLayout(f_ad)
        self._add_field(f_ad, "anti_detect.enabled", "启用防封", "bool", True)
        self._add_field(f_ad, "anti_detect.min_interval", "最小间隔(秒)", "float", 1.0, 0.1, 60)
        self._add_field(f_ad, "anti_detect.max_interval", "最大间隔(秒)", "float", 5.0, 0.1, 120)
        self._add_field(f_ad, "anti_detect.action_jitter", "点击抖动", "bool", True)
        self._add_field(f_ad, "anti_detect.random_fail_rate", "随机失败率", "float", 0.02, 0.0, 1.0, 0.01)
        self._form_layout.addWidget(g_ad)

        # ── 异常检测组（2026-08-16 信号体系）────────────────
        g_an, an_content = panel_group("异常检测 (anomaly)")
        f_an = QFormLayout()
        an_content.addLayout(f_an)
        self._add_field(f_an, "anomaly.count", "连续相同场景次数", "int", 5, 1, 100)
        self._add_field(f_an, "anomaly.window", "时间窗口(秒)", "int", 30, 5, 600)
        hint_an = QLabel("异常判定：同一节点识别出同一场景信号连续 N 次，或时间窗口内\n"
                         "连续识别到同一场景信号 N 次 → 判定异常，任务交由全局任务安全结束。")
        hint_an.setStyleSheet("color:#8a94a6; font-size:12px;")
        an_content.addWidget(hint_an)
        self._form_layout.addWidget(g_an)

        # ── 日志组 ──────────────────────────────────────
        g_lg, lg_content = panel_group("日志 (log)")
        f_lg = QFormLayout()
        lg_content.addLayout(f_lg)
        self._add_field(f_lg, "log.level", "日志级别", "choice", "INFO", choices=LOG_LEVELS)
        self._add_field(f_lg, "log.dir", "日志目录", "line", "logs")
        self._add_field(f_lg, "log.rotation", "轮转大小", "line", "10 MB")
        self._add_field(f_lg, "log.retention", "保留时长", "line", "30 days")
        self._add_field(f_lg, "log.console", "控制台输出", "bool", True)
        self._add_field(f_lg, "log.structured", "结构化日志", "bool", False)
        self._form_layout.addWidget(g_lg)

        self._form_layout.addStretch()

    def _add_field(self, form, key: str, label: str, dtype: str,
                   default: Any, lo: float = 0, hi: float = 0,
                   step: float = 0.0, choices: list | None = None) -> QWidget:
        """创建表单行并登记到 _fields"""
        if dtype == "line":
            w = QLineEdit(str(default))
            w.setPlaceholderText(str(default))
        elif dtype == "int":
            w = QSpinBox()
            w.setRange(int(lo), int(hi))
            w.setValue(int(default))
        elif dtype == "float":
            w = QDoubleSpinBox()
            w.setRange(float(lo), float(hi))
            w.setDecimals(3)
            if step > 0:
                w.setSingleStep(step)
            w.setValue(float(default))
        elif dtype == "bool":
            w = QCheckBox(label)
            w.setChecked(bool(default))
            w._cfg_default = default
            form.addRow("", w)
            self._fields.append((key, w, dtype))
            return w
        elif dtype == "choice":
            w = QComboBox()
            for c in (choices or []):
                w.addItem(c, c)
            idx = w.findData(default)
            w.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            w = QLineEdit()
        w._cfg_default = default
        form.addRow(label + ":", w)
        self._fields.append((key, w, dtype))
        return w

    # ── 值读写（经 ConfigBridge → ConfigManager） ──────────

    def _get_value(self, key: str, default: Any) -> Any:
        if self._bridge and hasattr(self._bridge, 'get'):
            try:
                v = self._bridge.get("global." + key, None)
                if v is not None:
                    return v
            except Exception:
                pass
        return default

    def load_values(self) -> None:
        """从配置中心读取当前值填充表单（缺失字段用 schema 默认值）"""
        for key, w, dtype in self._fields:
            default = getattr(w, '_cfg_default', None)
            val = self._get_value(key, default)
            try:
                if dtype == "line":
                    w.setText(str(val) if val is not None else "")
                elif dtype == "int":
                    w.setValue(int(val))
                elif dtype == "float":
                    w.setValue(float(val))
                elif dtype == "bool":
                    w.setChecked(bool(val))
                elif dtype == "choice":
                    idx = w.findData(val)
                    w.setCurrentIndex(idx if idx >= 0 else 0)
            except Exception:
                pass
        self._status_label.setText("已加载配置")

    def save(self) -> None:
        """保存全部字段到 global.yaml（ConfigBridge.set 原子写盘）"""
        if not self._bridge or not hasattr(self._bridge, 'set'):
            self._status_label.setText("配置中心未连接")
            return
        saved = 0
        errors: list[str] = []
        for key, w, dtype in self._fields:
            try:
                if dtype == "line":
                    value = w.text().strip()
                elif dtype == "int":
                    value = w.value()
                elif dtype == "float":
                    value = w.value()
                elif dtype == "bool":
                    value = w.isChecked()
                elif dtype == "choice":
                    value = w.currentData()
                else:
                    continue
                self._bridge.set("global." + key, value)
                saved += 1
            except Exception as e:
                errors.append(f"{key}: {e}")
        if errors:
            self._status_label.setStyleSheet("color:#e74c3c;")
            self._status_label.setText(f"保存部分成功 ({saved} 项)，失败: {'; '.join(errors[:3])}")
        else:
            self._status_label.setStyleSheet("color:#4CAF50;")
            note = "（模拟设备模式需重启生效）" if self._get_value("device.mock", False) else ""
            self._status_label.setText(f"✅ 已保存 {saved} 项配置{note}")

