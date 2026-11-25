"""探针：libVLC 反复挂载字幕 slave 的行为——
（a）同一路径重复 add 是「去重」还是「新增一条轨」？
（b）不同路径 add 是否会无限累积字幕轨？
结论决定「60 秒逐段出字幕」该用固定文件还是轮转文件。

时间轴写法用绝对时间，全部为无效区间（不实际显示），只看轨道表。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vlc_player import VlcPlayer  # noqa: E402

TOOLS = os.path.join(os.path.dirname(ROOT), "tools")
MEDIA = os.path.join(TOOLS, "test.mp4")
TMP = os.path.join(TOOLS, "_probe_srt")
os.makedirs(TMP, exist_ok=True)

app = QApplication(sys.argv)


def spin(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def write_srt(path, n):
    with open(path, "w", encoding="utf-8") as f:
        for i in range(n):
            f.write(f"{i+1}\n00:00:{i*2:02d},000 --> 00:00:{i*2+1:02d},000\nline{i}\n\n")


def spus(pl):
    return [n for _, n in pl.get_subtitle_tracks()]


MAX = 6
p = VlcPlayer(["--vout=dummy", "--aout=dummy"])
p.open(MEDIA)
spin(3000)
print("初始字幕轨:", spus(p))

p1 = os.path.join(TMP, "a.srt")
write_srt(p1, 2)
print("add a#1 ->", p._player.video_set_subtitle_file(p1), spus(p))
print("停 0.6s 让 VLC 解析…")
spin(600)
print("  轨道:", spus(p))

write_srt(p1, 5)                       # 同路径改内容
p._player.video_set_subtitle_file(p1)  # 绕过应用层去重，直接压给 VLC
spin(600)
t_same = spus(p)
print("同路径重复 add ->", t_same)

p2 = os.path.join(TMP, "b.srt")
write_srt(p2, 3)
p._player.video_set_subtitle_file(p2)
spin(600)
t2 = spus(p)
print("新增不同路径 b ->", t2)

for i in range(MAX):
    px = os.path.join(TMP, f"c{i}.srt")
    write_srt(px, 2)
    p._player.video_set_subtitle_file(px)
    spin(300)
    print(f"  再挂 c{i} -> 轨数 {len(spus(p))}")

final = spus(p)
print()
print(f"同一路径重复挂载后轨数 = {len(t_same)}")
print(f"不同路径 1 条后轨数     = {len(t2)}")
print(f"不同路径 {MAX+2} 条后轨数 = {len(final)}")
print("结论:", "同路径=去重(不新增)" if len(t_same) <= len([x for x in spus(p)]) - MAX - 2 else "同路径=新增轨")
print("累积:", "会累积(一路 +1)" if len(final) >= len(t2) + MAX else "不累积")

p.release()
