"""UI 冒烟：AI 字幕对话框「分段实时出字幕」开关 + 段长选择 -> worker.chunk_seconds 链路。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import settings  # noqa: E402
from ai_subtitle_ui import AiSubtitleDialog, AiSubtitleWorker  # noqa: E402

app = QApplication.instance() or QApplication([])
ok = True


def check(label, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(f"[{'PASS' if good else 'FAIL'}] {label}: {got!r} (want {want!r})")


cfg = settings.Settings.load()
# 干净基线：默认开启分段实时、60 秒
cfg.ai_chunk_live = True
cfg.ai_chunk_seconds = 60
media = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test.mp4")

dlg = AiSubtitleDialog(media, None, cfg)
check("chunk_cb 存在", hasattr(dlg, "chunk_cb"), True)
check("默认勾选分段实时", dlg.chunk_cb.isChecked(), True)
check("默认段长 60s", dlg.chunk_seconds, 60.0)
check("段长下拉可选 30/60/120",
      [dlg.chunk_combo.itemData(i) for i in range(dlg.chunk_combo.count())],
      [30, 60, 120])
check("勾选时段长下拉可用", dlg.chunk_combo.isEnabled(), True)

w = AiSubtitleWorker(media, "tiny", "zh", "", True, "auto", "", None,
                     workers=dlg.workers, beam_size=5,
                     temp_fallback=dlg.temp_fallback,
                     chunk_seconds=dlg.chunk_seconds)
check("worker.chunk_seconds", w.chunk_seconds, 60.0)
check("worker.partial 信号存在", hasattr(w, "partial"), True)

# 取消勾选 -> 0.0（等整片出字幕），下拉禁用
dlg.chunk_cb.setChecked(False)
check("取消勾选后 chunk_seconds", dlg.chunk_seconds, 0.0)
check("取消勾选后下拉禁用", dlg.chunk_combo.isEnabled(), False)

# 换段长 + 落盘 + 重开恢复
dlg.chunk_cb.setChecked(True)
dlg.chunk_combo.setCurrentIndex(dlg.chunk_combo.findData(30))
check("切换段长生效", dlg.chunk_seconds, 30.0)
dlg._save_defaults()
cfg2 = settings.Settings.load()
check("配置落盘 ai_chunk_live", bool(getattr(cfg2, "ai_chunk_live", None)), True)
check("配置落盘 ai_chunk_seconds", int(getattr(cfg2, "ai_chunk_seconds", 0)), 30)
dlg2 = AiSubtitleDialog(media, None, cfg2)
check("重开后勾选恢复", dlg2.chunk_cb.isChecked(), True)
check("重开后段长恢复", dlg2.chunk_seconds, 30.0)

dlg.close()
dlg2.close()
print("SMOKE_OK" if ok else "SMOKE_FAIL")
sys.exit(0 if ok else 1)
