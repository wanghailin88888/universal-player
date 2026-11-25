"""万能视频播放器 —— 主窗口与全部交互逻辑。

UI 用 PySide6 原生控件（跟随系统主题，黑底视频区），控制逻辑对接 VlcPlayer。
无 VLC 运行库时引擎置空、UI 照常构建，仅提示先安装 VLC。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import (
    Qt, QSize, QTimer, QUrl, QStandardPaths, QModelIndex, QEvent,
)
from PySide6.QtGui import (
    QAction, QDesktopServices, QIcon, QKeySequence, QPalette, QColor,
    QPainter,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QToolButton, QLabel, QSlider, QFrame, QListWidget, QAbstractItemView,
    QMenu, QMenuBar, QStatusBar, QDockWidget, QFileDialog, QDialog,
    QFormLayout, QLineEdit, QPushButton, QCheckBox, QComboBox, QMessageBox,
    QDialogButtonBox, QStyle, QToolBar,
)

from settings import (
    Settings, load_history, get_position, update_history,
    get_sub_delay, set_sub_delay,
    VIDEO_EXTS, SUB_EXTS,
)
from playlist import PlaylistModel
from vlc_player import VlcPlayer, VlcError, _VLC_AVAILABLE
from theme import apply_theme
import license as license_gate
import about_dialog


def fmt_time(ms: int) -> str:
    if not ms or ms <= 0:
        return "00:00"
    s = int(ms / 1000)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def _icon_path() -> str:
    """应用图标（林主题）；资源缺失时返回空串避免崩溃。"""
    try:
        from resources import asset_path
        return asset_path("app.ico")
    except Exception:
        return ""


# 逐段实时字幕的提前量：已挂字幕至少覆盖到「播放进度 + 该值」才不重挂。
# libVLC 3.x 每次挂载都会新增一条字幕轨（无法移除），靠这个阈值把轨数压到最低。
_AI_LIVE_AHEAD_MS = 30000


class VideoWidget(QWidget):
    """VLC 渲染区：黑底、接收拖拽、双击全屏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumSize(320, 180)
        self.setStyleSheet("background-color:#000;")
        self._main = parent

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        p.end()

    def mouseDoubleClickEvent(self, event):
        if self._main:
            self._main.toggle_fullscreen()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if urls and self._main:
            self._main.handle_drop(urls)


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("偏好设置")
        self.settings = settings
        layout = QFormLayout(self)

        self.screenshot_edit = QLineEdit(settings.screenshot_dir)
        btn = QPushButton("选择…")
        btn.clicked.connect(self._choose_dir)
        row = QHBoxLayout()
        row.addWidget(self.screenshot_edit)
        row.addWidget(btn)
        layout.addRow("截图保存目录：", row)

        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 125)
        self.volume.setValue(min(125, settings.default_volume))
        layout.addRow("默认音量：", self.volume)

        self.rate = QComboBox()
        for r in ["0.5", "0.75", "1.0", "1.25", "1.5", "2.0"]:
            self.rate.addItem(r + "x", float(r))
        idx = self.rate.findData(settings.default_rate)
        self.rate.setCurrentIndex(idx if idx >= 0 else 2)
        layout.addRow("默认倍速：", self.rate)

        self.loop = QComboBox()
        for v, t in [("order", "顺序播放"), ("repeat_one", "单曲循环"),
                     ("repeat_all", "列表循环"), ("shuffle", "随机播放")]:
            self.loop.addItem(t, v)
        self.loop.setCurrentIndex(self.loop.findData(settings.loop_mode))

        self.auto_resume = QCheckBox("关闭时记忆进度，下次续播")
        self.auto_resume.setChecked(settings.auto_resume)
        self.auto_subtitle = QCheckBox("打开视频时自动加载字幕文件（含 AI 生成过的 .srt）")
        self.auto_subtitle.setChecked(getattr(settings, "auto_subtitle", True))
        self.auto_subtitle.setToolTip("开启后，视频同目录下的同名 .srt 会自动挂上，\n"
                                      "AI 字幕只需识别一次，之后每次播放直接复用。")
        self.auto_ai = QCheckBox("换视频时自动生成 AI 字幕（没有 .srt 时后台识别，较耗 CPU）")
        self.auto_ai.setChecked(getattr(settings, "ai_auto_on_open", False))
        self.auto_ai.setToolTip("开启后，打开/切换到一部还没有字幕文件的视频，\n"
                                "会自动用上次那套 AI 配置在后台生成字幕并挂载。\n"
                                "长片很吃 CPU，笔记本建议关。")
        self.on_top = QCheckBox("窗口始终置顶")
        self.on_top.setChecked(settings.on_top)
        self.start_last = QCheckBox("启动时恢复上次播放列表")
        self.start_last.setChecked(settings.start_with_last_list)
        layout.addRow(self.auto_resume)
        layout.addRow(self.auto_subtitle)
        layout.addRow(self.auto_ai)
        layout.addRow(self.on_top)
        layout.addRow(self.start_last)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择截图目录",
                                             self.screenshot_edit.text())
        if d:
            self.screenshot_edit.setText(d)

    def apply(self):
        self.settings.screenshot_dir = self.screenshot_edit.text()
        self.settings.default_volume = self.volume.value()
        self.settings.default_rate = self.rate.currentData()
        self.settings.loop_mode = self.loop.currentData()
        self.settings.auto_resume = self.auto_resume.isChecked()
        self.settings.auto_subtitle = self.auto_subtitle.isChecked()
        self.settings.ai_auto_on_open = self.auto_ai.isChecked()
        self.settings.on_top = self.on_top.isChecked()
        self.settings.start_with_last_list = self.start_last.isChecked()
        self.settings.save()


class UrlDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("打开网络流 / 直链")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("支持 http(s) / rtsp / rtmp / mms / udp 等地址："))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("例如：http://example.com/video.m3u8  或  rtsp://...")
        layout.addWidget(self.edit)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        self.edit.returnPressed.connect(self.accept)

    def url(self) -> str:
        return self.edit.text().strip()


class MainWindow(QMainWindow):
    def __init__(self, files: Optional[List[str]] = None):
        super().__init__()
        self.settings = Settings.load()
        self.playlist = PlaylistModel()
        self.playlist.loop_mode = self.settings.loop_mode
        self.player: Optional[VlcPlayer] = None
        self.vlc_ok = False
        self.current_row = -1
        self._hwnd_set = False
        self._fitting = False
        self._seeking = False
        self._ab_state = 0  # 0 未设, 1 已设A, 2 循环中
        self._ab_a = None
        self._pip_active = False       # 画中画（迷你置顶）状态
        self._pip_restore = None       # (geometry, dock_visible)
        self._ai_worker = None   # 后台 AI 字幕任务（对话框关闭后由主窗口持有）
        self._ai_media = ""
        # 逐段实时字幕：当前已挂载的实时字幕覆盖到的绝对时间(ms)。
        # 只有覆盖不到播放进度 + 提前量时才重挂新轨（VLC 3.x 无法移除字幕轨）。
        self._ai_live_cover_ms = 0

        self._build_ui()
        self._build_menu()
        self._build_playlist_dock()

        # 尝试初始化 VLC 引擎（无 VLC 时降级）
        try:
            self.player = VlcPlayer()
            self.vlc_ok = True
            self.player.time_changed.connect(lambda _: None)
            self.player.end_reached.connect(self._on_end)
            self.player.error_occurred.connect(self._on_error)
            self.player.tracks_updated.connect(self._on_tracks_updated)
            self.player.length_changed.connect(self._on_length)
            self.player.set_volume(self.settings.default_volume)
            self.player.set_rate(self.settings.default_rate)
        except VlcError as e:
            self.player = None
            self.vlc_ok = False
            self.status_right.setText("未检测到 VLC — 请安装 VLC 后重启")
            QMessageBox.warning(self, "缺少 VLC", str(e))

        # UI 刷新定时器
        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(200)
        self._ui_timer.timeout.connect(self._update_ui)
        self._ui_timer.start()

        self.setAcceptDrops(True)
        self.resize(1100, 680)
        if self.settings.on_top:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.show()

        if files:
            self.open_files(files)
        else:
            self._restore_last_session()

        # 授权门禁：窗口就绪后稍作延迟再检查（不挡窗口绘制）
        QTimer.singleShot(400, self._license_gate)

    # ---------------- UI 构建 ----------------
    def _build_ui(self):
        self.setWindowTitle("万能视频播放器")
        self.setWindowIcon(QIcon(_icon_path()))
        central = QWidget()
        self.setCentralWidget(central)
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        self.video_widget = VideoWidget(self)
        vbox.addWidget(self.video_widget, 1)

        # 专用渲染子窗口：libVLC 在 Windows 嵌入模式会在 vout 重建时把宿主 HWND
        # SetWindowPos 成视频原始尺寸（表现为"播放中窗口突然变宽"）。
        # 把一个独立原生子窗口的 HWND 交给 VLC，它再改也只改这个子窗口，
        # 主窗口/布局不受影响；尺寸偏差由 eventFilter 打回（见 eventFilter/_fit_render_host）。
        self.video_widget.setAttribute(Qt.WA_NativeWindow)
        self.video_widget.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self._render_host = QWidget(self.video_widget)
        self._render_host.setAttribute(Qt.WA_NativeWindow)
        self._render_host.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self._render_host.installEventFilter(self)
        self.video_widget.installEventFilter(self)

        # OSD 屏显提示：音量/倍速/快进退等操作在画面中央短暂显示反馈
        self._osd_timer = QTimer(self)
        self._osd_timer.setSingleShot(True)
        self._osd_timer.timeout.connect(self._hide_osd)
        self.osd_label = QLabel(self.video_widget)
        self.osd_label.setAlignment(Qt.AlignCenter)
        self.osd_label.setStyleSheet(
            "QLabel { background: rgba(20,20,22,190); color: #fff;"
            " font-size: 20px; font-weight: 600; padding: 14px 30px;"
            " border-radius: 10px; }")
        self.osd_label.hide()

        # 控制栏
        ctrl = QFrame()
        ctrl.setFrameShape(QFrame.NoFrame)
        cbox = QHBoxLayout(ctrl)
        cbox.setContentsMargins(8, 6, 8, 6)
        cbox.setSpacing(6)

        # 原生标准图标（不依赖系统字体，任何平台都能正确渲染）
        style = self.style()
        self.icon_play = style.standardIcon(QStyle.SP_MediaPlay)
        self.icon_pause = style.standardIcon(QStyle.SP_MediaPause)
        self.icon_volume = style.standardIcon(QStyle.SP_MediaVolume)
        self.icon_muted = style.standardIcon(QStyle.SP_MediaVolumeMuted)

        self.play_btn = QToolButton()
        self.play_btn.setIcon(self.icon_play)
        self.play_btn.setToolTip("播放 / 暂停 (空格)")
        self.play_btn.clicked.connect(self._play_pause)
        self.stop_btn = QToolButton()
        self.stop_btn.setIcon(style.standardIcon(QStyle.SP_MediaStop))
        self.stop_btn.setToolTip("停止")
        self.stop_btn.clicked.connect(self._stop)
        self.prev_btn = QToolButton()
        self.prev_btn.setIcon(style.standardIcon(QStyle.SP_MediaSkipBackward))
        self.prev_btn.setToolTip("上一曲 (PgUp)")
        self.prev_btn.clicked.connect(self._prev)
        self.next_btn = QToolButton()
        self.next_btn.setIcon(style.standardIcon(QStyle.SP_MediaSkipForward))
        self.next_btn.setToolTip("下一曲 (PgDn)")
        self.next_btn.clicked.connect(self._next)

        self.time_label = QLabel("00:00")
        self.time_label.setMinimumWidth(48)
        self.progress = QSlider(Qt.Horizontal)
        self.progress.setRange(0, 100000)
        self.progress.setMinimumWidth(200)
        self.progress.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.progress.sliderReleased.connect(self._on_seek_released)
        self.progress.sliderMoved.connect(self._on_seek_moved)
        self.duration_label = QLabel("00:00")
        self.duration_label.setMinimumWidth(48)

        self.rate_btn = QToolButton(text="1.0x")
        self.rate_btn.setToolTip("播放速度")
        self.rate_btn.setPopupMode(QToolButton.InstantPopup)
        self.rate_menu = QMenu()
        for r in [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 3.0, 4.0]:
            a = QAction(f"{r}x", self)
            a.triggered.connect(lambda _=False, r=r: self._set_rate(r))
            self.rate_menu.addAction(a)
        self.rate_btn.setMenu(self.rate_menu)

        self.vol_btn = QToolButton()
        self.vol_btn.setIcon(self.icon_volume)
        self.vol_btn.setToolTip("静音 (M)")
        self.vol_btn.clicked.connect(self._toggle_mute)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 125)
        self.volume.setValue(self.settings.default_volume)
        self.volume.setFixedWidth(90)
        self.volume.valueChanged.connect(self._on_volume_changed)

        self.loop_btn = QToolButton(text="顺序")
        self.loop_btn.setToolTip("循环模式")
        self.loop_btn.setPopupMode(QToolButton.InstantPopup)
        self.loop_menu = QMenu()
        for v, t in [("order", "顺序播放"), ("repeat_one", "单曲循环"),
                     ("repeat_all", "列表循环"), ("shuffle", "随机播放")]:
            a = QAction(t, self)
            a.triggered.connect(lambda _=False, v=v: self._on_loop_changed(v))
            self.loop_menu.addAction(a)
        self.loop_btn.setMenu(self.loop_menu)

        self.ab_btn = QToolButton(text="A-B")
        self.ab_btn.setToolTip("A-B 片段循环（点两次设定 A、B）")
        self.ab_btn.clicked.connect(self._on_ab)

        self.snap_btn = QToolButton()
        self.snap_btn.setIcon(style.standardIcon(QStyle.SP_DialogSaveButton))
        self.snap_btn.setToolTip("截图当前帧 (S)")
        self.snap_btn.clicked.connect(self._take_snapshot)

        self.list_btn = QToolButton()
        self.list_btn.setIcon(style.standardIcon(QStyle.SP_FileDialogDetailedView))
        self.list_btn.setToolTip("显示 / 隐藏播放列表")
        self.list_btn.clicked.connect(self._toggle_playlist)

        self.fs_btn = QToolButton()
        self.fs_btn.setIcon(style.standardIcon(QStyle.SP_TitleBarMaxButton))
        self.fs_btn.setToolTip("全屏 (F)")
        self.fs_btn.clicked.connect(self.toggle_fullscreen)

        for w in (self.play_btn, self.stop_btn, self.prev_btn, self.next_btn,
                  self.rate_btn, self.vol_btn, self.loop_btn, self.ab_btn,
                  self.snap_btn, self.list_btn, self.fs_btn):
            w.setFixedHeight(34)
            w.setIconSize(QSize(20, 20))

        cbox.addWidget(self.play_btn)
        cbox.addWidget(self.stop_btn)
        cbox.addWidget(self.prev_btn)
        cbox.addWidget(self.next_btn)
        cbox.addSpacing(8)
        cbox.addWidget(self.time_label)
        cbox.addWidget(self.progress, 1)
        cbox.addWidget(self.duration_label)
        cbox.addSpacing(8)
        cbox.addWidget(self.rate_btn)
        cbox.addWidget(self.vol_btn)
        cbox.addWidget(self.volume)
        cbox.addSpacing(8)
        cbox.addWidget(self.loop_btn)
        cbox.addWidget(self.ab_btn)
        cbox.addWidget(self.snap_btn)
        cbox.addWidget(self.list_btn)
        cbox.addWidget(self.fs_btn)
        vbox.addWidget(ctrl)

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_left = QLabel("就绪")
        self.status_mid = QLabel("")
        self.status_sub = QLabel("")          # 字幕同步偏移常驻显示
        self.status_ai = QLabel("")           # AI 字幕后台进度（换片也不被覆盖）
        self.status_right = QLabel("")
        self.status_bar.addWidget(self.status_left, 3)
        self.status_bar.addWidget(self.status_mid, 2)
        self.status_bar.addWidget(self.status_sub, 0)
        self.status_bar.addWidget(self.status_ai, 1)
        self.status_bar.addWidget(self.status_right, 1)
        if _VLC_AVAILABLE:
            try:
                self.status_right.setText("引擎：VLC " +
                                         (vlc.libvlc_get_version().decode() if vlc else ""))
            except Exception:
                pass

    # ---------------- 菜单 ----------------
    def _build_menu(self):
        mb = self.menuBar()

        fmenu = mb.addMenu("文件(&F)")
        fmenu.addAction("打开文件…", self._on_open_files, "Ctrl+O")
        fmenu.addAction("打开文件夹…", self._on_open_folder)
        fmenu.addAction("打开网络流…", self._on_open_url, "Ctrl+U")
        self.recent_menu = fmenu.addMenu("最近播放")
        self._rebuild_recent_menu()
        fmenu.addSeparator()
        fmenu.addAction("退出", self.close, "Ctrl+Q")

        pmenu = mb.addMenu("播放(&P)")
        pmenu.addAction("播放 / 暂停", self._play_pause, "Space")
        pmenu.addAction("停止", self._stop)
        pmenu.addAction("上一曲", self._prev, "PgUp")
        pmenu.addAction("下一曲", self._next, "PgDown")
        rate_sub = pmenu.addMenu("倍速")
        rate_sub.addAction("减速 [", lambda: self._step_rate(-1))
        rate_sub.addAction("加速 ]", lambda: self._step_rate(1))
        rate_sub.addAction("恢复 1.0x（退格）", lambda: self._step_rate(0))
        rate_sub.addSeparator()
        for r in [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 4.0]:
            rate_sub.addAction(f"{r}x", lambda r=r: self._set_rate(r))
        loop_sub = pmenu.addMenu("循环模式")
        for v, t in [("order", "顺序播放"), ("repeat_one", "单曲循环"),
                     ("repeat_all", "列表循环"), ("shuffle", "随机播放")]:
            loop_sub.addAction(t, lambda v=v: self._on_loop_changed(v))

        vmenu = mb.addMenu("视频(&V)")
        vmenu.addAction("截图当前帧", self._take_snapshot, "S")
        vmenu.addSeparator()
        vmenu.addAction("AI 字幕：识别人声并翻译…", self._on_ai_subtitle, "Ctrl+B")
        vmenu.addAction("取消 AI 字幕任务", self._ai_cancel)
        vmenu.addAction("管理 AI 模型…", self._on_ai_models)
        vmenu.addSeparator()
        self.sub_menu = vmenu.addMenu("字幕")
        self.sub_menu.addAction("加载外部字幕…", self._load_subtitle_file)
        self.sub_menu.addAction("关闭字幕", lambda: self.player and self.player.disable_subtitle())
        self.sub_menu.addSeparator()
        self.sub_delay_menu = self.sub_menu.addMenu("字幕同步（延迟）")
        self.sub_delay_menu.addAction("提前 50ms", lambda: self._adjust_subtitle_delay(-50), "H")
        self.sub_delay_menu.addAction("延后 50ms", lambda: self._adjust_subtitle_delay(50), "G")
        self.sub_delay_menu.addSeparator()
        self.sub_delay_menu.addAction("提前 250ms", lambda: self._adjust_subtitle_delay(-250))
        self.sub_delay_menu.addAction("延后 250ms", lambda: self._adjust_subtitle_delay(250))
        self.sub_delay_menu.addAction("提前 1 秒", lambda: self._adjust_subtitle_delay(-1000))
        self.sub_delay_menu.addAction("延后 1 秒", lambda: self._adjust_subtitle_delay(1000))
        self.sub_delay_menu.addSeparator()
        self.sub_delay_menu.addAction("自定义…", self._set_subtitle_delay_dialog, "Ctrl+G")
        self.sub_delay_menu.addAction("归零（恢复同步）", self._reset_subtitle_delay, "Ctrl+Shift+G")
        self.sub_delay_menu.addSeparator()
        self.sub_delay_menu.addAction("把当前偏移写入字幕文件", self._burn_subtitle_delay)
        self.audio_menu = vmenu.addMenu("音轨")
        aspect_sub = vmenu.addMenu("画面比例")
        for label, ratio in [("原始", ""), ("16:9", "16:9"), ("4:3", "4:3"),
                             ("21:9", "21:9"), ("填充", "0")]:
            aspect_sub.addAction(label, lambda r=ratio: self.player and self.player.set_aspect_ratio(r))
        vmenu.addAction("全屏", self.toggle_fullscreen, "F")
        vmenu.addAction("窗口置顶", self._toggle_on_top)
        vmenu.addAction("画中画（迷你置顶）", self._toggle_pip, "I")

        smenu = mb.addMenu("设置(&S)")
        self.dark_action = smenu.addAction("深色主题")
        self.dark_action.setCheckable(True)
        self.dark_action.setChecked(self.settings.theme == "dark")
        self.dark_action.triggered.connect(self._toggle_theme)
        smenu.addAction("偏好设置…", self._on_settings)
        smenu.addAction("清空播放历史", self._clear_history)

        hmenu = mb.addMenu("帮助(&H)")
        hmenu.addAction("激活 / 续期…", self._activate_license)
        hmenu.addAction("关于 / 授权…", self._about)

    def _rebuild_recent_menu(self):
        self.recent_menu.clear()
        for p in self.settings.recent[:15]:
            name = os.path.basename(p)
            a = QAction(name, self)
            a.setToolTip(p)
            a.triggered.connect(lambda _=False, p=p: self.open_path(p))
            self.recent_menu.addAction(a)
        if not self.settings.recent:
            self.recent_menu.setEnabled(False)
        else:
            self.recent_menu.setEnabled(True)

    # ---------------- 播放列表面板 ----------------
    def _build_playlist_dock(self):
        self.dock = QDockWidget("播放列表", self)
        self.dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.playlist_view = QListWidget()
        self.playlist_view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.playlist_view.itemDoubleClicked.connect(self._on_playlist_double)
        self.playlist_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.playlist_view.customContextMenuRequested.connect(self._playlist_context)
        self.dock.setWidget(self.playlist_view)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        if not self.settings.show_playlist:
            self.dock.hide()
        self._sync_playlist_view()

    def _sync_playlist_view(self):
        self.playlist_view.clear()
        for p in self.playlist.paths():
            self.playlist_view.addItem(os.path.basename(p))

    def _on_playlist_double(self, item):
        row = self.playlist_view.row(item)
        path = self.playlist.item_at(row)
        if path:
            self.open_path(path.path)

    def _playlist_context(self, pos):
        item = self.playlist_view.itemAt(pos)
        if not item:
            return
        row = self.playlist_view.row(item)
        menu = QMenu()
        play_a = menu.addAction("播放")
        del_a = menu.addAction("移除")
        open_a = menu.addAction("打开所在文件夹")
        menu.addSeparator()
        clear_a = menu.addAction("清空列表")
        act = menu.exec(self.playlist_view.mapToGlobal(pos))
        if act == play_a:
            it = self.playlist.item_at(row)
            if it:
                self.open_path(it.path)
        elif act == del_a:
            self.playlist.remove_at(row)
            self._sync_playlist_view()
        elif act == open_a:
            d = os.path.dirname(self.playlist.item_at(row).path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))
        elif act == clear_a:
            self.playlist.clear()
            self._sync_playlist_view()

    # ---------------- 打开 / 播放控制 ----------------
    def open_files(self, paths: List[str]):
        added = self.playlist.add_files(paths)
        self._sync_playlist_view()
        if added:
            if self.current_row < 0:
                self.open_path(added[0])

    def eventFilter(self, obj, ev):
        # 渲染子窗口被 libVLC 强行改成视频原始尺寸（或视频区自身随布局变化）时，
        # 把渲染子窗口重新铺满视频区。VLC 只在 vout 重建时改一次尺寸，不会拉锯。
        # _fitting 守卫避免「setGeometry → Resize → 再排 _fit」的 resize 风暴。
        if getattr(self, "_render_host", None) is not None and not getattr(self, "_fitting", False):
            if obj is self._render_host and ev.type() == QEvent.Resize:
                QTimer.singleShot(0, self._fit_render_host)
            elif obj is self.video_widget and ev.type() == QEvent.Resize:
                QTimer.singleShot(0, self._fit_render_host)
        return super().eventFilter(obj, ev)

    def _fit_render_host(self):
        host = getattr(self, "_render_host", None)
        if host is None:
            return
        self._fitting = True
        try:
            vw, vh = self.video_widget.width(), self.video_widget.height()
            if host.width() != vw or host.height() != vh:
                host.setGeometry(0, 0, vw, vh)
        finally:
            self._fitting = False

    def open_path(self, path: str, start_ms: int = 0):
        if not self.player:
            QMessageBox.warning(self, "无法播放",
                                "未检测到 VLC 运行库，请先安装 VLC 播放器。")
            return
        if not (path.startswith(("http://", "https://", "rtsp://", "rtmp://",
                                "udp://", "ftp://", "mms://"))) and not os.path.exists(path):
            QMessageBox.warning(self, "文件不存在", f"找不到文件：\n{path}")
            return
        # 绑定渲染窗口（首次）
        if not self._hwnd_set:
            try:
                self._fit_render_host()
                self.player.set_hwnd(int(self._render_host.winId()))
                self._hwnd_set = True
            except Exception:
                pass
        resume = start_ms
        if resume == 0 and self.settings.auto_resume:
            resume = get_position(path)
        self.player.open(path, resume)
        # 套用该片上次调好的字幕同步偏移（换片时清掉上一部的偏移）
        self.player.set_subtitle_delay(get_sub_delay(path))
        self.current_row = self.playlist.index_of_path(path)
        # 换片：实时字幕的挂载窗口作废（新片的 srt 是另一份文件）
        self._ai_live_cover_ms = 0
        if self.current_row < 0:
            # 不在列表里（例如拖进来的单个文件）：补进列表，
            # 否则 _current_path() 为空 → AI 字幕拿不到源文件、字幕也记不住
            try:
                self.playlist.add_files([path])
                self._sync_playlist_view()
                self.current_row = self.playlist.index_of_path(path)
            except Exception:
                pass
        if self.current_row >= 0:
            self.playlist_view.setCurrentRow(self.current_row)
        self.settings.add_recent(path)
        self.settings.save()
        self._rebuild_recent_menu()
        self.status_left.setText(os.path.basename(path))
        self.setWindowTitle(f"{os.path.basename(path)} — 万能视频播放器")
        # 1.2s 后刷新媒体信息
        QTimer.singleShot(1200, self._update_media_info)
        # 自动挂载同名字幕（AI 字幕生成过一次后，之后每次打开都秒出，不必重跑识别）
        # 立即挂一次，VLC 输入未就绪时内部按短间隔重试
        if self.settings.auto_subtitle:
            QTimer.singleShot(0, lambda p=path: self._auto_load_srt(p))

    def _auto_load_srt(self, path: str, attempt: int = 0) -> None:
        """打开视频时自动加载同目录同名字幕（优先双语 > 译文 > 原字幕）。

        这样 AI 字幕只需生成一次，之后每次播放直接复用，不用重新识别。
        打开就立刻挂（不等固定延迟）；VLC 输入还没建好时挂不上，
        就按 400/1200/2500ms 重试，最多 3 次。
        """
        if not self.player or self.current_row < 0:
            return
        if path.startswith(("http://", "https://", "rtsp://", "rtmp://",
                            "udp://", "ftp://", "mms://")):
            return
        try:
            item = self.playlist.item_at(self.current_row)
        except Exception:
            item = None
        # 列表里已记过字幕就用记过的，否则按文件名找
        saved = getattr(item, "subtitle", "") if item else ""
        if saved and os.path.isfile(saved):
            if self.player.add_subtitle(saved):
                return
            self._retry_auto_srt(path, attempt, "记住的字幕")
            return
        base = os.path.splitext(path)[0]
        # 同名多份字幕时取**修改时间最新**的：重新生成后不会被旧文件抢优先级
        suffixes = (".双语.srt", ".译文.srt", ".srt", ".zh.srt", ".en.srt")
        existing = []
        for s in suffixes:
            cand = base + s
            if os.path.isfile(cand):
                try:
                    existing.append((os.path.getmtime(cand), cand))
                except OSError:
                    pass
        if existing:
            existing.sort(reverse=True)
            cand = existing[0][1]
            if self.player.add_subtitle(cand):
                if item is not None:
                    self.playlist.set_subtitle(self.current_row, cand)
                return
            self._retry_auto_srt(path, attempt, os.path.basename(cand))
            return
        # 没有任何字幕文件且开了「换视频自动生成」→ 后台起一次 AI 识别
        if getattr(self.settings, "ai_auto_on_open", False):
            QTimer.singleShot(600, lambda p=path: self._auto_ai_subtitle(p))

    def _retry_auto_srt(self, path: str, attempt: int, what: str):
        """字幕没挂上（VLC 输入未就绪）→ 短间隔重试，最多 3 次。"""
        delays = (400, 1200, 2500)
        if attempt < len(delays):
            QTimer.singleShot(delays[attempt],
                              lambda: self._auto_load_srt(path, attempt + 1))
        else:
            self.statusBar().showMessage(f"字幕未挂载成功：{what}", 4000)

    def _has_srt(self, path: str) -> bool:
        base = os.path.splitext(path)[0]
        return any(os.path.isfile(base + s) for s in
                   (".双语.srt", ".译文.srt", ".srt", ".zh.srt", ".en.srt"))

    def _auto_ai_subtitle(self, path: str):
        """换视频后自动生成 AI 字幕（需设置里打开，且模型已就绪）。"""
        try:
            import ai_subtitle
            from ai_subtitle_ui import AiSubtitleWorker
        except Exception:
            return
        if not path or not os.path.isfile(path):
            return
        if self._has_srt(path):
            return                      # 已经有字幕就别白跑
        if self._ai_worker is not None and self._ai_worker.isRunning():
            return                      # 上一个还没跑完
        size = str(getattr(self.settings, "ai_model", "small（推荐，480MB）")).split("（")[0].strip()
        if not ai_subtitle.is_model_ready(size):
            self._ai_set_status(f"AI 模型 {size} 未下载，跳过自动生成")
            return
        src = ai_subtitle.WHISPER_LANGS.get(
            getattr(self.settings, "ai_src_lang", "中文"), "") or None
        dst = ai_subtitle.WHISPER_LANGS.get(
            getattr(self.settings, "ai_dst_lang", "不翻译"), "")
        bilingual = bool(getattr(self.settings, "ai_bilingual", True))
        base = os.path.splitext(path)[0]
        out = base + (".双语.srt" if (dst and bilingual) else
                      (".译文.srt" if dst else ".srt"))
        worker = AiSubtitleWorker(path, size, src, dst, bilingual, "auto", out, None,
                                  workers=int(getattr(self.settings, "ai_workers", 0) or 0),
                                  temp_fallback=bool(getattr(self.settings, "ai_temp_fallback", False)),
                                  chunk_seconds=(float(getattr(self.settings, "ai_chunk_seconds", 60) or 60)
                                                 if getattr(self.settings, "ai_chunk_live", True) else 0.0))
        self._ai_task_started(worker)

    def _play_pause(self):
        if not self.player:
            return
        if self.current_row < 0:
            return
        self.player.toggle()

    def _stop(self):
        if self.player:
            self.player.stop()
        self.progress.setValue(0)
        self.time_label.setText("00:00")
        self.duration_label.setText("00:00")

    def _next(self):
        nxt = self.playlist.next_index(self.current_row)
        if nxt >= 0:
            self.open_path(self.playlist.item_at(nxt).path)

    def _prev(self):
        prev = self.playlist.prev_index(self.current_row)
        if prev >= 0:
            self.open_path(self.playlist.item_at(prev).path)

    def _on_end(self):
        nxt = self.playlist.next_index(self.current_row)
        if nxt >= 0:
            self.open_path(self.playlist.item_at(nxt).path)
        else:
            self._stop()

    def _on_error(self, msg: str):
        self.status_left.setText("错误：" + msg)
        QMessageBox.warning(self, "播放错误", msg)

    def _on_length(self, length: int):
        if self.current_row >= 0 and length > 0:
            self.playlist.set_duration(self.current_row, length)

    # ---------------- 进度 / 音量 / 倍速 ----------------
    def _on_seek_moved(self, val: int):
        if self.player and self.player.get_length() > 0:
            self.time_label.setText(fmt_time(val / 100000 * self.player.get_length()))

    def _on_seek_released(self):
        if self.player:
            pos = self.progress.value() / 100000
            self.player.set_position(pos)
        self._seeking = False

    def _on_volume_changed(self, v: int):
        if self.player:
            self.player.set_volume(v)
            self.vol_btn.setIcon(self.icon_muted if self.player.is_muted() else self.icon_volume)
            self._show_osd(f"音量 {v}%" + ("（增强）" if v > 100 else ""))

    def _toggle_mute(self):
        if not self.player:
            return
        self.player.set_mute(not self.player.is_muted())
        muted = self.player.is_muted()
        self.vol_btn.setIcon(self.icon_muted if muted else self.icon_volume)
        self._show_osd("已静音" if muted else "取消静音")

    def _set_rate(self, r: float):
        if self.player:
            self.player.set_rate(r)
        self.rate_btn.setText(f"{r}x")
        self._show_osd(f"倍速 {r}x")

    def _step_rate(self, direction: int):
        """[ / ] 调整倍速；Backspace 恢复 1.0x。"""
        rates = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 3.0, 4.0]
        cur = self.player.get_rate() if self.player else 1.0
        if direction == 0:
            self._set_rate(1.0)
            return
        idx = 0
        for i, r in enumerate(rates):
            if abs(r - cur) < 0.001:
                idx = i
                break
        idx = max(0, min(len(rates) - 1, idx + direction))
        self._set_rate(rates[idx])

    def _frame_step(self):
        """逐帧步进（. 键）。"""
        if self.player:
            try:
                self.player.next_frame()
                self._show_osd("逐帧")
            except Exception:
                pass

    def _toggle_pip(self):
        """画中画：迷你置顶窗口，Esc / 再按 I 恢复原布局。"""
        if self.isFullScreen():
            return
        if not self._pip_active:
            self._pip_restore = (self.geometry(), self.dock.isVisible())
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            # 控制栏次要控件收起，保证 480px 能塞下
            self._pip_hidden = [w for w in (
                self.stop_btn, self.prev_btn, self.next_btn, self.rate_btn,
                self.loop_btn, self.ab_btn, self.snap_btn, self.list_btn,
                self.volume, self.duration_label) if w.isVisible()]
            for w_ in self._pip_hidden:
                w_.hide()
            self.progress.setMinimumWidth(60)
            if self.dock.isVisible():
                self.dock.hide()
            # 硬约束尺寸（布局最小宽度可能顶开窗口，画中画必须强制收紧）
            self.setFixedSize(min(480, self.width()), 320)
            self._pip_active = True
            self._show_osd("画中画：Esc 恢复")
        else:
            geo, dock_vis = self._pip_restore or (None, True)
            if geo is not None:
                self.setGeometry(geo)
            self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(self.settings.on_top))
            for w_ in getattr(self, "_pip_hidden", []):
                w_.show()
            self.progress.setMinimumWidth(200)
            if dock_vis:
                self.dock.show()
            # 解除画中画硬约束，恢复原几何
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            if geo is not None:
                self.setGeometry(geo)
            self._pip_active = False
        self.show()

    # ---------------- OSD ----------------
    def _show_osd(self, text: str):
        self.osd_label.setText(text)
        self.osd_label.adjustSize()
        vw = self.video_widget.width()
        vh = self.video_widget.height()
        self.osd_label.move(max(0, (vw - self.osd_label.width()) // 2),
                            max(0, vh // 2 - self.osd_label.height() - 30))
        self.osd_label.show()
        self.osd_label.raise_()
        self._osd_timer.start(1100)

    def _hide_osd(self):
        self.osd_label.hide()

    def _on_loop_changed(self, mode: str):
        self.playlist.loop_mode = mode
        self.settings.loop_mode = mode
        self.settings.save()
        label = {"order": "顺序", "repeat_one": "单曲",
                 "repeat_all": "列表", "shuffle": "随机"}[mode]
        self.loop_btn.setText(label)

    # ---------------- 字幕 / 音轨 ----------------
    def _on_tracks_updated(self):
        self._rebuild_track_menus()

    def _rebuild_track_menus(self):
        if not self.player:
            return
        # 字幕轨
        for a in list(self.sub_menu.actions())[5:]:
            self.sub_menu.removeAction(a)
        for tid, name in self.player.get_subtitle_tracks():
            a = QAction(f"字幕轨：{name}", self)
            a.triggered.connect(lambda _=False, t=tid: self.player.set_subtitle_track(t))
            self.sub_menu.addAction(a)
        # 音轨
        self.audio_menu.clear()
        for tid, name in self.player.get_audio_tracks():
            a = QAction(f"音轨：{name}", self)
            a.triggered.connect(lambda _=False, t=tid: self.player.set_audio_track(t))
            self.audio_menu.addAction(a)
        if not self.audio_menu.actions():
            self.audio_menu.addAction("(无可选音轨)").setEnabled(False)

    def _current_path(self) -> str:
        it = self.playlist.item_at(self.current_row) if self.current_row >= 0 else None
        return it.path if it else ""

    # ---------------- AI 字幕（识别人声 / 翻译） ----------------
    def _on_ai_subtitle(self):
        """打开 AI 字幕对话框：识别当前视频人声生成字幕，可选翻译。

        点「开始生成」后对话框立即关闭，任务转主窗口后台执行。
        """
        try:
            from ai_subtitle_ui import AiSubtitleDialog
        except Exception as e:
            QMessageBox.critical(self, "AI 字幕",
                                 f"AI 字幕模块未安装：{e}\n"
                                 f"请执行 pip install -r requirements.txt")
            return
        if self._ai_worker is not None and self._ai_worker.isRunning():
            QMessageBox.information(self, "AI 字幕",
                                    "已有识别任务在后台进行，请等它完成或先取消。")
            return
        dlg = AiSubtitleDialog(self._current_path(), self, self.settings)
        dlg.started.connect(self._ai_task_started)
        dlg.exec()

    def _ai_task_started(self, worker):
        """对话框移交后台任务：接管信号并启动线程。"""
        self._ai_worker = worker
        self._ai_media = worker.media
        self._ai_live_cover_ms = 0        # 新任务：实时字幕覆盖范围重新计
        worker.progress.connect(self._ai_progress)
        worker.partial.connect(self._ai_partial)
        worker.finished.connect(self._ai_finished)
        worker.failed.connect(self._ai_failed)
        worker.start()
        self._ai_set_status(f"AI 字幕 0% — {os.path.basename(worker.media)}")

    def _ai_set_status(self, text: str):
        """AI 进度写在独立状态栏格子里，换片/播放信息不会把它覆盖掉。"""
        self.status_ai.setText(text)

    def _ai_partial(self, segs, srt: str):
        """逐段实时字幕：一段识别完就刷新画面上的字幕，保证字幕一直存在。

        节流：libVLC 3.x 每挂一次字幕就多一条轨，所以只有当**已挂字幕覆盖不到
        当前播放位置 + 提前量**时才重挂（同路径重复挂会强制重读新内容）。
        """
        n = len(segs or [])
        cover_ms = int(max((getattr(s, "end", 0.0) for s in (segs or [])),
                           default=0.0) * 1000)
        cur = self._current_path()
        on_this = bool(self.player and cur and self._ai_media
                       and os.path.abspath(cur) == os.path.abspath(self._ai_media))
        if not on_this:
            self._ai_set_status(f"实时字幕已生成（{n} 条），后台继续识别…")
            return
        try:
            play_ms = int(self.player.get_time() or 0)
        except Exception:
            play_ms = 0
        if self._ai_live_cover_ms and self._ai_live_cover_ms >= play_ms + _AI_LIVE_AHEAD_MS:
            # 画面上已挂的字幕够用（覆盖到当前进度之后），不重复加轨
            self._ai_set_status(f"实时字幕 {n} 条（已覆盖后面 {int((cover_ms - play_ms) / 1000)}s），后台继续识别…")
            return
        ok = False
        try:
            # replace=False：同路径也强制重挂，让 VLC 重新读取更新后的内容
            ok = self.player.add_subtitle(srt, replace=False)
        except Exception:
            ok = False
        if ok:
            self._ai_live_cover_ms = max(cover_ms, self._ai_live_cover_ms)
        if n == 0:
            self._ai_set_status("已清掉画面上的旧字幕，等第一段识别出来…"
                                if ok else "AI 字幕启动中…")
        else:
            self._ai_set_status(
                f"实时字幕 {n} 条已挂载，后台继续识别…" if ok
                else f"实时字幕已生成（{n} 条），后台继续识别…")

    def _ai_progress(self, p: int, msg: str):
        tail = f" — {msg}" if msg else ""
        self._ai_set_status(f"AI 字幕 {p}%{tail}")

    def _ai_finished(self, res, srt: str):
        self._ai_worker = None
        self._ai_set_status("")
        # 实时分段挂的是同一路径的旧内容，必须重开媒体才能读到完整字幕
        self._ai_live_cover_ms = 0
        cur = self._current_path()
        same = (self.player and cur and self._ai_media
                and os.path.abspath(cur) == os.path.abspath(self._ai_media))
        if same:
            ok = self._mount_subtitle_fresh(srt)
            if ok:
                self.statusBar().showMessage(
                    f"AI 字幕已加载：{os.path.basename(srt)}", 5000)
            else:
                QMessageBox.warning(self, "AI 字幕", f"字幕已生成但加载失败：\n{srt}")
            return
        # 已经换了别的片：不打断播放，问要不要切回去
        r = QMessageBox.question(
            self, "AI 字幕",
            f"字幕已生成：\n{srt}\n\n"
            f"当前播放的是另一部片（{os.path.basename(cur) if cur else '未播放'}），"
            f"未自动挂载。\n是否切换到该视频并加载字幕？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r == QMessageBox.Yes and self._ai_media and os.path.exists(self._ai_media):
            self.open_path(self._ai_media)   # 打开时会自动挂最新的 srt

    def _ai_failed(self, msg: str):
        self._ai_worker = None
        if "已取消" in msg:
            # 用户主动取消不是错误：不弹窗，已识别的部分已保存在字幕文件里
            self._ai_set_status("AI 字幕已取消")
            self.statusBar().showMessage(
                "AI 字幕已取消（已识别部分已保存到字幕文件）", 5000)
            return
        self._ai_set_status("AI 字幕失败")
        QMessageBox.warning(self, "AI 字幕", msg)

    def _ai_cancel(self):
        w = self._ai_worker
        if w is not None and w.isRunning():
            w.cancel()
            self._ai_set_status("AI 字幕：正在取消…（当前段跑完即停，已识别部分保留）")
            self.statusBar().showMessage("正在停止 AI 字幕任务…", 4000)
        else:
            self.statusBar().showMessage("当前没有进行中的 AI 字幕任务", 3000)

    def _mount_subtitle_fresh(self, srt: str) -> bool:
        """生成/更换字幕后的**干净挂载**。

        libVLC 3.x 无法移除已存在的字幕轨：若当前媒体已挂着旧字幕（比如打开时
        自动加载的旧版本文件），直接重复挂会叠层、或因同路径去重而不刷新。
        处理：先记下播放进度 → 重开媒体（顺带清空旧轨）→ 回到原进度 → 挂新字幕。
        """
        cur = self._current_path()
        ok = False
        try:
            has_tracks = bool(self.player.get_subtitle_tracks())
            if has_tracks and cur and not cur.startswith(
                    ("http://", "https://", "rtsp://", "rtmp://",
                     "udp://", "ftp://", "mms://")):
                pos = max(0, self.player.get_time() - 300)
                self.player.open(cur, start_ms=pos)
                # 等媒体起来再挂字幕：太早挂不上（VLC 输入还没建好），失败就重试
                QTimer.singleShot(1200, lambda: self._try_add_subtitle(srt, 0))
                ok = True
            else:
                ok = self.player.add_subtitle(srt)
        except Exception:
            ok = False
        if self.current_row >= 0:
            self.playlist.set_subtitle(self.current_row, srt)
        return ok

    def _try_add_subtitle(self, srt: str, attempt: int) -> None:
        """重挂字幕（带重试）：媒体刚重开时 VLC 输入可能尚未就绪。"""
        if not self.player:
            return
        try:
            ok = self.player.add_subtitle(srt)
        except Exception:
            ok = False
        if not ok and attempt < 3:
            QTimer.singleShot(1500, lambda: self._try_add_subtitle(srt, attempt + 1))
        elif ok and attempt:
            self.statusBar().showMessage(f"字幕已重新加载：{os.path.basename(srt)}", 4000)

    def _on_ai_models(self):
        """模型管理：预下载 Whisper 模型 / 翻译包。"""
        try:
            from ai_subtitle_ui import AiModelManagerDialog
        except Exception as e:
            QMessageBox.critical(self, "AI 模型", f"模块未安装：{e}")
            return
        AiModelManagerDialog(self).exec()

    def _load_subtitle_file(self):
        if not self.player:
            return
        f, _ = QFileDialog.getOpenFileName(self, "选择字幕文件", "",
                                           "字幕 (*.srt *.ass *.ssa *.sub *.vtt *.smi)")
        if f:
            ok = self.player.add_subtitle(f)
            QMessageBox.information(self, "字幕",
                                    "已加载字幕" if ok else "字幕加载失败")

    # ---------------- 字幕同步（延迟，单位毫秒） ----------------
    def _adjust_subtitle_delay(self, delta_ms: int):
        """正=字幕延后出现（对白先响字后出），负=字幕提前出现。"""
        if not self.player:
            return
        cur = self.player.get_subtitle_delay()
        self._apply_subtitle_delay(cur + delta_ms)

    def _apply_subtitle_delay(self, ms: int):
        if not self.player:
            return
        self.player.set_subtitle_delay(ms)
        p = self._current_path()
        if p:
            set_sub_delay(p, int(ms))   # 记住该片的偏移，下次打开自动套用
        sign = "+" if ms >= 0 else ""
        self.status_left.setText(f"字幕延迟 {sign}{ms} ms")

    def _reset_subtitle_delay(self):
        self._apply_subtitle_delay(0)

    def _set_subtitle_delay_dialog(self):
        from PySide6.QtWidgets import QInputDialog
        cur = self.player.get_subtitle_delay() if self.player else 0
        val, ok = QInputDialog.getInt(
            self, "字幕同步", "延迟毫秒（负数=字幕提前，正数=字幕延后）：",
            cur, -60000, 60000, 50)
        if ok:
            self._apply_subtitle_delay(val)

    def _burn_subtitle_delay(self):
        """把当前偏移永久写进字幕文件（原文件备份为 .bak）。"""
        if not self.player:
            return
        ms = self.player.get_subtitle_delay()
        path = getattr(self.player, "_subtitle_path", "") or ""
        if not ms:
            QMessageBox.information(self, "字幕同步", "当前没有偏移，无需写入。")
            return
        if not path or not os.path.exists(path):
            QMessageBox.information(self, "字幕同步",
                                    "没有可写入的字幕文件（需先加载外部或 AI 生成的 srt）。")
            return
        try:
            from srt_util import shift_file
            shift_file(path, ms)   # 播放器延后 ms == 时间轴整体后移 ms
            self._apply_subtitle_delay(0)
            QMessageBox.information(
                self, "字幕同步",
                f"已把 {ms:+d} ms 写入字幕：\n{os.path.basename(path)}\n（原文件已备份 .bak）")
        except Exception as e:
            QMessageBox.warning(self, "字幕同步", f"写入失败：{e}")

    # ---------------- 截图 ----------------
    def _take_snapshot(self):
        if not self.player:
            return
        d = self.settings.default_screenshot_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = os.path.basename(self.status_left.text() or "snapshot")
        base = os.path.splitext(name)[0]
        ext = "jpg" if self.settings.snapshot_format == "jpg" else "png"
        path = os.path.join(d, f"{base}_{ts}.{ext}")
        ok = self.player.snapshot(path)
        if ok:
            self.status_left.setText(f"已截图：{os.path.basename(path)}")
        else:
            QMessageBox.warning(self, "截图失败",
                                "截图失败，请确认视频正在播放且已渲染画面。")

    # ---------------- 视图 ----------------
    def _toggle_playlist(self):
        if self.dock.isVisible():
            self.dock.hide()
            self.settings.show_playlist = False
        else:
            self.dock.show()
            self.settings.show_playlist = True
        self.settings.save()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _toggle_on_top(self):
        on = not self.windowFlags() & Qt.WindowStaysOnTopHint
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.settings.on_top = on
        self.settings.save()
        self.show()

    def _toggle_theme(self, checked: bool):
        self.settings.theme = "dark" if checked else "light"
        self.settings.save()
        apply_theme(QApplication.instance(), checked)

    # ---------------- 设置 / 历史 ----------------
    def _on_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec() == QDialog.Accepted:
            dlg.apply()
            if self.player:
                self.player.set_volume(self.settings.default_volume)
                self.player.set_rate(self.settings.default_rate)
            self._on_loop_changed(self.settings.loop_mode)
            self.loop_btn.setText({"order": "顺序", "repeat_one": "单曲",
                                   "repeat_all": "列表", "shuffle": "随机"}[self.settings.loop_mode])

    def _clear_history(self):
        from settings import save_history
        save_history({})
        self.settings.recent = []
        self.settings.save()
        self._rebuild_recent_menu()
        QMessageBox.information(self, "完成", "播放历史已清空。")

    # ---------------- 拖拽 / 快捷键 ----------------
    def handle_drop(self, urls: List[str]):
        media = [u for u in urls
                 if os.path.splitext(u)[1].lower() in (VIDEO_EXTS | SUB_EXTS)]
        subs = [u for u in urls
                if os.path.splitext(u)[1].lower() in SUB_EXTS]
        if media:
            self.open_files(media)
        elif subs and self.player and self.current_row >= 0:
            for s in subs:
                self.player.add_subtitle(s)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.handle_drop(urls)

    def keyPressEvent(self, event):
        k = event.key()
        if k == Qt.Key_Space or k == Qt.Key_K:
            self._play_pause()
        elif k == Qt.Key_Left or k == Qt.Key_J:
            if self.player:
                self.player.seek_relative(-10000)
                self._show_osd("◀ 快退 10s")
        elif k == Qt.Key_Right or k == Qt.Key_L:
            if self.player:
                self.player.seek_relative(10000)
                self._show_osd("快进 10s ▶")
        elif k == Qt.Key_Up:
            self.volume.setValue(min(self.volume.maximum(), self.volume.value() + 5))
        elif k == Qt.Key_Down:
            self.volume.setValue(max(0, self.volume.value() - 5))
        elif k == Qt.Key_M:
            self._toggle_mute()
        elif k == Qt.Key_F:
            self.toggle_fullscreen()
        elif k == Qt.Key_S:
            self._take_snapshot()
        elif k == Qt.Key_BracketLeft:
            self._step_rate(-1)
        elif k == Qt.Key_BracketRight:
            self._step_rate(1)
        elif k == Qt.Key_Backspace:
            self._step_rate(0)
        elif k == Qt.Key_Period:
            self._frame_step()
        elif k == Qt.Key_I and not self._osd_label.isVisible():
            self._toggle_pip()
        elif k == Qt.Key_Escape:
            if self._pip_active:
                self._toggle_pip()
            elif self.isFullScreen():
                self.showNormal()
        elif k == Qt.Key_N or k == Qt.Key_PageDown:
            self._next()
        elif k == Qt.Key_P or k == Qt.Key_PageUp:
            self._prev()
        elif event.text().isdigit():
            d = int(event.text())
            if self.player:
                self.player.set_position(d / 10.0)
        else:
            super().keyPressEvent(event)

    # ---------------- 打开对话框 ----------------
    def _on_open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "打开媒体文件", "",
            "媒体文件 (*" + " *".join(sorted(VIDEO_EXTS | SUB_EXTS)) + ");;所有文件 (*.*)")
        if files:
            self.open_files(files)

    def _on_open_folder(self):
        d = QFileDialog.getExistingDirectory(self, "打开文件夹（自动收集媒体）")
        if d:
            self.open_files([d])

    def _on_open_url(self):
        dlg = UrlDialog(self)
        if dlg.exec() == QDialog.Accepted and dlg.url():
            self.open_path(dlg.url())

    # ---------------- 续播 / 关闭 ----------------
    def _restore_last_session(self):
        hist = load_history()
        plist = hist.get("_last_playlist", [])
        plist = [p for p in plist if p and os.path.exists(p)]
        if plist and self.settings.start_with_last_list:
            self.open_files(plist)
            last = hist.get("_last_position", {})
            if last.get("path") and self.settings.auto_resume:
                self.open_path(last["path"], last.get("position_ms", 0))

    def _update_media_info(self, retry: int = 1):
        if not self.player:
            return
        info = self.player.media_info()
        parts = []
        if info["width"] and info["height"]:
            parts.append(f"{info['width']}x{info['height']}")
        if info["fps"]:
            parts.append(f"{info['fps']}fps")
        if info["vcodec"]:
            parts.append(info["vcodec"])
        if info["acodec"]:
            parts.append("音:" + info["acodec"])
        self.status_mid.setText("  ".join(parts))
        self._rebuild_track_menus()
        # 慢解析容器（MPEG-TS、部分网络流）首轮可能拿不到分辨率 → 延迟重试一次
        if (not info["width"] or not info["height"]) and retry > 0:
            QTimer.singleShot(3000, lambda: self._update_media_info(0))

    def _update_ui(self):
        if not self.player:
            return
        try:
            if not self._seeking and self.player.get_length() > 0:
                self.progress.setValue(int(self.player.get_position() * 100000))
            t, l = self.player.get_time(), self.player.get_length()
            self.time_label.setText(fmt_time(t))
            self.duration_label.setText(fmt_time(l))
            self.play_btn.setIcon(
                self.icon_pause if self.player.is_playing() else self.icon_play)
            self.vol_btn.setIcon(
                self.icon_muted if self.player.is_muted() else self.icon_volume)
            d = self.player.get_subtitle_delay()
            self.status_sub.setText(f"字幕 {d:+d}ms" if d else "")
        except Exception:
            # libVLC 偶发异常（媒体切换/释放瞬间）不能让整个程序崩掉
            pass

    def _on_ab(self):
        if not self.player:
            return
        if self._ab_state == 0:
            self._ab_a = self.player.get_time()
            self._ab_state = 1
            self.ab_btn.setText("A●")
            self._show_osd(f"A-B：起点 {fmt_time(self._ab_a)}（再点一次设终点）")
        elif self._ab_state == 1:
            b = self.player.get_time()
            if self._ab_a is not None and b > self._ab_a + 500:
                self.player.set_ab_loop(self._ab_a, b)
                self._ab_state = 2
                self.ab_btn.setText("AB●")
                self._show_osd(f"A-B 循环：{fmt_time(self._ab_a)} ~ {fmt_time(b)}")
            else:
                self._ab_a = None
                self._ab_state = 0
                self.ab_btn.setText("A-B")
        else:
            self.player.clear_ab_loop()
            self._ab_a = None
            self._ab_state = 0
            self.ab_btn.setText("A-B")
            self._show_osd("A-B 循环已取消")

    def _about(self):
        dlg = about_dialog.AboutDialog(self, on_activated=self._refresh_license_status)
        dlg.exec()

    # ---------------- 授权门禁 ----------------
    def _refresh_license_status(self):
        """按当前授权状态刷新状态栏右侧（激活/续期成功后调用）。"""
        st = license_gate.status_text()
        if st["valid"]:
            self.status_right.setText(f"{st['state']} · 剩余 {st['days']}")
        else:
            self.status_right.setText("授权已过期 · 请在 帮助→激活/续期 续期")

    def _license_gate(self):
        """启动授权检查：无效/过期弹激活窗，拒绝激活则退出。"""
        res = license_gate.startup_check()
        if res["valid"]:
            self._refresh_license_status()
            if res["days"] <= 3:
                self.status_right.setText(
                    f"⚠️ 授权仅剩 {res['days']} 天，请在 帮助→激活/续期 续期")
            return
        while not license_gate.is_valid():
            dlg = about_dialog.ActivateDialog(self)
            if dlg.exec() != QDialog.Accepted:
                # 拒绝激活 → 退出（与母版门禁一致，过期不放行）
                QTimer.singleShot(0, self.close)
                return
        self._refresh_license_status()

    def _activate_license(self):
        dlg = about_dialog.ActivateDialog(self)
        dlg.exec()
        self._refresh_license_status()

    def closeEvent(self, event):
        # 关键：先停掉刷新定时器再释放 libVLC。
        # 否则 release() 之后定时器仍会调用 get_length() →
        # 访问已释放对象 → OSError: access violation（进程直接崩）。
        try:
            self._ui_timer.stop()
            self._seek_timer.stop() if hasattr(self, "_seek_timer") else None
        except Exception:
            pass
        # 关闭时若 AI 字幕后台线程还在跑：先取消，避免线程随窗口销毁崩溃
        w = getattr(self, "_ai_worker", None)
        if w is not None and w.isRunning():
            try:
                w.cancel()
                w.wait(3000)
            except Exception:
                pass
        self._ai_worker = None
        if self.player:
            # 保存进度与列表
            if self.current_row >= 0 and self.settings.auto_resume:
                try:
                    update_history(
                        self.playlist.item_at(self.current_row).path,
                        self.player.get_time(), self.player.get_length(),
                        self.playlist.paths())
                except Exception:
                    pass
            self.player.release()
            self.player = None
        self.settings.save()
        event.accept()
