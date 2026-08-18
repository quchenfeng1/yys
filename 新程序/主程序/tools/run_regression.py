"""
全量回归驱动器（并行版）。

并发运行 tools/verify_*.py 全部验证脚本（进程池），显著缩短总耗时：
  串行 ~158s → 并行 ~40s（并发数默认 = CPU 数，可 --workers 指定）。

用法：
    python tools/run_regression.py            # 并行跑全部（跳过已知崩溃的 theme_preview 可选）
    python tools/run_regression.py --workers 4
    python tools/run_regression.py --all      # 含已知崩溃脚本（verify_theme_preview）

自动设置 offscreen 测试环境变量（QT_QPA_PLATFORM/QT_PLUGIN_PATH），无需手动 export。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed

# tools/ 的上一级 = 主程序根
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 已知问题脚本：offscreen 下 Qt 退出段错误（预览工具，与功能无关），默认跳过
KNOWN_BROKEN = {"verify_theme_preview.py"}

# 完整执行类脚本（跑真实任务/组队流程，内部含核心逻辑 sleep，较慢 ~10-30s）
# --fast 快速回归时跳过（只跑轻量逻辑校验，~15s）
KNOWN_SLOW = {
    "verify_combat_test_log.py",
    "verify_once_test.py",
    "verify_task_images.py",
}

# 单脚本超时（秒）——防个别脚本卡死拖垮全量
SCRIPT_TIMEOUT = 180


def _env() -> dict:
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    plugin = os.path.join(
        PROJ, ".venv", "lib", "python3.9", "site-packages", "PyQt5", "Qt5", "plugins")
    if os.path.isdir(plugin):
        env["QT_PLUGIN_PATH"] = plugin
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"   # Windows 下子进程输出统一 UTF-8
    return env


def _run_one(path: str) -> tuple[str, int, float, str]:
    """运行单个脚本，返回 (文件名, 退出码, 耗时秒, 输出尾部)"""
    t0 = time.time()
    try:
        p = subprocess.run(
            [sys.executable, path], capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=SCRIPT_TIMEOUT, cwd=PROJ, env=_env())
        rc, out = p.returncode, (p.stdout + p.stderr)
    except subprocess.TimeoutExpired:
        rc, out = 124, "TIMEOUT"
    tail_lines = [l for l in out.splitlines()
                  if ("通过" in l or "失败" in l or "FAIL" in l or "exit" in l.lower())]
    summary = tail_lines[-1].strip() if tail_lines else out.strip().splitlines()[-1] if out.strip() else ""
    return os.path.basename(path), rc, time.time() - t0, summary


def main() -> int:
    # Windows GBK 控制台下打印 emoji 会 UnicodeEncodeError，统一 UTF-8
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = [a for a in sys.argv[1:]]
    workers = None
    include_broken = "--all" in args
    fast = "--fast" in args
    for i, a in enumerate(args):
        if a == "--workers" and i + 1 < len(args):
            try:
                workers = max(1, int(args[i + 1]))
            except ValueError:
                pass
    if workers is None:
        workers = min(8, (os.cpu_count() or 4) + 1)

    scripts = sorted(glob.glob(os.path.join(PROJ, "tools", "verify_*.py")))
    if not include_broken:
        scripts = [s for s in scripts if os.path.basename(s) not in KNOWN_BROKEN]
    if fast:
        scripts = [s for s in scripts if os.path.basename(s) not in KNOWN_SLOW]

    print(f"🧪 全量回归（并行 {workers} 进程）共 {len(scripts)} 个脚本"
          f"{'（快速模式，跳过完整执行脚本）' if fast else ''}…")
    t_total = time.time()
    results: list[tuple[str, int, float, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_run_one, s): s for s in scripts}
        for fut in as_completed(futs):
            results.append(fut.result())

    results.sort(key=lambda r: r[2], reverse=True)
    passed = [r for r in results if r[1] == 0]
    failed = [r for r in results if r[1] != 0]
    for name, rc, dt, info in results:
        st = "PASS" if rc == 0 else "FAIL"
        print(f"{st:4}  {dt:5.1f}s  {name}  {info}")

    print(f"\n总耗时 {time.time() - t_total:.1f}s  |  通过 {len(passed)}  失败 {len(failed)}")
    if failed:
        print("失败:", [n for n, _, _, _ in failed])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
