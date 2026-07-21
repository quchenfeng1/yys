# UI设计思路 v3.1

> **文档性质**：基于16模块架构的UI设计  ｜  **版本**：v3.1（沙盒+自检已实现，运行监控/小号面板为设计目标）

---

## 一、UI整体布局

三栏 QSplitter 布局 + 底部状态栏。左侧 185px 固定宽度菜单树，中间可切换内容区，右侧日志+终端面板。

```
┌──────────────────────────────────────────────────────────────────────┐
│  阴阳师自动化脚本                                    [─][□][×] │
├──────────┬───────────────────────────────────┬───────────────────────┤
│          │ [▶ 启动] [■ 停止] [⏸ 暂停] ● 就绪  [🧪沙盒] [🔍自检] │ [📋日志][🖥终端]
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
│ ● 已停止 │ 🔌 未连接 │ 👤 — │ 🖱 0 次 │ 🧪 沙盒关 │ 📅 — │
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
                        "🛡 防封号参数", "⏱ 运行时段",
                        "👥 阵容预设", "📝 日志配置"],
        "🖼  图片配置":   ["🏠 主界面", "🗺 探索", "✨ 召唤", "🛒 商城",
                        "⚔ 战斗", "🏯 阴阳寮", "🎪 活动", "🔧 通用", "👥 阵容"],
        "📋 任务管理":   ["📅 日常任务", "⚔ 常驻任务", "🎪 活动任务", "⭐ 特殊任务",
                        "🔧 通用模块", "🔨 特化模块"],
        "🎮 游戏任务":   ["📅 日常任务", "⚔ 常驻任务", "🎪 活动任务", "⭐ 特殊任务"],
        "📈 运行监控":   ["📊 运行指标", "📸 异常截图", "📄 运行报告", "📋 执行历史"],
        "👥 小号设置":   ["⚙ 小号配置"],              # 动态填充N个小号
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
| `sub_account` | 小号配置 | `SubAccountConfigPanel`（小号列表+增删改+模拟器/识别/组队配置） |
| `sub_account_detail` | 指定小号详情 | 同面板，切换到指定小号的配置表单 |

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
    → kind == "sub_account"→ _switch_center(sub_account_panel) → 显示小号配置列表
    → kind == "sub_account_detail"→ sub_account_panel.show_account(key)
```

**设计要点**：
- 所有面板**预先创建**，`hide()` 隐藏，切换时 `takeWidget()` + `setWidget()` + `show()`
- 不是销毁重建，避免重复初始化开销
- `_dashboard_stack`（任务队列）是默认视图，启动时显示

---

## 四、全局控制栏

位于中间区域顶部、任务队列上方。

> **架构说明**：当前实现使用 `ScriptWorker`（QThread 简化路径）直接驱动执行。
> 09-运行控制中心模块定义的完整 `RunController` 三线程模型（填充+执行+扫描）
> 作为未来升级路径保留。两者的接口通过 EventBus 事件对齐，
> ScriptWorker 发布相同的 `TASK_STARTED`/`TASK_DONE` 等事件。

```python
class ControlBar(QWidget):
    """启动/停止/暂停三按钮 + 沙盒开关 + 自检按钮 + 状态文字。"""

    # 信号 (✅ 全部已实现)
    start_clicked = pyqtSignal()       # → MainWindow._on_start()
    stop_clicked = pyqtSignal()        # → MainWindow._on_stop()
    pause_clicked = pyqtSignal()       # → MainWindow._on_pause() 发布 PAUSE_REQUESTED
    resume_clicked = pyqtSignal()      # → MainWindow._on_resume() 发布 RESUME_REQUESTED
    dry_run_toggled = pyqtSignal(bool) # → Executor.set_dry_run()
    self_check_clicked = pyqtSignal()  # → ADB/素材/配置自检

    # ★ 暂停按钮为三态：暂停(⏸) / 继续(▶) / 停止中(⏳)
    # 状态机
    # idle → (▶启动) → running → (⏸暂停) → paused → (▶继续) → running
    # running/paused → (■停止) → stopping → idle
```

**按钮状态表**：

| 状态 | 启动按钮 | 停止按钮 | 暂停/继续按钮 | 沙盒开关 | 自检按钮 | 状态文字 |
|------|---------|---------|-------------|---------|---------|---------|
| 就绪 | ▶ 启动 (绿) | ■ 停止 (灰禁用) | ⏸ 暂停 (灰禁用) | 🧪 (可切换) | 🔍 (可用) | ● 就绪 (灰) |
| 运行中 | ▶ 运行中 (灰禁用) | ■ 停止 (红) | ⏸ 暂停 (黄) | 🧪 (禁用) | 🔍 (禁用) | ● 运行中 (蓝) |
| 已暂停 | ▶ 继续 (蓝) | ■ 停止 (红) | ⏸ 已暂停 (灰禁用) | 🧪 (禁用) | 🔍 (禁用) | ⏸ 已暂停 (黄) |
| 停止中 | ▶ — (灰禁用) | ⏳ 停止中 (橙) | ⏸ — (灰禁用) | 🧪 (禁用) | 🔍 (禁用) | ⏳ 停止中 (橙) |
| 沙盒模式 | ▶ 启动 (绿) | ■ 停止 (灰禁用) | ⏸ 暂停 (灰禁用) | 🧪 沙盒开 (绿) | 🔍 (可用) | 🧪 沙盒模式 (紫) |

**与 09-运行控制中心的联动**：

| ControlBar 操作 | 发布的事件 | RunController 响应 |
|----------------|-----------|-------------------|
| 点击「启动」 | `START_REQUESTED` | `_on_start()` → 三线程启动 |
| 点击「暂停」 | `PAUSE_REQUESTED` | `_on_pause()` → 置 PAUSED |
| 点击「继续」 | `RESUME_REQUESTED` | 恢复 RUNNING |
| 点击「停止」 | `STOP_REQUESTED` | `stop()` → 保存进度 → RUN_STOPPED |

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
- `expire_at` → 显示 失效时间 (at字段)
- `special` → 显示 活动开始 + 活动结束
- `monthly_start` → 无额外字段（每月1号自动触发）
- 阵容预设 → 仅在 `task_type == "battle"` 时显示
- 活动有效期（`active_range`）→ 所有类型通用，始终显示

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

### 通用模块完整清单（12 个，来自 04-任务执行引擎）

| 模块 | 类名 | 用途 | UI 可见位置 |
|------|------|------|-----------|
| `close_popup` | `ClosePopup` | 关闭公告/提示弹窗 | 任务管理 → 通用模块 |
| `check_stamina` | `CheckStamina` | 体力检查 | 任务管理 → 通用模块 |
| `open_bottom_menu` | `OpenBottomMenu` | 主界面识别+展开菜单 | 任务管理 → 通用模块 |
| `pre_check_team` | `PreCheckTeam` | 战斗前阵容校验 | 任务管理 → 通用模块 |
| `select_team` | `SelectTeam` | 对局内选阵容 | 任务管理 → 通用模块 |
| `battle_loop` | `BattleLoop` | 战斗循环+结算 | 任务管理 → 通用模块 |
| `claim_reward` | `ClaimReward` | 领取奖励 | 任务管理 → 通用模块 |
| `return_hall` | `ReturnHall` | 返回庭院 | 任务管理 → 通用模块 |
| `error_return` | `ErrorReturn` | 错误恢复路径 | 任务管理 → 通用模块 |
| `coop_host` | `CoopHost` | 组队主机(创建队伍→开战) | 任务管理 → 通用模块 |
| `coop_join` | `CoopJoin` | 组队成员(接受邀请→准备) | 任务管理 → 通用模块 |
| `coop_passive` | `CoopPassive` | 组队待机(被带方自动领奖) | 任务管理 → 通用模块 |

### 运行时执行状态（任务队列面板 + 状态栏）

任务执行时，以下 04 模块状态通过 UI 实时展示：

| 状态 | UI 展示位置 | 数据来源 |
|------|-----------|---------|
| `current_task` (当前任务名) | StatusBar + TaskQueuePanel 大卡片 | StateManager |
| `current_step` (当前步骤名) | TaskQueuePanel 进度文字 | StateManager / EventBus STEP_DONE |
| `task_progress` (15/30) | TaskQueuePanel 进度条 | StateManager |
| `step_result` (success/fail/skip) | LogPanel 日志流 | EventBus STEP_DONE |
| `task_result` (success/fail/timeout) | LogPanel + StatusBar | EventBus TASK_DONE |

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
    #       顶部工具栏：[🔄 重载素材] 按钮 → 调 Recognizer.reload()

    # 底部状态栏：素材总数 | 当前分区数量 | 上次识别耗时
```

### 识别参数配置（位于脚本配置面板）

识别参数（阈值/灰度/OCR）属于全局配置，放在「⚙ 脚本配置」面板中：

```python
class RecognizerConfigWidget(QWidget):
    """图像识别全局参数配置。"""

    # 模板匹配
    #   默认阈值: [0.80]  (0.5~1.0, 步长0.05)
    #   ☑ 灰度匹配 (推荐开启，速度更快)
    #   ☐ 多尺度匹配 (缩放偏差时启用，速度较慢)

    # OCR (预留)
    #   ☐ 启用 OCR 文字定位
    #   语言: [chi_sim ▼]

    # 缓存
    #   结果缓存TTL: [1.0] 秒
    #   截图缓存TTL: [0.5] 秒
```

**关联模块方法**：
- `Recognizer.reload()` — 素材重载
- `Recognizer.suggest_template(screenshot)` — 未知场景自动收藏
- `Recognizer.list_templates()` — 列出所有素材名
- `Recognizer.has_template(name)` — 检查素材是否存在

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
        # emulator:     模拟器类型下拉 + ADB端口 + 自定义路径
        #               + [测试连接] 按钮 + 分辨率（只读）+ 心跳间隔
        #               + App包名/Activity配置
        #               + 连接质量（延迟/成功率，只读）
        # anti_detect:  点击偏移/延迟抖动/最小间隔/走神概率/每日上限
        #               + 行为档案预设 (SAFE/NORMAL/FAST/DEBUG)
        #               + 操作审计日志导出
        #               + 今日操作计数/运行时长（只读）
        # runtime:      运行时段 [08:00] ~ [23:00] + 定时启动 [06:00] + 定时停止 [23:00]
        # notification: 桌面弹窗 [☑] + 声音提示 [☑] + Webhook URL [____________]
        # log:          日志级别 + 保留天数 + 结构化开关
        # 其余:         显示"功能尚未实现"占位
```

---

## 十、日志 + 终端面板（右侧 ↔ 12-日志监控中心）

> 数据源：`12-日志监控中心.Monitor.log()` → `LOG_RECORD` 事件 → LogPanel 订阅显示。
> 日志检索：`Monitor.query_logs()` 支持按级别/模块/任务/时间/关键词检索。

```python
class LogPanel(QWidget):
    """QTabWidget 双标签：日志 + 内置终端。"""

    # 「📋 日志」标签：结构化日志流
    #   - 订阅 event_bus 的 log_record 事件（12 模块发布）
    #   - 级别筛选 (DEBUG/INFO/WARNING/ERROR)
    #   - 关键词搜索 [____________] [🔍]
    #   - [清除] [导出] 按钮
    #   - 动态日志行数上限：set_max_lines()（UI 自控）

    # 「🖥 终端」标签：内置只读终端
    #   - OutputRedirector 捕获 sys.stdout / sys.stderr
    #   - 深色背景 + Consolas 等宽字体
    #   - 自动着色：[INFO]=绿 [WARNING]=橙 [ERROR]=红 [DEBUG]=灰
    #   - 只读不可编辑，替代外部 PowerShell 黑窗口
```

### 运行监控子面板（12 模块 UI）

| 菜单项 | 面板 | 数据来源 | 说明 |
|--------|------|---------|------|
| 📊 运行指标 | `MetricsPanel` | `Monitor.get_all_metrics()` | 表格：任务名/次数/成功率/耗时/最后执行，5s 刷新 |
| 📸 异常截图 | `SnapshotViewer` | `logs/snapshots/` | 左列表+右预览+上下文 JSON |
| 📄 运行报告 | `ReportViewer` | `Monitor.generate_daily/weekly_report()` | Markdown 渲染 + 导出 |
| 📋 执行历史 | `ExecutionHistoryPanel` | `Monitor.query_task_history()` | 按任务+日期筛选明细 |

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
    """底部状态栏，展示 9 项全局指标，全部来自 07-运行时状态管理模块。"""

    # 运行状态  ← run_status                   "stopped"/"running"/"paused"/"error"/"stopping"
    # ● 已停止 / ● 运行中 / ⏸ 已暂停 / ⚠ 异常 / ⏳ 停止中

    # 连接状态  ← connection_status            "disconnected"/"connected"/"reconnecting"
    # 🔌 未连接 / 🔌 已连接（延迟 ms）/ 🔌 重连中...

    # 当前任务  ← current_task + current_step  "yuhun" + "进入战斗"
    # 📋 无任务 / 📋 魂十·进入战斗

    # 当前场景  ← current_scene                "courtyard"/"battle"/"explore"/...
    # 🏠 庭院 / ⚔ 战斗 / 🌲 探索 / ⏳ 加载 / ❓ 未知

    # 当前账号  ← current_account              "main"/"sub1"/"sub2"
    # 👤 主号 / 👤 小号1 / 👤 小号2

    # 今日操作  ← today_operation_count        int
    # 🖱 0 次 / 🖱 1,234 次

    # 运行上限  ← run_limit_reached            bool
    # （触发时显示）⛔ 已达上限 — 红色醒目

    # 沙盒模式  ← dry_run（UI 内部状态）         bool
    # 🧪 沙盒关 / 🧪 沙盒开

    # 运行时段  ← run_window 配置              "08:00"~"23:00"
    # 📅 08:00-23:00 / 📅 不限
```

### 状态刷新机制

StatusBar 通过 **两种渠道** 接收更新：

| 渠道 | 适用场景 | 说明 |
|------|---------|------|
| `event_bus.subscribe(STATE_CHANGED)` | `run_status`/`connection_status`/`current_task`/`current_scene`/`current_account`/`today_operation_count`/`run_limit_reached` | 07 模块 set_state 自动广播，MainWindow._on_state_changed() 分发到 StatusBar |
| 直接方法调用 | `dry_run`/`run_window` | UI 内部状态，不走事件总线 |

`STATE_CHANGED` 回调通过 `QTimer.singleShot(0, callback)` 桥接到 Qt 主线程，确保 QWidget 操作线程安全。

---

## 十三、事件驱动刷新机制（对齐 08-事件通信总线）

UI 通过订阅 EventBus 事件自动刷新，不轮询程序状态。

### 13.1 EventBus 事件订阅表

以下事件全部通过 `event_bus.subscribe()` 注册，与 08-事件通信总线模块完全对齐：

| 事件名 | 发布者 | UI 订阅者 | 刷新行为 |
|--------|--------|----------|---------|
| `SCHEDULE_UPDATED` | Scheduler (05) | TaskQueuePanel | 重建队列卡片 |
| `TASK_DUE` | Scheduler (05) | RunController (09) | 触发出队执行 |
| `DAILY_RESET` | Scheduler (05) | StateManager (07) | 重置每日计数 |
| `TASK_STARTED` | RunController (09) | TaskQueuePanel + StatusBar | 高亮当前任务卡片 |
| `TASK_DONE` | RunController (09) | TaskQueuePanel + Scheduler | 清除当前任务，刷新队列 |
| `STEP_DONE` | TaskGraph (04) | LogPanel + StatusBar | 追加步骤结果日志 |
| `TASK_SKIPPED` | Scheduler (05) | TaskQueuePanel + LogPanel | 标记跳过，追加日志 |
| `STATE_CHANGED` | StateManager (07) | StatusBar + ControlBar | 更新全部状态指标 |
| `CONFIG_CHANGED` | ConfigManager (06) | 各配置面板 | 提示热重载 |
| `ACCOUNT_SWITCHED` | Connection (01) | StateManager + StatusBar | 切换账号显示 |
| `RUN_STARTED` | RunController (09) | StatusBar + ControlBar | 按钮切换 + 状态更新 |
| `RUN_PAUSED` | RunController (09) | StatusBar + ControlBar | 按钮切换 |
| `RUN_STOPPED` | RunController (09) | StatusBar + ControlBar | 恢复空闲态 |
| `RUN_LIMIT_REACHED` | AntiDetect (03) | StatusBar + ControlBar | 显示红色上限警告 |
| `CONNECTION_LOST` | Connection (01) | StatusBar + ControlBar | 连接断开提示 |
| `CONNECTION_RESTORED` | Connection (01) | StatusBar | 连接恢复提示 |
| `CONNECTION_ERROR` | Connection (01) | LogPanel | 追加错误日志 |
| `LOG_RECORD` | Monitor (12) | LogPanel | 追加日志行 |
| `ERROR_OCCURRED` | 任意模块 | LogPanel + Monitor | 错误日志 + 截图保存 |

### 13.2 非 EventBus 的 UI 刷新（直接方法调用）

以下通知不走 EventBus，而是通过 **Qt 信号/槽** 或 **直接方法调用** 实现：

| 通知 | 来源 | 目标 | 方式 |
|------|------|------|------|
| `notify_alert` | Monitor.notify() | MainWindow 弹窗/声音 | 直接调用 |
| `preflight_complete` | Bootstrap | MainWindow 自检弹窗 | 启动时直接调用 |
| `assets_missing` | TaskManager | ImageManagerPanel | Qt 信号 |
| `scene_unknown` | Executor | TaskQueuePanel | 状态写入 StateManager |
| `task_file_created` | TaskManager | TaskManagerPanel | Qt 信号 |

### 13.3 线程安全

---

## 十四、模块间协作（当前实现）

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

> **注意**：当前 MainWindow 直接持有核心模块引用，未经过 `10-参数桥接`。
> 详见 [§十六 参数桥接模块](#十六参数桥接模块10-参数桥接模块) 了解桥接接口和迁移路径。

---

## 十五、关键设计决策

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

---

## 十六、参数桥接模块（10-参数桥接模块）

### 16.1 定位

参数桥接模块是 UI 与程序逻辑之间的**唯一数据通道**。设计目标：UI 控件不直接调用程序模块，全部经由桥接层中转。

```
用户操作 → UI 控件 → 10-参数桥接 → ConfigManager / EventBus → 程序逻辑
程序状态 → StateManager → EventBus → 10-参数桥接 → UI 控件自动刷新
```

### 16.2 子模块

| 子模块 | 文件 | 职责 | 实现状态 |
|--------|------|------|---------|
| `RunBridge` | `run_bridge.py` | 启停按钮 ↔ EventBus（START/STOP/PAUSE/RESUME_REQUESTED） | ✅ 完整 |
| `TaskBridge` | `task_bridge.py` | 任务行控件 ↔ Config + Scheduler（启用/优先级/倒计时/跳过） | ✅ 完整 |
| `UIBinding` | `ui_binding.py` | 通用控件 ↔ 配置/状态双向绑定（checkbox/spinbox/label） | ✅ 完整 |
| `AccountBridge` | `account_bridge.py` | 账号管理 ↔ Config + StateManager | ✅ 基础 |
| `ConfigBridge` | `config_bridge.py` | 全局配置 ↔ ConfigManager（热重载/校验/导入导出） | ✅ 基础 |
| `TaskParamSchema` | `schemas.py` | 参数 schema 定义（类型/标签/默认值/取值范围） | ✅ 完整 |

### 16.3 RunBridge 接口

```python
class RunBridge:
    bind_start_button(button)      # → START_REQUESTED
    bind_stop_button(button)       # → STOP_REQUESTED
    bind_pause_button(button)      # → PAUSE_REQUESTED
    bind_resume_button(button)     # → RESUME_REQUESTED
    bind_status_label(label)       # ← run_status 只读显示
    bind_current_task_label(label) # ← TASK_STARTED/TASK_DONE
```

### 16.4 TaskBridge 接口

```python
class TaskBridge:
    bind_enabled_checkbox(cb, name)      # 启用开关 ↔ config
    bind_priority_spinbox(sb, name)      # 优先级 ↔ config
    bind_next_run_display(label, name)   # 倒计时 ← scheduler
    bind_skip_button(btn, name)          # 跳过本次 → scheduler
    bind_single_step_button(btn, name, cb) # 单步执行 → callback
```

### 16.5 当前集成状态

> **现状**：MainWindow 当前**直接持有**核心模块引用（ConfigManager/Scheduler/StateManager），
> 未经过 10-参数桥接。`param_bridge/` 代码已完成并通过接口对齐，
> 作为未来 UI↔逻辑解耦的迁移目标。迁移时只需将 MainWindow 中的
> `config.get/set` 调用和 `event_bus.publish` 调用替换为桥接绑定即可。
>
> **已对齐的接口**：
> - ControlBar 信号（start/stop/pause/resume）→ RunBridge 方法一一对应
> - TaskQueuePanel 中的启用/优先级/倒计时 → TaskBridge 方法一一对应
> - StatusBar 只读状态 → UIBinding.bind_label 可覆盖
> - ConfigPanel 各配置表单 → ConfigBridge 待迁移

---

## 十七、用户界面模块（11-用户界面模块）

### 17.1 定位

11 模块是 UI 的架构总管。它定义了 UI 的整体结构、子面板划分、以及 UI 自身行为的元控能力。

```
11-用户界面模块
  ├── main_window.py          ← 主窗口（三栏布局 + 路由分发）
  ├── panels/                 ← 12 个子面板（各司其职）
  │   ├── menu_tree.py        ← 左菜单树（8 大类 30+ 菜单项）
  │   ├── control_bar.py      ← 全局控制栏（启停/暂停/恢复/沙盒/自检）
  │   ├── task_queue_panel.py ← 任务队列卡片（当前任务 + 队列）
  │   ├── log_panel.py        ← 日志终端（双标签：日志流 + 终端）
  │   ├── status_bar.py       ← 底部状态栏（9 项指标）
  │   ├── config_panel.py     ← 脚本配置面板（8 个子表单）
  │   ├── image_manager_panel.py ← 素材管理
  │   ├── task_manager_panel.py  ← 任务文件管理
  │   ├── game_task_panel.py  ← 游戏任务（列表 + 配置表单）
  │   ├── sub_account_panel.py   ← 小号配置
  │   ├── ui_settings_panel.py   ← ★ UI 自身设置（元控）
  │   └── execution_history.py   ← 执行历史
  └── widgets/                ← 4 个可复用组件
      ├── task_row.py         ← 任务行（启用/优先级/状态/跳过/单步）
      ├── repeat_editor.py    ← 执行规则编辑器（8 种类型）
      ├── countdown_label.py  ← 倒计时标签（1s 刷新，颜色分级）
      └── team_editor.py      ← 阵容编辑器（式神+御魂）
```

### 17.2 UI 自控（用 UI 控制 UI）

通过 🎨 **UI 设置** 面板，用户可在界面内控制界面行为：

| 设置项 | 作用 | 生效方式 |
|--------|------|---------|
| 主题（浅色/深色/系统） | 全局配色切换 | 即时 |
| 字号（11-16px） | 全局字体大小 | 即时 |
| 面板显隐开关 | 独立控制状态栏/控制栏/日志/菜单树 | 即时 |
| 日志自动滚动 | 新日志到达时自动滚到底部 | 即时 |
| 停止时确认 | 点击停止时弹出确认框 | 即时 |
| 刷新间隔 | 队列/状态刷新频率 | 即时 |
| 日志行数上限 | 超出自动截断旧日志 | 即时 |
| 动画效果 | 面板切换动画开关 | 即时 |

### 17.3 菜单路由表

| 菜单 | kind | 路由 | 目标面板 |
|------|------|------|---------|
| 🎯 全局控制 | dashboard | `_switch_center_dashboard()` | TaskQueuePanel |
| ⚙ 脚本配置 → * | config | `_show_config(key)` | ConfigPanel |
| 🖼 图片配置 → * | image | `_show_image(key)` | ImageManagerPanel |
| 📋 任务管理 → * | taskmgr | `_show_taskmgr(key)` | TaskManagerPanel |
| 🎮 游戏任务 → * | game | `_show_game(key)` | GameTaskPanel |
| 📈 运行监控 → history | monitor | `_switch_center(execution_history)` | ExecutionHistory |
| 📈 运行监控 → 其他 | monitor | `_show_placeholder()` | 占位符 |
| 🎨 UI 设置 | ui_settings | `_switch_center(ui_settings_panel)` | UISettingsPanel |
| 👥 小号设置 | sub_account | `_show_sub_account()` | SubAccountConfigPanel |

---

## 十八、任务文件管理（13-任务文件管理模块）

### 18.1 定位

13 模块是任务文件的开发时管理工具，与 04-任务执行引擎（运行时）分工明确：
- **13 模块**：扫描/创建/删除/编辑 .py 任务文件
- **04 模块**：加载/执行任务逻辑

### 18.2 TaskManagerPanel 结构

```python
class TaskManagerPanel(QWidget):
    """任务管理面板 — 上列表 + 下详情。"""

    # 上：任务列表（QScrollArea + ClickableRow）
    #   - 分组标题行（不可点击）
    #   - 每行：名称 + 类型徽章 + [打开编辑] [删除]
    #   - 点击行 → 下方显示模块标签

    # 下：模块标签区
    #   - 显示名/文件名/分类/类型/描述
    #   - 能力声明标签：uses_battle/uses_team/uses_soul/uses_stamina
    #   - loop_count / timeout

    # 底部：[+ 新建任务] 按钮 → NewTaskDialog
```

### 18.3 核心接口

| 方法 | 调用方 | 说明 |
|------|--------|------|
| `TaskManager.scan_all()` | MainWindow 初始化 | 扫描全部任务和通用模块 |
| `TaskManager.get_tasks_by_category(cat)` | TaskManagerPanel | 按分类获取任务列表 |
| `TaskManager.new_task(cat, name, display)` | NewTaskDialog | 创建骨架文件（含 uses_* 声明） |
| `TaskManager.delete_task(module)` | TaskManagerPanel | 安全删除（→ .py.deleted） |
| `TaskManager.open_file(module)` | TaskManagerPanel | 用系统默认程序打开 .py |
| `TaskManager.find_missing_assets()` | MainWindow 自检 | 对比 tasks/ 引用 vs assets/ 实存 |

### 18.4 新建任务模板

`new_task()` 生成的骨架文件包含：
- ① 模块声明区（display_name / description / task_type / uses_* / loop_count / timeout）
- ② 导入依赖（预注释通用模块 import）
- ③ 特化步骤区（预留）
- ④ build_graph() 函数（TaskGraph 构建）
- ⑤ 入口 TaskStep 类（execute → build_graph → run）

---

## 十九、执行器模块（14-执行器模块）

### 19.1 定位

14 模块是操作执行桥接层，封装"识图→安全偏移→设备操作"全链路。Executor 本身无独立 UI 面板，但通过以下触点与 UI 交互：

| UI 触点 | Executor 接口 | 方向 | 说明 |
|---------|-------------|------|------|
| ControlBar 沙盒开关 | `set_dry_run(enabled)` | UI→Exec | 沙盒模式下不实际点击，仅记录日志 |
| StatusBar 沙盒指示 | `is_dry_run()` | Exec→UI | 状态栏显示 🧪 沙盒开/关 |
| LogPanel 操作日志 | `click_image/wait_any/...` | Exec→Monitor→UI | 每次操作记录识别结果/坐标/耗时 |
| StatusBar tooltip | `get_last_operation()` | Exec→UI | 悬停查看上次操作详情 |

### 19.2 操作链路（UI 视角）

```
用户点击「启动」
  → ScriptWorker.run()
    → Executor.click_image("scenes/login/enter_game")
      → Recognizer.find()          识别 (640, 800)
      → AntiDetect.random_offset() 偏移 (641, 802)
      → dry_run? → ADB.click(641, 802)
      → Monitor.log("点击 enter_game @ (641,802)")
        → LOG_RECORD → LogPanel 实时显示
      → 返回 True
```

### 19.3 模块桥接关系

```
01-设备连接 ← 03-防封策略 ← 14-执行器 → 02-图像识别
                              ↓
                         12-日志监控
                              ↓
                     UI (LogPanel + StatusBar)
```

---

## 二十、账号管理模块（15-账号管理模块）

### 20.1 定位

15 模块管理主号和小号的配置、切换、任务范围过滤和组队协调。全部 10 个公开方法已实现，全局单例 `account_manager` 在启动时初始化。

### 20.2 UI 触点

| UI 组件 | 调用的 15 模块接口 | 方向 | 说明 |
|---------|------------------|------|------|
| SubAccountConfigPanel | `load_accounts()` → 读写 `accounts.yaml` | UI→配置 | 小号卡片列表 + 详情表单 |
| AccountBridge | `switch_to()` / `get_current()` | UI→AccountMgr | 账号切换下拉框 + 标签 |
| StatusBar | `get_current()` → `current_account` | AccountMgr→UI | 当前账号显示 |
| ScriptWorker | `get_task_scope()` | AccountMgr→逻辑 | 过滤可执行任务 |

### 20.3 数据流

```
accounts.yaml
  → ConfigManager.get("accounts")
    → AccountManager.load_accounts()
      → AccountInfo(id/role/device_id/server/task_scope/team_group/teaming_enabled)
        → SubAccountConfigPanel 展示
        → AccountBridge.switch_to() 切换
          → StateManager.set_state(current_account)
            → StatusBar 更新
```

### 20.4 AccountInfo 结构

| 字段 | 说明 |
|------|------|
| `id` | 账号标识（"main"/"sub1"/"sub2"） |
| `role` | 角色（"main"/"sub"） |
| `device_id` | 绑定模拟器设备 ID |
| `server` | 区服 |
| `task_scope` | 可执行任务分类列表 |
| `team_group` | 组队分组标识 |
| `teaming_enabled` | 是否允许被组队调用 |

---

## 二十一、应用启动引导（16-应用启动引导模块）

### 21.1 定位

16 模块是程序的总装蓝图，定义 16 个模块的初始化顺序、依赖注入方式和关闭流程。

### 21.2 当前启动路径 vs 设计目标

| 路径 | 实际使用 | 说明 |
|------|---------|------|
| **直接初始化**（当前） | ✅ `main.py` | `MainWindow()` 无参构造，内部自完成全部模块初始化 |
| **Bootstrap 编排**（设计目标） | 🔧 `bootstrap.py` | `ApplicationBootstrap.initialize()` 按 7 层依赖顺序创建所有模块 |

### 21.3 7 层初始化顺序

```
第1层 基础设施:  ⑥ ConfigManager → ⑧ EventBus
第2层 基础服务:  ⑫ Monitor → ⑦ StateManager
第3层 核心功能:  ① Connection → ② Recognizer → ③ AntiDetect
第4层 业务编排:  ⑤ Scheduler → ⑭ Executor → ④ TaskRegistry → ⑬ TaskManager → ⑩ ParamBridge
第5层 运行控制:  ⑨ RunController
第6层 账号管理:  ⑮ AccountManager
第7层 用户界面:  ⑪ MainWindow → Qt 事件循环
```

### 21.4 关闭流程

```
用户关闭窗口 / SIGINT
  → 1. RunController.stop()    停止三线程
  → 2. Scheduler.save_state()  保存调度状态
  → 3. Connection.disconnect() 断开设备连接
  → 4. sys.exit(0)
```
