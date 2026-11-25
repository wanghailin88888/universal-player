"""对比：默认温度回退 vs 关闭回退（temperature=0），同一段真实讲课语音。"""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_subtitle import transcribe
wav = os.path.join(tempfile.gettempdir(), "bench200.wav")
assert os.path.exists(wav), "缺 bench200.wav"
DUR = 200.0
t = time.time(); r = transcribe(wav, size="tiny", language="zh", beam_size=5, progress_cb=lambda p,m: None)
e0 = time.time()-t
print(f"DEFAULT(回退)  {e0:6.1f}s {len(r.segments):3d}segs {DUR/e0:5.2f}x", flush=True)
t = time.time(); r2 = transcribe(wav, size="tiny", language="zh", beam_size=5, temperature=[0.0], progress_cb=lambda p,m: None)
e1 = time.time()-t
print(f"TEMP0  (不回退) {e1:6.1f}s {len(r2.segments):3d}segs {DUR/e1:5.2f}x", flush=True)
print(f"提速 {e0/e1:.2f}x", flush=True)
print("样例:", " | ".join(s.text[:12] for s in r2.segments[:3]), flush=True)
