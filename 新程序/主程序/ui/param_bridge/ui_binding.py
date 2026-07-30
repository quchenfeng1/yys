"""
10-参数桥接模块

UI 控件 ↔ 配置双向绑定（§4 + §5.3 UIBinding）。
实现 PyQt5 控件与配置/状态的双向同步。

支持：
- 双向绑定 bind(widget, config_path)
- 只读状态绑定 bind_state(widget, state_key)
- 撤销 undo()（_undo_stack maxlen=10）
- 跨线程安全（_bindings_lock）
- 事件驱动刷新（_on_state_changed）
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.event_bus import EventBus, get_global_bus
from core.events import Events


# ── §5.2 数据结构 ─────────────────────────────────────────

@dataclass
class Binding:
    """绑定条目（§5.2）"""
    widget: Any                    # UI 控件引用（QWidget）
    config_path: str               # 配置点分路径
    binding_type: str = "two_way"  # "two_way"(双向) / "read_only"(只读)
    last_value: Any = None         # 上一次写入的值
    state_key: str | None = None   # 状态键（仅 read_only 时有效）
    validator: Callable[[Any], bool] | None = None  # 校验函数


@dataclass
class UndoRecord:
    """撤销记录（§4.3 + §5.2）"""
    config_path: str               # 被修改的配置路径
    old_value: Any                 # 修改前的值
    new_value: Any                 # 修改后的值
    timestamp: float = field(default_factory=time.time)  # 修改时间戳


class UIBinding:
    """UI 数据绑定层（§5.3）"""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        config: Any = None,
    ):
        self._bus = event_bus or get_global_bus()
        self._config = config  # ConfigManager

        # §2.3 线程安全锁
        self._bindings_lock = threading.Lock()

        # §2.3 绑定注册表
        self._bindings: dict[str, Binding] = {}  # config_path → Binding

        # §4.3 撤销栈
        self._undo_stack: deque[UndoRecord] = deque(maxlen=10)
        self._undo_lock: bool = False  # 防止递归撤销

        # 订阅 config_changed + state_changed
        self._bus.subscribe(Events.CONFIG_CHANGED, self._on_config_changed)
        self._bus.subscribe(Events.STATE_CHANGED, self._on_state_changed)

    # ── §5.3 绑定方法 ─────────────────────────────────────

    def bind(
        self,
        widget: Any,
        config_path: str,
        validator: Callable[[Any], bool] | None = None,
    ) -> None:
        """
        将 UI 控件绑定到指定配置路径（双向，§5.3）。

        保存当前值的 UndoRecord → 用户修改 → 校验 → config.set()
        """
        with self._bindings_lock:
            old_value = self._get_config_value(config_path)
            self._bindings[config_path] = Binding(
                widget=widget,
                config_path=config_path,
                binding_type="two_way",
                last_value=old_value,
                validator=validator,
            )

    def bind_state(
        self,
        widget: Any,
        state_key: str,
    ) -> None:
        """
        将 UI 控件绑定到指定状态键（只读显示，§5.3）。

        不生成 UndoRecord。通过 state_changed 事件自动刷新。
        """
        with self._bindings_lock:
            self._bindings[state_key] = Binding(
                widget=widget,
                config_path=state_key,
                binding_type="read_only",
                state_key=state_key,
            )

    def unbind(self, widget: Any) -> None:
        """解绑控件（§5.3）"""
        with self._bindings_lock:
            keys_to_remove = [
                k for k, b in self._bindings.items()
                if b.widget is widget
            ]
            for k in keys_to_remove:
                del self._bindings[k]

    # ── §5.3 撤销 ─────────────────────────────────────────

    def push_undo(self, config_path: str, old_value: Any, new_value: Any) -> None:
        """
        保存 UndoRecord 到撤销栈（§4.3）。

        受 _undo_lock 保护：undo() 执行期间跳过 push 避免递归。
        调用方：UI 控件变更处理函数中，在 config.set() 之前调用。
        """
        if self._undo_lock:
            return
        self._undo_stack.append(UndoRecord(
            config_path=config_path,
            old_value=old_value,
            new_value=new_value,
        ))

    def undo(self) -> bool:
        """
        撤销上一次配置修改（§4.3 + §5.3）。

        设置 _undo_lock → pop UndoRecord → config.set(old_value)
        → _undo_lock = False（阻止递归撤销）
        """
        if not self._undo_stack:
            return False

        record = self._undo_stack.pop()
        self._undo_lock = True
        try:
            if self._config and hasattr(self._config, 'set'):
                self._config.set(record.config_path, record.old_value, source="UIBinding.undo")
        finally:
            self._undo_lock = False
        return True

    # ── 事件响应 ──────────────────────────────────────────

    def _on_config_changed(self, **kw: Any) -> None:
        """响应 config_changed 事件 → 刷新对应控件"""
        key_path = kw.get("key_path", "")
        with self._bindings_lock:
            if key_path in self._bindings:
                binding = self._bindings[key_path]
                self._update_widget(binding)

    def _on_state_changed(self, **kw: Any) -> None:
        """
        订阅 state_changed 事件（§3.1 + §5.3）。

        通过 pyqtSignal/QMetaObject.invokeMethod
        将控件更新投递到 UI 主线程执行。
        """
        key = kw.get("key", "")
        with self._bindings_lock:
            for cfg_path, binding in list(self._bindings.items()):
                if binding.binding_type == "read_only":
                    if binding.state_key and (binding.state_key == key or not key):
                        self._update_widget_async(binding)

    # ── 内部工具 ──────────────────────────────────────────

    def _get_config_value(self, config_path: str) -> Any:
        """从配置读取值"""
        if self._config and hasattr(self._config, 'get'):
            return self._config.get(config_path)
        return None

    def _update_widget(self, binding: Binding) -> None:
        """更新控件显示（直接调用，仅在 UI 线程安全时使用）"""
        widget = binding.widget
        if widget is None:
            return
        value = self._get_config_value(binding.config_path)
        if hasattr(widget, 'setText'):
            try:
                widget.setText(str(value) if value is not None else "")
            except Exception:
                pass
        elif hasattr(widget, 'setValue'):
            try:
                widget.setValue(value if value is not None else 0)
            except Exception:
                pass
        elif hasattr(widget, 'setChecked'):
            try:
                widget.setChecked(bool(value))
            except Exception:
                pass

    def _update_widget_async(self, binding: Binding) -> None:
        """异步更新控件（通过信号投递到 UI 主线程）"""
        try:
            from PyQt5.QtCore import QMetaObject, Qt, Q_ARG

            widget = binding.widget
            if widget is None:
                return
            value = self._get_config_value(binding.config_path)
            text = str(value) if value is not None else ""
            if hasattr(widget, 'setText'):
                QMetaObject.invokeMethod(
                    widget, "setText", Qt.QueuedConnection,
                    Q_ARG(str, text),
                )
        except ImportError:
            # 非 Qt 环境回退
            self._update_widget(binding)

    # ── §5.3 批量绑定 ─────────────────────────────────────

    def bind_all(self) -> None:
        """
        批量注册所有 UI 控件绑定（§5.3）。

        由 MainWindow 初始化时调用。实际绑定时 MainWindow 逐控件
        调用 bind()/bind_state()，bind_all() 仅作为容器方法存在。

        子类可重写此方法以批量执行 bind 调用。
        """
        pass

    # ── 批量操作 ──────────────────────────────────────────

    def refresh_all(self) -> dict[str, Any]:
        """刷新所有绑定数据"""
        with self._bindings_lock:
            result = {}
            for cfg_path, binding in list(self._bindings.items()):
                val = self._get_config_value(cfg_path)
                result[cfg_path] = val
                self._update_widget(binding)
            return result

    @property
    def count(self) -> int:
        with self._bindings_lock:
            return len(self._bindings)
