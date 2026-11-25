"""单实例守卫（Windows 命名互斥体 + WM_COPYDATA 文件转发）。

设计要点：
1. 用 Windows 命名互斥体判重——进程崩溃/被杀时内核自动释放句柄，
   不会像锁文件那样残留"假锁"把用户挡在门外。
2. 第二个实例启动时不做"静默退出"，而是把命令行传入的文件列表通过
   WM_COPYDATA 发给已在运行的实例，并把它激活到前台；老实例收到后
   直接 open_files() 播新文件——用户双击第二个视频时体验是连续的。
3. 仅在 Windows 生效；其它平台直接放行（后续需要可换 QSharedMemory）。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import sys
from typing import List, Optional

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray

ERROR_ALREADY_EXISTS = 183
WM_COPYDATA = 0x004A
SW_RESTORE = 9

# 命名互斥体：Local\ 命名空间对本机单用户场景足够（Global\ 需要提权，
# 标准用户会 ACCESS_DENIED）。
MUTEX_NAME = "Local\\UniversalPlayer_SingleInstance_Mutex"

# —— 关键修复：显式声明 CreateMutexW 并启用 use_last_error ——
# ctypes 默认 restype=c_int 会截断 64 位 HANDLE；且默认 use_last_error=False
# 时 ctypes 会在调用后恢复调用者的 last error，导致 ctypes.GetLastError() 读不到
# ERROR_ALREADY_EXISTS —— 这会让 already_running 恒为 False、单实例失效、可多开。
# 显式声明可在所有环境稳健地判重。
_CreateMutexW = ctypes.WINFUNCTYPE(
    wintypes.HANDLE, wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR,
    use_last_error=True,
)(("CreateMutexW", ctypes.windll.kernel32))


def _create_named_mutex(name: str):
    """创建/打开命名互斥体，返回 (handle, already_running)。

    handle 为 None 表示调用失败（already_running 同时 False，按放行处理）。
    """
    handle = _CreateMutexW(None, False, name)
    if not handle:
        return None, False
    already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    if already:
        ctypes.windll.kernel32.CloseHandle(handle)
        return None, True
    return handle, False



class _COPYDATASTRUCT(ctypes.Structure):
    _fields_ = [
        ("dwData", ctypes.c_ulong),
        ("cbData", ctypes.c_ulong),
        ("lpData", ctypes.c_void_p),
    ]


def _find_window_by_title() -> int:
    """枚举顶层窗口，找标题含「万能视频播放器」的第一个可见窗口。"""
    user32 = ctypes.windll.user32
    found = 0

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        nonlocal found
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if "万能视频播放器" in buf.value:
            found = hwnd
            return False  # 停止枚举
        return True

    user32.EnumWindows(_cb, 0)
    return found


def _activate_window(hwnd: int) -> None:
    """还原（如最小化）并激活已有窗口。"""
    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    # 经典 trick：先 attach 再 SetForegroundWindow，绕过前台锁
    kernel32 = ctypes.windll.kernel32
    cur = kernel32.GetCurrentThreadId()
    fg = user32.GetWindowThreadProcessId(hwnd, None)
    if cur != fg:
        user32.AttachThreadInput(cur, fg, True)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(cur, fg, False)
    else:
        user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)


class NativeMessageReceiver(QAbstractNativeEventFilter):
    """老实例侧：接收 WM_COPYDATA 并把文件列表转给回调。"""

    def __init__(self, on_files):
        super().__init__()
        self._on_files = on_files

    def nativeEventFilter(self, eventType, message):  # noqa: N802 (Qt 风格)
        if eventType != "windows_generic_MSG":
            return False, 0
        try:
            msg = ctypes.wintypes.MSG.from_address(int(message))
        except Exception:
            return False, 0
        if msg.message != WM_COPYDATA:
            return False, 0
        try:
            cds = _COPYDATASTRUCT.from_address(msg.lParam)
            if not cds.lpData or cds.cbData <= 0:
                return True, 0
            raw = ctypes.string_at(cds.lpData, cds.cbData)
            # 约定：UTF-8 编码的 '\0' 分隔路径列表
            text = raw.decode("utf-8", errors="replace")
            paths = [p for p in text.split("\0") if p]
            if paths:
                self._on_files(paths)
        except Exception:
            pass
        return True, 0


class SingleInstance:
    """进程生命周期内持有一个命名互斥体句柄。"""

    def __init__(self, name: str = MUTEX_NAME):
        self._name = name
        self._handle = None
        self.already_running = False

        if os.name != "nt":
            return  # 非 Windows 暂不拦截

        handle, already = _create_named_mutex(self._name)
        if handle is None:
            if already:
                self.already_running = True
            # 创建失败（非重复）时保持放行，不挡用户
        else:
            self._handle = handle

    def send_to_existing(self, paths: List[str]) -> bool:
        """把路径列表发给已有实例，成功返回 True。"""
        if not paths:
            return False
        hwnd = _find_window_by_title()
        if not hwnd:
            return False
        payload = "\0".join(paths).encode("utf-8")
        buf = ctypes.create_string_buffer(payload)  # 自带 '\0' 结尾
        cds = _COPYDATASTRUCT(1, len(payload) + 1, ctypes.cast(buf, ctypes.c_void_p))
        user32 = ctypes.windll.user32
        result = user32.SendMessageW(hwnd, WM_COPYDATA, None, ctypes.byref(cds))
        _activate_window(hwnd)
        return True

    def activate_existing(self) -> None:
        hwnd = _find_window_by_title()
        if hwnd:
            _activate_window(hwnd)

    def release(self) -> None:
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None
