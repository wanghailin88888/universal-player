"""关于/授权功能冒烟测试：授权逻辑全链路 + 三个弹窗 offscreen 截图。

用法: QT_QPA_PLATFORM=offscreen python tools/smoke_about.py
"""
from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import license as lic  # noqa: E402

# 存储指向临时文件，不污染真实授权数据
TMP = tempfile.mkdtemp(prefix="up_license_")
lic.LICENSE_FILE = os.path.join(TMP, "license.json")

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402

app = QApplication(sys.argv)

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


# ---------- 1. 授权逻辑 ----------
res = lic.startup_check()
check("首次启动自动创建30天试用", res["valid"] and res["created_trial"])
st = lic.status_text()
check("试用状态/剩余天数", st["state"] == "试用中" and "30" in st["days"] or "29" in st["days"])
check("通用码规则(>=12位含2数字)", lic.verify_code("abcd1234efgh56")["valid"])
check("弱码拒绝", not lic.verify_code("short1")["valid"])
check("错误管理码拒绝", not lic.verify_code("HELLO-WORLD-XX")["valid"])

item = lic.generate_code(365, "测试VIP")
r1 = lic.activate(item["code"])
check("管理员生成码首次激活成功", r1["valid"] and r1["days"] == 365)
r2 = lic.verify_code(item["code"])
check("一码一用:二次使用被拒", not r2["valid"])
check("激活后状态=已授权", lic.status_text()["state"] == "已授权")
check("管理密码校验", lic.check_admin_pwd(lic.ADMIN_PWD) and not lic.check_admin_pwd("no"))
check("非管理员设备", not lic.is_admin_device())

# ---------- 2. UI 截图 ----------
OUT = os.path.join(HERE, "_smoke_about_out")
os.makedirs(OUT, exist_ok=True)
import about_dialog as ad  # noqa: E402

about = ad.AboutDialog()
about.resize(560, 780)
about.show()
about.refresh_status()


def shot():
    about.grab().save(os.path.join(OUT, "about.png"))

    act = ad.ActivateDialog()
    act.show()
    act.grab().save(os.path.join(OUT, "activate.png"))

    panel = ad.AdminPanelDialog()  # 跳过密码框直接验证面板
    panel.show()
    panel._gen()
    panel.grab().save(os.path.join(OUT, "admin.png"))

    for f in ["about.png", "activate.png", "admin.png"]:
        p = os.path.join(OUT, f)
        check(f"截图 {f}", os.path.exists(p) and os.path.getsize(p) > 1500)

    fails = [n for n, ok in results if not ok]
    print(f"\n==== {len(results) - len(fails)}/{len(results)} PASS ====")
    if fails:
        print("FAILED:", fails)
    app.quit()


QTimer.singleShot(400, shot)
app.exec()
sys.exit(1 if any(not ok for _, ok in results) else 0)
