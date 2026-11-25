"""v1.4 功能与界面优化验证：OSD / 主题 / 画中画 / 逐帧 / 倍速快捷键 / 音量 125。

offscreen 运行，断言不依赖真渲染。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication(sys.argv)

PASS = []
FAIL = []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name, flush=True)


from theme import apply_theme

# 1) 深色主题应用（setStyleSheet 后 style 会被包装成 QStyleSheetStyle，
#    改校验调色板窗口底色是否为深色 #202124）
apply_theme(app, True)
check("theme_dark_applied", app.palette().window().color().name().lower() == "#202124")
apply_theme(app, False)
apply_theme(app, True)

# 2) 主窗口启动
from main_window import MainWindow
w = MainWindow(None)

# 3) OSD 控件存在且初始隐藏
check("osd_exists", hasattr(w, "osd_label") and w.osd_label.parent() is w.video_widget)
check("osd_initially_hidden", w.osd_label.isHidden())
w._show_osd("测试提示")
check("osd_shows", w.osd_label.isVisible() and w.osd_label.text() == "测试提示")
check("osd_centered", 0 <= w.osd_label.x() <= w.video_widget.width())
w._hide_osd()
check("osd_hides", w.osd_label.isHidden())

# 4) 音量滑条范围 125
check("volume_range_125", w.volume.maximum() == 125)
w.volume.setValue(125)
check("volume_125_set", w.volume.value() == 125)

# 5) 倍速步进
w._step_rate(1)
r1 = w.player.get_rate()
check("rate_step_up", r1 == 1.25)
w._step_rate(-1)
check("rate_step_down", w.player.get_rate() == 1.0)
w._step_rate(-1)
check("rate_step_down2", w.player.get_rate() == 0.75)
w._step_rate(0)
check("rate_reset", w.player.get_rate() == 1.0)
check("rate_btn_text", w.rate_btn.text() == "1.0x")

# 6) 画中画切换
geo0 = w.geometry()
w._toggle_pip()
app.processEvents()
check("pip_on_top", bool(w.windowFlags() & Qt.WindowStaysOnTopHint))
check("pip_small", w.width() <= 500)
w._toggle_pip()
check("pip_restore_geo", abs(w.geometry().width() - geo0.width()) <= 2)
check("pip_restore_top", bool(w.windowFlags() & Qt.WindowStaysOnTopHint) == bool(w.settings.on_top))
check("pip_state_off", w._pip_active is False)

# 7) 逐帧 API 存在
check("frame_step_api", hasattr(w.player, "next_frame"))

# 8) 菜单项
menu_texts = []
for act in w.menuBar().actions():
    menu_texts.append(act.text())
    m = act.menu()
    if m:
        for a in m.actions():
            if a.menu():
                for sub in a.menu().actions():
                    menu_texts.append(sub.text())
            menu_texts.append(a.text())
joined = "|".join(menu_texts)
check("menu_pip", "画中画" in joined)
check("menu_rate_step", "减速 [" in joined and "加速 ]" in joined)
check("menu_dark", "深色主题" in joined)
dark_act = None
for act in w.menuBar().actions():
    if act.text().startswith("设置"):
        for a in act.menu().actions():
            if a.text() == "深色主题":
                dark_act = a
check("dark_action_checkable", dark_act is not None and dark_act.isCheckable())

# 9) 主题开关记忆
dark_act.trigger()  # 切到浅色
check("theme_toggle_setting", w.settings.theme == "light")
dark_act.trigger()  # 切回深色
check("theme_toggle_back", w.settings.theme == "dark")

# 10) OSD 视频区子窗口不干扰渲染宿主
check("render_host_intact", w._render_host.parent() is w.video_widget)

w.close()
print("\nALL_PASS" if not FAIL else f"\nFAILED: {FAIL}")
sys.exit(0 if not FAIL else 1)
