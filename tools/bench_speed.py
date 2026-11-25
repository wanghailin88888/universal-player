"""三档速度实测：标准(beam5) / 快速(beam1) / 4段并行(beam1)，同一段真实讲课语音。"""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_parallel import extract_wav, transcribe_parallel
from ai_subtitle import transcribe

SRC, DUR = r"E:/1/xyy.mp4", 200.0
wav = os.path.join(tempfile.gettempdir(), "bench200.wav")
assert extract_wav(SRC, 900.0, DUR, wav)
print("wav", os.path.getsize(wav), flush=True)

def go(tag, fn):
    t = time.time(); r = fn(); el = time.time() - t
    print(f"{tag} {el:6.1f}s {len(r.segments):3d}segs {DUR/el:5.2f}x", flush=True)
    return el, r

e1, r1 = go("BEAM5  ", lambda: transcribe(wav, size="tiny", language="zh", beam_size=5, progress_cb=lambda p,m: None))
e2, r2 = go("BEAM1  ", lambda: transcribe(wav, size="tiny", language="zh", beam_size=1, progress_cb=lambda p,m: None))
e3, r3 = go("PAR4B1 ", lambda: transcribe_parallel(wav, size="tiny", language="zh", workers=4, beam_size=1, duration=DUR, progress_cb=lambda p,m: None))
print(f"beam1 vs beam5: {e1/e2:.2f}x   并行+beam1 vs beam5: {e1/e3:.2f}x", flush=True)
print("B5:", " | ".join(s.text[:12] for s in r1.segments[:3]), flush=True)
print("B1:", " | ".join(s.text[:12] for s in r2.segments[:3]), flush=True)
