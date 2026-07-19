"""
素材管理辅助工具

职责：
- 校验所有素材能否被识别
- 列出缺失素材
- 统计素材数量
- 按目录层次展示素材

使用方法：
    python tools/asset_helper.py --check     # 校验所有素材
    python tools/asset_helper.py --list      # 列出所有素材（按层次）
    python tools/asset_helper.py --missing   # 列出缺失素材
    python tools/asset_helper.py --tree      # 树形展示素材目录
"""

import sys
import os
from pathlib import Path
from collections import defaultdict

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.recognizer import ASSETS_DIR, _imread_unicode


def scan_templates() -> dict:
    """扫描 assets/ 下所有 PNG，返回 {索引名: 文件路径} 字典"""
    templates = {}
    if not ASSETS_DIR.exists():
        return templates

    for root, dirs, files in os.walk(ASSETS_DIR):
        for f in files:
            if not f.lower().endswith(".png"):
                continue
            filepath = Path(root) / f
            rel_path = filepath.relative_to(ASSETS_DIR)
            name = str(rel_path.with_suffix("")).replace("\\", "/")
            templates[name] = filepath
    return templates


def list_templates():
    """列出所有已加载的素材（按层次分组展示）"""
    templates = scan_templates()
    print(f"\n已加载素材 ({len(templates)} 张):")
    print("-" * 60)

    # 按第一层目录分组
    groups = defaultdict(list)
    for name in sorted(templates.keys()):
        top = name.split("/")[0] if "/" in name else "(根目录)"
        groups[top].append(name)

    for group in sorted(groups.keys()):
        print(f"\n  [{group}/] ({len(groups[group])} 张)")
        for name in groups[group]:
            print(f"    {name}")

    return templates


def show_tree():
    """树形展示素材目录结构"""
    print(f"\n素材目录树 ({ASSETS_DIR.name}/):")
    print("-" * 60)

    if not ASSETS_DIR.exists():
        print("  (目录不存在)")
        return

    def print_tree(path: Path, prefix: str = "", is_last: bool = True):
        if path.is_dir():
            connector = "└── " if is_last else "├── "
            rel = path.relative_to(ASSETS_DIR) if path != ASSETS_DIR else Path(".")
            png_count = len(list(path.glob("*.png")))
            label = path.name + "/" if path != ASSETS_DIR else ""
            suffix = f"  ({png_count} 张图片)" if png_count > 0 else ""
            if path != ASSETS_DIR:
                print(f"{prefix}{connector}{label}{suffix}")

            children = sorted([c for c in path.iterdir() if c.is_dir()])
            for i, child in enumerate(children):
                last = (i == len(children) - 1)
                new_prefix = prefix + ("    " if is_last else "│   ")
                print_tree(child, new_prefix, last)

    print_tree(ASSETS_DIR)


def check_required():
    """校验必需素材是否齐全"""
    templates = scan_templates()

    # 必需素材清单（按新四层结构）
    required = [
        ("scenes/login/enter_game", "进入游戏按钮"),
        ("scenes/courtyard/main", "庭院主界面标志"),
    ]

    print(f"\n必需素材检查:")
    print("-" * 60)
    all_ok = True
    for img, desc in required:
        exists = img in templates
        status = "✅" if exists else "❌ 缺失"
        print(f"  {status}  {img}  ({desc})")
        if not exists:
            all_ok = False

    if all_ok:
        print("\n✅ 所有必需素材已就绪")
    else:
        print("\n⚠️  部分素材缺失，请将截图放入「所需图片」文件夹")

    return all_ok


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="素材管理辅助工具")
    parser.add_argument("--list", action="store_true", help="列出所有素材")
    parser.add_argument("--check", action="store_true", help="校验必需素材")
    parser.add_argument("--tree", action="store_true", help="树形展示目录")
    args = parser.parse_args()

    if args.tree:
        show_tree()
    elif args.list:
        list_templates()
    else:
        # 默认执行 check
        show_tree()
        list_templates()
        check_required()
