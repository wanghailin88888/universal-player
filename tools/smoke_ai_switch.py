"""验证：换片后 AI 后台进度不被覆盖、独立状态栏格子常驻显示。"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from main_window import MainWindow

app = QApplication([])
w = MainWindow(None)

assert hasattr(w, "status_ai"), "缺少 AI 进度状态栏格子"
w._ai_media = "E:/other/movie.mp4"
w._ai_progress(42, "识别中")
txt = w.status_ai.text()
print("AI 进度显示:", txt)
assert "42%" in txt and "识别中" in txt

# 模拟换片：open_path 会写 status_left（文件名），AI 进度必须还在
w.status_left.setText("新片.mp4")
print("换片后 status_left:", w.status_left.text(), "| status_ai:", w.status_ai.text())
assert "42%" in w.status_ai.text(), "换片后 AI 进度被覆盖"
assert w.status_left.text() == "新片.mp4"

w._ai_set_status("")
assert w.status_ai.text() == ""
print("SMOKE_OK")
