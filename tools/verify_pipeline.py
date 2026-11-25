"""验证翻译流水线：识别/翻译并行，逐段出字幕且译文随段出现。

用 whisper task=translate（dst=en）走流水线，无需 Argos 网络。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "universal_player"))
os.environ.setdefault("ARGOS_CHUNK_TYPE", "MINISBD")

MEDIA = os.path.join(ROOT, "tools", "speech_zh.mp4")

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name, flush=True)


from ai_subtitle import generate_subtitles
import ai_subtitle as _ais
# 验证目标是流水线时序；tiny 模型 + 3s 窗口输出易被抗幻觉过滤清空，先旁路
_ais.suppress_hallucination = lambda segs, **kw: list(segs)

partials = []


def on_partial(segs, srt_path):
    partials.append((len(segs), srt_path))
    print(f"  on_partial: {len(segs)} segs @ {time.strftime('%H:%M:%S')}", flush=True)


pct_log = []


def progress_cb(p, msg):
    pct_log.append((p, msg))
    print(f"  [{p:3d}%] {msg}", flush=True)


t0 = time.time()
res, srt = generate_subtitles(
    MEDIA, size="tiny", src_lang="zh", dst_lang="en",
    bilingual=True, out_srt=os.path.join(os.path.dirname(MEDIA), "_pipe_test.srt"),
    cancel_check=lambda: False, progress_cb=progress_cb,
    workers=1, chunk_seconds=3.0, on_partial=on_partial)
elapsed = time.time() - t0
print(f"elapsed {elapsed:.1f}s", flush=True)

check("multi_partials", len(partials) >= 2)          # 多次回调 = 逐段出字幕
check("segments_found", len(res.segments) > 0)
check("growing_partials",
      partials[-1][0] > 0 and
      all(a[0] <= b[0] for a, b in zip(partials, partials[1:])))  # 单调不减
check("trans_filled", all(sg.trans for sg in res.segments[:5]))  # 译文已填（whisper translate）
check("final_srt_exists", os.path.isfile(srt) and os.path.getsize(srt) > 100)
check("pipeline_msgs", any("后台翻译" in m for _, m in pct_log))
check("no_acc_reset", partials[-1][0] >= partials[-2][0])        # 累计不回退

# 清理
try:
    os.remove(os.path.join(os.path.dirname(MEDIA), "_pipe_test.srt"))
except Exception:
    pass

print("\nALL_PASS" if not FAIL else f"\nFAILED: {FAIL}")
sys.exit(0 if not FAIL else 1)
