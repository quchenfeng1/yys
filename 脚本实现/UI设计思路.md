# UI设计思路 v3.0

> **文档性质**：基于16模块架构的UI设计  ｜  **版本**：v3.0（对齐实际7组菜单+内联面板）

---

## 一、UI整体布局

三栏 QSplitter 布局 + 底部状态栏。左侧 185px 固定宽度菜单树，中间可切换内容区，右侧日志+终端面板。

```
┌──────────────────────────────────────────────────────────────────────┐
│  阴阳师自动化脚本              [🔍 启动前自检] [🧪 沙盒模式]    [─][□][×] │
├──────────┬───────────────────────────────────┬───────────────────────┤
│          │ [▶ 启动] [■ 停止] [⏸ 暂停] ● 就绪  │ [📋日志][🖥终端]      │
│ 导航菜单  │───────────────────────────────────│                       │
│          │                                   │  📋 日志标签           │
│ 🎯全局控制│  🔵 当前任务                      │  [筛选▾] [清除] [导出] │
│          │  ┌─────────────────────────┐     │  ─────────────────    │
│ ⚙ 脚本配置│  │ 御魂副本  P:10  第15/30轮 │     │  🖥 终端标签（只读）   │
│  └ 模拟器 │  │ ■■■■■■■□□□ 50%          │     │  深色背景 + 自动着色   │
│ ⚙ 账号   │  └─────────────────────────┘     │  stdout/stderr 实时    │
│  └ 运行时段│                                   │                       │
│  └ 通知设置│  📋 任务队列                       │                       │
│ 🖼 图片配置│  ┌────┐ ┌────┐ ┌────┐          │                       │
│ 📋 任务管理│  │觉醒 │ │结界 │ │悬赏 │          │                       │
│ 🎮 游戏任务│  │P:10│ │P:10│ │P:1 │          │                       │
│ 📈 运行监控│  └────┘ └────┘ └────┘          │                       │
│ 👥 小号设置│                                   │                       │
│          │  ┌─ 📋 小号状态 ─────────────────┐  │                       │
│          │  │ sub1 ● scanning  检查协作      │  │                       │
│          │  │ sub2 ● idle      等待中        │  │                       │
│          │  │ sub3 ● teaming   组队战斗中    │  │                       │
│          │  └────────────────────────────────┘  │                       │
│ 👥 小号设置│                                   │                       │
├──────────┴───────────────────────────────────┴───────────────────────┤
│ ● 已停止 │ 🔌 未连接 │ 👤 — │ 🖱 0 次 │ 🧪 沙盒关 │ 📅 运行时段: 08-23 │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 二、菜单树（左侧 185px）

```python
class MenuTree(QWidget):
    """7 组一级菜单，点击切换到对应中间面板。"""

    # 实际菜单结构（来自 ui/panels/menu_tree.py）
    STRUCTURE = {
        "🎯 全局控制":   [],                                  # 无子菜单，直接切换到任务队列视图
        "⚙  脚本配置":   ["📡 模拟器连接", "👤 账号管理", "📊 任务优先级",
                        "🛡 防封号参数", "⏱ 运行时段", "� 通知设置",
                        "👥 阵容预设", "📝 日志配置"],
        "🖼  图片配置":   ["🏠 主界面", "🗺 探索", "✨ 召唤", "🛒 商城",
                        "⚔ 战斗", "🏯 阴阳寮", "🎪 活动", "🔧 通用", "👥 阵容"],
        "📋 任务管理":   ["📅 日常任务", "⚔ 常驻任务", "🎪 活动任务", "⭐ 特殊任务",
                        "🔧 通用模块", "🔨 特化模块"],
        "🎮 游戏任务":   ["📅 日常任务", "⚔ 常驻任务", "🎪 活动任务", "⭐ 特殊任务"],
        "📈 运行监控":   ["📊 运行指标", "📸 异常截图", "📄 运行报告", "📋 执行历史"],
        "👥 小号设置":   ["小号 1", "小号 2"],              # 动态填充
    }
```

**菜单路由机制**：每个叶子节点携带 `(kind, key)` 元组：

| kind | 含义 | 切换到 |
|------|------|--------|
| `dashboard` | 全局控制 | 任务队列视图（`_dashboard_stack`） |
| `config` | 脚本配置 | `ConfigPanel`（内联切换） |
| `image` | 图片配置 | `ImageManagerPanel` |
| `taskmgr` | 任务管理 | `TaskManagerPanel`（含 ClickableRow 列表 + NewTaskDialog） |
| `game` | 游戏任务 | 游戏任务面板（任务列表 + 配置表单） |
| `monitor` | 运行监控 | 运行指标 + 异常截图 + 运行报告 + 执行历史 |
| `sub_account` | 小号设置 | 小号状态监控面板（SubAccountStatusPanel） |

---

## 三、中心区域切换机制

中间区域是一个 `QScrollArea`，通过 `_switch_center(widget)` 方法替换其内部 widget：

```
menu_tree.on_item_clicked
  → _on_menu_clicked(item, (kind, key))
    → kind == "dashboard"  → _switch_center_dashboard()  → 显示任务队列
    → kind == "config"     → _switch_center(config_panel) → show_config(key)
    → kind == "image"      → _switch_center(image_panel)  → show_section(key)
    → kind == "taskmgr"    → _switch_center(task_mgr_panel) → show_section(key)
    → kind == "game"       → _switch_center(game_panel)   → 显示任务列表+配置
    → kind == "monitor"    → 显示占位
    → kind == "sub_account"→ 显示占位
```

**设计要点**：
- 所有面板**预先创建**，`hide()` 隐藏，切换时 `takeWidget()` + `setWidget()` + `show()`
- 不是销毁重建，避免重复初始化开销
- `_dashboard_stack`（任务队列）是默认视图，启动时显示

---

## 四、全局控制栏

位于中间区域顶部、任务队列上方。

```python
class ControlBar(QWidget):
    """启动/停止/暂停三按钮 + 沙盒开关 + 自检按钮 + 状态文字。"""

    # 信号
    start_clicked = pyqtSignal()   # → MainWindow._on_start()
    stop_clicked = pyqtSignal()    # → MainWindow._on_stop()
    pause_clicked = pyqtSignal()   # → MainWindow._on_pause()
    dry_run_toggled = pyqtSignal(bool)  # → 14-执行器.set_dry_run()
    self_check_clicked = pyqtSignal()   # → 16-应用启动引导.self_check()

    # 状态机
    # idle → (点击启动) → running → (点击停止) → idle
    # running → (点击暂停) → paused → (点击继续) → running
```

**按钮状态表**：

| 状态 | 启动按钮 | 停止按钮 | 暂停按钮 | 沙盒开关 | 自检按钮 | 状态文字 |
|------|---------|---------|---------|---------|---------|---------|
| 就绪 | ▶ 启动 (绿) | ■ 停止 (灰) | ⏸ 暂停 (灰) | 🧪 沙盒 (可切换) | 🔍 自检 (可用) | ● 就绪 (灰) |
| 运行中 | ▶ 运行中 (灰) | ■ 停止 (红) | ⏸ 暂停 (黄) | 🧪 沙盒 (禁用) | 🔍 自检 (禁用) | ● 运行中 (蓝) |
| 已暂停 | ▶ 继续 (蓝) | ■ 停止 (红) | ⏸ 暂停 (灰) | 🧪 沙盒 (禁用) | 🔍 自检 (禁用) | ⏸ 已暂停 (黄) |
| 沙盒模式 | ▶ 启动 (绿) | ■ 停止 (灰) | ⏸ 暂停 (灰) | 🧪 沙盒 (开/绿) | 🔍 自检 (可用) | 🧪 沙盒模式 (紫) |

---

## 五、任务队列面板

位于控制栏下方，实时展示调度器日程表。

```python
class TaskQueuePanel(QWidget):
    """当前任务（大卡片）+ 队列任务（小卡片），数据来自 Scheduler。"""

    def set_scheduler(self, scheduler):
        """MainWindow 初始化后注入 Scheduler 实例。"""
        self._scheduler = scheduler

    def refresh(self):
        """从 scheduler.get_all_tasks() 读取最新日程，重建卡片。"""
```

**数据流**：
```
Scheduler.build_schedule()
  → event_bus.publish(SCHEDULE_UPDATED)
    → TaskQueuePanel 订阅收到
      → QTimer.singleShot(0, self.refresh)  ← ★ 线程桥：EventBus 分发线程 → Qt 主线程
        → scheduler.get_all_tasks() → 排序 → 重建卡片
```

**卡片设计**：

| 属性 | 大卡片（当前执行中） | 小卡片（队列等待） |
|------|-------------------|------------------|
| 高度 | 90px | 60px |
| 内容 | 名称 + 优先级徽章 + 状态 + 进度条 | 名称 + 优先级 + 预计时间 |
| 颜色 | 蓝底 + 蓝色边框光晕 | 白底 + 灰色边框 |
| 运行时进度 | 已完成 N/M 轮，剩余约 XX 分钟 | 不显示 |
| 优先级徽章 | P1(红)→P2(橙)→P3(黄)→P5(绿)→P10(蓝)→P20(紫)→P99(灰) |

> **运行时进度**：大卡片从 `07-运行时状态管理.task_runtime_progress` 读取当前任务的 `completed/total`，计算剩余轮次和预估时间。右键大卡片可「重置进度」调 `09.reset_progress(task_name)`。

**★ 线程安全机制**：`TaskQueuePanel.refresh()` 涉及 QWidget 操作，必须在 Qt 主线程执行。EventBus 的事件分发在独立线程中进行，因此使用 `QTimer.singleShot(0, callback)` 将回调推迟到主线程事件循环。

---

## 六、游戏任务面板

点击「游戏任务」→ 子菜单（日常/常驻/活动/特殊），显示该分类的任务列表 + 点击后展示配置表单。

### 6.1 任务列表（上半部分）

```python
# 每个任务显示为 ClickableRow（QFrame），包含：
#   📅 ⚔ 御魂副本-八岐大蛇  自动刷御魂八岐大蛇第十层
#    ↑   ↑       ↑                    ↑
#  分类  类型   显示名              功能描述
```

**ClickableRow**：鼠标悬停高亮（#F5F8FF），点击触发 `_on_game_task_clicked(task_module)`。

**批量编辑模式**：任务列表顶部新增 [📝 批量编辑] 按钮，点击后进入批量选择模式：
```
[📝 批量编辑] → 每行左侧出现复选框 ☐
  → 勾选多个任务 → 弹出批量编辑对话框
    → 字段：优先级 / 重复规则 / 启用/禁用 / 每日上限
    → 调 10-参数桥接模块.batch_update(names, key, value)
    → 全部保存后刷新列表
```

### 6.2 任务配置表单（下半部分）

点击任务行后，下半部分显示配置表单：

```
┌─────────────────────────────────────────┐
│ 📋 「御魂副本-八岐大蛇」— 战斗任务  [💾 保存配置] │
├─────────────────────────────────────────┤
│ ☑ 启用此任务                            │
│ 优先级: [10]                             │
│                                          │
│ ── ⏱ 重复规则 ──                        │
│ 重复规则: [daily ▼]                      │
│ 开始时间: [08:00]    结束时间: [22:00]   │
│ 每周: [☑一][☑二][☑三][☑四][☑五][□六][□日]│
│ 间隔天数: [1]    间隔小时: [1.0]         │
│ 执行时间: [2026-08-01 10:00] (once)     │
│ 活动开始: [YYYY-MM-DD]  活动结束: [...] │
│                                          │
│ ── 📊 执行规则 ──                        │
│ 执行方式: [按次数 ▼]    执行值: [10]     │
│ 每日上限: [0 (不限)]                     │
│                                          │
│ 下次执行: [2026-07-21 08:00]             │
│ 阵容预设: [阵容1 ▼]                      │
└─────────────────────────────────────────┘
```

**表单字段显隐逻辑**：根据 `_cfg_repeat_type` 的选中值动态显示/隐藏对应字段：
- `daily` → 显示 开始时间 + 结束时间
- `weekly` → 显示 每周多选 + 开始时间 + 结束时间
- `interval_days` → 显示 间隔天数
- `interval_hours` → 显示 间隔小时
- `once` → 显示 执行时间
- `special` → 显示 活动开始 + 活动结束
- 阵容预设 → 仅在 `task_type == "battle"` 时显示

**保存流程**：
```
点击 [💾 保存配置]
  → _on_save_task_config()
    → 从表单控件收集配置字典
    → 更新 tasks.yaml（通过 ConfigManager）
    → Scheduler.update_next_run()
    → Scheduler.build_schedule()
    → event_bus.publish(SCHEDULE_UPDATED)
    → TaskQueuePanel 自动刷新
```

**活动日历导入**：配置表单顶部新增 [📅 导入活动日历] 按钮：
```
点击 [📅 导入活动日历]
  → 打开文件选择器（支持 .json / .yaml）
  → 选择活动日历文件
  → 调 05-时间调度模块.import_calendar(events)
  → 自动设置活动任务的 active_range
  → 刷新日程表
```

### 6.3 未来扩展：uses_* 动态配置区

`TaskModule` 已扩展 `uses_battle / uses_team / uses_soul / uses_stamina / loop_count` 字段。当这些字段被 UI 读取后，可按声明动态显隐配置区：

| task_module 字段 | UI 自动显示的配置区 |
|-----------------|-------------------|
| `uses_battle = True` | 阵容预设 + 御魂方案 + 失败容忍 |
| `uses_team = True` | team_id 下拉框 |
| `uses_soul = True` | 御魂配置编辑区 |
| `uses_stamina = True` | 体力门槛数值 |
| `loop_count > 1` | 每轮循环次数输入 |

> **当前状态**：`uses_*` 字段已被 `TaskManager._parse_file()` 解析并存入 `TaskModule`，但 UI 的 `_on_game_task_clicked()` 尚未使用这些字段来动态显隐配置区。这是下一个待实现的 UI 增强。

---

## 七、任务管理面板

点击「任务管理」→ 子菜单，提供任务文件的开发管理功能（区别于「游戏任务」的配置功能）。

```python
class TaskManagerPanel(QWidget):
    """任务文件管理器。ClickableRow 列表 + 点击选中 + 下方模块标签。"""

    # 列表项（ClickableRow）
    #   📅 ⭐ 御魂副本-八岐大蛇  自动刷御魂八岐大蛇第十层  [打开] [删除]
    #    ↑   ↑         ↑                    ↑              ↑      ↑
    #  分类 类型图标   显示名              描述         打开.py  删除

class NewTaskDialog(QDialog):
    """新建任务对话框。
    字段：任务名称 / 显示名 / 分类(daily等) / 任务类型(battle/event_task)
    → 调用 task_mgr.new_task() → 生成五段骨架 .py 文件
    """
```

**ClickableRow 交互**：
- 点击行 → 选中高亮 → 下方显示该任务的通用模块标签列表
- [打开] 按钮 → `task_mgr.open_file(module)` → `os.startfile()` 打开 VSCode
- [删除] 按钮 → `task_mgr.delete_task(module)` → 重命名为 `.deleted`

**通用/特化模块视图**：子菜单"通用模块"/"特化模块"切换为模块列表，每个模块行显示名称 + 描述 + [打开] 按钮，只能查看不能删除。

---

## 八、图片配置面板

点击「图片配置」→ 子菜单选分区，显示该分区的图片管理界面。

```python
class ImageManagerPanel(QWidget):
    """可视化素材管理。左侧分区列表 + 右侧图片列表。"""

    # 左侧：9 个场景分区（主界面/探索/召唤/商城/战斗/阴阳寮/活动/通用/阵容）
    #       每个分区显示图标 + 名称 + 图片数量

    # 右侧：当前分区的图片列表（缩略图 + 名称 + 备注 + 尺寸）
    #       操作：添加(从本地选择PNG) / 删除 / 编辑备注 / 预览(真实尺寸)
```

---

## 八-E 运行监控 - 执行历史面板

子菜单「📋 执行历史」点击后展示单任务执行明细：

```python
class ExecutionHistoryPanel(QWidget):
    """按任务名+日期筛选，展示执行历史记录。"""

    # 筛选区：任务名下拉 + 日期选择器
    # 列表：每次执行一行：时间 | 结果(成功/失败) | 耗时 | 完成轮次/总轮次
    # 数据来源：12-日志监控中心.query_task_history(task_name, date)
    # 每行可展开查看详细日志
```

---

## 九、脚本配置面板

点击「脚本配置」→ 子菜单，内联显示对应配置表单。

```python
class ConfigPanel(QWidget):
    """内联配置面板。根据 key 切换内容。"""

    def show_config(self, key: str):
        """key = "emulator" | "account" | "priority" | "anti_detect"
                | "runtime" | "notification" | "teams" | "log"
        """
        # emulator:     模拟器类型下拉 + ADB端口 + 自定义路径 + 测试连接
        # anti_detect:  点击偏移/滑动时长/操作间隔/走神概率 等滑块
        # runtime:      运行时段 [08:00] ~ [23:00] + 定时启动 [06:00] + 定时停止 [23:00]
        # notification: 桌面弹窗 [☑] + 声音提示 [☑] + Webhook URL [____________]
        # log:          日志级别 + 保留天数 + 结构化开关
        # 其余:         显示"功能尚未实现"占位
```

---

## 十、日志 + 终端面板（右侧）

```python
class LogPanel(QWidget):
    """QTabWidget 双标签：日志 + 内置终端。"""

    # 「📋 日志」标签：结构化日志流
    #   - 订阅 event_bus 的 log_record 事件
    #   - 级别筛选 (DEBUG/INFO/WARNING/ERROR)
    #   - [清除] [导出] 按钮

    # 「🖥 终端」标签：内置只读终端
    #   - OutputRedirector 捕获 sys.stdout / sys.stderr
    #   - 深色背景 + Consolas 等宽字体
    #   - 自动着色：[INFO]=绿 [WARNING]=橙 [ERROR]=红 [DEBUG]=灰
    #   - 只读不可编辑，替代外部 PowerShell 黑窗口
```

---

## 十一、小号状态监控面板

位于中间区域任务队列面板下方，实时展示各小号当前状态。

```python
class SubAccountStatusPanel(QWidget):
    """小号状态监控。数据来源：07.sub_account_status。"""

    # 每 2 秒从 07 状态管理拉取最新状态
    # 每个小号显示为 SubAccountCard（QFrame）
    #   ├── sub1 ● scanning 检查协作    2/3
    #   ├── sub2 ● teaming  组队战斗    第15轮
    #   └── sub3 ● idle     等待中
    #
    # 状态色阶：
    #   idle(灰) → login(蓝) → scanning(黄)
    #   → teaming(绿) → battling(红) → error(暗红)
```

与任务队列的布局关系：

```
┌─────────────────────────────────┐
│  🔵 当前任务（大卡片）            │
│  ┌─────────────────────────┐   │
│  │ 御魂副本  第15/30轮  50% │   │
│  └─────────────────────────┘   │
│                                 │
│  📋 任务队列                    │
│  ┌────┐ ┌────┐ ┌────┐         │
│  │觉醒 │ │结界 │ │悬赏 │         │
│  └────┘ └────┘ └────┘         │
│                                 │
│  ── ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─    │  ← 分割线
│                                 │
│  📋 小号状态                    │
│  ├─ sub1 ● scanning 检查协作   │
│  ├─ sub2 ● idle     等待中     │
│  └─ sub3 ● teaming  组队战斗   │
└─────────────────────────────────┘
```

## 十二、底部状态栏

```python
class StatusBar(QWidget):
    """底部状态栏，展示 6 项全局指标。"""

    # ● 已停止 / ● 运行中 / ⏸ 已暂停 / ⚠ 异常     ← run_status
    # 🔌 未连接 / 🔌 已连接                           ← connection
    # 👤 — / 👤 主号                                   ← current_account
    # 🖱 0 次                                          ← today_ops
    # 🧪 沙盒关 / 🧪 沙盒开                            ← dry_run_mode
    # 📅 时段: 08-23 / 📅 无限制                       ← run_window
```

状态更新通过 `event_bus` 订阅 `STATE_CHANGED` 事件，主线程直接更新（StatusBar 始终在主线程）。

---

## 十二、事件驱动刷新机制

UI 通过订阅 EventBus 事件自动刷新，不轮询程序状态：

| 事件 | 发布者 | UI 订阅者 | 刷新行为 |
|------|--------|----------|---------|
| `SCHEDULE_UPDATED` | Scheduler | TaskQueuePanel | 重建队列卡片 |
| `TASK_STARTED` | ScriptWorker | TaskQueuePanel | 高亮当前任务卡片 |
| `TASK_DONE` | ScriptWorker | TaskQueuePanel | 清除当前任务，刷新队列 |
| `STATE_CHANGED` | StateManager | StatusBar + ControlBar | 更新状态文字和按钮 |
| `LOG_RECORD` | Monitor | LogPanel | 追加日志行 |
| `notify_alert` | Monitor | MainWindow（弹窗/声音） | 推送通知给用户 |
| `preflight_complete` | Bootstrap | MainWindow | 展示自检结果弹窗 |
| `assets_missing` | TaskManager | ImageManagerPanel | 提示缺失素材 |
| `scene_unknown` | Executor | TaskQueuePanel | 提示未知场景 |
| `task_file_created` | TaskManager | TaskManagerPanel | 刷新任务列表 |

**线程安全**：EventBus 在独立线程分发事件。涉及 QWidget 操作的回调通过 `QTimer.singleShot(0, callback)` 桥接到 Qt 主线程。

---

## 十三、模块间协作（当前实现）

```
MainWindow (11-用户界面模块)
  │
  ├── 直接持有 ──→ 06-配置管理中心    ← 读写配置
  ├── 直接持有 ──→ 13-任务文件管理    ← 扫描/创建/删除任务
  ├── 直接持有 ──→ ImageManager       ← 素材管理
  ├── 直接持有 ──→ 05-时间调度模块    ← 日程表 + 注入到 ScriptWorker
  ├── 传参绑定 ──→ 10-参数桥接模块    ← UI 控件 ↔ 配置双向同步
  │
  ├── 自检 ──→ 16-应用启动引导.self_check() → 弹窗展示结果
  ├── 通知 ──→ 12-日志监控中心.notify() → 桌面弹窗/声音
  │
  ├── 创建 ──→ 09-运行控制中心 (QThread)
  │              ├── 注入 Scheduler
  │              └── 创建 14-执行器 → 02-图像识别 + 03-防封策略 + 01-设备连接
  │
  ├── 子面板 ──→ ControlBar / TaskQueuePanel / LogPanel / StatusBar
  ├── 可切换 ──→ ConfigPanel / ImageManagerPanel / TaskManagerPanel / 游戏任务面板
  │
  └── 订阅 ──→ 08-事件通信总线 ← 所有模块发布事件
```

> **注意**：当前 MainWindow 直接持有核心模块引用，未经过 `10-参数桥接`。参数桥接模块为设计目标层，计划在未来版本中作为 UI↔逻辑的唯一中转通道。

---

## 十四、关键设计决策

1. **三栏布局保留**：左菜单/中内容/右日志，与 v0.5 一致
2. **中心区域可切换**：QScrollArea + takeWidget/setWidget，不是 QStackedWidget（避免所有面板同时占据内存）
3. **菜单路由化**：每个菜单项携带 `(kind, key)`，由 MainWindow 统一分发
4. **UI 零逻辑**：UI 只负责展示和接收输入，所有逻辑通过 ConfigManager/EventBus 传递给程序
5. **事件驱动刷新**：UI 订阅事件自动更新，不主动轮询
6. **QTimer.singleShot 线程桥**：EventBus 分发线程 → 主线程的安全通道
7. **ClickableRow 替代 QListWidget**：解决 `setItemWidget` 导致的滚动定位错乱
8. **配置内联非弹窗**：脚本配置/任务配置全部在中间区域展示，不弹对话框
9. **游戏任务与任务管理分离**：前者面向运行配置，后者面向开发编辑
10. **uses_* 声明驱动 UI**：任务文件声明能力 → TaskManager 解析 → UI 动态显隐配置区（部分已实现）
11. **底部状态栏集中展示**：运行/连接/账号/操作次数跨模块统一展示
12. **内置终端替代黑窗口**：OutputRedirector 捕获 stdout/stderr，pythonw 无窗口运行
