"""全局配置与播放历史（JSON 持久化）。

配置与续播记忆都落盘到用户配置目录，exe 分发后也能保留用户习惯。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QStandardPaths


def _config_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".universal_player")
    p = Path(base) / "UniversalPlayer"
    p.mkdir(parents=True, exist_ok=True)
    return p


CONFIG_FILE = _config_dir() / "settings.json"
HISTORY_FILE = _config_dir() / "history.json"

# 支持的本地视频/音频扩展名（用于“打开文件夹”自动收集）
VIDEO_EXTS = {
    ".mp4", ".m4v", ".mov", ".mkv", ".avi", ".wmv", ".flv", ".mpg", ".mpeg",
    ".m2ts", ".ts", ".webm", ".ogg", ".ogv", ".rm", ".rmvb", ".vob", ".3gp",
    ".mts", ".divx", ".asf", ".f4v", ".swf",
}
AUDIO_EXTS = {
    ".mp3", ".wav", ".flac", ".aac", ".m4a", ".ape", ".opus", ".wma", ".ac3",
    ".dts", ".tta", ".cue",
}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS
SUB_EXTS = {".srt", ".ass", ".ssa", ".sub", ".vtt", ".idx", ".smi"}


@dataclass
class Settings:
    screenshot_dir: str = ""
    default_volume: int = 80          # 0-100
    default_rate: float = 1.0
    loop_mode: str = "order"          # order | repeat_one | repeat_all | shuffle
    auto_resume: bool = True          # 记忆并续播进度
    auto_subtitle: bool = True        # 打开视频时自动挂载同名字幕文件
    on_top: bool = False
    snapshot_format: str = "png"      # png | jpg
    theme: str = "dark"               # dark | light（界面主题）
    start_with_last_list: bool = True
    show_playlist: bool = True
    recent: List[str] = field(default_factory=list)   # 最近打开（去重，最多 15）
    window_geometry: Optional[Dict] = None
    # AI 字幕默认值：源语言默认中文，改过之后自动记住
    ai_src_lang: str = "中文"
    ai_dst_lang: str = "不翻译"
    ai_model: str = "small（推荐，480MB）"
    ai_bilingual: bool = True
    ai_workers: int = 0              # 分段并行段数：0=自动按核数，1=单路
    ai_temp_fallback: bool = False   # 温度回退：False=快速(推荐)，True=难句重试(慢很多)
    ai_chunk_live: bool = True       # 分段实时出字幕：每段识别完立刻显示（保证字幕一直存在）
    ai_chunk_seconds: int = 60       # 分段长度（秒）：30 / 60 / 120
    ai_auto_on_open: bool = False    # 换视频时自动生成 AI 字幕（默认关，耗 CPU）

    def save(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in data.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
            except Exception:
                pass
        if not s.screenshot_dir:
            s.screenshot_dir = str(Path(QStandardPaths.writableLocation(
                QStandardPaths.MoviesLocation) or os.path.expanduser("~")) / "UniversalPlayer_Shots")
        return s

    def add_recent(self, path: str):
        path = os.path.abspath(path)
        self.recent = [p for p in self.recent if p != path]
        self.recent.insert(0, path)
        self.recent = self.recent[:15]

    def default_screenshot_dir(self) -> str:
        if not self.screenshot_dir:
            self.screenshot_dir = str(Path(QStandardPaths.writableLocation(
                QStandardPaths.MoviesLocation) or os.path.expanduser("~")) / "UniversalPlayer_Shots")
        os.makedirs(self.screenshot_dir, exist_ok=True)
        return self.screenshot_dir


# ---------------- 播放历史（续播记忆） ----------------
def load_history() -> Dict[str, dict]:
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_history(history: Dict[str, dict]):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def update_history(path: str, position_ms: int, length_ms: int, playlist: List[str]):
    """记录单个文件进度 + 当前播放列表，用于下次启动续播。"""
    hist = load_history()
    hist["_last_position"] = {
        "path": os.path.abspath(path),
        "position_ms": position_ms,
        "length_ms": length_ms,
    }
    hist["_last_playlist"] = [os.path.abspath(p) for p in playlist]
    # 逐文件进度表
    pos_table = hist.get("_positions", {})
    pos_table[os.path.abspath(path)] = {
        "position_ms": position_ms, "length_ms": length_ms}
    hist["_positions"] = pos_table
    save_history(hist)


def get_position(path: str) -> int:
    hist = load_history()
    pos_table = hist.get("_positions", {})
    rec = pos_table.get(os.path.abspath(path))
    return rec.get("position_ms", 0) if rec else 0


# ---------------- 逐文件字幕延迟（毫秒，正=延后，负=提前） ----------------
def set_sub_delay(path: str, delay_ms: int):
    """记住某个视频的字幕同步偏移，下次打开自动套用。"""
    hist = load_history()
    table = hist.get("_positions", {})
    key = os.path.abspath(path)
    rec = table.get(key) or {}
    rec["sub_delay_ms"] = int(delay_ms)
    table[key] = rec
    hist["_positions"] = table
    save_history(hist)


def get_sub_delay(path: str) -> int:
    hist = load_history()
    rec = hist.get("_positions", {}).get(os.path.abspath(path))
    return int(rec.get("sub_delay_ms", 0)) if rec else 0
