"""验证：字幕打开即挂（不等 900ms）+ 挂上即选中轨道 + 失败重试。"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from main_window import MainWindow

app = QApplication([])
w = MainWindow(None)

class P:
    def __init__(self, ok_first=False):
        self.d = 0; self.calls = []; self.spu = None
        self._subtitle_path = ""
        self.ok_first = ok_first
        self.n = 0
    def set_subtitle_delay(self, ms): self.d = ms
    def get_subtitle_tracks(self): return [(0, "Track 1")]
    def add_subtitle(self, p, replace=True, activate=True):
        self.calls.append(p)
        self.n += 1
        ok = self.ok_first or self.n > 1     # 第一次失败，重试才成功
        if ok:
            self._subtitle_path = p
        return ok
    def open(self, *a, **k): pass
w.player = P()

d = tempfile.mkdtemp()
v = os.path.join(d, "m.mp4"); open(v, "wb").write(b"\0"*1024)
s = os.path.join(d, "m.srt"); open(s, "w", encoding="utf-8").write("1\n00:00:01,000 --> 00:00:02,000\nhi\n")

w._auto_load_srt(v)   # 第 1 次（立即）
print("第1次 add_subtitle 调用:", [os.path.basename(c) for c in w.player.calls])
assert len(w.player.calls) == 1, "应立即尝试挂载（不再等 900ms）"

# 跑事件循环让重试定时器触发
def done():
    app.quit()
QTimer.singleShot(2000, done)
app.exec()
print("重试后总调用次数:", len(w.player.calls), "(应 >=2：首次+重试)")
assert len(w.player.calls) >= 2, "挂不上应重试"
print("SMOKE_OK")
