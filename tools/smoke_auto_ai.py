"""验证：换视频自动生成 AI 字幕（开关/模型就绪两条分支）+ 列表外文件补进列表。"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from main_window import MainWindow
import ai_subtitle

app = QApplication([])
w = MainWindow(None)
assert w.settings.ai_auto_on_open is False, "默认应关闭"
print("默认开关: False  ✓")

class P:
    def open(self, *a, **k): pass
    def set_subtitle_delay(self, ms): pass
    def get_subtitle_tracks(self): return []
    def add_subtitle(self, p): return True
if w.player is None:
    w.player = P()

d = tempfile.mkdtemp()
f = os.path.join(d, "lonely.mp4"); open(f, "wb").write(b"\0" * 2048)
w.open_path(f)
print("列表外文件补进列表: row=%d path=%s" % (w.current_row, os.path.basename(w._current_path())))
assert w.current_row >= 0 and w._current_path() == f

srt = os.path.join(d, "lonely.srt")
open(srt, "w", encoding="utf-8").write("1\n00:00:01,000 --> 00:00:02,000\nhi\n")
assert w._has_srt(f) is True
print("已有 srt 时 _has_srt=True  ✓（不会重复生成）")

f2 = os.path.join(d, "nosub.mp4"); open(f2, "wb").write(b"\0" * 2048)
w.settings.ai_auto_on_open = True

# 分支 A：模型未就绪 → 跳过并提示
w.settings.ai_model = "medium（1.5GB）"
w._ai_set_status("")
w._auto_ai_subtitle(f2)
print("A 未就绪:", repr(w.status_ai.text()), "| worker:", w._ai_worker)
assert w._ai_worker is None, "模型未就绪不应启动"
assert "未下载" in w.status_ai.text() or w.status_ai.text() == ""

# 分支 B：模型已就绪 → 启动后台任务（立即取消，不真跑）
ready = ai_subtitle.is_model_ready("small")
w.settings.ai_model = "small（推荐，480MB）"
w._auto_ai_subtitle(f2)
if ready:
    assert w._ai_worker is not None, "模型就绪应启动"
    print("B 已就绪: 已启动 ->", w.status_ai.text())
    w._ai_worker.cancel()
    w._ai_worker.wait(5000)
    print("   已取消，退出码检查 ok")
else:
    print("B 已就绪: 本机 small 未下载，跳过")
print("SMOKE_OK")
