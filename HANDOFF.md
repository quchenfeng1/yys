# 项目交接文档（HANDOFF）— 2026-08-13

> 本文件用于跨电脑无缝续接本项目的开发。新电脑 `git clone` 本项目后，
> 把本文件内容（或直接告诉 Copilot "读取项目根目录 HANDOFF.md 继续工作"）
> 交给新的 GitHub Copilot 会话，即可完整继承当前逻辑与上下文。

---

## 0. 快速启动

```bash
# 新电脑
git clone https://github.com/quchenfeng1/yys.git
cd yys/新程序/主程序
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # 或按依赖安装 PyQt5 NodeGraphQt 等
# 运行回归（offscreen）
QT_QPA_PLATFORM=offscreen QT_PLUGIN_PATH="$PWD/.venv/lib/python3.9/site-packages/PyQt5/Qt5/plugins" .venv/bin/python tools/run_regression.py --fast
```

- Python **3.9.6**（macOS venv）
- 主路径：`新程序/主程序/`
- 当前 git HEAD：`e9edcdd`（已推送 origin/main，工作区干净）
- 依赖：PyQt5 5.15.11、NodeGraphQt 0.6.44（导入名必须大写 `NodeGraphQt`）

---

## 1. 项目结构

```
新程序/主程序/
├── main.py                      # 入口
├── core/                        # 核心：bootstrap/config/executor/recognizer/run_controller/
│                                #   scheduler/task_manager/event_bus/events/game_profile/...
├── device/                      # ADB 连接（adb_client/connection/emulator/screenshot/heartbeat）
├── games/{game_id}/             # ★游戏解耦：每游戏独立 tasks/assets/coords/tasks.yaml/
│                                #   runtime/visual_tasks/operations + games/_shared/operations
├── visual/                      # ★可视化构建核心
│   ├── visual_schema.py         #   节点图模型 + teach(scenes/points/ocr_regions) + 序列化
│   ├── node_defs.py             #   16 种节点定义（NODE_DEFS 元数据驱动）
│   ├── nodes.py                 #   各节点执行器 + GraphContext + 场景判定
│   ├── graph_runner.py          #   图执行器（控制流/循环/分支/中断）
│   ├── visual_task.py / rule_store.py / operation_store.py / teach_engine.py
├── ui/
│   ├── main_window.py           # 主窗口（控制栏+菜单树+12面板栈+右侧日志+状态栏）
│   ├── param_bridge/            # UI↔核心通信（run/task/config/account/visual bridge）
│   └── visual_builder/          # 可视化编辑器（graph_canvas/pan_viewer/open_task_dialog/
│                                #   visual_builder_panel/screen_canvas/teach_console）
├── tools/                       # 验证脚本 tools/verify_*.py（回归自动发现）+ 诊断脚本
└── docs/
```

---

## 2. 已完成（截至交接）

- ✅ 游戏解耦迁移：games/{game_id}/ 独立目录 + GameProfile（路径/display_name/ocr_lang）+ scan_games
- ✅ 可视化构建 P0（数据结构）+ P1（示教）+ P2（节点画布/执行器）全闭环
- ✅ Operation 通用操作（4.26）+ 参数上浮（4.27）
- ✅ 编辑器交互：删除节点/连线（Delete 键）、PanNodeViewer 左键拖空白平移、backdrop 彻底移除、
    顶部游戏下拉、单游戏 OpenTaskDialog、NodesPaletteWidget 节点库、撤销/重做
- ✅ 节点内嵌控件样式统一：水平布局（label 左/输入右）、**真正透明**（透出节点卡片背景）、
    固定列宽 label=80 / input=150、修复 NodeGraphQt spinbox/lineedit/checkbox 的 proxy 140 限制
- ✅ 动画跳过模式：scene_probe 加 output_var（命中写1/未命中写0）、clicker 加 mode（固定点/随机点）
- ✅ **嵌套循环 bug 修复**（graph_runner）：链式回跳 while、进入 loop 重置计数、
    _eval_until 右值支持变量引用
- ✅ 回归 **57/57 通过**（tools/run_regression.py --fast）

---

## 3. ⏳ 进行中 / 下一步

### 3.1 主 UI 显示"正在运行的游戏"（刚分析完，未实施）
现状：游戏由 bootstrap 启动时读 `YYS_GAME` 环境变量（默认 yys）固定；主窗口标题/控制栏/
状态栏均不显示游戏；visual_bridge 有 game_list/current_game 但只影响可视化构建器。
已给出三层方案，**待用户确认范围**：
- A. 只显示当前游戏（标题+状态栏+控制栏徽标，低风险）← 推荐先做
- B. 显示 + 下拉切换（重启生效）
- C. 显示 + 运行时热切换（bootstrap.set_game 重建 registry/visual 模块）

### 3.2 后续可做（未要求）
- Operation 编辑器 UI（操作子图单独编辑界面）
- P3：滚动拼接 Stitcher、导出 .py、多分辨率
- OCR 引擎安装（PaddleOCR 懒加载降级，装上即生效）

---

## 4. 关键技术坑（务必让新会话先读）

### NodeGraphQt（PyQt5 兼容）
- 导入名大写 `NodeGraphQt`；动态节点类用 `type(ntype, (BaseNode,), {...})`，
  `__init__` 里必须 `BaseNode.__init__(self)`（不能用 super()）
- `type_ = __identifier__ + '.' + 类名`（非 NODE_NAME）；create_node 覆盖 NODE_NAME →
  类型识别一律 `node.type_.split('.')[-1]`
- 端口 API：`get_input(name)`/`get_output(name)`（非 get_input_port）；`port.node()` 是方法
- 参数 widget：`node.get_widget(name).set_value(v)`；读取 `node.properties()['custom']`
  （值可能是 proxy 或 None，取内嵌控件用 `node.get_widget(name).widget()`）
- 无 `graph.connections()` → 遍历 `node.output_ports()` + `port.connected_ports()`
- `node.pos()`；`combo.set_value(list)` 清空重填；`add_spinbox` 参数是 min_value/max_value
- 撤销/重做：`graph._undo_stack.undo()/redo()`
- backdrop 类型路径 `nodeGraphQt.nodes.BackdropNode`（已移除，兼容旧 JSON 跳过）
- 节点 body 色 (13,18,23,255)；选中叠加 SELECTED_COLOR

### 内嵌控件样式（graph_canvas.py `_patch_horizontal_node_widgets`）
- 替换私有 `_NodeGroupBox` 为 `_HorizontalNodeBox`（QGroupBox 子类）实现水平布局
- **透明方案**：`setAttribute(WA_TranslucentBackground, True)` + QSS `background: transparent`
  （必须 transparent，不能 background-color，否则白块/色差）
- **140 限制坑**：NodeLineEdit/NodeSpinBox/NodeCheckBox 在 __init__ 末尾
  `self.widget().setMaximumWidth(140)`，且自带半透明浅色 QSS →
  用包装 __init__ 在构造后 `proxy.setMaximumWidth(16777215)` 取消；add_node_widget 里
  对控件直接 `setStyleSheet(_INPUT_QSS)`（控件自身 QSS 优先于 group 继承）
- 固定列宽：label `setFixedWidth(80)`（AlignRight）+ 输入框 `setFixedWidth(150)`
- 像素采样验证注意：add_node 默认 selected=True → 先 set_selected(False) 再采样
- 控件全局坐标：`inp.mapTo(g, inp.rect().center())` + `proxy.mapToScene(off)`

### 图执行器（graph_runner.py）
- 循环回跳用 `while`（链式支持嵌套：内层 done→外层 loop_back）；从 in 进入 loop 重置计数
- `_eval_until` 右值支持变量引用（`n >= target` 取 vars['target']）
- loop 模式：固定次数（count 从任务 JSON 配置读）/ 直到条件（condition 表达式）

### 其他
- EventBus 事件名 dotted；publish 的 name 参数与 data 键冲突（用 task_name=）
- offscreen 测试必须带：`QT_QPA_PLATFORM=offscreen QT_PLUGIN_PATH="$PWD/.venv/lib/python3.9/site-packages/PyQt5/Qt5/plugins"`
- scene_probe/clicker 测试：monkeypatch `visual.nodes._judge_scene`；FakeExecutor 记录点击

---

## 5. 验证体系

- `tools/run_regression.py --fast`：自动发现 tools/verify_*.py 并逐个跑，当前 57/57
- 可视化相关：verify_visual_graph（执行器/循环/分支/登录流程）、verify_visual_complex
  （嵌套循环/次数配置/直到条件）、verify_visual_ui、verify_visual_operation、
  verify_visual_theme（样式/透明/列宽）、verify_visual_backdrop、verify_visual_open_dialog 等
- 新增验证脚本后直接放进 tools/ 即被回归自动纳入

---

## 6. 给新 Copilot 会话的引导语（可直接粘贴）

> 请先读取项目根目录的 HANDOFF.md，然后：
> 1. 运行回归确认基线：`cd 新程序/主程序 && QT_QPA_PLATFORM=offscreen QT_PLUGIN_PATH="$PWD/.venv/lib/python3.9/site-packages/PyQt5/Qt5/plugins" .venv/bin/python tools/run_regression.py --fast`
> 2. 继续完成"§3.1 主 UI 显示当前游戏"（等用户确认 A/B/C 方案后实施）
> 后续所有改动后跑全量回归。
