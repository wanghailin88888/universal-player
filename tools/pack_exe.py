"""把 onefile 成品打包发布到工作区 release/ 目录。

用法: python tools/pack_exe.py
产出: ../../release/万能视频播放器-单文件-v1.3.exe
"""
from __future__ import annotations

import os
import shutil
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RELEASE = os.path.normpath(os.path.join(ROOT, "..", "release"))

SRC = os.path.join(ROOT, "dist_a", "万能视频播放器.exe")
DST_NAME = "万能视频播放器-单文件-v1.4.0.exe"


def main() -> int:
    if not os.path.isfile(SRC):
        print("MISSING: 先执行 pyinstaller build_onefile.spec")
        return 1
    os.makedirs(RELEASE, exist_ok=True)
    dst = os.path.join(RELEASE, DST_NAME)
    shutil.copy2(SRC, dst)

    size = os.path.getsize(dst)
    crc = 0
    with open(dst, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            crc = zlib.crc32(chunk, crc)
    print(f"OUT : {dst}")
    print(f"SIZE: {size / 1024 / 1024:.1f} MB")
    print(f"CRC32: {crc & 0xFFFFFFFF:08X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
