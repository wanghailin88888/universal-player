import ctypes, ctypes.wintypes as wt, os, time
from PIL import ImageGrab
user32 = ctypes.windll.user32
target=None
def _enum(h,_):
    global target
    if user32.IsWindowVisible(h):
        n=user32.GetWindowTextLengthW(h)
        if n:
            b=ctypes.create_unicode_buffer(n+1); user32.GetWindowTextW(h,b,n+1)
            if "万能视频播放器" in b.value: target=h
    return True
P=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
user32.EnumWindows(P(_enum),0)
user32.SetForegroundWindow(target)
time.sleep(0.3)
user32.PostMessageW(target,0x0100,0x1B,0)  # WM_KEYDOWN ESC
user32.PostMessageW(target,0x0101,0x1B,0)  # WM_KEYUP ESC
time.sleep(0.5)
r=wt.RECT(); user32.GetWindowRect(target,ctypes.byref(r))
img=ImageGrab.grab(bbox=(max(r.left,0),max(r.top,0),r.right,r.bottom),all_screens=True)
img.save(os.path.abspath("tools/live_shot2.png"))
print("OK")
