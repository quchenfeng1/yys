# 素材目录（assets/）

本目录存放图像识别模块使用的**模板图片**（PNG 格式）。素材按场景/用途分目录组织，
引用名 = 相对路径不含扩展名（如 `common/ui/close_btn` 对应 `common/ui/close_btn.png`）。

## 目录结构约定

```
assets/
├── scenes/
│   ├── courtyard/      # 庭院场景
│   │   └── courtyard_main.png   # 庭院主界面
│   └── login/
│       └── enter_game.png       # 登录/进入游戏界面
├── common/
│   ├── battle/         # 战斗通用
│   │   ├── victory.png          # 战斗胜利
│   │   └── defeat.png           # 战斗失败
│   ├── popup/          # 弹窗通用
│   │   ├── popup_reward.png     # 奖励弹窗
│   │   ├── popup_ad.png         # 广告弹窗
│   │   └── popup_update.png     # 更新弹窗
│   └── ui/             # 界面通用
│       └── close_btn.png        # 关闭按钮
```

## 当前缺失的模板（启动自检会提示）

| 模板引用 | 建议文件路径 | 用途 |
|---------|------------|------|
| `close_btn` | `common/ui/close_btn.png` | 关闭按钮（弹窗拦截/错误恢复） |
| `confirm` | `common/ui/confirm.png` | 确认按钮（战斗结算） |
| `victory` | `common/battle/victory.png` | 战斗胜利结算 |
| `defeat` | `common/battle/defeat.png` | 战斗失败结算 |
| `courtyard_main` | `scenes/courtyard/courtyard_main.png` | 庭院场景（错误恢复） |
| `enter_game` | `scenes/login/enter_game.png` | 登录界面（断线检测） |
| `popup_reward` | `common/popup/popup_reward.png` | 奖励弹窗（弹窗拦截） |

## 如何添加素材

1. 在游戏模拟器中截图目标画面
2. 裁剪出目标区域（按钮/图标/场景标志）
3. 保存为 PNG 放入对应目录（目录不存在则新建）
4. 重启程序或点击「素材管理」面板的「刷新」按钮

> 提示：截图裁剪建议保留目标区域 + 少量边缘，模板越小匹配越快；
> 使用「素材管理」面板可可视化查看/删除已加载素材。
