"""离屏渲染 AI 字幕对话框，导出 PNG 供视觉核对（新增的分段实时开关）。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

import settings  # noqa: E402
from ai_subtitle_ui import AiSubtitleDialog  # noqa: E402

app = QApplication.instance() or QApplication([])
cfg = settings.Settings.load()
dlg = AiSubtitleDialog(os.path.join(os.path.dirname(ROOT), "tools", "speech_loop.mp4"),
                       None, cfg)
dlg.resize(600, 560)
dlg.show()
app.processEvents()
out = os.path.join(ROOT, "preview_ai_chunk.png")
dlg.grab().save(out)
print("saved", out, os.path.getsize(out), "bytes")
print("分段实时:", dlg.chunk_cb.isChecked(), "段长:", dlg.chunk_seconds, "s")
dlg.close()
