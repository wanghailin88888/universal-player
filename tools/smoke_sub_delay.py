import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from main_window import MainWindow
app = QApplication([])
w = MainWindow(None)

acts = [a.text() for a in w.sub_delay_menu.actions() if not a.isSeparator()]
print("菜单项:", acts)
assert any("延后 50ms" in a for a in acts), "缺少延后 50ms"
assert any("提前 50ms" in a for a in acts), "缺少提前 50ms"
assert any("写入字幕文件" in a for a in acts), "缺少写入字幕文件"

# 用假 player 验证调节链路（含 per-file 记忆写入）
class P:
    def __init__(self): self.d = 0; _subtitle_path = ""
    def set_subtitle_delay(self, ms): self.d = ms
    def get_subtitle_delay(self): return self.d
w.player = P()
w._adjust_subtitle_delay(50)
w._adjust_subtitle_delay(50)
print("累计延迟:", w.player.get_subtitle_delay(), "ms")
assert w.player.get_subtitle_delay() == 100
w._reset_subtitle_delay()
print("归零:", w.player.get_subtitle_delay())
assert w.player.get_subtitle_delay() == 0
print("SMOKE_OK")
