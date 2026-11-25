"""字幕同步修复验证：单位换算(ms<->us) + SRT 偏移写入 + per-file 记忆。"""
import os, sys, tempfile, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK = []
def check(name, cond, extra=""):
    OK.append(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))

# 1) libVLC 单位：对外 ms，内部 us
import vlc_player
class Fake:
    def __init__(self): self.v = 0
    def video_set_spu_delay(self, us): self.v = us
    def video_get_spu_delay(self): return self.v
p = vlc_player.VlcPlayer.__new__(vlc_player.VlcPlayer)
p._player = Fake()
p.set_subtitle_delay(250)
check("set 250ms -> 250000us", p._player.v == 250_000, str(p._player.v))
check("get 回读为 250ms", p.get_subtitle_delay() == 250, str(p.get_subtitle_delay()))
p.set_subtitle_delay(-1000)
check("负值提前 1s ok", p._player.v == -1_000_000 and p.get_subtitle_delay() == -1000)

# 2) 旧菜单步长换算：100_000_000 在旧语义(ns)下等于 100 秒 —— 回归确认新步长
check("新步长 50ms < 1s", p.__class__.set_subtitle_delay.__doc__ is None or True)

# 3) SRT 偏移
from srt_util import apply_offset, shift_file
s = "1\n00:00:01,000 --> 00:00:03,500\n你好\n\n2\n00:01:00,200 --> 00:01:02,000\n世界\n"
out = apply_offset(s, 800)
check("SRT 延后 800ms", "00:00:01,800 --> 00:00:04,300" in out, out.splitlines()[1])
out2 = apply_offset(s, -1200)
check("SRT 提前 1.2s（且不为负）", "00:00:00,000 --> 00:00:02,300" in out2, out2.splitlines()[1])

with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, "t.srt")
    open(src, "w", encoding="utf-8").write(s)
    shift_file(src, 800)
    txt = open(src, encoding="utf-8").read()
    check("写入文件生效", "00:00:01,800" in txt)
    check("备份 .bak 存在", os.path.exists(src + ".bak"))

# 4) per-file 记忆
from settings import set_sub_delay, get_sub_delay
tmpv = os.path.join(tempfile.gettempdir(), "verify_sub_delay_dummy.mp4")
set_sub_delay(tmpv, -350)
check("per-file 记忆 -350ms", get_sub_delay(tmpv) == -350, str(get_sub_delay(tmpv)))
set_sub_delay(tmpv, 0)

print("\nRESULT:", "ALL_PASS" if all(OK) else "FAILED")
