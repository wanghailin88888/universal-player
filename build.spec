# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包脚本（onedir 文件夹模式，禁用 UPX，无控制台）
# 用法: pyinstaller build.spec
import os

block_cipher = None

# zhconv 繁简转换词典是数据文件，PyInstaller 不会自动收集
from PyInstaller.utils.hooks import collect_data_files
_zhconv_datas = collect_data_files('zhconv')

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('assets/app.ico', 'assets'),
        ('assets/app.png', 'assets'),
        ('assets/qrcode.jpg', 'assets'),   # 关于页「支持作者」收款码
        # 内嵌 VLC 运行库，让文件夹版也无需本机安装 VLC 即可运行
        ('tools/vlcportable/vlc-3.0.24', 'vlc'),
    ] + _zhconv_datas,
    hiddenimports=['vlc', 'settings', 'playlist', 'vlc_player', 'main_window', 'zhconv', 'single_instance', 'theme'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='万能视频播放器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='assets/app.ico',
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='万能视频播放器',
)
