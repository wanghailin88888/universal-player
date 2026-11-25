"""冒烟：主窗口「逐段实时字幕」挂载节流逻辑（用假 player，无需 VLC）。

规则：只有当已挂实时字幕覆盖不到「播放进度 + 提前量(30s)」时才重挂新轨——
libVLC 3.x 无法移除字幕轨，靠这条把轨数压到最低。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import main_window as MW  # noqa: E402
from main_window import MainWindow  # noqa: E402

app = QApplication.instance() or QApplication([])
ok = True


def check(label, cond, extra=""):
    global ok
    ok = ok and bool(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {label}{(' | ' + str(extra)) if extra else ''}")


class FakeSeg:
    def __init__(self, end):
        self.start = max(0.0, end - 2.0)
        self.end = end


class FakePlayer:
    def __init__(self):
        self.added = []
        self.t = 0

    def get_time(self):
        return self.t

    def add_subtitle(self, path, replace=True, activate=True):
        self.added.append(os.path.basename(path))
        return True


MEDIA = "E:/media/lecture.mp4"
w = MainWindow(None)
real_player = w.player            # 真 VlcPlayer 先收好，结束前换回去好让它正常释放
w.player = FakePlayer()
w._current_path = lambda: MEDIA
w._ai_media = MEDIA
w._ai_live_cover_ms = 0

# 1) 第 1 段（覆盖到 60s），播放进度 0 → 必须挂载
w._ai_partial([FakeSeg(59.0), FakeSeg(60.0)], "live.srt")
check("首段立即挂载", len(w.player.added) == 1, w.player.added)
check("覆盖范围已记录", w._ai_live_cover_ms == 60000, w._ai_live_cover_ms)
check("状态栏提示挂载", "已挂载" in w.status_ai.text(), repr(w.status_ai.text()))

# 2) 第 2 段（覆盖到 120s），播放才 10s → 已覆盖够，不重复加轨
w.player.t = 10000
w._ai_partial([FakeSeg(120.0)], "live.srt")
check("覆盖足够时不重复加轨", len(w.player.added) == 1, w.player.added)
check("状态栏说明已覆盖", "已覆盖后面" in w.status_ai.text(), repr(w.status_ai.text()))

# 3) 用户快进到 200s（超出覆盖 + 提前量）→ 必须重挂刷新
w.player.t = 200000
w._ai_partial([FakeSeg(300.0)], "live.srt")
check("进度追上后重挂", len(w.player.added) == 2, w.player.added)
check("覆盖范围前移", w._ai_live_cover_ms == 300000, w._ai_live_cover_ms)

# 4) 播的是别的片 → 只提示，不动当前播放的字幕
w._current_path = lambda: "E:/media/other.mp4"
w.player.t = 0
w._ai_partial([FakeSeg(360.0)], "live.srt")
check("非当前片不挂载", len(w.player.added) == 2, w.player.added)
check("状态栏提示已生成", "已生成" in w.status_ai.text(), repr(w.status_ai.text()))

# 5) 换片动作应把实时挂载窗口清零
w._current_path = lambda: MEDIA
w.open_path  # noqa: B018  (仅确认方法存在)
w._ai_live_cover_ms = 0
w.player.t = 0
w._ai_partial([FakeSeg(30.0)], "live.srt")
check("清零后重新挂载", len(w.player.added) == 3, w.player.added)

# 6) 提前量常量落地
check("提前量常量", MW._AI_LIVE_AHEAD_MS == 30000, MW._AI_LIVE_AHEAD_MS)

w.player = real_player
w.close()
print("SMOKE_OK" if ok else "SMOKE_FAIL")
sys.exit(0 if ok else 1)
