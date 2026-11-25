"""Quick bench: single-pass vs 4-way parallel on the SAME 400s slice."""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_parallel import extract_wav, transcribe_parallel
from ai_subtitle import transcribe

SRC, DUR = r"E:/1/xyy.mp4", 400.0
wav = os.path.join(tempfile.gettempdir(), "bench400r.wav")
assert extract_wav(SRC, 600.0, DUR, wav), "extract failed"   # 取第 10 分钟起的一段讲课语音
print("wav ok", os.path.getsize(wav), flush=True)

t0 = time.time(); r1 = transcribe(wav, size="tiny", language="zh", progress_cb=lambda p, m: None)
t1 = time.time() - t0
print(f"SINGLE {t1:.1f}s {len(r1.segments)}segs {DUR/t1:.2f}x", flush=True)

t0 = time.time(); r4 = transcribe_parallel(wav, size="tiny", language="zh", workers=4,
                                          duration=DUR, progress_cb=lambda p, m: None)
t4 = time.time() - t0
print(f"PAR4   {t4:.1f}s {len(r4.segments)}segs {DUR/t4:.2f}x speedup={t1/t4:.2f}x", flush=True)
print("S1:", " | ".join(s.text[:12] for s in r1.segments[:4]), flush=True)
print("P4:", " | ".join(s.text[:12] for s in r4.segments[:4]), flush=True)
