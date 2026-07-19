"""
阴阳师自动化脚本 - 主界面（三栏布局）

布局结构（参考说明书第十一部分菜单结构）：
- 左栏：菜单树
    - 脚本配置（模拟器连接 / 默认优先级 / 防封号参数 / 运行时段 / 阵容预设 / 日志截图）
    - 任务控制（全局控制 / 日常 / 常驻 / 活动 / 特殊）
- 中栏：任务列表
    - 顶部：启动/停止按钮（运行时切换为停止 + 状态提示）
    - 下方：四类任务分组列表（自动从 tasks/ 扫描注册）
- 右栏：输出日志
    - 顶部：清除日志按钮
    - 下方：实时日志区
"""

import os
import time
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QCheckBox,
    QTextEdit, QGroupBox, QFileDialog, QMessageBox, QProgressBar,
    QSplitter, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QDialog, QFormLayout, QSlider, QFrame, QSizePolicy, QScrollArea
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor, QColor, QPalette

from core.config_manager import ConfigManager
from ui.script_worker import ScriptWorker

PROJECT_ROOT = Path(__file__).parent.parent.parent

# 模拟器选项
EMULATOR_TYPES = {
    "ldplayer": "雷电模拟器",
    "mumu": "MuMu模拟器",
    "nox": "夜神模拟器",
}

# 各模拟器默认 ADB 端口（MuMu12 为 16384）
EMULATOR_DEFAULT_PORTS = {
    "ldplayer": 5555,
    "mumu": 16384,
    "nox": 62001,
}


# ==================== 配置对话框 ====================

class EmulatorConfigDialog(QDialog):
    """模拟器连接设置对话框"""

    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("模拟器连接设置")
        self.setMinimumWidth(460)
        self._init_ui()
        self._load()

    def _init_ui(self):
        layout = QFormLayout(self)
        layout.setSpacing(10)

        self.emulator_combo = QComboBox()
        for key, name in EMULATOR_TYPES.items():
            self.emulator_combo.addItem(name, key)
        layout.addRow("模拟器类型:", self.emulator_combo)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        layout.addRow("ADB 端口:", self.port_spin)

        self.adb_path_edit = QLineEdit()
        self.adb_path_edit.setPlaceholderText("留空则自动检测模拟器自带 adb")
        adb_browse = QPushButton("浏览...")
        adb_browse.clicked.connect(self._browse_adb)
        adb_row = QHBoxLayout()
        adb_row.addWidget(self.adb_path_edit)
        adb_row.addWidget(adb_browse)
        adb_w = QWidget(); adb_w.setLayout(adb_row)
        layout.addRow("ADB 路径:", adb_w)

        self.emu_path_edit = QLineEdit()
        self.emu_path_edit.setPlaceholderText("留空则自动检测")
        emu_browse = QPushButton("浏览...")
        emu_browse.clicked.connect(self._browse_emu)
        emu_row = QHBoxLayout()
        emu_row.addWidget(self.emu_path_edit)
        emu_row.addWidget(emu_browse)
        emu_w = QWidget(); emu_w.setLayout(emu_row)
        layout.addRow("模拟器路径:", emu_w)

        self.auto_launch_check = QCheckBox("未检测到模拟器时自动启动")
        self.auto_launch_check.setChecked(True)
        layout.addRow("", self.auto_launch_check)

        self.emulator_combo.currentIndexChanged.connect(self._on_type_changed)

        btns = QHBoxLayout()
        ok = QPushButton("保存"); ok.clicked.connect(self._save)
        cancel = QPushButton("取消"); cancel.clicked.connect(self.reject)
        btns.addStretch(); btns.addWidget(ok); btns.addWidget(cancel)
        btns_w = QWidget(); btns_w.setLayout(btns)
        layout.addRow(btns_w)

    def _on_type_changed(self):
        emu_type = self.emulator_combo.currentData()
        self.port_spin.setValue(EMULATOR_DEFAULT_PORTS.get(emu_type, 5555))

    def _browse_adb(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择 adb.exe", "", "可执行文件 (*.exe)")
        if p: self.adb_path_edit.setText(p)

    def _browse_emu(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择模拟器程序", "", "可执行文件 (*.exe)")
        if p: self.emu_path_edit.setText(p)

    def _load(self):
        emu_type = self.config.get("emulator.type", "mumu")
        idx = self.emulator_combo.findData(emu_type)
        if idx >= 0: self.emulator_combo.setCurrentIndex(idx)
        self.port_spin.setValue(self.config.get("adb.port", 16384))
        self.adb_path_edit.setText(self.config.get("adb.path", ""))
        self.emu_path_edit.setText(self.config.get("emulator.path", ""))
        self.auto_launch_check.setChecked(self.config.get("emulator.auto_launch", True))

    def _save(self):
        emu_type = self.emulator_combo.currentData()
        port = self.port_spin.value()
        self.config.set("emulator.type", emu_type)
        self.config.set("emulator.path", self.emu_path_edit.text().strip())
        self.config.set("emulator.auto_launch", self.auto_launch_check.isChecked())
        self.config.set("adb.port", port)
        self.config.set("adb.device_id", f"127.0.0.1:{port}")
        adb_path = self.adb_path_edit.text().strip()
        if adb_path:
            self.config.set("adb.path", adb_path)
        self.config.save_global()
        self.accept()


class AntiDetectConfigDialog(QDialog):
    """防封号参数设置对话框"""

    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("防封号参数设置")
        self.setMinimumWidth(420)
        self._init_ui()
        self._load()

    def _init_ui(self):
        layout = QFormLayout(self)
        layout.setSpacing(10)

        self.offset_spin = QSpinBox()
        self.offset_spin.setRange(0, 50)
        layout.addRow("点击偏移半径 (px):", self.offset_spin)

        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.0, 3.0); self.delay_spin.setSingleStep(0.1)
        layout.addRow("延迟抖动系数:", self.delay_spin)

        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.0, 5.0); self.interval_spin.setSingleStep(0.1)
        layout.addRow("最小操作间隔 (s):", self.interval_spin)

        self.pause_spin = QDoubleSpinBox()
        self.pause_spin.setRange(0.0, 1.0); self.pause_spin.setSingleStep(0.01)
        layout.addRow("走神概率:", self.pause_spin)

        self.runtime_spin = QSpinBox()
        self.runtime_spin.setRange(1, 24)
        layout.addRow("每日运行上限 (h):", self.runtime_spin)

        self.actions_spin = QSpinBox()
        self.actions_spin.setRange(100, 100000)
        self.actions_spin.setSingleStep(100)
        layout.addRow("每日操作上限 (次):", self.actions_spin)

        btns = QHBoxLayout()
        ok = QPushButton("保存"); ok.clicked.connect(self._save)
        cancel = QPushButton("取消"); cancel.clicked.connect(self.reject)
        btns.addStretch(); btns.addWidget(ok); btns.addWidget(cancel)
        btns_w = QWidget(); btns_w.setLayout(btns)
        layout.addRow(btns_w)

    def _load(self):
        self.offset_spin.setValue(self.config.get("anti_detect.click_offset_radius", 12))
        self.delay_spin.setValue(self.config.get("anti_detect.delay_jitter", 0.6))
        self.interval_spin.setValue(self.config.get("anti_detect.min_interval", 0.8))
        self.pause_spin.setValue(self.config.get("anti_detect.long_pause_prob", 0.05))
        self.runtime_spin.setValue(self.config.get("anti_detect.max_daily_runtime", 8))
        self.actions_spin.setValue(self.config.get("anti_detect.max_daily_actions", 2000))

    def _save(self):
        self.config.set("anti_detect.click_offset_radius", self.offset_spin.value())
        self.config.set("anti_detect.delay_jitter", self.delay_spin.value())
        self.config.set("anti_detect.min_interval", self.interval_spin.value())
        self.config.set("anti_detect.long_pause_prob", self.pause_spin.value())
        self.config.set("anti_detect.max_daily_runtime", self.runtime_spin.value())
        self.config.set("anti_detect.max_daily_actions", self.actions_spin.value())
        self.config.save_global()
        self.accept()


class LogConfigDialog(QDialog):
    """日志与截图设置对话框"""

    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("日志与截图设置")
        self.setMinimumWidth(380)
        self._init_ui()
        self._load()

    def _init_ui(self):
        layout = QFormLayout(self)
        layout.setSpacing(10)

        self.level_combo = QComboBox()
        self.level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        layout.addRow("日志级别:", self.level_combo)

        self.screenshot_check = QCheckBox("异常时自动截图")
        layout.addRow("", self.screenshot_check)

        btns = QHBoxLayout()
        ok = QPushButton("保存"); ok.clicked.connect(self._save)
        cancel = QPushButton("取消"); cancel.clicked.connect(self.reject)
        btns.addStretch(); btns.addWidget(ok); btns.addWidget(cancel)
        btns_w = QWidget(); btns_w.setLayout(btns)
        layout.addRow(btns_w)

    def _load(self):
        level = self.config.get("run.log_level", "INFO")
        idx = self.level_combo.findText(level)
        if idx >= 0: self.level_combo.setCurrentIndex(idx)
        self.screenshot_check.setChecked(self.config.get("run.screenshot_on_error", True))

    def _save(self):
        self.config.set("run.log_level", self.level_combo.currentText())
        self.config.set("run.screenshot_on_error", self.screenshot_check.isChecked())
        self.config.save_global()
        self.accept()


# ==================== 主窗口 ====================

class MainWindow(QMainWindow):
    """主界面窗口（左中右三栏布局）"""

    append_log = pyqtSignal(str, str)  # (message, level)

    def __init__(self):
        super().__init__()
        self.worker: ScriptWorker = None
        self.config = ConfigManager()
        self._running = False

        self._init_ui()
        self._connect_signals()
        self._refresh_task_list()
        self._check_image_status()

        self.append_log.connect(self._on_append_log)

    # ---------- UI 初始化 ----------

    def _init_ui(self):
        self.setWindowTitle("阴阳师自动化识图脚本")
        self.setMinimumSize(1100, 680)
        self.resize(1280, 760)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # 顶部标题条
        top = QHBoxLayout()
        title = QLabel("阴阳师自动化识图脚本")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        title.setStyleSheet("color: #2c3e50;")
        top.addWidget(title)
        top.addStretch()
        self.version_label = QLabel("v0.3  |  三栏菜单")
        self.version_label.setStyleSheet("color: #95a5a6; font-size: 11px;")
        top.addWidget(self.version_label)
        outer.addLayout(top)

        # 三栏分割器
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(3)
        splitter.addWidget(self._build_left_panel())   # 左：菜单
        splitter.addWidget(self._build_middle_panel())  # 中：任务列表
        splitter.addWidget(self._build_right_panel())   # 右：日志
        splitter.setStretchFactor(0, 0)  # 左栏不伸缩
        splitter.setStretchFactor(1, 1)  # 中栏伸缩
        splitter.setStretchFactor(2, 1)  # 右栏伸缩
        splitter.setSizes([220, 560, 500])
        outer.addWidget(splitter, stretch=1)

        # 底部素材状态条
        self.image_status_label = QLabel("素材: 检查中...")
        self.image_status_label.setStyleSheet("color: #7f8c8d; font-size: 11px; padding: 2px 4px;")
        outer.addWidget(self.image_status_label)

        self.statusBar().showMessage("就绪 - 点击中间栏的「启动」按钮运行脚本")
        self.statusBar().setStyleSheet("color: #666; font-size: 11px;")

    def _build_left_panel(self) -> QWidget:
        """左栏：菜单树"""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QLabel("菜  单")
        header.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        header.setStyleSheet(
            "color: #2c3e50; padding: 6px 8px; background: #ecf0f1; border-radius: 4px;"
        )
        layout.addWidget(header)

        self.menu_tree = QTreeWidget()
        self.menu_tree.setHeaderHidden(True)
        self.menu_tree.setIndentation(16)
        self.menu_tree.setStyleSheet("""
            QTreeWidget { background: #fafbfc; border: 1px solid #dce4ea; border-radius: 4px; }
            QTreeWidget::item { padding: 6px 4px; }
            QTreeWidget::item:selected { background: #3498db; color: white; }
        """)

        # 脚本配置
        cfg_root = QTreeWidgetItem(self.menu_tree, ["脚本配置"])
        cfg_root.setFont(0, QFont("Microsoft YaHei", 10, QFont.Bold))
        cfg_items = [
            ("模拟器连接", "emulator"),
            ("默认优先级与执行顺序", "priority"),
            ("防封号参数", "anti_detect"),
            ("运行时段与限制", "runtime"),
            ("阵容御魂预设管理", "teams"),
            ("日志与截图", "log"),
        ]
        for name, key in cfg_items:
            it = QTreeWidgetItem(cfg_root, [name])
            it.setData(0, Qt.UserRole, ("config", key))

        # 任务控制
        task_root = QTreeWidgetItem(self.menu_tree, ["任务控制"])
        task_root.setFont(0, QFont("Microsoft YaHei", 10, QFont.Bold))
        task_items = [
            ("全局控制", "all"),
            ("日常任务", "daily"),
            ("常驻任务", "permanent"),
            ("活动任务", "event"),
            ("特殊任务", "special"),
        ]
        for name, key in task_items:
            it = QTreeWidgetItem(task_root, [name])
            it.setData(0, Qt.UserRole, ("task", key))

        self.menu_tree.expandAll()
        self.menu_tree.setFixedWidth(210)
        layout.addWidget(self.menu_tree)

        # 选中全局控制默认
        self._task_filter = "all"
        # 默认选中任务控制-全局控制
        root = self.menu_tree.topLevelItem(1)
        if root and root.childCount() > 0:
            self.menu_tree.setCurrentItem(root.child(0))

        return w

    def _build_middle_panel(self) -> QWidget:
        """中栏：启动按钮 + 任务列表"""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 顶部：启动/停止按钮 + 状态提示
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        self.run_btn = QPushButton("▶  启  动")
        self.run_btn.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        self.run_btn.setFixedHeight(42)
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self._style_run_button(False)
        top_bar.addWidget(self.run_btn)

        # 状态提示（运行时显示在按钮旁边）
        self.hint_label = QLabel("待机")
        self.hint_label.setFont(QFont("Microsoft YaHei", 10))
        self.hint_label.setStyleSheet("color: #7f8c8d;")
        top_bar.addWidget(self.hint_label)

        top_bar.addStretch()

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #95a5a6; font-size: 11px;")
        top_bar.addWidget(self.progress_label)

        layout.addLayout(top_bar)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        # 任务列表标题
        list_header = QLabel("任 务 列 表")
        list_header.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        list_header.setStyleSheet(
            "color: #2c3e50; padding: 4px 8px; background: #ecf0f1; border-radius: 4px;"
        )
        layout.addWidget(list_header)

        # 任务列表树
        self.task_tree = QTreeWidget()
        self.task_tree.setHeaderLabels(["任务名称", "状态", "下次执行"])
        self.task_tree.setRootIsDecorated(True)
        self.task_tree.setStyleSheet("""
            QTreeWidget { background: #ffffff; border: 1px solid #dce4ea; border-radius: 4px; }
            QTreeWidget::item { padding: 5px 4px; }
            QTreeWidget::item:selected { background: #ebf5fb; color: #2c3e50; }
            QHeaderView::section { background: #ecf0f1; padding: 4px; border: none; font-weight: bold; }
        """)
        header = self.task_tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        layout.addWidget(self.task_tree, stretch=1)

        return w

    def _build_right_panel(self) -> QWidget:
        """右栏：清除日志按钮 + 日志区"""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 顶部：标题 + 清除日志按钮
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        title = QLabel("输 出 日 志")
        title.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        title.setStyleSheet("color: #2c3e50;")
        top_bar.addWidget(title)

        top_bar.addStretch()

        self.clear_log_btn = QPushButton("清除日志")
        self.clear_log_btn.setFixedHeight(30)
        self.clear_log_btn.setCursor(Qt.PointingHandCursor)
        self.clear_log_btn.setStyleSheet("""
            QPushButton {
                background-color: #607D8B; color: white;
                border: none; border-radius: 4px; padding: 2px 14px;
            }
            QPushButton:hover { background-color: #546E7A; }
        """)
        top_bar.addWidget(self.clear_log_btn)

        layout.addLayout(top_bar)

        # 日志文本框
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e; color: #d4d4d4;
                border: 1px solid #3a3a3a; border-radius: 4px; padding: 6px;
            }
        """)
        layout.addWidget(self.log_text, stretch=1)

        return w

    def _style_run_button(self, running: bool):
        """切换启动/停止按钮样式"""
        if running:
            self.run_btn.setText("■  停  止")
            self.run_btn.setStyleSheet("""
                QPushButton {
                    background-color: #e74c3c; color: white;
                    border: none; border-radius: 6px;
                }
                QPushButton:hover { background-color: #c0392b; }
                QPushButton:pressed { background-color: #a93226; }
            """)
        else:
            self.run_btn.setText("▶  启  动")
            self.run_btn.setStyleSheet("""
                QPushButton {
                    background-color: #27ae60; color: white;
                    border: none; border-radius: 6px;
                }
                QPushButton:hover { background-color: #229954; }
                QPushButton:pressed { background-color: #1e8449; }
            """)

    # ---------- 信号连接 ----------

    def _connect_signals(self):
        self.run_btn.clicked.connect(self._on_run_toggle)
        self.clear_log_btn.clicked.connect(self._on_clear_log)
        self.menu_tree.itemClicked.connect(self._on_menu_clicked)

    # ---------- 菜单点击 ----------

    def _on_menu_clicked(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.UserRole)
        if not data:
            return  # 父节点
        kind, key = data

        if kind == "config":
            # 脚本配置子项 → 弹设置对话框
            if key == "emulator":
                dlg = EmulatorConfigDialog(self.config, self)
                dlg.exec_()
            elif key == "anti_detect":
                dlg = AntiDetectConfigDialog(self.config, self)
                dlg.exec_()
            elif key == "log":
                dlg = LogConfigDialog(self.config, self)
                dlg.exec_()
            elif key == "priority":
                QMessageBox.information(self, "默认优先级与执行顺序",
                    "任务优先级与执行顺序配置功能将在任务系统上线后开放。\n"
                    "届时可在此设置 default_order 大类顺序与各任务 priority。")
            elif key == "runtime":
                QMessageBox.information(self, "运行时段与限制",
                    "运行时段配置功能将在调度器上线后开放。\n"
                    "届时可设置每日允许运行时段、单次连续运行上限等。")
            elif key == "teams":
                QMessageBox.information(self, "阵容御魂预设管理",
                    "阵容预设管理功能将在阵容系统上线后开放。\n"
                    "届时可新增/编辑/删除阵容预设，查看式神编队与御魂方案。")
        elif kind == "task":
            # 任务控制子项 → 筛选中间任务列表
            self._task_filter = key
            self._refresh_task_list()
            label = {
                "all": "全部", "daily": "日常任务", "permanent": "常驻任务",
                "event": "活动任务", "special": "特殊任务",
            }.get(key, "全部")
            self.statusBar().showMessage(f"已切换到：{label}")

    # ---------- 任务列表 ----------

    def _refresh_task_list(self):
        """刷新任务列表（自动扫描 tasks/ 四子目录 + 登录流程占位）"""
        self.task_tree.clear()

        categories = [
            ("日常任务", "daily", "#3498db"),
            ("常驻任务", "permanent", "#16a085"),
            ("活动任务", "event", "#e67e22"),
            ("特殊任务", "special", "#9b59b6"),
        ]

        flt = self._task_filter
        for cat_name, cat_key, color in categories:
            if flt != "all" and flt != cat_key:
                continue

            # 扫描该目录下的任务文件
            task_dir = PROJECT_ROOT / "tasks" / cat_key
            tasks_found = []
            if task_dir.exists():
                for f in sorted(task_dir.glob("*.py")):
                    if f.name.startswith("_"):
                        continue
                    tasks_found.append(f.stem)

            # 特殊类始终显示"登录流程"占位
            if cat_key == "special" and "login_flow" not in tasks_found:
                tasks_found = ["login_flow(登录流程)"] + tasks_found

            root = QTreeWidgetItem(self.task_tree, [cat_name, "", ""])
            root.setFont(0, QFont("Microsoft YaHei", 10, QFont.Bold))
            root.setForeground(0, QColor(color))

            if tasks_found:
                for tname in tasks_found:
                    child = QTreeWidgetItem(root, [tname, "待执行", "—"])
                    child.setCheckState(0, Qt.Checked)
            else:
                empty = QTreeWidgetItem(root, ["（暂无任务）", "", ""])
                empty.setForeground(0, QColor("#bdc3c7"))
                empty.setFlags(empty.flags() & ~Qt.ItemIsEnabled)

        self.task_tree.expandAll()

    # ---------- 启动/停止 ----------

    def _on_run_toggle(self):
        if not self._running:
            self._start()
        else:
            self._stop()

    def _start(self):
        """启动脚本"""
        self._running = True
        self._style_run_button(True)
        self.hint_label.setText("运行中...")
        self.hint_label.setStyleSheet("color: #e67e22; font-weight: bold;")
        self.progress_bar.setVisible(True)
        self.progress_label.setText("初始化...")

        self.log_text.append(f"{'='*48}")
        self.log_text.append(f"  脚本启动  {time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.log_text.append(f"{'='*48}")

        # 读取配置构建 worker
        emu_type = self.config.get("emulator.type", "mumu")
        port = self.config.get("adb.port", 16384)
        path = self.config.get("emulator.path", "")
        auto_launch = self.config.get("emulator.auto_launch", True)

        self.worker = ScriptWorker(
            emulator_type=emu_type,
            adb_port=port,
            emulator_path=path,
            auto_launch=auto_launch,
            parent=self
        )
        self.worker.log_signal.connect(lambda m: self.append_log.emit(m, "INFO"))
        self.worker.status_signal.connect(self._on_status_change)
        self.worker.progress_signal.connect(self._on_progress)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.start()

    def _stop(self):
        """停止脚本"""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.hint_label.setText("正在停止...")
            self.hint_label.setStyleSheet("color: #7f8c8d;")

    def _on_status_change(self, status: str):
        hint_map = {
            "idle": ("待机", "#7f8c8d"),
            "running": ("运行中...", "#e67e22"),
            "success": ("执行成功", "#27ae60"),
            "error": ("执行失败", "#e74c3c"),
        }
        text, color = hint_map.get(status, ("未知", "#7f8c8d"))
        self.hint_label.setText(text)
        self.hint_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def _on_progress(self, msg: str):
        self.progress_label.setText(msg)
        self.statusBar().showMessage(msg)

    def _on_finished(self, success: bool, message: str):
        self._running = False
        self._style_run_button(False)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")

        if success:
            self.log_text.append(f"\n{'='*48}")
            self.log_text.append(f"  ✅ {message}")
            self.log_text.append(f"{'='*48}")
        else:
            self.log_text.append(f"\n{'='*48}")
            self.log_text.append(f"  ❌ {message}")
            self.log_text.append(f"{'='*48}")
        self.log_text.moveCursor(QTextCursor.End)

        self._check_image_status()

    # ---------- 日志 ----------

    def _on_clear_log(self):
        self.log_text.clear()

    def _on_append_log(self, msg: str, level: str):
        color_map = {
            "INFO": "#d4d4d4",
            "WARN": "#f1c40f",
            "ERROR": "#e74c3c",
            "DEBUG": "#7f8c8d",
        }
        color = color_map.get(level, "#d4d4d4")
        if "[ERROR]" in msg:
            color = "#e74c3c"
        elif "[WARN]" in msg:
            color = "#f1c40f"
        self.log_text.append(f'<span style="color:{color}">{msg}</span>')
        self.log_text.moveCursor(QTextCursor.End)

    # ---------- 素材状态 ----------

    def _check_image_status(self):
        """检查素材目录状态：统计 assets/ 下各分类的素材数量"""
        import os
        assets_dir = PROJECT_ROOT / "assets"
        if not assets_dir.exists():
            self.image_status_label.setText("素材: assets/ 目录不存在")
            self.image_status_label.setStyleSheet("color: #e74c3c; font-size: 11px; padding: 2px 4px;")
            return

        # 统计各分类素材数
        categories = {"common": 0, "scenes": 0, "tasks": 0, "teams": 0}
        total = 0
        for root, dirs, files in os.walk(assets_dir):
            for f in files:
                if not f.lower().endswith(".png"):
                    continue
                rel = Path(root).relative_to(assets_dir)
                top = str(rel).split(os.sep)[0] if str(rel) != "." else ""
                if top in categories:
                    categories[top] += 1
                total += 1

        # 检查「所需图片」暂存区
        source_dir = PROJECT_ROOT / "所需图片"
        pending = 0
        if source_dir.exists():
            pending = len([f for f in source_dir.iterdir() if f.suffix.lower() == ".png"])

        parts = [f"{k}={v}" for k, v in categories.items() if v > 0]
        cat_text = "  ".join(parts) if parts else "无素材"
        pending_text = f"  暂存={pending}" if pending > 0 else ""
        self.image_status_label.setText(f"素材: 共{total}张  {cat_text}{pending_text}")
        self.image_status_label.setStyleSheet("color: #7f8c8d; font-size: 11px; padding: 2px 4px;")

    # ---------- 关闭 ----------

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self, "确认退出",
                "脚本正在运行中，确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
            self.worker.stop()
            self.worker.wait(3000)
        self.config.save_global()
        event.accept()
