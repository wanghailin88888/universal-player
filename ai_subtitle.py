"""本地 AI 字幕引擎：faster-whisper 语音识别 + （可选）翻译。

设计要点
--------
* 纯离线：识别用 CTranslate2 版 Whisper（tiny/base/small/medium），翻译用 Argos
  （opus-mt 的量化版，单个语种 ~20MB）。不需要任何 API key 或外网账号。
* 线程友好：本模块本身不创建线程/UI 对象，由 UI 层放进 QThread 调用，
  识别进度通过 progress_cb 回调回传（0-100 + 描述文字）。
* 模型可自带：模型统一放在 <程序目录>/models 下，便于打包成绿色版分发；
  找不到时从 HuggingFace 下载（国内网络自动走 hf-mirror.com 镜像）。
"""
from __future__ import annotations

import math
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

# ---- 模型目录：优先程序同目录 models/，其次上级目录 models/ ----
# onefile 打包时 __file__ 指向临时解压目录，必须按 exe 所在目录定位
from resources import app_dir
_HERE = app_dir()
MODEL_ROOT = ""
for cand in (os.path.join(_HERE, "models"),
             os.path.join(os.path.dirname(_HERE), "models")):
    if os.path.isdir(cand):
        MODEL_ROOT = cand
        break
if not MODEL_ROOT:
    MODEL_ROOT = os.path.join(_HERE, "models")

# HuggingFace 国内镜像：本机直连 HF 经常超时/401，默认走镜像站
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
# 新版 huggingface_hub 的 xet 加速通道在部分网络下会 401，默认关闭
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
# GUI（console=False）下 tqdm 进度条往 stderr 写会崩（NoneType has no write），
# 且下载进度已由 UI 进度条呈现，直接关掉 HF 自己的进度条
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
# Argos 默认分句会走 stanza（需联网下载 HuggingFace 上的分词模型，
# 国内网络经常 502/失败）。强制用内置的 MiniSBD 分句：完全离线，
# 中英字幕翻译质量无损，只是不再依赖任何外网模型。
# 注意：必须在 import argostranslate 之前设置才会生效。
os.environ.setdefault("ARGOS_CHUNK_TYPE", "MINISBD")
# 兜底：即使被触发也不再联网
os.environ.setdefault("STANZA_OFFLINE", "TRUE")

# Whisper 模型仓库（CTranslate2 量化权重，体积远小于原版 torch 权重）
WHISPER_REPOS = {
    "tiny": "Systran/faster-whisper-tiny",            # ~75MB  最快
    "base": "Systran/faster-whisper-base",            # ~145MB
    "small": "Systran/faster-whisper-small",          # ~480MB  推荐
    "medium": "Systran/faster-whisper-medium",        # ~1.5GB
    "large-v3": "mobiuslabsgmbh/faster-whisper-large-v3",  # ~3GB 需 int8 才有意义
}

# Whisper 常见语言名 → 代码（用于下拉框与自动检测兜底）
WHISPER_LANGS = {
    "自动检测": "", "中文": "zh", "英语": "en", "日语": "ja", "韩语": "ko",
    "粤语": "yue", "法语": "fr", "德语": "de", "西班牙语": "es",
    "俄语": "ru", "葡萄牙语": "pt", "意大利语": "it", "荷兰语": "nl",
    "阿拉伯语": "ar", "印地语": "hi", "泰语": "th", "越南语": "vi",
    "土耳其语": "tr", "波兰语": "pl", "乌克兰语": "uk", "瑞典语": "sv",
    "印尼语": "id", "捷克语": "cs", "芬兰语": "fi", "挪威语": "no",
}


class AsrError(Exception):
    """AI 字幕生成失败。"""


@dataclass
class Segment:
    """一条字幕。"""
    start: float          # 秒
    end: float            # 秒
    text: str = ""        # 原文
    trans: str = ""       # 译文（可选）
    prob: float = 0.0     # 置信度（可选）

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class AsrResult:
    segments: List[Segment] = field(default_factory=list)
    language: str = ""
    language_prob: float = 0.0
    duration: float = 0.0

    def __len__(self) -> int:
        return len(self.segments)


# ---------------------------------------------------------------- SRT 读写
def _fmt_ts(t: float) -> str:
    """秒 → SRT 时间戳 00:00:01,234"""
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms >= 1000:  # 浮点进位
        ms -= 1000
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments: Sequence[Segment], path: str,
              mode: str = "original") -> str:
    """导出 SRT。mode: original=原文 / translated=译文 / bilingual=双语（原文在上）。"""
    lines = []
    n = 0
    for seg in segments:
        if mode == "translated":
            body = (seg.trans or seg.text).strip()
        elif mode == "bilingual":
            top = (seg.trans or "").strip()
            bottom = seg.text.strip()
            body = (top + "\n" + bottom) if top else bottom
        else:
            body = seg.text.strip()
        if not body:
            continue
        n += 1
        lines.append(str(n))
        lines.append(f"{_fmt_ts(seg.start)} --> {_fmt_ts(seg.end)}")
        lines.append(body)
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def parse_srt(path: str) -> List[Segment]:
    """解析 SRT 文件（用于重新加载/编辑已有字幕）。"""
    out: List[Segment] = []
    try:
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            blocks = f.read().replace("\r\n", "\n").split("\n\n")
    except Exception:
        return out
    for blk in blocks:
        rows = [r for r in blk.split("\n") if r.strip()]
        if len(rows) < 2:
            continue
        # 第一行可能是序号，也可能就是时间轴
        idx = 1 if "-->" not in rows[0] else 0
        if idx >= len(rows) or "-->" not in rows[idx]:
            continue
        try:
            a, b = rows[idx].split("-->")
            hms = lambda s: sum(float(x) * f for x, f in zip(
                s.strip().replace(",", ".").split(":"), (3600, 60, 1)))
            start, end = hms(a), hms(b)
        except Exception:
            continue
        text = "\n".join(rows[idx + 1:]).strip()
        out.append(Segment(start, end, text))
    return out


# ---------------------------------------------------------------- Whisper 识别
_MODEL_CACHE: dict = {}


def whisper_model_dir(size: str) -> str:
    return os.path.join(MODEL_ROOT, "whisper-" + size)


def is_model_ready(size: str) -> bool:
    d = whisper_model_dir(size)
    return os.path.isfile(os.path.join(d, "config.json")) and \
           os.path.isfile(os.path.join(d, "model.bin"))


def ensure_whisper_model(size: str,
                         progress_cb: Optional[Callable[[int, str], None]] = None
                         ) -> str:
    """确保模型就位（已存在则直接返回，否则下载到本地 models/）。"""
    d = whisper_model_dir(size)
    if is_model_ready(size):
        return d
    repo = WHISPER_REPOS.get(size)
    if not repo:
        raise AsrError(f"未知模型尺寸: {size}")
    if progress_cb:
        progress_cb(2, f"正在下载 Whisper {size} 模型（首次使用需下载，请耐心）")
    try:
        os.makedirs(d, exist_ok=True)
        from huggingface_hub import snapshot_download
        # 下载中间层（.cache/*.lock）放到系统临时目录：
        # 程序目录保持干净（打包分发不带垃圾），也避免残留锁文件
        cache = os.path.join(tempfile.gettempdir(), "universal_player_hf_cache")
        snapshot_download(repo, local_dir=d, cache_dir=cache)
        # 下载成功后清掉临时缓存（失败则留着，下次续传）
        try:
            import shutil
            shutil.rmtree(cache, ignore_errors=True)
        except Exception:
            pass
    except Exception as e:
        raise AsrError(
            f"Whisper 模型下载失败：{e}\n"
            f"可手动下载 {repo} 的全部文件放到 {d} 后再试。")
    if not is_model_ready(size):
        raise AsrError(f"模型文件不完整：{d}")
    if progress_cb:
        progress_cb(10, "模型就绪")
    return d


def _load_whisper(size: str, device: str = "auto", compute: str = "int8"):
    """加载 WhisperModel（带进程内缓存，避免重复加载耗时）。"""
    if device == "auto":
        device = "cuda" if _cuda_available() else "cpu"
    if device == "cuda" and compute == "int8":
        compute = "float16"  # int8 在 GPU 上反而不一定可用，用 fp16 更稳
    key = (size, device, compute)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    from faster_whisper import WhisperModel
    d = ensure_whisper_model(size)
    # 关键：CPU 识别默认会吃满所有核心，导致同一台机器上正在播放的视频
    # 卡顿、音频断续甚至无声、字幕与画面错位。这里留一半核心给播放，
    # 单 worker 顺序解码，牺牲一点识别速度换取“边播边识别”的流畅度。
    try:
        cpu = os.cpu_count() or 4
    except Exception:
        cpu = 4
    kw = {}
    if device == "cpu":
        import inspect
        names = inspect.signature(WhisperModel.__init__).parameters
        if "cpu_threads" in names:
            kw["cpu_threads"] = max(2, cpu // 2)
        if "num_workers" in names:
            kw["num_workers"] = 1
    model = WhisperModel(d, device=device, compute_type=compute, **kw)
    _MODEL_CACHE[key] = model
    return model


def _cuda_available() -> bool:
    try:
        import ctranslate2 as c2
        return c2.get_cuda_device_count() > 0
    except Exception:
        return False


def detect_language(audio: str, size: str = "tiny", device: str = "auto",
                    ) -> Tuple[str, float]:
    """快速语言检测：只跑 30 秒音频，返回 (语言代码, 置信度)。"""
    model = _load_whisper(size, device)
    segs, info = model.transcribe(
        audio, language=None, beam_size=1, best_of=1, without_timestamps=True)
    for _ in iter(segs.__next__, None):
        break  # 触发一次识别即可拿到 language
    return info.language, getattr(info, "language_probability", 0.0)


def progress_hook(value: float, desc: str,
                  cb: Optional[Callable[[int, str], None]]) -> None:
    """把 faster-whisper 的 0-1 进度映射到 UI 的 0-100。"""
    if cb:
        try:
            cb(max(1, min(99, int(value * 100))), desc)
        except Exception:
            pass


def _to_simplified(text: str) -> str:
    """繁体→简体（zhconv 纯离线转换）。

    Whisper 的中文训练语料繁简混杂，经常整段吐繁体（实测："因為你沒有
    在上面互動"）；中文用户要简体，识别输出统一转一遍。库缺失时原样返回。
    """
    try:
        import zhconv
        return zhconv.convert(text or "", "zh-hans")
    except Exception:
        return text


def transcribe(audio: str,
               size: str = "small",
               language: str = "",
               device: str = "auto",
               translate_to_en: bool = False,
               beam_size: int = 5,
               temperature: Optional[Sequence[float]] = None,
               vad: bool = True,
               min_silence_ms: int = 500,
               cancel_check: Optional[Callable[[], bool]] = None,
               progress_cb: Optional[Callable[[int, str], None]] = None,
               ) -> AsrResult:
    """识别音频生成字幕段落。

    audio          视频/音频文件路径（Whisper 自带 demux，无需先转 wav）
    translate_to_en True=Whisper 内置翻译（只能翻成英文），False=转写原文
    """
    progress_hook(0.01, "加载模型…", progress_cb)
    model = _load_whisper(size, device)

    kw = dict(language=(language or None),
              beam_size=beam_size,
              without_timestamps=False,
              word_timestamps=False,
              vad_filter=vad,
              vad_parameters={"min_silence_duration_ms": min_silence_ms},
              # 关掉"参考上文"：长静音/音乐段容易触发重复幻觉（一直吐同一句）
              condition_on_previous_text=False,
              # 防复读循环：同一 3-gram 只允许出现一次（正常语句不受影响，
              # 但能直接掐断 "2940, 2940, 2940, …" 这类解码死循环）
              no_repeat_ngram_size=3,
              task="translate" if translate_to_en else "transcribe")
    if temperature is not None:
        kw["temperature"] = list(temperature)
    # 不同 faster-whisper 版本参数名略有差异，逐个剔除不支持项
    import inspect
    try:
        sig = inspect.signature(model.transcribe)
        kw = {k: v for k, v in kw.items() if k in sig.parameters}
    except Exception:
        pass

    segments, info = model.transcribe(audio, **kw)

    result = AsrResult(language=getattr(info, "language", "") or "",
                       language_prob=float(getattr(info, "language_probability", 0.0)),
                       duration=float(getattr(info, "duration", 0.0)))
    zh_out = (language or "").lower() in ("zh", "zh-cn", "zh-tw") or \
             result.language == "zh"      # 中文输出统一转简体

    progress_hook(0.05, "开始识别…", progress_cb)
    dur = max(result.duration, 1e-3)
    last_i = 0
    for i, seg in enumerate(segments):
        if cancel_check and cancel_check():
            raise AsrError("已取消")
        txt = (seg.text or "").strip()
        if txt and zh_out:
            txt = _to_simplified(txt)
        result.segments.append(Segment(
            start=float(seg.start), end=float(seg.end),
            text=txt,
            prob=float(getattr(seg, "avg_logprob", 0.0))))
        last_i = i
        if progress_cb and (i % 5 == 0):
            pct = min(0.99, (seg.end or 0) / dur)
            progress_hook(max(0.06, pct),
                          f"已识别 {int((seg.end or 0))}s / {int(dur)}s（{last_i + 1} 条）",
                          progress_cb)
    progress_hook(1.0, f"识别完成，共 {len(result.segments)} 条", progress_cb)
    return result


# ---------------------------------------------------------------- 翻译后端
class Translator:
    """字幕翻译器（Argos 离线优先，Whisper 译英兜底）。"""

    def __init__(self):
        self._installed_cache: Optional[set] = None
        self._packages = None

    # -- Argos 离线翻译 --
    def available_pairs(self) -> List[Tuple[str, str, str]]:
        """返回已安装的语种对 [(from_code, to_code, 包名)]。"""
        try:
            from argostranslate import package
            pairs = []
            for p in package.get_installed_packages():
                pairs.append((p.from_code, p.to_code,
                              f"{p.from_name}→{p.to_name}"))
            return pairs
        except Exception:
            return []

    def is_pair_installed(self, src: str, dst: str) -> bool:
        for a, b, _ in self.available_pairs():
            if a == src and b == dst:
                return True
        return False

    def install_pair(self, src: str, dst: str,
                     progress_cb: Optional[Callable[[int, str], None]] = None
                     ) -> bool:
        """从 Argos 官方仓库下载并安装语种包（~20-80MB/语言对）。"""
        try:
            from argostranslate import package
            if progress_cb:
                progress_cb(5, "获取翻译包索引…")
            package.update_package_index()
            avail = package.get_available_packages()
            hit = [p for p in avail
                   if (p.from_code == src and p.to_code == dst)]
            if not hit:
                raise AsrError(f"Argos 未提供 {src}→{dst} 语言包")
            pkg = hit[0]
            if progress_cb:
                progress_cb(20, f"下载 {src}→{dst} 语言包…")
            path = pkg.download()
            if progress_cb:
                progress_cb(70, "安装语言包…")
            package.install_from_path(path)
            self._installed_cache = None
            if progress_cb:
                progress_cb(95, "语言包安装完成")
            return True
        except AsrError:
            raise
        except Exception as e:
            raise AsrError(f"翻译包安装失败：{e}")

    def translate_text(self, text: str, src: str, dst: str) -> str:
        """单段文本翻译（离线）。找不到语种包抛 AsrError。"""
        if not text.strip() or src == dst:
            return text
        try:
            from argostranslate import translate
            return translate.translate(text, src, dst) or text
        except Exception as e:
            raise AsrError(f"翻译失败（{src}→{dst}）：{e}；"
                           f"请先在『AI 字幕』里安装该语种包。")

    def translate_segments(self, segments: Sequence[Segment],
                           src: str, dst: str,
                           progress_cb: Optional[Callable[[int, str], None]] = None
                           ) -> None:
        """原地填充 Segment.trans（批量翻译，带进度）。"""
        total = len(segments)
        for i, seg in enumerate(segments):
            try:
                seg.trans = self.translate_text(seg.text, src, dst)
            except AsrError:
                raise
            except Exception:
                seg.trans = ""
            if progress_cb and total:
                progress_cb(int((i + 1) / total * 100),
                            f"翻译字幕 {i + 1}/{total}")


def merge_segments(*chunks: Sequence[Segment]) -> List[Segment]:
    """按时间轴合并多段字幕：排序 + 去掉重叠尾巴（分段时间窗重叠区只留一份）。"""
    flat: List[Segment] = []
    for c in chunks:
        flat.extend(c or [])
    flat.sort(key=lambda x: (x.start, x.end))
    out: List[Segment] = []
    for sg in flat:
        if out and sg.start < out[-1].end - 0.05:
            if sg.end <= out[-1].end:
                continue                        # 完全被前一条盖住 → 丢弃
            sg = Segment(start=out[-1].end, end=sg.end, text=sg.text,
                         trans=sg.trans, prob=sg.prob)
        out.append(sg)
    return out


# ---------------------------------------------------------------- 幻觉抑制
def _norm_text(t: str) -> str:
    """比较用的宽松归一化：去空白/中英标点，只留字母数字和 CJK。"""
    return "".join(c for c in (t or "").lower()
                   if c.isalnum() or "\u4e00" <= c <= "\u9fff")


def suppress_hallucination(segments: Sequence[Segment],
                           expected_lang: str = "") -> List[Segment]:
    """压掉 Whisper 的复读幻觉。

    典型症状（实机截图）：
      A) 画面被几十条 "2940, 2940, 2940,…" 刷屏——解码器在无语音/噪声段
         陷入循环，短文本被无限复读成大量重叠字幕；
      B) 整句短语周期性复读："product of the product of the product…"——
         重复的不是单个词而是 2~4 个词的短语，逐词连续性检测抓不到；
      C) 中文片吐整句英文（解码器在音乐/噪声上跑飞）。
    处理五招，都只动"确凿幻觉"，不碰正常内容：
      1) 单条内部：同一短单元**连续**重复就截断到 2 次；
      2) 单条内部：2~4 词短语在句内出现 ≥3 次 → 从第 3 次出现处截断；
      3) 相邻条目：归一化后完全相同的连续复读只留一条；
      4) 已知幻觉句（Thank you for watching / Subscribe / Amara…）整条丢弃；
      5) 语言不匹配（源语言是中日韩，却整句拉丁字母）或低置信+高度重复 → 丢弃。
    """
    import re
    from collections import Counter

    _tok = re.compile(r"[^,，。.、;；\s]+[,，。.、;；\s]*")

    # Whisper 高频幻觉句（归一化后整句匹配才丢，正常内容里不会整句只有这个）
    _BLACKLIST = {
        "thankyou", "thankyouforwatching", "thankyouforwatchingmyvideo",
        "pleasesubscribe", "pleasesubscribetomychannel",
        "subscribetomychannel", "amaraorg", "amaraorgcommunity",
        "subtitlesbytheamaradeorgcommunity", "subtitlesbycommunity",
        "翻译", "字幕由amaraorg社区提供", "请订阅我的频道",
    }

    def _script_mismatch(text: str) -> bool:
        """源语言是中日韩，识别结果却全是拉丁字母 → 基本可断定幻觉。"""
        if expected_lang not in ("zh", "ja", "ko"):
            return False
        cjk = sum(1 for c in text
                  if "\u4e00" <= c <= "\u9fff" or "\u3040" <= c <= "\u30ff"
                  or "\uac00" <= c <= "\ud7af")
        if cjk > 0:
            return False
        ascii_letters = sum(1 for c in text if c.isascii() and c.isalpha())
        return ascii_letters >= 6

    def trim_inner(text: str) -> str:
        toks = _tok.findall(text or "")
        if len(toks) < 3:
            return text
        out: List[str] = []
        prev_n, run_n = "", 0
        for tk in toks:
            nt = _norm_text(tk)
            if nt and nt == prev_n:
                run_n += 1
                if run_n < 2:          # 保留前 2 次重复，后面的全部吞掉
                    out.append(tk)
            else:
                prev_n, run_n = nt, 0
                out.append(tk)
        s = "".join(out).strip()
        return s if s else ""

    def collapse_periodic(text: str) -> str:
        """短语的周期性复读："product of the | product of the | product of the …"
        找 2~4 词短语在句内出现 ≥3 次，从第 3 次出现处截断（保留前 2 次）。"""
        toks = _tok.findall(text or "")
        n = len(toks)
        if n < 12:
            return text
        nts = [_norm_text(t) for t in toks]
        for L in (2, 3, 4):
            if n < L * 3 + 4:          # 太短的句子不上这条规则，防误伤
                continue
            cnt = Counter(tuple(nts[i:i + L]) for i in range(n - L + 1))
            for i in range(n - L + 1):
                sh = tuple(nts[i:i + L])
                if not all(sh) or cnt[sh] < 3:
                    continue
                occ, cut = 0, -1
                j = i
                while j + L <= n:
                    if tuple(nts[j:j + L]) == sh:
                        occ += 1
                        if occ == 3:
                            cut = j
                            break
                    j += 1
                if cut > 0:
                    s = "".join(toks[:cut]).strip()
                    return s if _norm_text(s) else ""
            break                        # 只按 2-gram 查一遍就够，减少误伤
        return text

    res: List[Segment] = []
    last_nt, last_end = "", -1e18
    for sg in segments:
        t = trim_inner(sg.text)
        t = collapse_periodic(t)
        nt = _norm_text(t)
        if not nt:
            continue
        if nt in _BLACKLIST:
            continue                              # 已知幻觉句
        if _script_mismatch(t):
            continue                              # 中文片吐英文
        if nt == last_nt and sg.start < last_end + 3.0:
            last_end = max(last_end, sg.end)     # 连续复读同一句 → 丢弃
            continue
        if sg.prob and sg.prob < -1.2 and len(nt) >= 3:
            units = [u for u in re.split(r"[,，。.、;；\s]+", nt) if u]
            if units and len(set(units)) <= max(1, len(units) // 3):
                continue                          # 低置信 + 高度重复 → 幻觉
        sg.text = t
        res.append(sg)
        last_nt, last_end = nt, sg.end
    return res


def generate_subtitles(media: str,
                       size: str = "small",
                       src_lang: str = "",
                       dst_lang: str = "",
                       bilingual: bool = True,
                       device: str = "auto",
                       out_srt: str = "",
                       cancel_check: Optional[Callable[[], bool]] = None,
                       progress_cb: Optional[Callable[[int, str], None]] = None,
                       workers: int = 0,
                       beam_size: int = 5,
                       temp_fallback: bool = False,
                       front_seconds: float = 300.0,
                       chunk_seconds: float = 60.0,
                       on_partial: Optional[Callable[[Sequence[Segment], str], None]] = None,
                       ) -> Tuple[AsrResult, str]:
    """一站式：识别 → 翻译 → 写 SRT。

    参数：
      workers        并行段数：0=自动（按核数），1=单路，>1=分段并行
      temp_fallback  True=难句升温重试（慢很多）；False=快速（推荐）
      chunk_seconds  逐段实时模式：按 N 秒一段**顺序**识别，每段完成就回调
                     on_partial(累计 segments, 实时 srt 路径) 让字幕立刻出现，
                     再继续下一段——保证「字幕实时存在」。0=关闭。
      front_seconds  兼容参数：整段并行模式下先出前 N 秒（chunk_seconds>0 时忽略）
      on_partial     中途回调（用于立即挂载/刷新字幕）
    """
    use_whisper_translate = (dst_lang == "en")
    # 默认关闭"温度回退"：faster-whisper 遇低置信度会把 temperature 从 0 逐档升到 1
    # 反复重解码，长片实测慢 5 倍以上；清晰语音关掉它准确度几乎不变。
    _temps = None if temp_fallback else [0.0]
    n_workers = int(workers or 0)
    if n_workers == 0:
        try:
            from ai_parallel import auto_workers
            n_workers = auto_workers()
        except Exception:
            n_workers = 1

    def _mode(src: str) -> str:
        if not dst_lang or dst_lang == src:
            return "original"
        if use_whisper_translate:
            return "translated"
        return "bilingual" if bilingual else "translated"

    def _tag_for_mode() -> str:
        # 提前算文件名（渐进式第一次落盘就要用）
        if not dst_lang or (src_lang and dst_lang == src_lang):
            return ""
        if use_whisper_translate:
            return ".译文"
        return ".双语" if bilingual else ".译文"

    if not out_srt:
        base = os.path.splitext(os.path.basename(media))[0]
        out_srt = os.path.join(os.path.dirname(os.path.abspath(media)),
                               f"{base}{_tag_for_mode()}.srt")

    def _translate(segs: Sequence[Segment], src: str, pcb=None):
        rep = pcb or progress_cb
        if not dst_lang or dst_lang == src or not segs:
            return
        if use_whisper_translate:
            for sg in segs:
                sg.trans = sg.text      # Whisper task=translate 输出即译文
            return
        if rep:
            rep(5, "准备翻译…")
        tr = Translator()
        if not tr.is_pair_installed(src, dst_lang):
            tr.install_pair(src, dst_lang, rep)

        def _cb(p, msg):
            if rep:
                rep(p, msg)

        tr.translate_segments(segs, src, dst_lang, _cb)

    def _asr_window(off: float, lim: float, pcb,
                    workers_override: int = 0) -> AsrResult:
        """识别 [off, off+lim) 时间窗（并行可用时走并行）。"""
        if n_workers > 1:
            from ai_parallel import transcribe_parallel
            return transcribe_parallel(
                media, size=size, language=src_lang, device=device,
                translate_to_en=use_whisper_translate,
                workers=(workers_override or n_workers),
                beam_size=beam_size, temp_fallback=temp_fallback,
                cancel_check=cancel_check, progress_cb=pcb,
                duration=_total_dur(), offset=off, limit=lim,
                allow_short=bool(lim))
        return transcribe(media, size=size, language=src_lang, device=device,
                          translate_to_en=use_whisper_translate,
                          beam_size=beam_size, temperature=_temps,
                          cancel_check=cancel_check, progress_cb=pcb)

    _dur_cache: List[float] = []

    def _total_dur() -> float:
        if not _dur_cache:
            try:
                from ai_parallel import media_duration
                _dur_cache.append(float(media_duration(media)))
            except Exception:
                _dur_cache.append(0.0)
        return _dur_cache[0]

    total_dur = _total_dur()

    def _asr_single_window(off: float, lim: float, pcb, full_wav: str = "") -> AsrResult:
        """单路识别一个时间窗：优先从整条 wav 切片（无 ffmpeg seek），否则现抽。"""
        from ai_parallel import extract_wav, slice_wav
        tmpd = tempfile.mkdtemp(prefix="up_aw_")
        wav = os.path.join(tmpd, "w.wav")
        ok = False
        if full_wav and os.path.exists(full_wav):
            ok = slice_wav(full_wav, off, lim, wav)
        if not ok:
            ok = extract_wav(media, off, lim, wav)
        try:
            if not ok:
                raise AsrError("音频抽取失败")
            r = transcribe(wav, size=size, language=src_lang, device=device,
                           translate_to_en=use_whisper_translate,
                           beam_size=beam_size, temperature=_temps,
                           cancel_check=cancel_check, progress_cb=pcb)
            for sg in r.segments:       # 窗口内时间 → 全片绝对时间
                sg.start += off
                sg.end += off
            return r
        finally:
            shutil.rmtree(tmpd, ignore_errors=True)

    # ---------------- 逐段实时：每 chunk_seconds 一段，边识别边出字幕 ----------------
    use_chunk = bool(chunk_seconds and chunk_seconds > 0
                     and total_dur > chunk_seconds * 2.2)
    if use_chunk:
        n_chunks = max(1, int(math.ceil(total_dur / chunk_seconds)))
        tmpd = tempfile.mkdtemp(prefix="up_live_")
        live_srt = os.path.join(tmpd, "live.srt")
        full_wav = os.path.join(tmpd, "full.wav")
        acc: List[Segment] = []
        src_detected = src_lang or ""
        try:
            # 整条音轨只抽一次：逐段切样本即可，省掉上百次 ffmpeg seek
            try:
                from ai_parallel import extract_wav_full
                if not extract_wav_full(media, full_wav, progress_cb):
                    full_wav = ""
            except Exception:
                full_wav = ""
            # 开局先挂一份空实时字幕：把画面上可能残留的旧脏字幕（上次任务
            # 中断落盘的、或自动加载的错误 SRT）从显示中顶掉——VLC 不能移除
            # 字幕轨，但可以让"选中的轨"切到这份空内容上。
            try:
                write_srt([], live_srt, _mode(src_lang or ""))
                if on_partial:
                    on_partial([], live_srt)
            except Exception:
                pass
            for i in range(n_chunks):
                if cancel_check and cancel_check():
                    raise AsrError("已取消")
                off = i * chunk_seconds
                lim = min(chunk_seconds, max(0.0, total_dur - off))
                if lim <= 0.2:
                    continue
                base = 3 + (i / n_chunks) * 94.0

                def pcb(p, msg, _b=base, _n=n_chunks, _i=i):
                    if progress_cb:
                        progress_cb(int(_b + (p / 100.0) * (94.0 / _n)),
                                    f"第 {_i + 1}/{_n} 段 · {msg}")
                try:
                    r = _asr_single_window(off, lim, pcb, full_wav)
                    r.segments = suppress_hallucination(
                        r.segments, expected_lang=(src_detected or src_lang or ""))
                except AsrError:
                    raise
                except Exception as e:      # 单段失败不拖垮整片
                    if progress_cb:
                        progress_cb(int(base), f"第 {i + 1} 段失败（{e}），跳过")
                    continue
                if not src_detected:
                    src_detected = r.language or ""
                _translate(r.segments, src_detected, pcb)
                acc = merge_segments(acc, r.segments)
                write_srt(acc, live_srt, _mode(src_detected))
                if progress_cb:
                    cover = acc[-1].end if acc else 0.0
                    progress_cb(int(base + (94.0 / n_chunks)),
                                f"第 {i + 1}/{n_chunks} 段完成，字幕已更新到 "
                                f"{int(cover // 60):02d}:{int(cover % 60):02d}")
                if on_partial:
                    try:
                        on_partial(list(acc), live_srt)
                    except Exception:
                        pass
        finally:
            # 取消/异常也把已识别的部分落盘，别让用户白等
            if acc:
                try:
                    write_srt(acc, out_srt, _mode(src_detected))
                except Exception:
                    pass
            shutil.rmtree(tmpd, ignore_errors=True)
        write_srt(acc, out_srt, _mode(src_detected))
        res = AsrResult(language=src_detected, language_prob=0.0,
                        duration=total_dur)
        res.segments = acc
        if progress_cb:
            progress_cb(100, f"识别完成，共 {len(acc)} 条")
        return res, out_srt

    use_front = (front_seconds and front_seconds > 30 and n_workers > 1
                 and total_dur > front_seconds * 1.6)

    # ---------------- 渐进式：前 N 秒优先 ----------------
    if use_front:
        first = None
        try:
            def pcb1(p, msg):
                if progress_cb:
                    progress_cb(4 + int(p * 0.22), "前置片段 " + str(msg))
            first = _asr_window(0.0, front_seconds, pcb1,
                                workers_override=min(2, n_workers))
        except Exception as e:
            if "已取消" in str(e):
                raise
            if progress_cb:
                progress_cb(3, f"前置片段失败（{e}），改为整片识别…")
            first = None

        if first is not None and first.segments:
            src_detected = first.language or src_lang or ""
            _translate(first.segments, src_detected)
            first.segments.sort(key=lambda x: (x.start, x.end))
            write_srt(first.segments, out_srt, _mode(src_detected))
            if on_partial:
                try:
                    on_partial(first.segments, out_srt)
                except Exception:
                    pass
            if progress_cb:
                progress_cb(28, f"前 {int(front_seconds)}s 字幕已生成，继续识别后面的…")

            def pcb2(p, msg):
                if progress_cb:
                    progress_cb(28 + int(p * 0.66), "后续部分 " + str(msg))
            rest = _asr_window(front_seconds,
                               max(0.0, total_dur - front_seconds), pcb2)
            rest_segs = list(rest.segments)
            _translate(rest_segs, src_detected)
            all_segs = list(first.segments) + rest_segs
            all_segs.sort(key=lambda x: (x.start, x.end))
            merged: List[Segment] = []
            for sg in all_segs:
                if merged and sg.start < merged[-1].end - 0.05:
                    if sg.end <= merged[-1].end:
                        continue
                    sg = Segment(start=merged[-1].end, end=sg.end,
                                 text=sg.text, prob=sg.prob,
                                 trans=getattr(sg, "trans", ""))
                merged.append(sg)
            res = AsrResult(language=src_detected,
                            language_prob=first.language_prob,
                            duration=total_dur)
            res.segments = merged
            write_srt(merged, out_srt, _mode(src_detected))
            if progress_cb:
                progress_cb(100, f"识别完成，共 {len(merged)} 条")
            return res, out_srt

    # ---------------- 常规：整片一次识别 ----------------
    if n_workers > 1:
        try:
            from ai_parallel import transcribe_parallel
            res = transcribe_parallel(
                media, size=size, language=src_lang, device=device,
                translate_to_en=use_whisper_translate, workers=n_workers,
                beam_size=beam_size, temp_fallback=temp_fallback,
                cancel_check=cancel_check, progress_cb=progress_cb)
        except AsrError as e:
            if "已取消" in str(e):
                raise
            if progress_cb and "短片不分段" not in str(e):
                progress_cb(3, f"分段识别失败（{e}），改用单路…")
            res = transcribe(media, size=size, language=src_lang, device=device,
                             translate_to_en=use_whisper_translate,
                             beam_size=beam_size, temperature=_temps,
                             cancel_check=cancel_check, progress_cb=progress_cb)
        except Exception as e:
            # 分段出问题就退回单路，别让用户白等
            if progress_cb:
                progress_cb(3, f"分段识别不可用（{e}），改用单路…")
            res = transcribe(media, size=size, language=src_lang, device=device,
                             translate_to_en=use_whisper_translate,
                             beam_size=beam_size, temperature=_temps,
                             cancel_check=cancel_check, progress_cb=progress_cb)
    else:
        res = transcribe(media, size=size, language=src_lang, device=device,
                         translate_to_en=use_whisper_translate,
                         beam_size=beam_size, temperature=_temps,
                         cancel_check=cancel_check, progress_cb=progress_cb)

    src = res.language or (src_lang or "")
    _translate(res.segments, src)
    mode = _mode(src)
    write_srt(res.segments, out_srt, mode)
    return res, out_srt
