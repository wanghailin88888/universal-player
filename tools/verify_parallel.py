"""分段并行识别验证：时长探测/切段/抽音/并行合并/时间戳对齐。"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_parallel import media_duration, plan_segments, extract_wav, transcribe_parallel, auto_workers

OK = []
def check(n, c, e=""):
    OK.append(c); print(("PASS " if c else "FAIL ") + n + (f"  [{e}]" if e else ""))

ROOT_TOOLS = r"E:/期权/新建文件夹/2026-10-15-10-45-29/tools"
media = os.path.join(ROOT_TOOLS, "speech_zh.mp4")
if not os.path.exists(media):
    media = os.path.join(ROOT_TOOLS, "speech_short.mp4")
dur = media_duration(media)
check("时长探测", dur > 0, f"{dur:.2f}s")
check("自动段数合理", 1 <= auto_workers() <= 4, str(auto_workers()))

plan = plan_segments(dur, 3)
check("切成 3 段", len(plan) == 3, str([(round(a,1), round(b,1), round(c,1)) for a,b,c in plan]))
check("末段覆盖到片尾", abs((plan[-1][0]+plan[-1][1]) - dur) < 0.01)
check("有效起点递增", plan[0][2] == 0 and plan[1][2] > 0 and plan[2][2] > plan[1][2])

import tempfile
w = os.path.join(tempfile.gettempdir(), "p0.wav")
check("ffmpeg 抽段成功", extract_wav(media, plan[0][0], min(5.0, plan[0][1]), w),
      f"{os.path.getsize(w) if os.path.exists(w) else 0}B")

t0 = time.time()
res = transcribe_parallel(media, size="tiny", language="zh", workers=3,
                          progress_cb=lambda p, m: None)
el = time.time() - t0
segs = res.segments
check("并行返回字幕", len(segs) > 0, f"{len(segs)} 条 / {el:.1f}s")
if segs:
    check("时间戳单调递增", all(segs[i].start <= segs[i+1].start + 0.01 for i in range(len(segs)-1)))
    check("时间戳不超片长", segs[-1].end <= dur + 3, f"last={segs[-1].end:.1f}s dur={dur:.1f}s")
    check("无重叠段", all(segs[i].end <= segs[i+1].start + 0.06 for i in range(len(segs)-1)))
    print("  首条:", round(segs[0].start,2), round(segs[0].end,2), segs[0].text[:40])
    print("  末条:", round(segs[-1].start,2), round(segs[-1].end,2), segs[-1].text[:40])

# 单路对照：条数不应差太多（允许边界差异）
from ai_subtitle import transcribe as single
s1 = single(media, size="tiny", language="zh", progress_cb=lambda p,m: None)
print(f"  单路 {len(s1.segments)} 条 vs 并行 {len(segs)} 条")
check("并行/单路条数接近", abs(len(segs) - len(s1.segments)) <= max(2, len(s1.segments) * 0.5))
print("\nRESULT:", "ALL_PASS" if all(OK) else "FAILED")
