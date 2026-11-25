"""长视频 AI 字幕：分段并行识别。

把音频按时间切成 N 段，每段一个 Whisper 实例并行识别（CTranslate2 在 C++ 层
推理会释放 GIL，所以多线程能真正跑满多核），最后把各段时间戳补偿后合并成一份 SRT。

相比单路识别，1.5 小时的长片在 8 核机器上通常能快 3~4 倍。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional, Sequence, Tuple

from ai_subtitle import (
    AsrError, AsrResult, Segment, _load_whisper, _cuda_available,
    _MODEL_CACHE, _HERE,
)


# ---------------------------------------------------------------- 工具
def ffmpeg_exe() -> str:
    """找 ffmpeg：imageio-ffmpeg 自带优先，其次 PATH。"""
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    p = shutil.which("ffmpeg")
    if p:
        return p
    raise AsrError("找不到 ffmpeg（分段识别需要），请安装 imageio-ffmpeg 或 ffmpeg")


def media_duration(path: str) -> float:
    """取媒体时长（秒）：优先 av，失败则用 ffmpeg 解析。"""
    try:
        import av
        try:
            c = av.open(path, metadata_errors="ignore")
        except TypeError:
            c = av.open(path)
        d = (c.duration or 0) / 1_000_000
        if d > 0:
            c.close()
            return float(d)
        # 容器没写 duration：取最长音频流
        best = 0.0
        for s in c.streams:
            if s.duration and s.time_base:
                best = max(best, float(s.duration * s.time_base))
        c.close()
        if best > 0:
            return best
    except Exception:
        pass
    try:
        out = subprocess.run(
            [ffmpeg_exe(), "-hide_banner", "-i", path],
            capture_output=True, text=True, encoding="utf-8", errors="ignore")
        for line in (out.stderr or "").splitlines():
            line = line.strip()
            if line.startswith("Duration:"):
                hms = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = hms.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        pass
    raise AsrError("无法获取媒体时长，不能分段识别")


def plan_segments(duration: float, workers: int,
                  overlap: float = 1.0) -> List[Tuple[float, float, float]]:
    """按等长切段，返回 [(解码起点, 解码时长, 有效起点), ...]。

    每段往前多取 overlap 秒，避免把词切断；识别后落在有效起点之前的内容丢弃。
    """
    workers = max(1, int(workers))
    seg = duration / workers
    plan = []
    for i in range(workers):
        vstart = i * seg
        vend = duration if i == workers - 1 else (i + 1) * seg
        dstart = max(0.0, vstart - (overlap if i > 0 else 0.0))
        plan.append((dstart, vend - dstart, vstart))
    return plan


def extract_wav(media: str, start: float, length: float, out_wav: str) -> bool:
    """用 ffmpeg 抽一段 16k 单声道 wav。"""
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    if start > 0.01:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-t", f"{length:.3f}", "-i", media, "-vn",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out_wav]
    try:
        r = subprocess.run(cmd, capture_output=True)
        return r.returncode == 0 and os.path.exists(out_wav) and os.path.getsize(out_wav) > 1024
    except Exception:
        return False


def extract_wav_full(media: str, out_wav: str,
                     progress_cb: Optional[Callable[[int, str], None]] = None) -> bool:
    """整条音轨只抽一次成 16k 单声道 wav。

    逐段模式如果每段都让 ffmpeg 重新 seek，长片会白花上百次定位/解码开销；
    一次抽完再按样本切片，段数越多收益越大（101 段的长片约省 1~3 分钟）。
    """
    if progress_cb:
        progress_cb(1, "抽取整条音轨…")
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-i", media, "-vn", "-ac", "1", "-ar", "16000",
           "-c:a", "pcm_s16le", out_wav]
    try:
        r = subprocess.run(cmd, capture_output=True)
        return (r.returncode == 0 and os.path.exists(out_wav)
                and os.path.getsize(out_wav) > 4096)
    except Exception:
        return False


def slice_wav(src_wav: str, start: float, length: float, out_wav: str) -> bool:
    """从整条 wav 里按时间切片（纯文件读取，无 ffmpeg seek）。"""
    import wave
    try:
        with wave.open(src_wav, "rb") as r:
            nch, sw, fr = r.getnchannels(), r.getsampwidth(), r.getframerate()
            n_frames = r.getnframes()
            first = max(0, min(n_frames - 1, int(start * fr)))
            want = max(1, int(length * fr))
            r.setpos(first)
            data = r.readframes(want)
        if not data:
            return False
        with wave.open(out_wav, "wb") as w:
            w.setnchannels(nch)
            w.setsampwidth(sw)
            w.setframerate(fr)
            w.writeframes(data)
        return os.path.getsize(out_wav) > nch * sw * fr * 0.2   # 至少 0.2 秒
    except Exception:
        return False


# ---------------------------------------------------------------- 并行识别
_model_lock = threading.Lock()
_thread_models: dict = {}


def _thread_model(size: str, device: str, cpu_threads: int):
    """每线程一个模型实例（多实例才能真正并行；同实例并发会互相拖慢）。"""
    key = (size, device, cpu_threads, threading.get_ident())
    with _model_lock:
        m = _thread_models.get(key)
    if m is not None:
        return m
    from faster_whisper import WhisperModel
    import inspect

    d = _MODEL_CACHE.get((size, device, "int8")) or None
    if d is None:
        # 复用单路加载时的目录解析逻辑
        from ai_subtitle import whisper_model_dir, is_model_ready
        d = whisper_model_dir(size)
        if not is_model_ready(size):
            raise AsrError(f"模型 {size} 未下载，请先在「管理 AI 模型」里下载")
    kw = {}
    try:
        names = inspect.signature(WhisperModel.__init__).parameters
        if "cpu_threads" in names:
            kw["cpu_threads"] = max(1, int(cpu_threads))
        if "num_workers" in names:
            kw["num_workers"] = 1
    except Exception:
        pass
    if device in ("auto", ""):
        device = "cuda" if _cuda_available() else "cpu"
    m = WhisperModel(d, device=device, compute_type="int8", **kw)
    with _model_lock:
        _thread_models[key] = m
    return m


def _transcribe_piece(wav: str, size: str, language: str, device: str,
                      translate_to_en: bool, cpu_threads: int,
                      vad: bool, min_silence_ms: int,
                      beam_size: int = 5,
                      temperature: Optional[Sequence[float]] = None) -> List[Segment]:
    """识别单个音频片段（时间戳从片段头开始）。"""
    model = _thread_model(size, device, cpu_threads)
    if temperature is not None:
        kw_t = list(temperature)
    else:
        kw_t = None
    kw = dict(language=(language or None),
              beam_size=max(1, int(beam_size)),
              without_timestamps=False,
              word_timestamps=False,
              vad_filter=vad,
              vad_parameters={"min_silence_duration_ms": min_silence_ms},
              condition_on_previous_text=False,   # 防重复幻觉
              no_repeat_ngram_size=3,             # 防复读循环（同 ai_subtitle.transcribe）
              task="translate" if translate_to_en else "transcribe")
    if kw_t is not None:
        kw["temperature"] = kw_t
    import inspect
    try:
        sig = inspect.signature(model.transcribe)
        kw = {k: v for k, v in kw.items() if k in sig.parameters}
    except Exception:
        pass
    segments, _info = model.transcribe(wav, **kw)
    from ai_subtitle import _to_simplified
    zh_out = (language or "").lower() in ("zh", "zh-cn", "zh-tw") or \
             (getattr(_info, "language", "") or "") == "zh"
    out: List[Segment] = []
    for seg in segments:
        txt = (seg.text or "").strip()
        if txt and zh_out:
            txt = _to_simplified(txt)       # 中文输出统一转简体
        if txt:
            out.append(Segment(start=float(seg.start), end=float(seg.end),
                               text=txt,
                               prob=float(getattr(seg, "avg_logprob", 0.0))))
    return out


def transcribe_parallel(media: str,
                        size: str = "small",
                        language: str = "",
                        device: str = "auto",
                        translate_to_en: bool = False,
                        workers: int = 4,
                        beam_size: int = 5,
                        temp_fallback: bool = False,
                        vad: bool = True,
                        min_silence_ms: int = 500,
                        cancel_check: Optional[Callable[[], bool]] = None,
                        progress_cb: Optional[Callable[[int, str], None]] = None,
                        duration: Optional[float] = None,
                        offset: float = 0.0,
                        limit: float = 0.0,
                        allow_short: bool = False,
                        ) -> AsrResult:
    """分段并行识别 → 合并成一个 AsrResult（时间戳已对齐整片）。

    offset/limit 可把识别限制在 [offset, offset+limit) 这个时间窗内，
    用于"先出前 N 分钟字幕，再补其余部分"的渐进式生成。
    """
    total = float(duration or media_duration(media))
    if total <= 0:
        raise AsrError("媒体时长为 0，无法分段")
    off = max(0.0, float(offset or 0.0))
    span = float(limit or 0.0) or max(0.0, total - off)
    span = max(0.0, min(span, total - off))
    if span <= 0.5:
        raise AsrError("识别区间为空")
    dur = span

    try:
        cores = os.cpu_count() or 4
    except Exception:
        cores = 4
    if dur < MIN_PARALLEL_SECONDS and workers > 1 and not allow_short:
        # 短片切段反而丢内容，直接单路（调用方看到 n=1 会走原逻辑）
        raise AsrError("短片不分段")
    plan = plan_segments(dur, workers)
    n = len(plan)
    per_threads = max(1, cores // max(1, n))

    if progress_cb:
        try:
            lo, hi = int(off), int(off + dur)
            rng = f"{lo}s~{hi}s" if off > 0 else f"共 {int(total)}s"
            progress_cb(1, f"分段并行：{n} 段 × {per_threads} 线程（{rng}）")
        except Exception:
            pass

    tmpdir = tempfile.mkdtemp(prefix="ai_sub_")
    stop = threading.Event()
    result = AsrResult(language=language or "", language_prob=0.0, duration=total)
    finished = [0]
    lock = threading.Lock()

    def work(idx: int):
        dstart, dlen, vstart = plan[idx]
        dstart += off          # 窗口平移：实际解码起点
        vstart += off          # 有效起点（整片时间轴）
        wav = os.path.join(tmpdir, f"part{idx:03d}.wav")
        if stop.is_set():
            return idx, []
        if not extract_wav(media, dstart, dlen, wav):
            raise AsrError(f"第 {idx + 1}/{n} 段音频抽取失败")
        if stop.is_set():
            return idx, []
        segs = _transcribe_piece(wav, size, language, device, translate_to_en,
                                 per_threads, vad, min_silence_ms, beam_size,
                                 None if temp_fallback else [0.0])
        try:
            os.remove(wav)
        except OSError:
            pass
        # 丢弃落在重叠区（上一段已经覆盖）的内容，并按整片时间补偿
        out = []
        for s in segs:
            if s.end <= vstart + 0.01:
                continue
            st = s.start + dstart
            en = s.end + dstart
            if st < vstart:
                st = vstart
            if en > st:
                out.append(Segment(start=st, end=en, text=s.text, prob=s.prob))
        return idx, out

    errors: List[str] = []
    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = {ex.submit(work, i): i for i in range(n)}
        for fut in as_completed(futures):
            idx = futures[fut]
            if cancel_check and cancel_check():
                stop.set()
            try:
                _i, segs = fut.result()
            except AsrError as e:
                errors.append(str(e))
                stop.set()
                continue
            except Exception as e:
                errors.append(f"第 {idx + 1}/{n} 段失败：{e}")
                stop.set()
                continue
            with lock:
                result.segments.extend(segs)
                finished[0] += 1
                done = finished[0]
            if progress_cb:
                try:
                    progress_cb(max(2, min(99, int(done / n * 100))),
                                f"分段完成 {done}/{n}")
                except Exception:
                    pass
            if cancel_check and cancel_check():
                stop.set()

    shutil.rmtree(tmpdir, ignore_errors=True)

    if errors:
        raise AsrError("；".join(errors[:2]))
    if cancel_check and cancel_check():
        raise AsrError("已取消")

    # 合并：按时间排序，去掉与前一段区间重叠的尾巴
    result.segments.sort(key=lambda s: (s.start, s.end))
    merged: List[Segment] = []
    for s in result.segments:
        if merged and s.start < merged[-1].end - 0.05:
            if s.end <= merged[-1].end:
                continue                       # 完全被覆盖
            s = Segment(start=merged[-1].end, end=s.end, text=s.text, prob=s.prob)
        if s.end - s.start < 0.05:
            continue
        merged.append(s)
    result.segments = merged

    if progress_cb:
        try:
            progress_cb(100, f"识别完成，共 {len(merged)} 条")
        except Exception:
            pass
    return result


def auto_workers(cores: Optional[int] = None) -> int:
    """默认并行段数：一半核用于识别（每段 2 线程），最多 4 段。

    多实例比单实例多线程更划算，所以宁可多切两段。
    """
    c = cores or (os.cpu_count() or 4)
    return max(1, min(4, c // 2))


# 太短的音频无需分段（切碎反而丢边界内容），也不值得开多实例
MIN_PARALLEL_SECONDS = 120.0
