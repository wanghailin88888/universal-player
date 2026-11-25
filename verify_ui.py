import os, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import PySide6.QtWidgets as qw
qw.QMessageBox.warning = lambda *a, **k: None   # headless 下屏蔽模态提示

from PySide6.QtWidgets import QApplication
from main_window import MainWindow, SettingsDialog, UrlDialog, fmt_time
from playlist import PlaylistItem

app = QApplication([])
w = MainWindow()
w.resize(1100, 680)

# 填充示例播放列表（英文文件名，避免 offscreen 缺字体导致方框，便于看布局）
w.playlist._items = [
    PlaylistItem('C:/media/movie_sample.mkv'),
    PlaylistItem('C:/media/lecture_2026.ts'),
    PlaylistItem('C:/media/clip_demo.mp4'),
    PlaylistItem('C:/media/concert.avi'),
]
w._sync_playlist_view()
w.playlist_view.setCurrentRow(0)
w.status_left.setText("movie_sample.mkv")
w.status_mid.setText("1920x1080  25.0fps")
w.status_right.setText("VLC 3.0.21")

# 对话框构建冒烟
dlg1 = SettingsDialog(w.settings, w)
dlg2 = UrlDialog(w)
print('DIALOGS_OK', dlg1.windowTitle(), '|', dlg2.windowTitle())

# AI 字幕对话框 / 模型管理对话框构建冒烟
try:
    from ai_subtitle_ui import AiSubtitleDialog, AiModelManagerDialog
    dlg3 = AiSubtitleDialog('C:/media/lecture_2026.mp4', w)
    dlg4 = AiModelManagerDialog(w)
    print('AI_DIALOGS_OK', dlg3.windowTitle(), '|', dlg4.windowTitle(),
          '| 模型', dlg3.model_size, '设备', dlg3.device)
    app.processEvents()
    pix3 = dlg3.grab()
    pix3.save(os.path.join(os.path.dirname(__file__), 'preview_ai_subtitle.png'))
    print('AI_DIALOG_GRAB_OK', pix3.size().width(), pix3.size().height())
except Exception as e:
    print('AI_DIALOGS_FAIL', repr(e)[:200])

# 时间格式化
print('FMT', fmt_time(0), fmt_time(61_000), fmt_time(3_725_000))

# 无 VLC 时点击控制不应崩溃
w._play_pause(); w._stop(); w._next(); w._prev()
w._toggle_mute(); w._set_rate(1.5); w._on_ab(); w._take_snapshot()
print('SLOTS_OK (无 VLC 时安全降级)')

app.processEvents()
pix = w.grab()
out = os.path.join(os.path.dirname(__file__), 'preview.png')
ok = pix.save(out)
print('GRAB_OK', ok, 'SIZE', pix.size().width(), pix.size().height())
