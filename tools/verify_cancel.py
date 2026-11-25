"""验证：逐段实时模式下「取消」能及时停住，并且已识别的部分会落盘保留。"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import ai_subtitle  # noqa: E402
from ai_subtitle import AsrError  # noqa: E402

TOOLS = os.path.join(os.path.dirname(ROOT), "tools")
MEDIA = os.path.join(TOOLS, "speech_loop.mp4")
OUT = os.path.join(TOOLS, "_cancel_test.srt")
if os.path.exists(OUT):
    os.remove(OUT)

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  | " + detail) if detail else ""))
    if not cond:
        fails.append(name)


t0 = time.time()
partials = []


def cancel_check():
    # 第 1 段字幕一出就立刻取消（模拟用户看到第一段后按停止）
    return len(partials) >= 1 and (time.time() - t0) > 5


cancelled = False
try:
    ai_subtitle.generate_subtitles(
        MEDIA, size="tiny", src_lang="zh", dst_lang="", bilingual=True,
        device="cpu", out_srt=OUT, workers=1, beam_size=5, temp_fallback=False,
        chunk_seconds=20.0, on_partial=lambda segs, p: partials.append(len(segs)),
        cancel_check=cancel_check,
        progress_cb=lambda p, m: print(f"    · {p:3d}% {m}"))
except AsrError as e:
    cancelled = "已取消" in str(e)
    print("  抛出:", e)

el = time.time() - t0
print(f"\n取消耗时 {el:.1f}s；取消前回调 {len(partials)} 次")

check("取消能抛「已取消」", cancelled)
check("取消后很快停下（不跑完整片）", el < 150, f"{el:.1f}s")
check("取消前已出过实时字幕", len(partials) >= 1, str(partials))
check("已识别部分已落盘", os.path.exists(OUT), OUT)
if os.path.exists(OUT):
    segs = ai_subtitle.parse_srt(OUT)
    check("保留的字幕条数 > 0", len(segs) > 0, f"{len(segs)} 条")
    check("保留内容时间轴有序",
          all(segs[i].start <= segs[i + 1].start for i in range(len(segs) - 1)))
    if segs:
        print(f"  已保留覆盖到 {segs[-1].end:.1f}s")
    os.remove(OUT)

print("\n结论:", "ALL_PASS" if not fails else "FAIL -> " + ", ".join(fails))
sys.exit(0 if not fails else 1)
