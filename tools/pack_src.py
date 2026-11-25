import os, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.path.dirname(ROOT), "release", "universal_player-v1.3-src.zip")
INCLUDE_FILES = [
    "main.py", "main_window.py", "vlc_player.py", "playlist.py",
    "settings.py", "ai_subtitle.py", "ai_subtitle_ui.py", "ai_parallel.py",
    "resources.py", "srt_util.py",
    "README.md", "requirements.txt", "run.bat", "build.spec",
    "verify_ui.py", "verify_playback.py", "verify_ai_subtitle.py",
    "verify_subtitle_swap.py",
]
INCLUDE_PATHS = [
    "assets/app.ico", "assets/app.png",
    "tools/make_icon.py", "tools/pack_src.py", "tools/verify_sub_delay.py",
    "tools/smoke_sub_delay.py", "tools/smoke_icon.py",
    "tools/smoke_ai_bg.py", "tools/smoke_ai_switch.py", "tools/smoke_auto_ai.py",
    "tools/smoke_srt_instant.py", "tools/smoke_workers_ui.py",
    "tools/verify_parallel.py", "tools/verify_parallel_speed.py",
    "tools/verify_parallel_real.py", "tools/bench_parallel.py",
    "tools/bench_speed.py", "tools/bench_temp.py", "tools/smoke_fastmode.py",
    "tools/verify_front_first.py", "tools/verify_chunk_live.py",
    "tools/verify_cancel.py", "tools/verify_antiloop.py",
    "tools/smoke_chunk_ui.py", "tools/smoke_chunk_flow.py",
    "tools/probe_slave.py", "tools/shot_ai_chunk.py",
]
os.makedirs(os.path.dirname(OUT), exist_ok=True)
if os.path.exists(OUT):
    os.remove(OUT)
n = 0
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for f in INCLUDE_FILES + INCLUDE_PATHS:
        p = os.path.join(ROOT, f)
        if os.path.exists(p):
            z.write(p, os.path.join("universal_player", f))
            n += 1
        else:
            print("MISSING:", f)
print("PACKED", n, "files ->", OUT, os.path.getsize(OUT), "bytes")
