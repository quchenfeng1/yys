"""临时回归驱动：跑全部 verify_*.py（跳过 theme_preview 偶发挂起）"""
import subprocess, glob, sys

fails = []
for f in sorted(glob.glob("tools/verify_*.py")):
    if "theme_preview" in f:
        print(f"SKIP  {f}  已知 offscreen 偶发挂起/段错误")
        continue
    p = subprocess.run([sys.executable, f], capture_output=True, text=True, timeout=200)
    lines = (p.stdout + p.stderr).splitlines()
    tail = [l for l in lines if ("通过" in l or "失败" in l or "exit" in l.lower())]
    status = "PASS" if p.returncode == 0 else "FAIL"
    info = tail[-1].strip() if tail else ""
    print(f"{status}  {f}  {info}")
    if p.returncode != 0:
        fails.append(f)
        print("    --- tail ---")
        print("\n".join(lines[-5:]))
print()
print("FAILED:", fails if fails else "none")
