"""真实讲课视频对照：单路 vs 4 段并行（速度 + 文本质量）。"""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_parallel import extract_wav, transcribe_parallel
from ai_subtitle import transcribe

SRC = r"E:/1/xyy.mp4"
DUR = 400.0
wav = os.path.join(tempfile.gettempdir(), "bench_real.wav")
print("抽音频:", flush=True)
assert extract_wav(SRC, 0, DUR, wav)
print(f"  {os.path.getsize(wav)/1e6:.1f}MB")

t0 = time.time(); r1 = transcribe(wav, size="tiny", language="zh", progress_cb=lambda p,m: None)
t1 = time.time() - t0
t0 = time.time(); r4 = transcribe_parallel(wav, size="tiny", language="zh", workers=4,
                                           duration=DUR, progress_cb=lambda p,m: None)
t4 = time.time() - t0
n1 = [s for s in r1.segments if s.text.strip()]
n4 = [s for s in r4.segments if s.text.strip()]
print(f"单路  : {t1:6.1f}s  {len(n1):3d} 条  {DUR/t1:.2f}x")
print(f"4段并行: {t4:6.1f}s  {len(n4):3d} 条  {DUR/t4:.2f}x   提速 {t1/t4:.2f}x")
print("单路样例:", " | ".join(s.text[:14] for s in n1[:5]))
print("并行样例:", " | ".join(s.text[:14] for s in n4[:5]))
# 时间轴连续性：并行结果按 100 秒分段应各有内容
for lo, hi, tag in [(0,100,"0-100s"), (100,200,"100-200s"), (200,300,"200-300s"), (300,400,"300-400s")]:
    c1 = sum(1 for s in n1 if lo <= s.start < hi)
    c4 = sum(1 for s in n4 if lo <= s.start < hi)
    print(f"  {tag}: 单路 {c1} 条 / 并行 {c4} 条")
