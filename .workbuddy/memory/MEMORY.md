# 阴阳师脚本项目 - 长期记忆

## 项目概述
- 项目：阴阳师手游自动化识图脚本（PC端连接模拟器）
- 路径：D:\阴阳师脚本
- 基准文件：脚本模块说明书.md（文档驱动开发，代码以说明书为准）

## 技术栈
- Python 3.10+ / OpenCV 模板匹配 / ADB 连接模拟器 / PyQt5 界面 / YAML+JSON 配置
- 模拟器统一分辨率 1280×720

## ★ 操作权限边界（永久规则）
- 未经用户明确授权，只可操作 D:\阴阳师脚本 文件夹内部文件
- 禁止用 adb 修改模拟器系统设置：wm size/density 设置、kill 进程、安装卸载应用等写操作一律禁止
- adb 只读命令（get-state / wm size 查询 / devices / screencap 截图）可用
- 任何涉及模拟器/系统变更的操作必须先征得用户许可
- 教训：曾擅自执行 `adb shell wm size 1280x720` 修改模拟器分辨率，被用户纠正要求恢复原样

## 关键设计决策
- 五层架构：基础设施层 / 设备层 / 核心服务层 / 任务调度层 / UI层
- 任务层禁止直接调用设备层，所有操作必须经操作执行模块（强制防封号处理）
- ★ 素材四层分类结构(v1.6)：assets/ 下 common/(公共素材)/scenes/(场景标志)/tasks/(任务专属,按daily/permanent/event/special分)/teams/(阵容预设)；「所需图片」为原始截图暂存区
- 素材索引名=相对assets/路径(去.png,用/分隔)，如 common/battle/challenge_btn、scenes/login/enter_game、tasks/permanent/yuhun/entry
- 任务三者绑定：name = assets/tasks/{category}/{name}/ = config/coords/{name}.json
- 防封号核心：正态分布随机偏移、贝塞尔曲线鼠标轨迹、随机延迟、走神暂停、每日运行限制(8h/2000次)

## 运行环境
- 可用 Python: C:\Users\q\.workbuddy\binaries\python\versions\3.13.12\python.exe (managed, preferred)
- 可用 Node: C:\Users\q\.workbuddy\binaries\node\versions\22.22.2\node.exe
- 包安装到隔离venv: C:\Users\q\.workbuddy\binaries\python\envs\default

## 当前状态
- 说明书 v1.7 已完成（v1.6 + 附录D用户确认事项全面修订）
- v1.7 核心变更：①新增账号管理模块(多区切换+多开小号,最多1主+2小) ②新增小号设置一级菜单 ③任务优先级归入配置精确到每个任务 ④运行时段改全天 ⑤时间规则默认每任务单独设置 ⑥阵容切换首次进战前必须检查
- 新增第十二部分"账号管理与多开体系"：AccountManager(core/account_manager.py)、accounts.yaml、多开设备绑定、小号仅副本不日常
- 核心扩展机制：自动注册(目录扫描) + 脚手架工具(task_generator.py) + 标准接口契约(BaseTask生命周期钩子)
- 任务4类划分：日常(daily,BaseTask纯领奖)/常驻(permanent,DungeonTask战斗副本)/活动(event,EventTask限时)/特殊(special,SpecialTask固定流程特殊方式)
- 阵容御魂管理(TeamManager, core/team_manager.py)：跨模块核心服务，两阶段流程（对局外ensure_team调整阵容御魂 + 对局内select_team+lock_team选阵容锁定）
- ★ 阵容检查强制性(v1.7)：每个战斗任务首次进战前必须检查阵容，锁定与否在副本配置lock_team_after_select字段
- 阵容预设与副本解耦：team_id 引用 config/coords/teams/<team_id>.json，可被多副本复用
- 副本标准流程：任务触发→pre_check_team→ensure_team(对局外调整)→进本→select_team→lock_team→挑战→重复刷取(已锁定不再选阵容)
- 任务调度(Scheduler, core/scheduler.py)：独立调度中枢，RepeatRule+priority优先级+default_order默认顺序+日程表+次数控制(times/max_daily/max_total/cooldown)
- ★ RepeatRule统一模型(v1.5)：TimeRule+run_strategy合并为RepeatRule七种类型(once/daily/weekly/monthly/interval_days/interval_hours/expire_at)，所有任务必配含常驻副本
- ★ next_run_time双重判据：now≥next_run_time AND (window为空 OR 在window内)
- ★ next_run_time UI可见可改可持久化：任务行显示倒计时，可视化编辑器改执行规则，时间选择器改下次时间，写入tasks.yaml+task_state.json
- ★ 执行记录持久化：config/runtime/task_state.json，记录last_run_time/next_run_time/success_count/today_count/expire_at；原子写盘(临时文件→替换)；启动load_state恢复；删除即重置
- ★ 失败不推进原则：mark_done(success=False)不推进next_run_time，任务保持到期可重试
- ★ 重置时刻默认00:00（阴阳师游戏每日重置时间）；结界卡失效时间识图识别单独处理；好友寄养6h间隔可UI调整
- ★ 运行时段(v1.7)：脚本全天运行，任务靠时间规则(repeat)控制，运行时段菜单仅保留每日时长/操作上限作为安全阀
- ★ 任务优先级(v1.7)：归入配置菜单下，精确到每个单独任务，可在配置中逐任务设置priority值
- tasks/目录四子目录：daily/permanent/event/special；菜单自动扫描生成，新增任务文件即出现在UI
- 界面菜单(v1.7)三大部分：脚本配置(模拟器/账号管理/任务优先级/防封号/运行时段/阵容预设/日志) + 任务控制(启停+4类面板) + 小号设置(独立一级菜单,小号模拟器端口与副本配置)
- ★ 账号管理(v1.7)：AccountManager多区切换+多开(最多1主+2小)，小号仅配合主号刷副本不执行日常，每账号绑定独立模拟器ADB端口
- 附录D已确认项：第1-9项+第12项已确认；待确认：第10(阵容预设清单)/11(御魂装配精度)/13(特殊任务需求)/14(组队模式)/15(活动更新)
- 等用户回答附录D剩余待确认事项(5项)后开始搭建代码框架

## 当前代码状态（v0.5）
- 框架已搭建：五层架构 + 三栏GUI(左菜单/中任务列表/右日志) + 登录流程脚本
- MuMu连接已修复：adb路径自动检测(MuMu自带 nx_main/adb.exe，系统adb损坏)；端口16384；is_connected多设备bug已修
- ★ 脚本不自动改模拟器分辨率：script_worker 只读取 get_screen_size()，不匹配时提示用户在模拟器设置中自行调整；横纵比容错匹配({w,h}集合比较)
- ★ 连接后优先启动阴阳师App（不依赖识图）：script_worker Step4 用 adb am start 启动，等待进程就绪
- 阴阳师包名：com.netease.onmyoji.wyzymnqsd_cps（渠道包），Activity: com.netease.onmyoji.Launcher
- 模拟器 adb 路径配置：global.yaml adb.path = C:/Program Files/Netease/MuMu/nx_main/adb.exe
- ★ assets/ 四层分类重构(v0.5)：common/(battle/ui/nav) + scenes/(login/courtyard/town/explore) + tasks/(daily/permanent/event/special) + teams/；recognizer 用 PIL 读取图片兼容中文路径
- ★ 放弃6张必传图：登录流程改为 OCR(rapidocr-onnxruntime) 识别"进入游戏"位置 → 循环点击固定区域；core/ocr_locator.py 已创建
- ★ 用户已提供1张登录界面参考图：所需图片/MuMu-20260719-020905-471.png (1280x720横屏)；OCR识别"进入游戏"位置：框[556,576,718,619]，中心(637,598)
- 待完成：login_flow.py 重写为循环点击固定位置（task 43 进行中）
- ★ 模块拆解v2.0已确认：12模块体系（用户8模块+新增4个：状态管理/事件总线/运行控制/日志监控），传参模块内部拆分（配置模型+UI绑定）
- ★ 模块拆解v2.0进一步增强：任务(超时/重试/回滚/并行)、事件总线(溯源/优先级/去重)、配置(三级分层覆盖/迁移)、安全(审计/行为多样性/节奏控制)、运行控制(异常恢复/熔断)、连接(质量监控/预热)
- 模块拆解文件在 D:\阴阳师脚本\模块拆解\（15个文件，4702行），含总览+12模块详细+主程序/UI设计思路
- 说明书已拆分为13个子文件在 D:\阴阳师脚本\说明书\，原说明书保留
