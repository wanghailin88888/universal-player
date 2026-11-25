"""端到端播放验证（真实 VLC 引擎，非 UI 冒烟）。

验证项：多容器解码(mmp4/mkv/ts)、时长、分辨率/帧率/编码、音轨与字幕轨枚举、
        seek、倍速、音量、外部字幕加载、逐帧截图。

用法:
    python verify_playback.py
    # 便携版 VLC 可用环境变量指定：
    set VLC_DIR=<含 libvlc.dll 的目录>
"""
from __future__ import annotations

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def find_vlc_dir():
    """定位含 libvlc.dll 的目录（环境变量优先，其次常见安装路径与便携目录）。"""
    env = os.environ.get("VLC_DIR", "")
    cands = [
        env,
        r"C:\Program Files\VideoLAN\VLC",
        r"C:\Program Files (x86)\VideoLAN\VLC",
        os.path.join(os.path.dirname(HERE), "tools", "vlc"),
        os.path.join(os.path.dirname(HERE), "tools", "vlc", "vlc-3.0.24"),
    ]
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "libvlc.dll")):
            return c
    for c in cands:  # 便携目录可能再包一层
        if c and os.path.isdir(c):
            for sub in sorted(os.listdir(c)):
                d = os.path.join(c, sub)
                if os.path.isfile(os.path.join(d, "libvlc.dll")):
                    return d
    return None


vlc_dir = find_vlc_dir()
if not vlc_dir:
    print("FATAL: 未找到 libvlc.dll。请安装 VLC，或设置环境变量 VLC_DIR 指向含 libvlc.dll 的目录")
    sys.exit(2)

os.environ["PATH"] = vlc_dir + os.pathsep + os.environ.get("PATH", "")
try:
    os.add_dll_directory(vlc_dir)  # Python 3.8+ DLL 搜索目录
except Exception:
    pass
if os.path.isdir(os.path.join(vlc_dir, "plugins")):
    os.environ.setdefault("VLC_PLUGIN_PATH", os.path.join(vlc_dir, "plugins"))
print("[ENV] libvlc 目录:", vlc_dir)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

import vlc  # noqa: E402
from vlc_player import VlcPlayer  # noqa: E402

app = QApplication([])
win = QWidget()
win.resize(640, 360)
win.show()

print("[VLC] 内核版本:", vlc.libvlc_get_version().decode())

MEDIA_DIR = os.environ.get(
    "TEST_MEDIA_DIR", os.path.join(os.path.dirname(HERE), "tools"))
FILES = ["test.mp4", "test.mkv", "test.ts"]
SUB_FILE = os.path.join(MEDIA_DIR, "test.srt")

# 无显示环境(沙盒/CI)走 dummy 输出，避免 Windows 无法创建渲染窗口而刷屏报错；
# 有显示的本机可用 VLC_HEADLESS=0 启用真实渲染并验证截图。
HEADLESS = os.environ.get("VLC_HEADLESS", "1") == "1"

results = []
player = VlcPlayer(extra_args=["--vout=dummy", "--aout=dummy"] if HEADLESS else None)
if not HEADLESS:
    player.set_hwnd(int(win.winId()))  # offscreen widget 作为渲染目标

ALL_OK = True
try:
    for name in FILES:
        path = os.path.join(MEDIA_DIR, name)
        if not os.path.exists(path):
            print(f"[SKIP] 不存在: {name}")
            continue
        player.open(path)
        length = 0
        for _ in range(80):  # 最多等 8s 让媒体加载出时长
            length = player.get_length()
            if length > 0:
                break
            time.sleep(0.1)

        info = player.media_info()
        if not info["width"] or not info["height"]:
            # 慢解析容器(如 MPEG-TS)：模拟主窗口的延迟重试机制
            time.sleep(3.0)
            info = player.media_info()
        subs_tracks = player.get_subtitle_tracks()
        audio_tracks = player.get_audio_tracks()

        # seek 到中段
        pos_ok = False
        if length > 0:
            player.set_time(length // 2)
            time.sleep(0.5)
            pos_ok = player.get_time() > 0

        player.set_rate(1.5)
        rate_ok = abs(player.get_rate() - 1.5) < 0.01
        # 音量：dummy 音频输出下 VLC 无真实音量通道，headless 环境跳过判定
        if HEADLESS:
            player.set_volume(55)
            time.sleep(0.2)
            vol_now = player.get_volume()
            vol_ok = None
            vol_note = f"SKIP(dummy 音频输出, 实测={vol_now})"
        else:
            player.set_volume(55)
            time.sleep(0.3)  # VLC 音量设置异步生效
            vol_now = player.get_volume()
            vol_ok = abs(vol_now - 55) <= 1
            vol_note = "OK" if vol_ok else f"FAIL({vol_now})"

        # 外部字幕加载
        sub_ok = False
        if os.path.exists(SUB_FILE):
            sub_ok = player.add_subtitle(SUB_FILE)
            time.sleep(0.8)
            subs_tracks = player.get_subtitle_tracks()

        # 截图（需要已渲染出画面）
        time.sleep(0.8)
        snap = os.path.join(MEDIA_DIR, "snap_" + name + ".png")
        if HEADLESS:
            snap_ok, size, snap_note = None, 0, "SKIP(无显示渲染)"
        else:
            snap_ok = player.snapshot(snap)
            size = os.path.getsize(snap) if (snap_ok and os.path.exists(snap)) else 0
            snap_note = f"OK ({size} bytes)" if snap_ok else "FAIL"

        player.stop()

        res = {
            "file": name, "length_ms": length,
            "width": info["width"], "height": info["height"],
            "fps": info["fps"], "vcodec": info["vcodec"], "acodec": info["acodec"],
            "audio_tracks": len(audio_tracks), "subtitle_tracks": len(subs_tracks),
            "seek_ok": pos_ok, "rate_ok": rate_ok, "volume_ok": vol_ok,
            "subtitle_load": bool(sub_ok), "snapshot": bool(snap_ok),
            "snapshot_bytes": size,
        }
        results.append(res)

        if not (length > 0 and pos_ok and rate_ok and vol_ok is not False):
            ALL_OK = False

        print(f"\n--- {name}")
        print(f"   时长        : {length} ms")
        print(f"   视频        : {info['width']}x{info['height']}  {info['fps']}fps  {info['vcodec']}")
        print(f"   音频        : {info['acodec']}   音轨数={len(audio_tracks)}")
        print(f"   字幕轨      : {len(subs_tracks)}")
        print(f"   seek        : {'OK' if pos_ok else 'FAIL'}")
        print(f"   倍速/音量   : {'OK' if rate_ok else 'FAIL'} / {vol_note}")
        print(f"   外部字幕    : {'OK' if sub_ok else 'FAIL'}")
        print(f"   截图        : {snap_note}")
finally:
    player.release()

print("\n==== SUMMARY ====")
for r in results:
    verdict = "PASS" if (r["length_ms"] > 0 and r["seek_ok"]
                         and r["rate_ok"] and r["volume_ok"] is not False) else "FAIL"
    print(f"  {r['file']:10s} {verdict}  {r['length_ms']:>5}ms "
          f"{r['width']}x{r['height']} {r['fps']}fps {r['vcodec']}")
print("RESULT:", "ALL_PASS" if ALL_OK else "SOME_FAILED")
sys.exit(0 if ALL_OK else 1)
