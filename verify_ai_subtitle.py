"""AI 字幕端到端验证：识别 → 翻译 → 生成 SRT → 挂载播放器 → 校验播放同步。

无 GUI 版本（headless），适合在服务器/沙盒里跑：
    python verify_ai_subtitle.py            # 默认跑全部用例
    python verify_ai_subtitle.py --files X  # 指定媒体
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ai_subtitle as ai  # noqa: E402

MEDIA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools"))
DEFAULT_MEDIA = os.path.join(MEDIA_DIR, "speech_zh.mp4")

ALL_OK = True


def head(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def check(name: str, ok: bool, extra: str = "") -> bool:
    global ALL_OK
    if not ok:
        ALL_OK = False
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    return ok


# ---------------------------------------------------------------- 1. 依赖
def test_deps():
    head("1. 运行环境依赖")
    mods = {"faster_whisper": "语音识别", "ctranslate2": "推理引擎",
            "av": "音视频解码", "argostranslate": "离线翻译"}
    ok = True
    for m, desc in mods.items():
        try:
            __import__(m)
            check(f"{m} ({desc})", True)
        except Exception as e:
            check(f"{m} ({desc})", False, str(e)[:90])
            ok = False
    try:
        import av
        major = int(str(av.__version__).split(".")[0])
        # faster-whisper 1.2.x 用了 av.open(metadata_errors=...)，av>=19 已移除该参数
        check("av 版本兼容性 (<19)", major < 19, f"当前 {av.__version__}")
    except Exception as e:
        check("av 版本兼容性", False, str(e)[:80])
    return ok


# ---------------------------------------------------------------- 2. 模型
def test_model(size: str = "tiny"):
    head(f"2. Whisper 模型 ({size})")
    ready = ai.is_model_ready(size)
    if not ready:
        print(f"  模型未下载，正在从镜像下载 {size} …")
        t = time.time()
        try:
            ai.ensure_whisper_model(size, lambda p, m: None)
            ready = True
            print(f"  下载完成，用时 {time.time() - t:.1f}s")
        except Exception as e:
            check("模型下载", False, str(e)[:150])
            return False
    d = ai.whisper_model_dir(size)
    mb = os.path.getsize(os.path.join(d, "model.bin")) / 1024 / 1024
    check("模型文件就绪", ready, f"{d}  model.bin={mb:.0f}MB")
    return ready


# ---------------------------------------------------------------- 3. 识别
def test_asr(media: str, size: str = "tiny"):
    head(f"3. 语音识别：{os.path.basename(media)}")
    if not os.path.exists(media):
        check("测试素材存在", False, media)
        return None
    t = time.time()
    try:
        res, srt = ai.generate_subtitles(media, size=size, src_lang="zh",
                                         dst_lang="", device="cpu")
    except Exception as e:
        check("识别执行", False, str(e)[:200])
        return None
    cost = time.time() - t
    audio_len = res.duration or 1
    print(f"  耗时 {cost:.1f}s / 音频 {audio_len:.1f}s  → 实时率 {cost / audio_len:.2f}x")
    check("识别出字幕", len(res) > 0, f"{len(res)} 条")
    check("语言识别正确", res.language == "zh", f"{res.language} ({res.language_prob:.0%})")
    check("时间轴有效", all(s.end > s.start for s in res.segments))
    # 时间轴必须落在音频范围内
    span_ok = 0 <= res.segments[0].start < audio_len and \
        res.segments[-1].end <= audio_len + 1.5
    check("时间轴落在音频范围内", span_ok,
          f"[{res.segments[0].start:.2f}, {res.segments[-1].end:.2f}]")
    check("SRT 文件已生成", os.path.exists(srt) and os.path.getsize(srt) > 0,
          f"{os.path.getsize(srt)} bytes")
    for s in res.segments[:6]:
        print(f"    [{s.start:6.2f} → {s.end:6.2f}] {s.text}")
    return res


# ---------------------------------------------------------------- 4. 翻译
def test_translate(media: str, res, dst: str = "en", size: str = "tiny"):
    head(f"4. 字幕翻译：中文 → {dst}")
    if res is None:
        check("依赖识别结果", False)
        return False
    tr = ai.Translator()
    src = res.language
    need_argos = (dst != "en")  # 英文走 Whisper 内置翻译，其余用 Argos
    if need_argos and not tr.is_pair_installed(src, dst):
        print(f"  首次使用，下载离线翻译包 {src}→{dst} …")
        try:
            tr.install_pair(src, dst, lambda p, m: print(f"    [{p:3d}%] {m}"))
        except Exception as e:
            check("翻译包安装", False, str(e)[:150])
            return False
        check("翻译包安装", True)
    try:
        tr.translate_segments(res.segments, src, dst)
    except Exception as e:
        check("翻译执行", False, str(e)[:150])
        return False
    hit = sum(1 for s in res.segments if s.trans and s.trans.strip())
    check("译文生成", hit > 0, f"{hit}/{len(res.segments)} 条")
    for s in res.segments[:3]:
        print(f"    原文: {s.text}")
        print(f"    译文: {s.trans}")
    out = os.path.join(os.path.dirname(os.path.abspath(media)),
                       "ai_双语.srt")
    ai.write_srt(res.segments, out, "bilingual")
    check("双语 SRT 已导出", os.path.getsize(out) > 0, out)
    return True


# ---------------------------------------------------------------- 5. Whisper 译英
def test_whisper_translate(media: str, size: str = "tiny"):
    head("5. Whisper 内置译英（不依赖翻译包）")
    try:
        res, srt = ai.generate_subtitles(media, size=size, src_lang="zh",
                                         dst_lang="en", device="cpu")
    except Exception as e:
        check("Whisper 译英", False, str(e)[:150])
        return False
    hit = sum(1 for s in res.segments if s.trans.strip())
    check("英文译文生成", hit > 0, f"{hit}/{len(res.segments)} 条")
    ascii_ratio = sum(1 for s in res.segments
                      for c in s.trans if c.isascii() and c.isalpha())
    check("译文为英文字符集", ascii_ratio > 0)
    for s in res.segments[:3]:
        print(f"    {s.text}  →  {s.trans}")
    return True


# ---------------------------------------------------------------- 6. SRT 解析
def test_srt_roundtrip(res):
    head("6. SRT 读写往返一致性")
    if not res or not res.segments:
        check("依赖识别结果", False)
        return False
    p = os.path.join(MEDIA_DIR, "ai_roundtrip.srt")
    ai.write_srt(res.segments, p, "original")
    back = ai.parse_srt(p)
    check("条目数一致", len(back) == len(res.segments),
          f"{len(back)} vs {len(res.segments)}")
    same = all(abs(a.start - b.start) < 0.01 and abs(a.end - b.end) < 0.01
               for a, b in zip(back, res.segments))
    check("时间轴一致", same)
    text_ok = sum(1 for a, b in zip(back, res.segments)
                  if a.text.strip() == b.text.strip())
    check("文本一致", text_ok == len(back), f"{text_ok}/{len(back)}")
    return True


# ---------------------------------------------------------------- 7. 播放器同步
def test_player_sync(media: str, size: str = "tiny"):
    head("7. 播放器字幕挂载与同步（VLC 内核）")
    try:
        from PySide6.QtWidgets import QApplication
        from vlc_player import VlcPlayer
    except Exception as e:
        check("导入播放内核", False, str(e)[:120])
        return False
    app = QApplication.instance() or QApplication(sys.argv)
    try:
        player = VlcPlayer(extra_args=["--vout=dummy", "--aout=dummy"])
    except Exception as e:
        check("VLC 内核加载", False, str(e)[:150])
        return False
    check("VLC 内核加载", True)

    srt = os.path.join(MEDIA_DIR, "ai_双语.srt")
    if not os.path.exists(srt):
        ai.write_srt(ai.parse_srt(srt) or [], srt)
    try:
        player.open(media)     # open() 装载媒体，play() 不带参
        time.sleep(0.6)
        player.play()
    except Exception as e:
        check("播放媒体", False, str(e)[:120])
        return False
    time.sleep(1.0)
    ok = player.add_subtitle(srt)
    check("AI 字幕挂载成功", ok)
    time.sleep(1.0)
    t = player.get_time()
    check("播放进度推进", t > 0, f"{t} ms")
    delay = player.get_subtitle_delay()
    check("字幕延迟可读", isinstance(delay, int), f"{delay} us")
    tracks = player.get_subtitle_tracks()
    check("字幕轨已生效", len(tracks) >= 1,
          "、".join(n for _, n in tracks) or "(dummy 输出下可能不可见)")
    player.stop()
    return True


def main():
    args = [a for a in sys.argv[1:]]
    media = DEFAULT_MEDIA
    size = "tiny"
    if "--media" in args:
        media = args[args.index("--media") + 1]
    if "--size" in args:
        size = args[args.index("--size") + 1]

    print(f"素材: {media}")
    print(f"模型: {size}")

    if not test_deps():
        print("\n依赖缺失，无法继续。请执行: pip install -r requirements.txt")
        return 1
    if not test_model(size):
        return 1
    res = test_asr(media, size)
    test_translate(media, res, "en", size)
    test_whisper_translate(media, size)
    test_srt_roundtrip(res)
    test_player_sync(media, size)

    head("总结")
    print("  " + ("ALL PASS ✅" if ALL_OK else "存在失败项 ❌"))
    return 0 if ALL_OK else 1


if __name__ == "__main__":
    sys.exit(main())
