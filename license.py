"""万能视频播放器 —— 授权门禁（LicenseGate）。

移植自「猎豹盯盘 / 股票多周期共振」js/license.js 同一套授权体系：
  1) 试用 30 天 + 首次安装时间戳（配置目录持久化，重装不刷期）
  2) 激活码本地离线校验：
       - 管理员码（ADMIN_CODES）→ 长期授权（并解锁管理后台入口）
       - 本地生成的 RADAR-XXXX-XXXX-XXXX → 一码一用，有效期由生成时设定
       - 通用码（≥12 位且含 ≥2 个数字）→ 30 天
  3) 管理后台（管理密码保护）可本地生成授权码
  4) 授权到期 → 引导联系作者续期

存储：用户配置目录 license.json（与 settings.json 同目录）。
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from typing import Dict, List, Optional

from settings import _config_dir

APP_NAME = "万能视频播放器"
APP_VERSION = "1.3.1"
TRIAL_DAYS = 30
ADMIN_PWD = "ccim7jiu"
ADMIN_CODES = ["LIN-BOSS-8888", "PLAYER-VIP-2026"]
CONTACT = {"name": "林老板", "qq": "1679253880"}

LICENSE_FILE = _config_dir() / "license.json"
RADAR_RE = re.compile(r"^RADAR-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")


def _load() -> Dict:
    try:
        if os.path.exists(str(LICENSE_FILE)):
            with open(LICENSE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save(data: Dict):
    try:
        with open(LICENSE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------- 授权状态 ----------------
def get_license() -> Optional[Dict]:
    return _load().get("license")


def _set_license(lic: Dict):
    data = _load()
    data["license"] = lic
    _save(data)


def get_first_install() -> Optional[int]:
    return _load().get("first_install")


def _set_first_install(ts: int):
    data = _load()
    data["first_install"] = ts
    _save(data)


def get_admin_list() -> List[Dict]:
    return _load().get("admin_codes", [])


def _set_admin_list(lst: List[Dict]):
    data = _load()
    data["admin_codes"] = lst
    _save(data)


def days_left(lic: Optional[Dict] = None) -> int:
    lic = lic if lic is not None else get_license()
    if not lic or not lic.get("expires_at"):
        return -1
    return int((lic["expires_at"] - time.time() * 1000) // 86400000) + (
        1 if (lic["expires_at"] - time.time() * 1000) % 86400000 else 0)


def is_valid(lic: Optional[Dict] = None) -> bool:
    return days_left(lic) > 0


def is_admin_device(lic: Optional[Dict] = None) -> bool:
    lic = lic if lic is not None else get_license()
    if not lic or lic.get("type") == "trial":
        return False
    code = str(lic.get("code", "")).upper()
    return any(c.upper() == code for c in ADMIN_CODES)


# ---------------- 校验 / 激活 ----------------
def verify_code(code: str) -> Dict:
    """本地离线校验激活码，返回 {valid, ...}。"""
    code = (code or "").strip()
    if not code:
        return {"valid": False, "msg": "请输入授权码"}
    if code.upper() in (c.upper() for c in ADMIN_CODES):
        return {"valid": True, "code": code, "type": "license",
                "days": 36500, "note": "管理员授权"}
    if RADAR_RE.match(code.upper()):
        for item in get_admin_list():
            if item.get("code", "").upper() == code.upper():
                if item.get("used"):
                    return {"valid": False, "msg": "授权码已被使用，请联系管理员"}
                return {"valid": True, "code": item["code"], "type": "license",
                        "days": item.get("days", 30),
                        "note": item.get("note") or "管理员生成"}
        return {"valid": False, "msg": "授权码无效或已不存在"}
    if len(code) >= 12 and len(re.findall(r"\d", code)) >= 2:
        return {"valid": True, "code": code, "type": "license",
                "days": 30, "note": "通用授权码"}
    return {"valid": False, "msg": "授权码无效"}


def _mark_used(code: str):
    lst = get_admin_list()
    for item in lst:
        if item.get("code", "").upper() == code.upper():
            item["used"] = True
            item["used_at"] = int(time.time())
            _set_admin_list(lst)
            return


def create_trial() -> Dict:
    """创建/恢复试用期：首次安装时间戳防重装刷期。"""
    now_ms = int(time.time() * 1000)
    fi = get_first_install()
    start = fi or now_ms
    lic = {"code": "TRIAL", "type": "trial", "activated_at": start,
           "expires_at": start + TRIAL_DAYS * 86400000, "days": TRIAL_DAYS}
    _set_license(lic)
    if not fi:
        _set_first_install(now_ms)
    return lic


def activate(code: str) -> Dict:
    """校验并写入授权，一码一用的码同时标记已用。返回校验结果。"""
    res = verify_code(code)
    if res.get("valid"):
        now_ms = int(time.time() * 1000)
        _set_license({"code": res["code"], "type": res["type"],
                      "activated_at": now_ms,
                      "expires_at": now_ms + res["days"] * 86400000,
                      "days": res["days"], "note": res.get("note", "")})
        if RADAR_RE.match(res["code"].upper()):
            _mark_used(res["code"])
    return res


def status_text() -> Dict:
    """当前授权摘要：{state, state_color, days, expire}（供关于页展示）。"""
    lic = get_license()
    dl = days_left(lic)
    expire = ""
    if lic and lic.get("expires_at"):
        t = time.localtime(lic["expires_at"] / 1000)
        expire = f"{t.tm_year}/{t.tm_mon}/{t.tm_mday}"
    if dl > 0:
        return {"state": "试用中" if lic.get("type") == "trial" else "已授权",
                "days": f"{dl} 天", "expire": expire, "valid": True, "left": dl}
    return {"state": "已过期" if lic else "未激活", "days": "-",
            "expire": expire or "-", "valid": False, "left": dl if lic else 0}


# ---------------- 管理后台 ----------------
def check_admin_pwd(pwd: str) -> bool:
    return (pwd or "").strip() == ADMIN_PWD


def generate_code(days: int, note: str = "") -> Dict:
    seg = lambda: "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=4))
    item = {"code": f"RADAR-{seg()}-{seg()}-{seg()}", "days": int(days),
            "note": note or "", "created_at": int(time.time()), "used": False}
    lst = get_admin_list()
    lst.insert(0, item)
    _set_admin_list(lst)
    return item


# ---------------- 启动门禁 ----------------
def startup_check() -> Dict:
    """返回 {valid, lic, days, created_trial, restored_trial}。

    valid=False 时 UI 应弹出激活窗口；无授权记录时自动建试用。
    """
    lic = get_license()
    created = restored = False
    if not lic:
        fi = get_first_install()
        lic = create_trial()
        created = not fi
        restored = bool(fi)
    dl = days_left(lic)
    return {"valid": dl > 0, "lic": lic, "days": dl,
            "created_trial": created, "restored_trial": restored}
