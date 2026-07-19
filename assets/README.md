# 素材目录说明

本目录存放所有图像识别素材。采用**四层分类**结构，所有任务均从此目录调用图片。

## 目录结构

```
assets/
├── common/                 ← 公共素材（跨任务复用）
│   ├── battle/             ← 通用战斗界面
│   ├── ui/                 ← 通用UI元素（关闭/确认/返回按钮等）
│   └── nav/                ← 通用导航（主页/菜单按钮等）
├── scenes/                 ← 场景标志图（判断当前所在场景）
│   ├── login/              ← 登录场景
│   ├── courtyard/          ← 庭院主界面
│   ├── town/               ← 町中
│   └── explore/            ← 探索
├── tasks/                  ← 任务专属素材（按任务类型分）
│   ├── daily/              ← 日常任务（每个任务一个子目录）
│   ├── permanent/          ← 常驻副本
│   ├── event/              ← 活动任务
│   └── special/            ← 特殊任务
└── teams/                  ← 阵容御魂预设（每个 team_id 一个子目录）
```

## 命名规范

- 文件名：全小写，下划线分词，如 `challenge_btn.png`
- 素材索引名：相对 assets/ 的路径（去掉 .png），用 `/` 分隔
  - 示例：`common/battle/challenge_btn`、`scenes/login/enter_game`、`tasks/permanent/yuhun/entry`
- 代码中引用素材时使用完整索引名

## 各目录用途

### common/ — 公共素材
跨任务复用的通用图片。多个任务都会用到的按钮、图标放这里。

| 子目录 | 内容 | 示例 |
|--------|------|------|
| `battle/` | 通用战斗界面按钮 | `challenge_btn.png` 挑战、`victory.png` 胜利、`defeat.png` 失败、`auto_battle_toggle.png` 自动战斗 |
| `ui/` | 通用UI元素 | `close_btn.png` 关闭(X)、`confirm_btn.png` 确认、`back_btn.png` 返回 |
| `nav/` | 通用导航 | `home_btn.png` 主页、`menu_btn.png` 菜单 |

### scenes/ — 场景标志图
用于判断"当前在哪个界面"。每个场景至少一张标志性全屏图或特征区域图。

| 子目录 | 内容 | 示例 |
|--------|------|------|
| `login/` | 登录流程各节点 | `splash_skip.png` 开屏跳过、`enter_game.png` 进入游戏 |
| `courtyard/` | 庭院主界面 | `main.png` 庭院标志、`icon_explore.png` 探索入口 |
| `town/` | 町中界面 | — |
| `explore/` | 探索界面 | — |

### tasks/ — 任务专属素材
每个任务一个子目录，存放该任务专属的识别图。

| 子目录 | 对应任务类型 | 示例 |
|--------|-------------|------|
| `daily/sign_in/` | 每日签到 | `sign_btn.png` |
| `daily/daily_rewards/` | 奖励领取 | — |
| `permanent/yuhun/` | 御魂副本 | `entry.png`、`floor_select.png` |
| `permanent/juexing/` | 觉醒副本 | — |
| `event/event_xxx/` | 限时活动 | — |
| `special/xuanshang/` | 悬赏封印 | — |

任务目录名必须与 `tasks/<类别>/<name>.py` 中的 `name` 字段一致，形成绑定。

### teams/ — 阵容御魂预设
每个 `team_id` 一个子目录，存放阵容标记图与选阵容分步图。

| 子目录 | 内容 |
|--------|------|
| `teams/yuhun_speed/` | 御魂输出队预设：`marker.png`、`select_step1.png` |

## 素材入库流程

1. 用户将原始截图放入「所需图片」文件夹（暂存区）
2. 脚本或工具裁剪后归入 assets/ 对应子目录
3. 运行 `python tools/asset_helper.py --check` 校验素材有效性
4. 无需改代码，重启脚本即生效

## 截图要求

- 分辨率：1280×720（与模拟器一致）
- 格式：PNG（无损）
- 内容：只截取按钮/图标的最小有效区域，避免过多背景
- 标志图：每个场景至少一张用于场景判断
