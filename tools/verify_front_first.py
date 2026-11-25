"""渐进式识别验证：先出前 N 秒字幕（回调）→ 再补全整片。"""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_subtitle import generate_subtitles, parse_srt

MEDIA = r"E:/期权/新建文件夹/2026-10-15-10-45-29/tools/speech_loop.mp4"  # 207s，前段有语音
FRONT = 60.0
out = os.path.join(tempfile.gettempdir(), "front_test.srt")
if os.path.exists(out):
    os.remove(out)

events = []
def on_partial(segs, path):
    mx = max((s.end for s in segs), default=0)
    events.append((len(segs), mx, os.path.getsize(path), time.time()))
    print(f"PARTIAL 回调: {len(segs)} 条, 最晚 {mx:.1f}s, 文件 {os.path.getsize(path)}B", flush=True)

t0 = time.time()
res, path = generate_subtitles(MEDIA, size="tiny", src_lang="zh", out_srt=out,
                               workers=2, front_seconds=FRONT,
                               on_partial=on_partial,
                               progress_cb=lambda p, m: None)
el = time.time() - t0
print(f"TOTAL {el:.1f}s  最终 {len(res.segments)} 条", flush=True)

assert events, "on_partial 未被调用（渐进式未生效）"
n_p, mx_p, sz_p, t_p = events[0]
assert mx_p <= FRONT + 2, f"前置片段超出 {FRONT}s：{mx_p:.1f}s"
print(f"前置耗时 {t_p - t0:.1f}s / 总耗时 {el:.1f}s（前段占比 {(t_p-t0)/el:.0%}）")

final = parse_srt(path)
mx_f = max((s.end for s in final), default=0)
print(f"最终 SRT {len(final)} 条，覆盖到 {mx_f:.1f}s")
assert mx_f > FRONT + 5, "后续部分没写进最终 SRT"
assert len(final) >= n_p, "最终条数少于前置片段"
print("SMOKE_OK")
