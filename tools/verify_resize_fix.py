"""验证「播放中窗口突然变宽」修复：VLC 只持有 _render_host 子窗口 HWND，
即便 vout 重建时强行 SetWindowPos 改掉子窗口尺寸，eventFilter + _fit_render_host
也必须把它重新打回铺满 video_widget，且主窗口尺寸不被牵连。
"""
import os
import sys

# 让脚本在 tools/ 下也能 import 项目根模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 打桩 VLC（无头环境无系统 VLC，避免弹 QMessageBox 阻塞）
import vlc_player
from PySide6.QtCore import QObject, Signal
class _DummyPlayer(QObject):
    time_changed = Signal(int)
    end_reached = Signal()
    error_occurred = Signal(str)
    tracks_updated = Signal()
    length_changed = Signal(int)
    def __init__(self, *a, **k):
        super().__init__()
        self._hwnd = None
    def set_hwnd(self, hwnd):
        self._hwnd = hwnd
    def set_volume(self, v):
        pass
    def set_rate(self, r):
        pass
    def open(self, path, resume=0):
        pass
    def set_subtitle_delay(self, ms):
        pass
    def add_subtitle(self, path):
        return False
    def release(self):
        pass
vlc_player.VlcPlayer = _DummyPlayer
vlc_player._VLC_AVAILABLE = True

# 必须在打桩后导入 main_window
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEvent, QTimer
import main_window as mw_mod
# main_window 用 `from vlc_player import VlcPlayer` 绑定了名字，
# 需直接替换其模块命名空间里的 VlcPlayer 才生效
mw_mod.VlcPlayer = _DummyPlayer

# 授权门禁打桩（避免弹窗阻塞）
mw_mod.MainWindow._license_gate = lambda self: None

app = QApplication.instance() or QApplication(sys.argv)

errors = []
def check(cond, msg):
    if cond:
        print(f"  PASS: {msg}")
    else:
        print(f"  FAIL: {msg}")
        errors.append(msg)

win = mw_mod.MainWindow()
win.resize(1100, 680)
win.show()
app.processEvents()

# 1) 渲染子窗口应已建立，且首次 open 时 HWND 绑定的是 _render_host 而非 video_widget
check(win._render_host is not None, "_render_host 子窗口已创建")
check(win._render_host.parent() is win.video_widget, "_render_host 是 video_widget 的子窗口")

test_video = os.path.join(os.path.dirname(__file__), "test60.mp4")
if os.path.isfile(test_video):
    win._hwnd_set = False
    win.open_path(test_video)
    captured = win.player._hwnd
    rh_hwnd = int(win._render_host.winId())
    vw_hwnd = int(win.video_widget.winId())
    check(captured == rh_hwnd, "open_path 把 VLC HWND 绑定到 _render_host（非 video_widget）")
    check(captured != vw_hwnd, "VLC 未直接拿到 video_widget 的 HWND（这正是变宽根因的隔离点）")
else:
    print(f"  SKIP: 测试视频缺失 {test_video}")
    check(False, "测试视频 test60.mp4 应存在")

# 给 video_widget 一个确定尺寸（用 setFixedSize 避免被布局覆盖，offscreen 下稳定）
win.video_widget.setFixedSize(1000, 600)
app.processEvents()
vw, vh = win.video_widget.width(), win.video_widget.height()
check(vw == 1000 and vh == 600, f"video_widget 尺寸稳定为 1000x600（实际 {vw}x{vh}）")

# 2) 模拟 VLC vout 重建时强行把宿主 HWND 改成视频原始尺寸（如 640x360）
win._render_host.setGeometry(0, 0, 640, 360)
app.processEvents()
# 触发 eventFilter 的 Resize 分支（真实场景是 VLC SetWindowPos 引发），
# 再让单次 singleShot(0) 的 _fit_render_host 执行（守卫防风暴，不会死循环）
win.eventFilter(win._render_host, QEvent(QEvent.Resize))
app.processEvents()  # 让 QTimer.singleShot(0, _fit_render_host) 执行
g = win._render_host.geometry()
check(g.x() == 0 and g.y() == 0, f"render_host 被归位到 (0,0)（实际 {g.x()},{g.y()}）")
check(g.width() == vw and g.height() == vh,
      f"render_host 被重新铺满 video_widget {vw}x{vh}（实际 {g.width()}x{g.height()}）")

# 3) 主窗口尺寸必须稳定，绝不能被 VLC 牵连成视频/子窗口尺寸（「突然变宽」根因判定）
mw, mh = win.width(), win.height()
# 5px 为窗口边框/标题栏的正常误差；真 bug 会撑到视频原始分辨率（如 640x360 或 1000x600）
check(mw == 1100 and 680 <= mh <= 720, f"主窗口尺寸稳定 {mw}x{mh}（未被 VLC 拉宽）")
check(not (mw == 640 and mh == 360), "主窗口未被 VLC 改回成视频原始 640x360")
check(not (mw == 1000 and mh == 600), "主窗口未被 VLC 改回成子窗口 1000x600")

# 4) video_widget 自身尺寸变化时也要重新铺满
win.video_widget.setFixedSize(1200, 700)
app.processEvents()
win.eventFilter(win.video_widget, QEvent(QEvent.Resize))
app.processEvents()
g2 = win._render_host.geometry()
vw2, vh2 = win.video_widget.width(), win.video_widget.height()
check(g2.width() == vw2 and g2.height() == vh2,
      f"video_widget 变 1200x700 后 render_host 仍铺满（实际 {g2.width()}x{g2.height()}）")

win.close()
print()
if errors:
    print(f"RESULT: FAIL ({len(errors)} 项未通过)")
    sys.exit(1)
else:
    print("RESULT: ALL_PASS — 突然变宽修复逻辑验证通过")
    sys.exit(0)
