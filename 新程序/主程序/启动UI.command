#!/bin/bash
# 阴阳师自动化工具 - UI 启动脚本（macOS）
# 双击运行，或在终端执行: ./启动UI.command

# 切换到脚本所在目录
cd "$(dirname "$0")"

# 如无虚拟环境则创建
if [ ! -d ".venv" ]; then
    echo "首次运行：正在创建虚拟环境并安装依赖..."
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip -q
    .venv/bin/pip install PyQt5 loguru pyyaml numpy opencv-python-headless watchdog
fi

# 设置 Qt 平台插件路径（macOS pip 安装 PyQt5 必需）
export QT_QPA_PLATFORM_PLUGIN_PATH="$PWD/.venv/lib/python3.9/site-packages/PyQt5/Qt5/plugins"

echo "正在启动 UI..."
exec .venv/bin/python main.py
