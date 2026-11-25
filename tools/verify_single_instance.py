"""单实例守卫端到端验证。

流程：
1. 启动实例 A（无参数），等窗口就绪；
2. 带参数启动实例 B（test.mp4），B 应立即退出；
3. 断言：A、B 同时只有 1 个进程在跑；
4. 断言：A 的窗口标题出现 test.mp4（证明 WM_COPYDATA 文件转发成功）；
5. 再空参启动实例 C，同样只应有 1 个进程。

用法: python tools/verify_single_instance.py
退出码: 0 = ALL_PASS, 1 = 有失败项
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "dist", "万能视频播放器.exe")
TEST_MEDIA = os.path.abspath(os.path.join(ROOT, "..", "tools", "test.mp4"))
PROC = "万能视频播放器.exe"

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def tasklist_pids() -> list:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {PROC}", "/NH"],
                         capture_output=True, text=True)
    pids = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.startswith(PROC):
            pids.append(line)
    return pids


def window_title_of(proc_line: str) -> str:
    out = subprocess.run(["tasklist", "/V", "/FI", f"IMAGENAME eq {PROC}", "/NH"],
                         capture_output=True, text=True)
    for line in out.stdout.splitlines():
        if line.strip() and line.strip().startswith(PROC):
            parts = line.rsplit(None, 1)
            return parts[-1] if parts else ""
    return ""


def wait_procs(n: int, timeout: float = 30.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if len(tasklist_pids()) >= n:
            return True
        time.sleep(1)
    return False


def kill_all() -> None:
    subprocess.run(["taskkill", "/F", "/IM", PROC],
                   capture_output=True, text=True)


def main() -> int:
    if not os.path.isfile(EXE):
        print(f"MISSING: {EXE}（先构建）")
        return 1
    if not os.path.isfile(TEST_MEDIA):
        print(f"WARN: 测试素材不存在 {TEST_MEDIA}，改用无参实例 C 验证")

    kill_all()
    time.sleep(1)

    # ---- 实例 A ----
    a = subprocess.Popen([EXE])
    if not wait_procs(1, 60):
        check("实例 A 启动", False, "60s 内未见进程")
        kill_all()
        return 1
    check("实例 A 启动", True)
    time.sleep(8)  # 等窗口就绪

    # ---- 实例 B（带文件）----
    b = subprocess.Popen([EXE, TEST_MEDIA] if os.path.isfile(TEST_MEDIA) else [EXE])
    b_exit = b.wait(timeout=30)
    check("实例 B 立即退出", b_exit == 0, f"exit={b_exit}")

    time.sleep(3)
    lines = tasklist_pids()
    check("双实例互斥（仅 1 个进程）", len(lines) == 1, f"当前 {len(lines)} 个进程")

    # ---- 文件转发：窗口标题应含 test.mp4 ----
    if os.path.isfile(TEST_MEDIA):
        time.sleep(6)
        title = window_title_of(PROC)
        base = os.path.basename(TEST_MEDIA)
        check("WM_COPYDATA 转发（标题含文件名）", base in title,
              f"title={title!r}")

    # ---- 实例 C（无参数，验证不闪退也不多开）----
    c = subprocess.Popen([EXE])
    c_exit = c.wait(timeout=30)
    time.sleep(3)
    lines = tasklist_pids()
    check("实例 C 立即退出", c_exit == 0, f"exit={c_exit}")
    check("三连启动仍仅 1 个进程", len(lines) == 1, f"当前 {len(lines)} 个进程")

    kill_all()
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{'ALL_PASS' if not failed else 'FAILED: ' + ', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
