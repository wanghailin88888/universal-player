"""端到端验证：按 60 秒（这里用 30 秒加速测试）分段顺序识别，字幕逐段实时出现。

验收点
1) on_partial 被多次回调（每段一次）——不是等整片跑完才出字幕；
2) 每次回调的 SRT 覆盖时长单调增长，且文件内容确实是累计的；
3) 第一次回调发生在总耗时很早的位置（用户马上就有字幕看）；
4) 最终写出的完整 SRT 时间轴有序、无重叠、覆盖到片尾。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import ai_subtitle  # noqa: E402

TOOLS = os.path.join(os.path.dirname(ROOT), "tools")
MEDIA = os.path.join(TOOLS, "speech_loop.mp4")
OUT = os.path.join(TOOLS, "_chunk_live.srt")
CHUNK = 30.0

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  | " + detail) if detail else ""))
    if not cond:
        fails.append(name)


dur = 0.0
try:
    from ai_parallel import media_duration
    dur = float(media_duration(MEDIA))
except Exception:
    pass
print(f"素材 {os.path.basename(MEDIA)} 时长 {dur:.1f}s，分段 {CHUNK:.0f}s\n")

events = []
t0 = time.time()


def on_partial(segs, srt):
    el = time.time() - t0
    cover = max((s.end for s in segs), default=0.0)
    size = os.path.getsize(srt) if os.path.exists(srt) else 0
    events.append({"t": el, "n": len(segs), "cover": cover, "size": size, "path": srt})
    print(f"  [{el:6.1f}s] PARTIAL {len(segs):3d} 条  覆盖到 {cover:6.1f}s  ({size}B)")


res, srt_out = ai_subtitle.generate_subtitles(
    MEDIA, size="tiny", src_lang="zh", dst_lang="", bilingual=True,
    device="cpu", out_srt=OUT, workers=1, beam_size=5, temp_fallback=False,
    chunk_seconds=CHUNK, on_partial=on_partial,
    progress_cb=lambda p, m: print(f"    · {p:3d}% {m}"))

total = time.time() - t0
print()
print(f"总耗时 {total:.1f}s，最终 {len(res.segments)} 条，写出 {srt_out}")

check("逐段回调多次(每段一次)", len(events) >= 3, f"{len(events)} 次")
if events:
    covs = [e["cover"] for e in events]
    check("覆盖时长单调增长", all(b >= a - 0.01 for a, b in zip(covs, covs[1:])), str(
        [round(c, 1) for c in covs]))
    check("SRT 文件逐次变大(累计写盘)",
          all(b >= a for a, b in zip([e["size"] for e in events],
                                     [e["size"] for e in events[1:]])),
          str([e["size"] for e in events]))
    check("第一条字幕很早就出", events[0]["t"] < total * 0.35,
          f"首次 {events[0]['t']:.1f}s / 总 {total:.1f}s")
    check("最后一次覆盖到片尾附近", covs[-1] >= dur * 0.9,
          f"{covs[-1]:.1f}s / {dur:.1f}s")

# 最终文件检查
parsed = ai_subtitle.parse_srt(srt_out)
check("最终 SRT 有序", all(parsed[i].start <= parsed[i + 1].start
                           for i in range(len(parsed) - 1)))
check("最终 SRT 无重叠", all(parsed[i].end <= parsed[i + 1].start + 0.06
                             for i in range(len(parsed) - 1)))
check("最终条数不少于逐段累计", len(parsed) >= (events[-1]["n"] if events else 0),
      f"{len(parsed)} vs {events[-1]['n'] if events else 0}")

if os.path.exists(OUT):
    os.remove(OUT)

print("\n结论:", "ALL_PASS" if not fails else "FAIL -> " + ", ".join(fails))
sys.exit(0 if not fails else 1)
