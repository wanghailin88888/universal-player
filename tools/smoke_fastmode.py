"""验证「识别模式（温度回退）」链路：UI 默认快速 + 配置记忆 + 参数贯通 + 真实识别不报错。"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from settings import Settings
from ai_subtitle_ui import AiSubtitleDialog

app = QApplication([])
s = Settings()
d = AiSubtitleDialog("", None, s)
items = [(d.speed_combo.itemText(i), d.speed_combo.itemData(i)) for i in range(d.speed_combo.count())]
print("模式选项:", items)
assert len(items) == 2 and items[0][1] == 0
print("默认 temp_fallback =", d.temp_fallback, "（应为 False=快速）")
assert d.temp_fallback is False
d.speed_combo.setCurrentIndex(1)
print("切稳健 -> ", d.temp_fallback); assert d.temp_fallback is True
d._save_defaults(); print("已保存 ai_temp_fallback =", s.ai_temp_fallback)
assert s.ai_temp_fallback is True

tmp = os.path.join(tempfile.gettempdir(), "fastmode.mp4"); open(tmp, "wb").write(b"\0"*1024)
d2 = AiSubtitleDialog(tmp, None, s)
got = {}
d2.started.connect(lambda w: got.setdefault("w", w))
d2._start()
w = got["w"]
print("worker.temp_fallback =", w.temp_fallback, "| beam =", w.beam_size)
assert w.temp_fallback is True and w.beam_size == 5

# 真实调用：确认 temperature 参数被 faster-whisper 接受（短片 10s）
from ai_subtitle import generate_subtitles
media = r"E:/期权/新建文件夹/2026-10-15-10-45-29/tools/speech_zh.mp4"
out = os.path.join(tempfile.gettempdir(), "fastmode_test.srt")
res, path = generate_subtitles(media, size="tiny", src_lang="zh", out_srt=out,
                               workers=1, temp_fallback=False,
                               progress_cb=lambda p, m: None)
print(f"真实识别: {len(res.segments)} 条 -> {os.path.basename(path)}")
print("内容:", " | ".join(x.text for x in res.segments[:3]))
assert len(res.segments) > 0
s.ai_temp_fallback = False; s.save()   # 还原默认
print("SMOKE_OK")
