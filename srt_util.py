"""SRT 工具：解析 / 时间轴整体偏移，用于把调好的字幕延迟永久写入文件。"""
from __future__ import annotations

import re

TIME_RE = re.compile(
    r"(\d{1,3}):(\d{1,2}):(\d{1,2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,3}):(\d{1,2}):(\d{1,2})[,.](\d{1,3})"
)


def _to_ms(h, m, s, ms) -> int:
    return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms)


def _fmt(ms: int) -> str:
    if ms < 0:
        ms = 0
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, msec = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{msec:03d}"


def apply_offset(text: str, offset_ms: int) -> str:
    """给 SRT 时间轴整体加偏移（正=字幕延后出现，负=提前出现）。"""
    if not offset_ms:
        return text

    def repl(mo: "re.Match") -> str:
        g = mo.groups()
        start = _to_ms(*g[0:4])
        end = _to_ms(*g[4:8])
        return f"{_fmt(start + offset_ms)} --> {_fmt(end + offset_ms)}"

    return TIME_RE.sub(repl, text)


def shift_file(src: str, offset_ms: int, dst: str | None = None,
               backup: bool = True) -> str:
    """读取 src 应用偏移后写回（默认同文件覆盖），返回写入路径。"""
    dst = dst or src
    with open(src, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    out = apply_offset(text, offset_ms)
    if backup and dst == src:
        try:
            with open(src + ".bak", "w", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass
    with open(dst, "w", encoding="utf-8") as f:
        f.write(out)
    return dst
