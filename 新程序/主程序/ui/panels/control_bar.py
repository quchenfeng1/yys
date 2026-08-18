"""
UI 子面板：ControlBar 顶部控制栏（2026-08-16 重构 + 模拟器下拉）。

布局：模拟器选择 → 游戏选择 → 连接/断开模拟器 → 启动/暂停/停止。
- 模拟器/游戏下拉：脚本未运行时可选；运行中禁用。
- 连接按钮：未连接「🔌 连接模拟器」；连接成功变「🔌 断开连接」。
- 沙盒/自检按钮已移除（试跑由可视化构建测试启动覆盖；ADB 状态由连接按钮反映）。
"""
from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget,
)


class ControlBar(QWidget):
    """顶部控制栏：模拟器选择 + 游戏选择 + 连接/断开 + 启动/暂停/停止"""

    start_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    resume_clicked = pyqtSignal()
    emulator_changed = pyqtSignal(str)  # 用户切换模拟器下拉（emulator_id）
    game_changed = pyqtSignal(str)      # 用户切换游戏下拉（game_id）
    connect_toggled = pyqtSignal()      # 点击连接/断开按钮

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(8)

        # ── 模拟器选择（2026-08-16）────────────────────
        layout.addWidget(QLabel("模拟器"))
        self.combo_emu = QComboBox()
        self.combo_emu.setMinimumWidth(140)
        self.combo_emu.setToolTip("选择要连接的模拟器（运行中不可切换）")
        layout.addWidget(self.combo_emu)

        # ── 游戏选择 ──────────────────────────────────
        layout.addWidget(QLabel("游戏"))
        self.combo_game = QComboBox()
        self.combo_game.setMinimumWidth(120)
        self.combo_game.setToolTip("选择要运行的脚本所属游戏（运行中不可切换）")
        layout.addWidget(self.combo_game)

        # ── 连接/断开模拟器 ───────────────────────────
        self.btn_connect = QPushButton("🔌 连接模拟器")
        self.btn_connect.setToolTip("连接模拟器设备；连接成功后变为断开连接")
        layout.addWidget(self.btn_connect)

        layout.addSpacing(8)

        # ── 启动/暂停/停止 ────────────────────────────
        self.btn_start = QPushButton("▶ 启动")
        self.btn_stop = QPushButton("■ 停止")
        self.btn_pause = QPushButton("⏸ 暂停")

        from ui.theme import icon
        _ic = icon("fa5s.play-circle", "#2e7d32")
        if _ic:
            self.btn_start.setIcon(_ic)
        _ic = icon("fa5s.stop-circle", "#c62828")
        if _ic:
            self.btn_stop.setIcon(_ic)
        _ic = icon("fa5s.pause-circle", "#ef6c00")
        if _ic:
            self.btn_pause.setIcon(_ic)

        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)

        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_pause)
        layout.addWidget(self.btn_stop)
        layout.addStretch()

        # 信号
        self.combo_emu.currentIndexChanged.connect(self._on_emu_index_changed)
        self.combo_game.currentIndexChanged.connect(self._on_game_index_changed)
        self.btn_connect.clicked.connect(self.connect_toggled.emit)
        self.btn_start.clicked.connect(self.start_clicked.emit)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        self.btn_pause.clicked.connect(self._toggle_pause)

        self._last_emu: str = ""
        self._last_game: str = ""

    # ── 模拟器下拉（2026-08-16）──────────────────────

    def set_emulators(self, items: list[tuple[str, str]]) -> None:
        """填充模拟器下拉：[(emulator_id, 显示名)]"""
        self.combo_emu.blockSignals(True)
        self.combo_emu.clear()
        for eid, label in items:
            self.combo_emu.addItem(label, eid)
        self.combo_emu.blockSignals(False)

    def set_current_emulator(self, emu_id: str) -> None:
        """设置当前选中模拟器（不触发 emulator_changed）"""
        self._last_emu = emu_id
        idx = self.combo_emu.findData(emu_id)
        if idx >= 0:
            self.combo_emu.blockSignals(True)
            self.combo_emu.setCurrentIndex(idx)
            self.combo_emu.blockSignals(False)

    def current_emulator(self) -> str:
        return self.combo_emu.currentData() or ""

    def _on_emu_index_changed(self, index: int) -> None:
        if index < 0:
            return
        eid = self.combo_emu.currentData() or ""
        if not eid or eid == self._last_emu:
            return
        self._last_emu = eid
        self.emulator_changed.emit(eid)

    # ── 游戏下拉 ──────────────────────────────────────

    def set_games(self, items: list[tuple[str, str]]) -> None:
        """填充游戏下拉：[(game_id, 显示名)]"""
        self.combo_game.blockSignals(True)
        self.combo_game.clear()
        for gid, label in items:
            self.combo_game.addItem(label, gid)
        self.combo_game.blockSignals(False)

    def set_current_game(self, game_id: str) -> None:
        """设置当前选中游戏（不触发 game_changed）"""
        self._last_game = game_id
        idx = self.combo_game.findData(game_id)
        if idx >= 0:
            self.combo_game.blockSignals(True)
            self.combo_game.setCurrentIndex(idx)
            self.combo_game.blockSignals(False)

    def current_game(self) -> str:
        return self.combo_game.currentData() or ""

    def _on_game_index_changed(self, index: int) -> None:
        if index < 0:
            return
        gid = self.combo_game.currentData() or ""
        if not gid or gid == self._last_game:
            return
        self._last_game = gid
        self.game_changed.emit(gid)

    # ── 连接按钮 ──────────────────────────────────────

    def set_connected(self, connected: bool) -> None:
        """连接状态 → 按钮文案切换（连接成功 → 断开连接）"""
        self.btn_connect.setText("🔌 断开连接" if connected else "🔌 连接模拟器")
        self.btn_connect.setToolTip(
            "断开与模拟器的连接" if connected else "连接模拟器设备")

    # ── 启停 ──────────────────────────────────────────

    def _toggle_pause(self) -> None:
        if self.btn_pause.text() == "⏸ 暂停":
            self.pause_clicked.emit()
            self.btn_pause.setText("▶ 继续")
        else:
            self.resume_clicked.emit()
            self.btn_pause.setText("⏸ 暂停")

    def set_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.btn_pause.setEnabled(running)
        # 运行中：模拟器/游戏不可切换、不可断开连接
        self.combo_emu.setEnabled(not running)
        self.combo_game.setEnabled(not running)
        self.btn_connect.setEnabled(not running)
        if running:
            self.btn_pause.setText("⏸ 暂停")

    def set_paused(self, paused: bool) -> None:
        """更新暂停按钮状态（§3.7 运行启停）"""
        if paused:
            self.btn_pause.setText("▶ 继续")
        else:
            self.btn_pause.setText("⏸ 暂停")
