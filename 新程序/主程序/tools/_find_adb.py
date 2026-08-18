"""搜索常见模拟器自带的 adb.exe"""
import os

ROOTS = [r"C:\Program Files", r"C:\Program Files (x86)",
         r"D:\Program Files", "D:\\", "E:\\"]
KEYS = ("mumu", "netease", "ldplayer", "leidian", "nox", "bluestacks")


def main():
    hits = []
    for root in ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath.count(os.sep) - root.count(os.sep)
            if depth > 5:
                dirnames[:] = []
                continue
            low = dirpath.lower()
            if "adb.exe" in filenames and any(k in low for k in KEYS):
                hits.append(os.path.join(dirpath, "adb.exe"))
    if hits:
        print("\n".join(sorted(set(hits))))
    else:
        print("not found")


if __name__ == "__main__":
    main()
