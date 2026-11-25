"""验证单文件 exe 的 VLC 自解压链路（模拟 frozen 环境，无需等 PyInstaller 构建）。

做法：把真实 tools/vlc_bundle.zip 放进一个伪 _MEIPASS/vlc_bundle/，设 sys.frozen /
sys._MEIPASS，然后 import main（触发 _extract_bundled_vlc），再验证：
  1) %TEMP%/universal_player_vlc/vlc-3.0.24/libvlc.dll 被解压出来
  2) VLC_DIR 指向该目录
  3) vlc_player._bootstrap_vlc 找到它、VlcPlayer() 能真正加载 libvlc
"""
import os
import sys
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# 1) 构造伪 _MEIPASS，内含 vlc_bundle.zip（复刻冻结态分发）
fake_meipass = tempfile.mkdtemp(prefix="fake_meipass_")
os.makedirs(os.path.join(fake_meipass, "vlc_bundle"), exist_ok=True)
zip_src = os.path.join(ROOT, "tools", "vlc_bundle.zip")
assert os.path.isfile(zip_src), f"缺少 {zip_src}"
shutil.copy(zip_src, os.path.join(fake_meipass, "vlc_bundle", "vlc_bundle.zip"))

sys.frozen = True
sys._MEIPASS = fake_meipass

# 2) import main → 触发 _extract_bundled_vlc()
import main  # noqa: E402

# 3) 验证解压结果
dest = os.path.join(tempfile.gettempdir(), "universal_player_vlc")
vlc_dir = os.path.join(dest, "vlc-3.0.24")
libvlc = os.path.join(vlc_dir, "libvlc.dll")

errors = []
def check(cond, msg):
    print(("  PASS: " if cond else "  FAIL: ") + msg)
    if not cond:
        errors.append(msg)

check(os.path.isfile(libvlc), f"libvlc.dll 已自解压到 {libvlc}")
check(os.environ.get("VLC_DIR", "") == vlc_dir, f"VLC_DIR 指向解压目录（实际 {os.environ.get('VLC_DIR')}）")
check(os.path.isdir(os.environ.get("VLC_PLUGIN_PATH", "")), "VLC_PLUGIN_PATH 已设置")

# 4) 验证 vlc_player 引导 + 真正加载 libvlc
import vlc_player  # noqa: E402
print(f"  vlc_player.VLC_DIR = {vlc_player.VLC_DIR}")
check(vlc_player._VLC_AVAILABLE, "python-vlc 可导入")
try:
    p = vlc_player.VlcPlayer()
    check(p is not None, "VlcPlayer() 构造成功，libvlc 真正加载")
except Exception as e:
    check(False, f"VlcPlayer() 失败: {e}")

# 清理伪 _MEIPASS
shutil.rmtree(fake_meipass, ignore_errors=True)

print()
if errors:
    print(f"RESULT: FAIL ({len(errors)} 项)")
    sys.exit(1)
else:
    print("RESULT: ALL_PASS — VLC 单文件自解压链路验证通过")
    sys.exit(0)
