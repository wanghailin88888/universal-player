"""验证：AI 字幕默认中文 + 点开始生成后设置界面立即可关、任务转后台。"""
import os, sys, types, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, QTimer
import tempfile

app = QApplication([])
from settings import Settings
from ai_subtitle_ui import AiSubtitleDialog

# 造假素材文件（不真识别，只验证信号移交）
tmp = os.path.join(tempfile.gettempdir(), "ai_bg_dummy.mp4")
open(tmp, "wb").write(b"\0" * 1024)

s = Settings()
s.ai_src_lang = "中文"; s.ai_dst_lang = "不翻译"; s.ai_model = "small（推荐，480MB）"
dlg = AiSubtitleDialog(tmp, None, s)
print("源语言默认:", dlg.src_combo.currentText())
print("目标语言默认:", dlg.dst_combo.currentText())
assert dlg.src_combo.currentText() == "中文", "源语言默认应为中文"

# 用户改成日语后保存 → 再开对话框应记住日语
dlg.src_combo.setCurrentText("日语")
dlg.dst_combo.setCurrentText("英语")
got = {}
def on_started(w):
    got["worker"] = w
dlg.started.connect(on_started)
dlg._start()
print("对话框已关闭(result):", dlg.result())
assert "worker" in got, "未发出 started 信号"
w = got["worker"]
print("worker parent:", w.parent(), "(应为 None)")
assert w.parent() is None
print("worker media:", os.path.basename(w.media), "out:", os.path.basename(w.out_srt))
assert w.out_srt.endswith(".srt")
print("配置已保存: src=%s dst=%s" % (s.ai_src_lang, s.ai_dst_lang))
assert s.ai_src_lang == "日语", "改过的配置应记住"

dlg2 = AiSubtitleDialog(tmp, None, s)
print("重开对话框源语言:", dlg2.src_combo.currentText())
assert dlg2.src_combo.currentText() == "日语"
print("SMOKE_OK")
