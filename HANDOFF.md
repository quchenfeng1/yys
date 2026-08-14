# 项目交接文档（HANDOFF）— 2026-08-14

> 本文件用于跨电脑无缝续接本项目的开发。新电脑 `git clone` 本项目后，
> 把本文件内容（或直接告诉 Copilot "读取项目根目录 HANDOFF.md 继续工作"）
> 交给新的 GitHub Copilot 会话，即可完整继承当前逻辑与上下文。
>
> ⚠️ 本日（08-14）做了大量设计讨论与代码改动，**设计思路已单独沉淀在
> 根目录《示教节点设计构想.md》**，请务必一并阅读（尤其第十一节「场景状态机定稿」）。

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
- 当前 git HEAD：`db8acba`；⚠️ 08-14 有一批改动**未提交**（见 §7 提交清单）
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
- ✅ **识图缺口补全**（2026-08-14）：clicker「识别坐标」点 matcher 输出（识图→点击闭环）、
    edge_line 边缘检测、color_block 区域占比、matcher 多实例（index 参数）、
    scroll_capture 拼接全景 panorama.png、navigator 实际动作（BACK×N/重启游戏）
- ✅ **多分辨率适配已完备并验证**：示教坐标全部相对(0~1)存储，VisualTask.execute 从实际截图
    动态推断 screen_size；verify_visual_multires.py 覆盖换算
- ✅ **OCR case_sensitive 修复**（ocr_locator find_text/find_texts）
- ✅ 回归 **58/58 通过**（tools/run_regression.py --fast）
- ✅ **识图器(matcher)示教**（2026-08-14）：红框=搜索区域、蓝框=整体标识、画笔遮罩、
    多遮罩按连通域拆块、彩色匹配（修灰度丢失颜色 bug）、template 为空自动触发示教
- ✅ **场景判定 v2**（nodes.py `_judge_scene_v2`）：红框(regions)+蓝框(markers)+精度(accuracy)；
    蓝框内多个遮罩块 = 一个整体（连通域拆分 + 相对位置对应校验）
- ✅ **点击区域随机**：clicker 固定点模式支持 point.region（区域内随机点击）
- ✅ **可编辑选框**（screen_canvas）：PPT 风格 选中/拖动/8手柄拉伸/Delete删除/双击改名
- ✅ **示教模式锁定**（teach_console）：节点触发示教时禁用其他模式切换按钮
- ✅ **scene_store.py**：识别素材库（games/{game}/scenes/ + _shared/scenes/）
- ✅ **Show 设计构想**：根目录《示教节点设计构想.md》

---

## 3. ⏳ 进行中 / 下一步

### 3.1 ★核心方向：场景状态机架构（详见《示教节点设计构想.md》第十一节）
用户已把思路从「线性脚本」转为「有限状态机」：
- 每个任务若干固定画面（场景）；在已知场景内=未脱离任务，否则=异常。
- **场景信号表**（新增）：区域特征→场景信号的映射，一次截图多分类识别，输出命中场景 id。
- **场景起始节点**（新增 scene_entry）：监听场景信号，命中即激活该场景任务。
- **期望页面快速路径**：跳转固定时先查期望页面（复用 scene_probe），未命中才回查全局表。
- 异常=全无命中→接示教；重试上限=连续 N 次同一场景→报错。

**待拍板的 3 个细节**（见设计文档第十一节末尾）。

### 3.2 主 UI 显示"正在运行的游戏"（已分析，未实施）
游戏由 bootstrap 读 `YYS_GAME` 环境变量（默认 yys）固定；已给 A/B/C 三层方案，待用户确认。

### 3.3 后续可做（未要求）
- Operation 编辑器 UI、导出 .py、OCR 引擎安装（pip install paddleocr，懒加载）

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

- `tools/run_regression.py --fast`：自动发现 tools/verify_*.py 并逐个跑，当前 58/58
  （⚠️ 并发模式下 verify_signal.py 偶发失败是既有 EventBus 时序问题，串行 --workers 1 必过）
- 可视化相关：verify_visual_graph（执行器/循环/分支/登录流程）、verify_visual_complex
  （嵌套循环/次数配置/直到条件）、verify_visual_ui、verify_visual_operation、
  verify_visual_theme（样式/透明/列宽）、verify_visual_backdrop、verify_visual_open_dialog 等
- 新增验证脚本后直接放进 tools/ 即被回归自动纳入

---

## 6. 给新 Copilot 会话的引导语（可直接粘贴）

> 请依次读取：
> 1. 项目根目录 `HANDOFF.md`（上下文、坑、命令）
> 2. 项目根目录《示教节点设计构想.md》（尤其第十一节「场景状态机定稿」——用户的核心设计思路都在里面）
> 然后运行回归确认基线：
> `cd 新程序/主程序 && QT_QPA_PLATFORM=offscreen QT_PLUGIN_PATH="$PWD/.venv/lib/python3.9/site-packages/PyQt5/Qt5/plugins" .venv/bin/python tools/run_regression.py --fast --workers 1`
> 当前核心任务是落地「场景状态机」（见设计文档第十一节 + HANDOFF §3.1），先和用户确认那 3 个待拍板细节再动手。
> 所有改动后跑全量回归。

---

## 7. ⚠️ 未提交改动清单（2026-08-14，换设备前务必先提交推送）

以下文件有本地改动**尚未 commit/push**，换设备前执行：
```bash
cd /Users/mac/quproject1/yys
git add -A
git commit -m "识图器示教+场景判定v2+可编辑选框+示教模式锁定+设计构想文档"
git push
```

改动文件（git status）：
- 新增：`visual/scene_store.py`、`games/yys/scenes/`、`示教节点设计构想.md`
- 修改：`visual/nodes.py`、`visual/node_defs.py`、`visual/teach_engine.py`、
  `visual/visual_task.py`、`core/bootstrap.py`、`core/game_profile.py`、
  `ui/visual_builder/{screen_canvas,teach_console,pan_viewer,graph_canvas,visual_builder_panel}.py`、
  `ui/param_bridge/{visual_bridge,run_bridge}.py`、`ui/main_window.py`、
  `tools/verify_visual_graph.py`、`tools/verify_visual_complex.py`
