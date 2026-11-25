"""VLC 万能解码内核封装。

通过 python-vlc 调用 libVLC，支持几乎所有音视频封装与流媒体协议
（mkv / rmvb / avi / wmv / flv / ts / 以及 rtsp / rtmp / http / https / mms / udp）。
本模块只负责“播放引擎”，UI 与控制逻辑在 main_window.py。

注意：真正的播放依赖本机安装的 VLC（libvlc.dll / libvlc.so / libvlc.dylib）。
构造 VlcPlayer 时若找不到 libVLC 会抛 VlcError，由上层捕获并提示用户安装 VLC。
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, Tuple

def _bootstrap_vlc() -> str:
    """定位 VLC 运行库并注入 DLL 搜索路径，返回实际使用的目录（'' 表示用系统 PATH）。

    查找顺序：① 环境变量 VLC_DIR ② 注册表安装项 ③ 常见安装路径
             ④ 程序同目录 / 上级 tools 下的便携版
    Windows 上 Python 3.8+ 不再从 PATH 找 DLL，必须显式 add_dll_directory。
    """
    candidates = []

    env_dir = os.environ.get("VLC_DIR", "").strip().strip('"')
    if env_dir:
        candidates.append(env_dir)

    # 注册表：VLC 安装器写入的安装目录
    try:
        import winreg
        for root, sub in (
            (getattr(winreg, "HKEY_LOCAL_MACHINE", None), r"SOFTWARE\VideoLAN\VLC"),
            (getattr(winreg, "HKEY_LOCAL_MACHINE", None), r"SOFTWARE\WOW6432Node\VideoLAN\VLC"),
            (getattr(winreg, "HKEY_CURRENT_USER", None), r"SOFTWARE\VideoLAN\VLC"),
        ):
            if root is None:
                continue
            try:
                with winreg.OpenKey(root, sub) as k:
                    candidates.append(winreg.QueryValueEx(k, "InstallDir")[0])
            except Exception:
                pass
    except Exception:
        pass

    # 常见安装路径
    for pf in (os.environ.get("ProgramFiles", r"C:\Program Files"),
               os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
               os.environ.get("ProgramW6432", r"C:\Program Files")):
        if pf:
            candidates.append(os.path.join(pf, "VideoLAN", "VLC"))

    # 便携版：程序同目录 / 上级 tools 目录（onefile 按 exe 所在目录算）
    from resources import app_dir
    here = app_dir()
    candidates.append(os.path.join(here, "vlc"))
    candidates.append(os.path.join(here, "vlcportable"))
    base = getattr(sys, "_MEIPASS", here)
    if base != here:
        candidates.append(os.path.join(base, "vlc"))
        candidates.append(os.path.join(base, "vlcportable"))
    for up in (os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
        candidates.append(os.path.join(up, "tools", "vlcportable"))

    for d in candidates:
        if not d:
            continue
        d = os.path.abspath(os.path.expanduser(d))
        # 允许传入 ".../vlcportable/vlc-3.0.24" 或 ".../vlcportable"（下含单个版本目录）
        sub_dirs = [d]
        try:
            sub_dirs += [os.path.join(d, c) for c in sorted(os.listdir(d))]
        except Exception:
            pass
        for sd in sub_dirs:
            if os.path.isfile(os.path.join(sd, "libvlc.dll")) or \
               os.path.isfile(os.path.join(sd, "libvlc.so.5")) or \
               os.path.isfile(os.path.join(sd, "libvlc.dylib")):
                try:
                    if hasattr(os, "add_dll_directory"):  # Python 3.8+ Windows
                        os.add_dll_directory(sd)
                except Exception:
                    pass
                os.environ["PATH"] = sd + os.pathsep + os.environ.get("PATH", "")
                # 显式指定插件目录，避免 libVLC 在 _MEIPASS 解压目录下找不到 plugins/
                plugins_dir = os.path.join(sd, "plugins")
                if os.path.isdir(plugins_dir):
                    os.environ["VLC_PLUGIN_PATH"] = plugins_dir
                return sd
    return ""


VLC_DIR = _bootstrap_vlc()

try:
    import vlc
    _VLC_AVAILABLE = True
except Exception:  # 本机未安装 VLC（libvlc 加载失败）时优雅降级
    vlc = None
    _VLC_AVAILABLE = False

from PySide6.QtCore import QObject, QTimer, Signal

VLC_NOT_FOUND = "未检测到 VLC 运行库(libvlc)。请安装 VLC 播放器(https://www.videolan.org) 后重启本程序。"


class VlcError(Exception):
    pass


# fourcc → 可读编码名（状态栏展示用）
_CODEC_ALIAS = {
    "avc1": "H.264", "h264": "H.264", "x264": "H.264",
    "hev1": "HEVC/H.265", "hvc1": "HEVC/H.265",
    "mp4v": "MPEG-4", "xvid": "Xvid", "divx": "DivX",
    "vp09": "VP9", "vp90": "VP9", "vp80": "VP8", "av01": "AV1",
    "mpgv": "MPEG-1/2", "mp2v": "MPEG-2",
    "aac ": "AAC", "mp4a": "AAC", "mpga": "MPEG audio",
    "mp3 ": "MP3", "a52 ": "AC-3", "eac3": "E-AC-3",
    "opus": "Opus", "flac": "FLAC", "vorb": "Vorbis", "s16l": "PCM",
}


def _codec_name(codec: int) -> str:
    """fourcc 整数转可读编码名；未知则返回 fourcc 四字符，便于后续补充。"""
    if not codec:
        return ""
    # fourcc 在 python-vlc 里按小端读取，必须用 'little' 反转，
    # 用 'big' 会得到倒序字符串（例如 mp4a → a4pm）。
    try:
        raw = int(codec).to_bytes(4, "little").decode("ascii", "ignore")
    except Exception:
        return hex(codec)
    return _CODEC_ALIAS.get(raw.lower(), raw.strip() or hex(codec))


class VlcPlayer(QObject):
    # ---- 信号（全部跨线程安全，VLC 回调里直接 emit） ----
    time_changed = Signal(int)        # 当前时间 ms
    length_changed = Signal(int)      # 总时长 ms
    end_reached = Signal()            # 播放结束 → 上层切下一曲
    media_changed = Signal(str)       # 媒体切换（路径）
    error_occurred = Signal(str)      # 错误描述
    state_changed = Signal(int)       # vlc.State 值
    tracks_updated = Signal()         # 音/字幕轨变化
    ab_loop_triggered = Signal()      # A-B 循环回到 A

    def __init__(self, extra_args: Optional[List[str]] = None):
        super().__init__()
        try:
            args = [
                "--no-video-title-show",
                "--no-sub-autodetect-file",   # 关键：关掉 VLC 同目录字幕自动探测，
                                              # 否则目录里的新旧 srt 会被它全部自动加载，
                                              # 与手动挂载叠成多层且永远"清不掉"
                "--network-caching=1500",
                "--audio-resampler=soxr",
                "--avcodec-hw=any",
                "--drop-late-frames",
            ]
            if extra_args:
                args.extend(list(extra_args))
            self._instance = vlc.Instance(args)
            if self._instance is None:
                raise VlcError(VLC_NOT_FOUND)
            self._player = self._instance.media_player_new()
        except Exception as e:  # 找不到 libvlc 等
            raise VlcError(f"{VLC_NOT_FOUND} ({e})")

        self._current_path = ""
        self._media = None
        self._pending_seek: Optional[int] = None
        self._ab_loop: Tuple[Optional[int], Optional[int]] = (None, None)
        self._subtitle_path = ""      # 当前挂载的外部字幕（用于去重）

        # 事件挂接：不同 VLC / python-vlc 版本支持的事件名有差异，用安全方式挂载，
        # 不支持的事件直接跳过（否则会在构造时抛 AttributeError 直接崩）。
        em = self._player.event_manager()

        def attach(name, cb):
            evt = getattr(vlc.EventType, name, None)
            if evt is not None:
                em.event_attach(evt, cb)

        attach("MediaPlayerEndReached", self._on_end)
        attach("MediaPlayerMediaChanged", self._on_media_changed)
        attach("MediaPlayerEncounteredError", self._on_error)
        attach("MediaPlayerLengthChanged", self._on_length)
        # 轨道（音轨/字幕轨）变化，用于刷新 UI 菜单
        for n in ("MediaPlayerESAdded", "MediaPlayerESDeleted",
                  "MediaPlayerESSelected", "MediaPlayerTrackListChanged"):
            attach(n, lambda e: self.tracks_updated.emit())

        # 媒体加载后补 seek（open 后 length 为 0，需等加载）
        self._seek_timer = QTimer(self)
        self._seek_timer.setInterval(80)
        self._seek_timer.timeout.connect(self._flush_pending_seek)

        # A-B 循环检测
        self._ab_timer = QTimer(self)
        self._ab_timer.setInterval(100)
        self._ab_timer.timeout.connect(self._check_ab)

    # ---------------- 渲染窗口绑定 ----------------
    def set_hwnd(self, hwnd: int):
        if os.name == "nt":
            self._player.set_hwnd(int(hwnd))
        elif os.name == "posix":
            self._player.set_xwindow(int(hwnd))

    # ---------------- 打开 / 播放控制 ----------------
    def open(self, path: str, start_ms: int = 0):
        self._current_path = path
        # 换片：清掉上一部片子挂上去的外部字幕（否则旧字幕会跟着显示）
        self._subtitle_path = ""
        try:
            self._player.video_set_spu(-1)
        except Exception:
            pass
        if path.startswith(("http://", "https://", "rtsp://", "rtmp://",
                            "udp://", "ftp://", "mms://")):
            media = self._instance.media_new_location(path)
        else:
            media = self._instance.media_new_path(os.path.abspath(path))
        media.add_option("network-caching=1500")
        self._media = media
        self._player.set_media(media)
        self._ab_loop = (None, None)
        self._ab_timer.stop()
        if start_ms and start_ms > 0:
            self._pending_seek = start_ms
            self._seek_timer.start()
        self._player.play()

    def play(self):
        self._player.play()

    def pause(self):
        self._player.pause()

    def toggle(self):
        if self.is_playing():
            self.pause()
        else:
            self.play()

    def stop(self):
        try:
            self._player.stop()
        except Exception:
            pass

    def is_playing(self) -> bool:
        try:
            return self._player.get_state() == vlc.State.Playing
        except Exception:
            return False

    def is_paused(self) -> bool:
        try:
            return self._player.get_state() == vlc.State.Paused
        except Exception:
            return False

    # ---------------- 进度 ----------------
    def get_time(self) -> int:
        # 媒体切换 / 播放器已释放的瞬间，libVLC 可能抛 OSError(access violation)。
        # 这里一律兜住返回安全值，避免整个进程崩掉。
        try:
            t = self._player.get_time()
        except Exception:
            return 0
        return t if t > 0 else 0

    def get_length(self) -> int:
        try:
            l = self._player.get_length()
        except Exception:
            return 0
        return l if l > 0 else 0

    def get_position(self) -> float:
        try:
            p = self._player.get_position()
        except Exception:
            return 0.0
        return p if 0 <= p <= 1 else 0.0

    def set_time(self, ms: int):
        self._player.set_time(max(0, int(ms)))

    def set_position(self, pos: float):
        self._player.set_position(max(0.0, min(1.0, float(pos))))

    def seek_relative(self, delta_ms: int):
        self.set_time(self.get_time() + delta_ms)

    def next_frame(self):
        """逐帧步进（. 键）。"""
        try:
            self._player.next_frame()
        except Exception:
            pass

    # ---------------- 音量 ----------------
    def set_volume(self, v: int):
        # 允许 >100 音量增强（libVLC 内部钳制到 125）
        self._player.audio_set_volume(max(0, min(125, int(v))))

    def get_volume(self) -> int:
        return self._player.audio_get_volume()

    def set_mute(self, m: bool):
        self._player.audio_set_mute(bool(m))

    def is_muted(self) -> bool:
        try:
            return bool(self._player.audio_get_mute())
        except Exception:
            return False

    # ---------------- 倍速 ----------------
    def set_rate(self, r: float):
        self._player.set_rate(float(r))

    def get_rate(self) -> float:
        try:
            return self._player.get_rate()
        except Exception:
            return 1.0

    # ---------------- 截图 ----------------
    def snapshot(self, filepath: str) -> bool:
        try:
            return self._player.video_take_snapshot(0, filepath, 0, 0) == 0
        except Exception:
            return False

    # ---------------- 字幕 ----------------
    def add_subtitle(self, path: str, replace: bool = True,
                     activate: bool = True) -> bool:
        """挂载外部字幕（挂上就选中，画面立即显示）。

        libVLC 3.x 每调用一次 video_set_subtitle_file 就会**多出一条字幕轨**，
        重复挂载同一个文件会让画面上叠好几层字幕、切视频后旧字幕也不消失。
        这里做去重：同一文件只挂一次，重复调用直接复用已有轨道。
        """
        try:
            p = os.path.abspath(path)
            if replace and self._subtitle_path == p:
                # 同一个文件：确保它处于启用状态（可能被手动关过字幕）
                if activate:
                    self._activate_last_spu()
                return True          # 已挂载，避免重复叠加
            ok = bool(self._player.video_set_subtitle_file(p))
            if ok:
                self._subtitle_path = p
                if activate:
                    self._activate_last_spu()
            return ok
        except Exception:
            return False

    def _activate_last_spu(self):
        """选中最后一条字幕轨（新挂的字幕追加在末尾），保证画面上看得到。"""
        try:
            tracks = [t for t in self.get_subtitle_tracks() if t[0] >= 0]
            if tracks:
                self._player.video_set_spu(int(tracks[-1][0]))
        except Exception:
            pass

    def get_subtitle_tracks(self) -> List[Tuple[int, str]]:
        try:
            out = []
            for i, name in (self._player.video_get_spu_description() or []):
                out.append((int(i), self._to_str(name)))
            return out
        except Exception:
            return []

    def set_subtitle_track(self, track_id: int):
        try:
            self._player.video_set_spu(int(track_id))
        except Exception:
            pass

    def disable_subtitle(self):
        try:
            self._player.video_set_spu(-1)
        except Exception:
            pass

    # 字幕延迟：对外统一用**毫秒**，libVLC 内部是微秒（×1000）。
    def set_subtitle_delay(self, ms: int):
        try:
            self._player.video_set_spu_delay(int(ms) * 1000)
        except Exception:
            pass

    def get_subtitle_delay(self) -> int:
        try:
            return int(self._player.video_get_spu_delay()) // 1000
        except Exception:
            return 0

    # ---------------- 音轨 ----------------
    def get_audio_tracks(self) -> List[Tuple[int, str]]:
        try:
            out = []
            for i, name in (self._player.audio_get_track_description() or []):
                out.append((int(i), self._to_str(name)))
            return out
        except Exception:
            return []

    def set_audio_track(self, track_id: int):
        try:
            self._player.audio_set_track(int(track_id))
        except Exception:
            pass

    # ---------------- 画面 ----------------
    def set_aspect_ratio(self, ratio: str):
        try:
            self._player.video_set_aspect_ratio(ratio or None)
        except Exception:
            pass

    def set_crop(self, geo: str):
        try:
            self._player.video_set_crop_geometry(geo or None)
        except Exception:
            pass

    def set_scale(self, s: float):
        try:
            self._player.video_set_scale(float(s) if s else 0.0)
        except Exception:
            pass

    def get_video_size(self) -> Tuple[int, int]:
        try:
            w, h = self._player.video_get_size(0)
            return (int(w), int(h))
        except Exception:
            return (0, 0)

    # ---------------- A-B 循环 ----------------
    def set_ab_loop(self, a_ms: Optional[int], b_ms: Optional[int]):
        self._ab_loop = (a_ms, b_ms)
        if a_ms is not None and b_ms is not None and b_ms > a_ms:
            self.set_time(a_ms)
            if not self._ab_timer.isActive():
                self._ab_timer.start()
        else:
            self._ab_timer.stop()

    def clear_ab_loop(self):
        self._ab_loop = (None, None)
        self._ab_timer.stop()

    def get_ab_loop(self) -> Tuple[Optional[int], Optional[int]]:
        return self._ab_loop

    # ---------------- 媒体信息 ----------------
    def media_info(self) -> Dict:
        info = {"width": 0, "height": 0, "fps": 0.0, "vcodec": "",
                "acodec": "", "title": ""}
        try:
            m = self._media
            if not m:
                return info
            # python-vlc 需显式 parse 才有 track 信息；timeout 必须给足，
            # 传 0 会立刻返回、导致 tracks_get() 拿到空列表。
            # 某些容器(如 MPEG-TS)首轮 local 解析拿不到 track，再试 network 标志。
            tracks = []
            try:
                flag = getattr(vlc, "MediaParseFlag", None)
                if flag is not None:
                    local_f = getattr(flag, "local", 0)
                    net_f = getattr(flag, "network", local_f)
                    for f in (local_f, net_f):
                        try:
                            m.parse_with_options(f, 1000)
                        except Exception:
                            pass
                        try:
                            tracks = m.tracks_get() or []
                        except Exception:
                            tracks = []
                        if tracks:
                            break
                else:
                    m.parse()
                    tracks = m.tracks_get() or []
            except Exception:
                try:
                    m.parse()
                    tracks = m.tracks_get() or []
                except Exception:
                    tracks = []
            for t in tracks:
                try:
                    if t.type == vlc.TrackType.video:
                        v = t.video
                        info["width"] = int(v.width)
                        info["height"] = int(v.height)
                        if getattr(v, "frame_rate_den", 0):
                            info["fps"] = round(v.frame_rate_num / v.frame_rate_den, 2)
                        info["vcodec"] = _codec_name(t.codec)
                    elif t.type == vlc.TrackType.audio:
                        info["acodec"] = _codec_name(t.codec)
                except Exception:
                    continue
            # 回退：解析拿不到时用运行时视频尺寸补分辨率
            if not info["width"] or not info["height"]:
                w, h = self.get_video_size()
                if w and h:
                    info["width"], info["height"] = w, h
        except Exception:
            pass
        return info

    # ---------------- 释放 ----------------
    def release(self):
        try:
            self._seek_timer.stop()
            self._ab_timer.stop()
            self._player.stop()
        except Exception:
            pass
        try:
            self._player.release()
        except Exception:
            pass
        try:
            self._instance.release()
        except Exception:
            pass

    # ---------------- 内部回调 ----------------
    @staticmethod
    def _to_str(name) -> str:
        if isinstance(name, bytes):
            try:
                return name.decode("utf-8", "ignore")
            except Exception:
                return str(name)
        return str(name)

    def _flush_pending_seek(self):
        if self._pending_seek is None:
            self._seek_timer.stop()
            return
        if self.get_length() > 0:
            self.set_time(self._pending_seek)
            self._pending_seek = None
            self._seek_timer.stop()

    def _check_ab(self):
        a, b = self._ab_loop
        if a is None or b is None:
            self._ab_timer.stop()
            return
        t = self.get_time()
        if t >= b or t < a:
            self.set_time(a)
            self.ab_loop_triggered.emit()

    def _on_end(self, event):
        self.end_reached.emit()

    def _on_media_changed(self, event):
        if self._current_path:
            self.media_changed.emit(self._current_path)

    def _on_error(self, event):
        self.error_occurred.emit("播放出错：格式不支持或网络/文件不可达")

    def _on_length(self, event):
        self.length_changed.emit(self.get_length())
