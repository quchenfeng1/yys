# UI设计思路

> **文档性质**：基于12模块解耦方案的UI分解设计  ｜  **版本**：v2.2（新增任务队列展示面板）

---

## 一、UI整体布局

保留v0.5的三栏QSplitter布局，增加底部状态栏：

```
┌──────────────────────────────────────────────────────────────────┐
│  阴阳师自动化脚本                                           [─][□][×] │
├──────────┬──────────────────────────────────┬────────────────────┤
│          │  [启动] [停止] [暂停]  当前: 御魂(15/30) │ [📋日志][🖥终端]│
│  菜单树    │──────────────────────────────────│                    │
│          │                                  │  📋 日志标签        │
│ ▸脚本配置 │  日常任务 [▾]                     │  ...               │
│  ...     │  ...                             │  [清除] [导出]      │
│          │                                  │ ────────────────── │
│ ▸任务控制 │                                  │  🖥 终端标签（只读） │
│          │                                  │  深色背景+自动着色   │
│ ▸运行监控 │                                  │  stdout/stderr输出  │
│          │                                  │  [清屏]             │
│ ▸小号设置 │                                  │                    │
├──────────┴──────────────────────────────────┴────────────────────┤
│ 状态: 运行中 │ 连接: 已连接 │ 账号: 主号 │ 今日操作: 456次        │
└──────────────────────────────────────────────────────────────────┘
```

---

## 二、UI子模块设计

### 2.1 菜单树（左侧）

```python
class MenuTree(QTreeWidget):
    """左侧菜单树。三大一级菜单+子菜单。"""

    STRUCTURE = {
        "脚本配置": ["模拟器连接", "账号管理", "任务优先级",
                    "防封号参数", "运行时段", "阵容预设", "日志配置"],
        "任务控制": ["日常任务", "常驻任务", "活动任务", "特殊任务"],
        "运行监控": ["运行指标", "异常截图", "运行报告"],  # v2.0新增
        "小号设置": [],  # 动态填充小号列表
    }

    def on_item_clicked(self, item):
        """点击菜单项 → 切换中间面板显示对应配置/任务列表"""
        # 通过传参模块切换面板，不直接操作逻辑
```

### 2.2 任务列表面板（中间）

```python
class TaskListPanel(QWidget):
    """任务列表面板。四类可折叠面板，自动从tasks/扫描生成。"""

    def refresh(self):
        """扫描tasks/目录刷新列表"""
        for category in ["daily", "permanent", "event", "special"]:
            panel = self._category_panels[category]
            panel.clear()
            for task in task_registry.list_by_category(category):
                row = TaskRow(task)
                # 通过传参模块绑定所有控件
                self._bridge.task_bridge.bind_task_row(task.name, row)
                panel.add_row(row)

class TaskRow(QWidget):
    """单个任务行。显示: 名称|启用|优先级|执行规则|下次时间|状态|操作"""

    def __init__(self, task):
        self.enabled_checkbox = QCheckBox()
        self.name_label = QLabel(task.display_name)
        self.priority_spinbox = QSpinBox()
        self.repeat_summary = QLabel()        # 执行规则摘要
        self.next_run_time_edit = QDateTimeEdit()  # 可编辑下次时间
        self.countdown_label = CountdownLabel()    # 倒计时（自动刷新）
        self.status_label = QLabel()               # 待执行/等待中/已完成
        self.detail_btn = QPushButton("详细")      # 展开参数面板
        self.step_btn = QPushButton("单步")        # 调试用
        self.skip_btn = QPushButton("跳过")        # 推进next_run_time
```

### 2.3 全局控制栏 + 任务队列面板（中间上方）★ v2.2

```python
class ControlBar(QWidget):
    """全局控制栏。启动/停止/暂停按钮 + 当前任务显示。"""

    def __init__(self):
        self.start_btn = QPushButton("▶ 启动")
        self.stop_btn = QPushButton("■ 停止")
        self.pause_btn = QPushButton("⏸ 暂停")

    def bind(self, bridge):
        bridge.run_bridge.bind_start_button(self.start_btn)
        bridge.run_bridge.bind_stop_button(self.stop_btn)
        bridge.run_bridge.bind_pause_button(self.pause_btn)

# ★ v2.2 新增：控制栏下方 → 任务队列面板
class TaskQueuePanel(QWidget):
    """任务队列展示面板。当前任务（大卡片）+ 队列（小方块）。"""
    # 详见 ui/panels/task_queue_panel.py
```

### 2.4 日志+终端组合面板（右侧）★ v2.1 升级

```python
class LogPanel(QWidget):
    """右侧组合面板。QTabWidget 双标签：
    - 📋 日志：结构化日志流（级别筛选 + 模块筛选 + 清除 + 导出）
    - 🖥 终端：只读内置终端（捕获 stdout/stderr，替代外部黑窗口）
    """

    def __init__(self):
        self._tabs = QTabWidget()
        self._log_stream = LogStreamWidget()   # 日志标签
        self._terminal = TerminalWidget()       # 终端标签
        self._tabs.addTab(self._log_stream, "📋 日志")
        self._tabs.addTab(self._terminal, "🖥 终端")

    def start(self):
        self._log_stream.start()               # 订阅日志事件
        self._terminal.install_redirector()    # 安装 stdout 重定向

    def shutdown(self):
        self._terminal.uninstall_redirector()  # 卸载重定向
```

### 2.4.1 终端控件（只读）

```python
class TerminalWidget(QWidget):
    """内置只读终端。深色背景，Consolas 等宽字体，自动着色。"""

    def install_redirector(self):
        """安装 OutputRedirector → 替换 sys.stdout/stderr"""
        self._redirector = OutputRedirector()
        self._redirector.output_received.connect(self._append_terminal)
        self._redirector.install()

    def _append_terminal(self, text: str):
        """追加文本，按级别自动着色"""
        # [INFO]=绿 [WARNING]=橙 [ERROR]=红 [DEBUG]=灰 [STEP]=蓝

class OutputRedirector(QObject):
    """捕获 sys.stdout/stderr，通过 Qt 信号线程安全发送到终端。"""
    output_received = pyqtSignal(str)
    def write(self, text): ...  # 替换 sys.stdout.write
    def flush(self): ...
    def install(self):          # sys.stdout = self
    def uninstall(self):        # 恢复原始 stdout
```

### 2.5 状态展示栏（底部）

```python
class StatusBar(QWidget):
    """底部状态栏。展示全局运行状态。"""

    def __init__(self):
        self.run_status = QLabel("已停止")
        self.connection_status = QLabel("未连接")
        self.current_account = QLabel("—")
        self.today_ops = QLabel("0次")

    def start(self):
        """订阅状态变化事件自动刷新"""
        event_bus.subscribe(Events.STATE_CHANGED,
            handler=self._on_state_changed,
            filter=lambda e: e.data.get("key") in [
                StateKeys.RUN_STATUS, StateKeys.CONNECTION_STATUS,
                StateKeys.CURRENT_ACCOUNT, StateKeys.TODAY_OPERATION_COUNT
            ])
```

### 2.6 配置面板（左侧弹出）

各配置面板（模拟器连接/账号管理/任务优先级/防封号/运行时段/阵容预设/日志配置）结构类似：

```python
class ConnectionPanel(QWidget):
    """模拟器连接配置面板"""

    def __init__(self):
        self.adb_path_edit = QLineEdit()
        self.port_spinbox = QSpinBox()
        self.device_id_edit = QLineEdit()
        self.resolution_label = QLabel()  # 只读显示
        self.test_btn = QPushButton("测试连接")

    def bind(self, bridge):
        """通过传参模块绑定配置"""
        bridge.config_bridge.bind_lineedit(self.adb_path_edit, "global.adb.path")
        bridge.config_bridge.bind_spinbox(self.port_spinbox, "global.adb.port")
        bridge.config_bridge.bind_lineedit(self.device_id_edit, "global.adb.device_id")
        # 测试按钮 → 发布test_connection事件
        self.test_btn.clicked.connect(
            lambda: event_bus.publish("test_connection_requested")
        )
```

---

## 三、可复用组件

### 3.1 执行规则编辑器

```python
class RepeatEditor(QWidget):
    """执行规则可视化编辑器。选择类型→动态显示对应字段。"""

    def __init__(self):
        self.type_combo = QComboBox()  # once/daily/weekly/monthly/...
        self.time_edit = QDateTimeEdit()
        self.weekday_checks = [QCheckBox(d) for d in "一二三四五六日"]
        self.times_spinbox = QSpinBox()
        self.window_start = QTimeEdit()
        self.window_end = QTimeEdit()

    def bind(self, bridge, config_key):
        bridge.task_bridge.bind_repeat_editor(self, config_key)
```

### 3.2 倒计时标签

```python
class CountdownLabel(QLabel):
    """倒计时标签。订阅next_run_time变化，每秒刷新倒计时。"""

    def __init__(self):
        self._target_time = None
        self._timer = QTimer()
        self._timer.timeout.connect(self._refresh)

    def set_target(self, dt: datetime):
        self._target_time = dt
        self._timer.start(1000)  # 每秒刷新

    def _refresh(self):
        if self._target_time:
            delta = self._target_time - datetime.now()
            if delta.total_seconds() > 0:
                hours = int(delta.total_seconds() // 3600)
                mins = int((delta.total_seconds() % 3600) // 60)
                self.setText(f"{hours}小时{mins}分后")
            else:
                self.setText("可执行")
```

---

## 四、UI与传参模块的协作

```
用户操作                    UI模块              传参模块            程序模块
─────────                   ──────              ──────              ──────
点击"启动"          →  ControlBar.start_btn  →  RunBridge      →  event_bus: start_requested
                                                                →  RunController._on_start()
勾选"御魂启用"      →  TaskRow.checkbox     →  TaskBridge     →  ConfigManager.set(...)
                                                                →  Scheduler.refresh()
修改"优先级=5"      →  TaskRow.priority     →  TaskBridge     →  ConfigManager.set(...)
修改"下次时间"      →  TaskRow.next_run     →  TaskBridge     →  Scheduler.update_next_run()
点击"跳过"          →  TaskRow.skip_btn     →  TaskBridge     →  Scheduler.update_next_run(下一周期)
点击"单步执行"      →  TaskRow.step_btn     →  TaskBridge     →  event_bus: step_execute_requested

程序状态变化                程序模块             事件总线            UI模块
──────────                  ──────              ──────              ──────
任务开始            →  RunController        →  task_started    →  StatusBar刷新
步骤完成            →  TaskGraph            →  step_done       →  TaskListPanel刷新进度
连接断开            →  ConnectionManager    →  connection_lost →  StatusBar标红
运行状态变          →  StateManager         →  state_changed   →  StatusBar刷新
日志记录            →  Monitor              →  log_record      →  LogPanel追加
熔断触发            →  CircuitBreaker       →  circuit_tripped →  StatusBar告警
运行结束            →  RunController        →  run_summary     →  MonitorPanel显示摘要
```

---

## 五、关键设计决策

1. **三栏布局保留**：左菜单/中任务/右日志，与v0.5一致，用户已熟悉
2. **底部状态栏新增**：集中展示运行/连接/账号/操作次数，跨模块信息统一展示
3. **UI零逻辑**：所有操作通过传参模块→事件总线/配置模块传递，UI不含业务逻辑
4. **事件驱动刷新**：UI订阅事件自动更新，不轮询程序状态
5. **菜单自动生成**：任务列表扫描tasks/目录，新增任务自动出现
6. **可复用组件**：TaskRow/RepeatEditor/CountdownLabel抽到widgets/复用
7. **面板按需加载**：点击菜单项才初始化对应配置面板，减少启动开销
8. **配置面板弹出式**：点击左侧菜单项→中间区域切换为配置面板（或弹出对话框）
9. **运行监控面板**：v2.0新增，展示运行指标/异常截图/运行报告，帮助用户了解脚本运行状况
10. **日志导出功能**：右侧日志面板新增"导出日志"按钮，一键打包日志+截图+指标
