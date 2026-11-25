"""入口：解析命令行媒体参数并启动万能视频播放器。"""
from __future__ import annotations

import os
import sys


def _setup_stdio():
    """console=False 打包后没有控制台，sys.stdout/stderr 可能是 None
    （任何 print / tqdm / 日志写入都会报 'NoneType' object has no attribute
    'write'，实测 HF 模型下载必踩）或指向无效句柄。

    打包运行时一律重定向到程序目录 _player.log：既防崩溃，又解决无控制台盲调。
    """
    if not getattr(sys, "frozen", False):
        return
    try:
        from resources import app_dir
        log = os.path.join(app_dir(), "_player.log")
        if sys.stdout is None:
            sys.stdout = open(log, "a", buffering=1, encoding="utf-8",
                              errors="replace")
        if sys.stderr is None:
            sys.stderr = open(log, "a", buffering=1, encoding="utf-8",
                              errors="replace")
    except Exception:
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
        except Exception:
            pass


_setup_stdio()


def _extract_bundled_vlc():
    """单文件 exe 内置的 VLC 以单个 zip 形式分发。

    PyInstaller 单文件对 364 个 VLC 文件的解压在本机实测不可靠（_MEIPASS 下整棵
    vlc 目录缺失），故改为：把 VLC 压成 vlc_bundle.zip 随 exe 分发，启动时由本函数
    自行解压这一个 zip 到持久临时目录，并把 VLC_DIR / dll 搜索路径指过去。

    必须在 import vlc_player 之前调用，使模块级的 _bootstrap_vlc() 能立即找到 VLC_DIR。
    仅在冻结（frozen）运行时生效；开发态/onedir 走各自的系统或便携路径。
    """
    if not getattr(sys, "frozen", False):
        return
    try:
        import zipfile
        import tempfile
        import shutil
        from resources import app_dir

        base = getattr(sys, "_MEIPASS", app_dir())
        zsrc = os.path.join(base, "vlc_bundle", "vlc_bundle.zip")
        if not os.path.isfile(zsrc):
            zsrc = os.path.join(app_dir(), "tools", "vlc_bundle.zip")
        if not os.path.isfile(zsrc):
            return

        dest = os.path.join(tempfile.gettempdir(), "universal_player_vlc")
        marker = os.path.join(dest, ".extracted")
        vlc_dir = os.path.join(dest, "vlc-3.0.24")
        if not os.path.isfile(marker) or not os.path.isfile(
                os.path.join(vlc_dir, "libvlc.dll")):
            if os.path.isdir(dest):
                shutil.rmtree(dest, ignore_errors=True)
            os.makedirs(dest, exist_ok=True)
            with zipfile.ZipFile(zsrc) as z:
                z.extractall(dest)
            try:
                open(marker, "w").close()
            except Exception:
                pass
        if os.path.isfile(os.path.join(vlc_dir, "libvlc.dll")):
            os.environ["VLC_DIR"] = vlc_dir
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(vlc_dir)
                except Exception:
                    pass
            plugins = os.path.join(vlc_dir, "plugins")
            if os.path.isdir(plugins):
                os.environ["VLC_PLUGIN_PATH"] = plugins
    except Exception as e:
        try:
            sys.stderr.write(f"[vlc-bundle] extract failed: {e}\n")
        except Exception:
            pass


_extract_bundled_vlc()

from PySide6.QtCore import QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from main_window import MainWindow
from resources import asset_path
from settings import Settings
from single_instance import NativeMessageReceiver, SingleInstance
from theme import apply_theme


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("万能视频播放器")
    app.setOrganizationName("UniversalPlayer")
    app.setOrganizationDomain("universal-player.local")
    app.setWindowIcon(QIcon(asset_path("app.ico")))
    # 界面主题（深色默认，偏好设置可切换并记忆）
    apply_theme(app, Settings.load().theme == "dark")

    # 解析命令行传入的媒体文件 / file:// 链接
    files = []
    for a in sys.argv[1:]:
        if a.startswith("-"):
            continue
        if a.startswith("file://"):
            a = QUrl(a).toLocalFile()
        files.append(a)
    files = [f for f in files if f]

    # 单实例守卫：已有实例在跑时，把命令行文件转交给它并激活其窗口，自身退出
    si = SingleInstance()
    if si.already_running:
        if not si.send_to_existing(files):
            si.activate_existing()
        return 0

    window = MainWindow(files if files else None)

    # 老实例侧：接收第二个实例转交来的文件列表（WM_COPYDATA）
    receiver = NativeMessageReceiver(window.open_files)
    app.installNativeEventFilter(receiver)
    # 防止被 GC；退出时一并释放互斥体
    app._si = si
    app._si_receiver = receiver
    app.aboutToQuit.connect(si.release)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
