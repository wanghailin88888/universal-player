import ctypes, ctypes.wintypes as wt, os, sys
from PIL import ImageGrab
user32 = ctypes.windll.user32
target = None
def _enum(hwnd, lParam):
    global target
    if user32.IsWindowVisible(hwnd):
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n+1)
            user32.GetWindowTextW(hwnd, buf, n+1)
            if "万能视频播放器" in buf.value:
                target = hwnd
    return True
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
user32.EnumWindows(EnumWindowsProc(_enum), 0)
if not target:
    print("NO_WINDOW"); sys.exit(1)
r = wt.RECT()
user32.GetWindowRect(target, ctypes.byref(r))
print("RECT", r.left, r.top, r.right, r.bottom)
try:
    user32.SetForegroundWindow(target)
except Exception:
    pass
box = (max(r.left,0), max(r.top,0), r.right, r.bottom)
img = ImageGrab.grab(bbox=box, all_screens=True)
out = os.path.abspath("tools/live_shot.png")
os.makedirs("tools", exist_ok=True)
img.save(out)
print("SAVED", out, img.size)
