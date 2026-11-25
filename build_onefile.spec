# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包脚本：单文件 exe（onefile，禁用 UPX，无控制台）
#
# 用法: pyinstaller build_onefile.spec
# 产出: dist/万能视频播放器.exe （单文件，可直接拷走使用）
#
# 说明：onefile 每次运行会把依赖解压到临时目录，首次启动比 onedir 慢几秒；
#       优势是只有一个文件，方便传播/拷给别人。要最快的启动速度请用 build.spec（文件夹版）。
import os
import sys

from PyInstaller.utils.hooks import collect_data_files

_zhconv_datas = collect_data_files('zhconv')

# 定位 venv 的 site-packages（faster-whisper / imageio-ffmpeg 的数据文件需显式打包，
# 这两个库都没有 PyInstaller 收集钩子，否则单文件 exe 解压后缺数据文件 → 目标机 AI 字幕失效）
_site = os.path.join(sys.prefix, 'Lib', 'site-packages')

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('assets/app.ico', 'assets'),
        ('assets/app.png', 'assets'),
        ('assets/qrcode.jpg', 'assets'),   # 关于页「支持作者」收款码
        # 内嵌 VLC 运行库：压成单个 zip 随 exe 分发，启动时任程序自行解压到临时目录
        # （PyInstaller 单文件对 364 个 VLC 文件解压不可靠，单 zip 解压稳定）。
        # 见 main.py _extract_bundled_vlc()。
        ('tools/vlc_bundle.zip', 'vlc_bundle'),
        # faster-whisper 的 VAD 模型（vad.py 通过 get_assets_path() 在包内 assets/ 查找）
        (os.path.join(_site, 'faster_whisper', 'assets', 'silero_vad_v6.onnx'), 'faster_whisper/assets'),
        # 音频抽取用的 ffmpeg 二进制（imageio_ffmpeg 用 importlib.resources 在包内 binaries/ 查找）
        (os.path.join(_site, 'imageio_ffmpeg', 'binaries', 'ffmpeg-win-x86_64-v7.1.exe'), 'imageio_ffmpeg/binaries'),
    ] + _zhconv_datas,
    hiddenimports=[
        'vlc', 'settings', 'playlist', 'vlc_player', 'main_window',
        'zhconv', 'license', 'about_dialog', 'resources',
        'ai_subtitle', 'ai_parallel', 'ai_subtitle_ui',
        'srt_util', 'tools_esc', 'tools_shot', 'single_instance', 'theme',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 体积优化：本项目完全用不到的重型依赖
        'torch', 'tensorflow', 'scipy', 'pandas', 'matplotlib',
        'notebook', 'IPython', 'PyQt5', 'pytest', 'PIL.ImageQt',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='万能视频播放器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # 与文件夹版保持一致：UPX 会触发 ucrtbase.dll 权限错
    console=False,           # GUI 模式（无黑框），排错时改成 True 看 traceback
    icon='assets/app.ico',
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
