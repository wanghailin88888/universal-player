"""资源路径助手：兼容源码运行与 PyInstaller 打包（_MEIPASS）。"""
from __future__ import annotations

import os
import sys


def app_dir() -> str:
    """程序所在目录（真实落盘位置）。

    onefile 打包时 __file__ 指向临时解压目录（_MEIPASS），models/、便携 VLC
    等"放在程序旁边"的数据必须按 exe 所在目录定位，否则模型会下到临时目录
    （每次运行丢失）、便携 VLC 也找不到。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def asset_path(name: str) -> str:
    """返回 assets/ 下资源文件的绝对路径。

    PyInstaller onefile/onedir 下资源在 sys._MEIPASS；源码运行在包目录 assets/。
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", name)
