"""验证：AI 对话框分段并行选项 + 配置记忆 + 传给 worker。"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from settings import Settings
from ai_subtitle_ui import AiSubtitleDialog

app = QApplication([])
s = Settings()
s.ai_workers = 0
d = AiSubtitleDialog("", None, s)
opts = [(d.workers_combo.itemText(i), d.workers_combo.itemData(i)) for i in range(d.workers_combo.count())]
print("选项:", opts)
assert len(opts) == 5, "应有 5 个分段选项"
assert d.workers == 0, "默认自动"

d.workers_combo.setCurrentIndex(d.workers_combo.findData(2))
print("选择 2 段 -> property workers =", d.workers)
assert d.workers == 2

d._save_defaults()
print("已保存 ai_workers =", s.ai_workers)
assert s.ai_workers == 2

d2 = AiSubtitleDialog("", None, s)
print("重开对话框默认:", d2.workers_combo.currentText(), d2.workers)
assert d2.workers == 2

# 传给 worker
tmp = os.path.join(tempfile.gettempdir(), "workers_ui.mp4"); open(tmp, "wb").write(b"\0"*1024)
d3 = AiSubtitleDialog(tmp, None, s)
got = {}
d3.started.connect(lambda w: got.setdefault("w", w))
d3._start()
print("worker.workers =", got["w"].workers)
assert got["w"].workers == 2
s.ai_workers = 0; s.save()   # 还原
print("SMOKE_OK")
