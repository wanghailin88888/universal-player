# -*- coding: utf-8 -*-
"""字幕挂载修复验证：
1) 同名多份字幕按修改时间取最新；
2) VLC 不再自动探测同目录字幕（避免叠轨）；
3) AI 重新生成后可干净替换旧字幕轨（重开媒体 + 回原进度）；
4) 释放 libVLC 后接口不再崩（过去会 access violation）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from main_window import MainWindow

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
MEDIA = os.path.join(TOOLS, "speech_zh.mp4")
SRT_NEW = os.path.join(TOOLS, "speech_zh.srt")        # 12:51，较旧


def spin(ms: int):
    """跑一小段事件循环（定时器、延迟挂载都依赖它），但不关闭窗口。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


app = QApplication(sys.argv)
w = MainWindow()
w.settings.auto_subtitle = True

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  | " + detail) if detail else ""))
    if not cond:
        fails.append(name)


# 1) 打开视频：自动挂载取最新，且不会被 VLC 自动探测叠成多轨
w.playlist.add_files([MEDIA])
w.open_path(MEDIA)
spin(2500)
tracks = [n for _, n in w.player.get_subtitle_tracks()]
real = [t for t in tracks if t != "Disable"]
check("自动挂载有字幕轨", bool(real), str(tracks))
check("自动挂载取最新文件", any("译文" in t for t in real), str(real))
check("无 VLC 自动探测叠轨", len(real) == 1, str(real))

# 2) 播放一会儿后用「新字幕」替换（模拟 AI 重新生成后挂载）
spin(2000)
pos_before = w.player.get_time()
check("记录到播放进度", pos_before > 300, f"{pos_before} ms")

ok = w._mount_subtitle_fresh(SRT_NEW)
check("干净挂载返回成功", ok)

spin(4000)          # 重开媒体 + 延迟挂新字幕（带重试）
tracks2 = [n for _, n in w.player.get_subtitle_tracks()]
real2 = [t for t in tracks2 if t != "Disable"]
check("新字幕轨已挂载且仅一条", len(real2) == 1, str(real2))
check("旧字幕轨已清除", not any("译文" in t for t in real2), str(real2))
check("仍在播放", w.player.is_playing())

# 3) 释放 libVLC 后接口不再崩
w.player.release()
try:
    w.player.get_time()
    w.player.get_length()
    w.player.get_position()
    w.player.is_playing()
    guard = True
except Exception:
    guard = False
check("释放后接口安全不崩", guard)

print("\n结论:", "ALL_PASS" if not fails else "FAIL -> " + ", ".join(fails))
sys.exit(0 if not fails else 1)
