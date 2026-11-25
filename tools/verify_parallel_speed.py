"""分段并行提速实测：同一段音频，单路 vs 4 段并行的耗时对比。"""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_parallel import extract_wav, transcribe_parallel, auto_workers
from ai_subtitle import transcribe

SRC = r"E:/1/2.mp4"
DUR = 400.0     # 取前 400 秒做基准
wav = os.path.join(tempfile.gettempdir(), "bench_400.wav")
print("抽音频…", end=" ", flush=True)
assert extract_wav(SRC, 0, DUR, wav), "抽音失败"
print(f"{os.path.getsize(wav)/1e6:.1f}MB  自动段数={auto_workers()}")

def run(label, fn):
    t0 = time.time()
    r = fn()
    el = time.time() - t0
    print(f"{label}: {el:6.1f}s  {len(r.segments):3d} 条  ({DUR/el:.2f}x 实时)")
    return el, r

# 单路（内部 4 线程）
t1, r1 = run("单路  ", lambda: transcribe(wav, size="tiny", language="zh",
                                          progress_cb=lambda p, m: None))
# 4 段并行
t4, r4 = run("4 段并行", lambda: transcribe_parallel(wav, size="tiny", language="zh",
                                                     workers=4, duration=DUR,
                                                     progress_cb=lambda p, m: None))
print(f"\n提速：{t1/t4:.2f}x （{t1:.1f}s → {t4:.1f}s）")
print(f"条数：单路 {len(r1.segments)} vs 并行 {len(r4.segments)}")
