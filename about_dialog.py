"""万能视频播放器 —— 「关于 / 授权」弹窗组。

复刻「乾象·期衡 · 股票多周期共振」关于页六个模块：
  开发者信息 / 授权状态 / 管理授权码 / 支持作者 / 软件功能定制 / 免责声明
外加：激活/续期弹窗、管理后台弹窗（密码保护 + 生成一码一用授权码）。

暗色卡片风格仅作用于本组弹窗，不影响主窗口原生主题。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget, QSpinBox, QApplication, QFrame,
)

import license as lic
from resources import asset_path

# ---- 母版同款配色 ----
C_BG = "#151a24"
C_CARD = "#1b2230"
C_LINE = "#2a3140"
C_ROW = "#23293a"
C_TXT = "#e6eaf2"
C_SUB = "#9aa3b8"
C_BLUE = "#5cc8ff"
C_PURPLE = "#7b5cff"
C_GREEN = "#4caf50"
C_RED = "#ff6b6b"
C_GOLD = "#ffd479"
C_QQ = "#b89cff"

DIALOG_QSS = f"""
QDialog, QDialogScroll {{ background: {C_BG}; }}
QLabel {{ color: {C_TXT}; font-size: 13px; }}
#head {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #7b5cff, stop:1 #8e44ad);
    border-top-left-radius: 14px; border-top-right-radius: 14px;
}}
#headTitle {{ color: #fff; font-size: 16px; font-weight: 700; background: transparent; }}
#card {{
    background: {C_CARD}; border: 1px solid {C_LINE};
    border-radius: 12px;
}}
#cardAdmin {{
    background: {C_CARD}; border: 2px solid {C_PURPLE}; border-radius: 12px;
}}
#cardTitle {{ font-size: 14px; font-weight: 700; color: {C_TXT}; background: transparent; }}
#rowLine {{ background: {C_ROW}; max-height: 1px; border: none; }}
#rowLabel {{ color: {C_SUB}; font-size: 13px; background: transparent; }}
#rowValue {{ color: {C_TXT}; font-size: 13px; font-weight: 600; background: transparent; }}
#rowValueQQ {{ color: {C_QQ}; font-size: 15px; font-weight: 700; background: transparent; }}
#rowValueBlue {{ color: {C_BLUE}; font-size: 13px; font-weight: 600; background: transparent; }}
#desc {{ color: {C_SUB}; font-size: 12px; background: transparent; }}
#btnPurple {{
    background: {C_PURPLE}; color: #fff; border: none; border-radius: 8px;
    padding: 10px 0; font-size: 14px; font-weight: 600;
}}
#btnPurple:hover {{ background: #8d70ff; }}
#btnGhost {{
    background: #222b3a; color: #b8c0d4; border: none; border-radius: 8px;
    padding: 10px 0; font-size: 14px; font-weight: 600;
}}
#btnBlue {{ background: #2b6cff; color: #fff; border: none; border-radius: 8px;
    padding: 10px 0; font-size: 14px; font-weight: 600; }}
#codeInput, #pwdInput {{
    background: #0f141d; border: 1px solid {C_LINE}; border-radius: 8px;
    padding: 10px 12px; color: {C_TXT}; font-size: 14px;
}}
#codeInput:focus, #pwdInput:focus {{ border-color: #3a7bff; }}
#closeBtn {{
    background: rgba(255,255,255,.15); color: #fff; border: none;
    border-radius: 6px; font-size: 14px; min-width: 28px; min-height: 28px;
}}
#closeBtn:hover {{ background: rgba(255,255,255,.28); }}
#resultCode {{
    font-family: Consolas, monospace; font-size: 18px; font-weight: 700;
    color: #7bdc8b; letter-spacing: 2px; background: transparent;
}}
#codeBox {{ background: #0f141d; border: 1px dashed #3a7bff; border-radius: 10px; }}
"""


def _card(title: str, admin: bool = False) -> tuple:
    """创建一张圆角卡片，返回 (frame, vbox)。"""
    f = QFrame()
    f.setObjectName("cardAdmin" if admin else "card")
    v = QVBoxLayout(f)
    v.setContentsMargins(16, 14, 16, 14)
    v.setSpacing(6)
    t = QLabel(title)
    t.setObjectName("cardTitle")
    v.addWidget(t)
    return f, v


def _row(label: str, value: str, obj: str = "rowValue") -> tuple:
    """一行 label + value，返回 (label_w, value_label)。"""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 5, 0, 5)
    la = QLabel(label)
    la.setObjectName("rowLabel")
    va = QLabel(value)
    va.setObjectName(obj)
    va.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    h.addWidget(la)
    h.addStretch(1)
    h.addWidget(va)
    line = QFrame()
    line.setObjectName("rowLine")
    line.setFixedHeight(1)
    v = QVBoxLayout()
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)
    v.addWidget(w)
    return w, va


class AboutDialog(QDialog):
    """「关于」弹窗：六模块卡片，滚动浏览。"""

    def __init__(self, parent=None, on_activated=None):
        super().__init__(parent)
        self.on_activated = on_activated  # 激活成功后通知主窗口刷新状态栏
        self.setWindowTitle("关于")
        self.setStyleSheet(DIALOG_QSS)
        self.setModal(True)
        self.setFixedWidth(560)
        self.setMinimumHeight(640)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部紫色渐变标题栏
        head = QFrame()
        head.setObjectName("head")
        h = QHBoxLayout(head)
        h.setContentsMargins(20, 14, 14, 14)
        title = QLabel("👤  关于")
        title.setObjectName("headTitle")
        close = QPushButton("✕")
        close.setObjectName("closeBtn")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.reject)
        h.addWidget(title)
        h.addStretch(1)
        h.addWidget(close)
        root.addWidget(head)

        # 滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setStyleSheet(f"background: {C_BG};")
        v = QVBoxLayout(body)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(12)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # ---- 卡片 1：开发者信息 ----
        from PySide6.QtCore import QTimer
        f, cv = _card("👤  开发者信息")
        w, va = _row("📱 QQ", lic.CONTACT["qq"], "rowValueQQ")
        cv.addWidget(w)
        va.setToolTip("点击复制")
        va.setCursor(Qt.PointingHandCursor)

        def _copy_qq(_=False, t=va):
            QApplication.clipboard().setText(lic.CONTACT["qq"])
            t.setText("已复制 ✓")
            QTimer.singleShot(1500, lambda: t.setText(lic.CONTACT["qq"]))
        va.mousePressEvent = _copy_qq
        w, _ = _row("作者", lic.CONTACT["name"])
        cv.addWidget(w)
        w, _ = _row("版本", f"{lic.APP_NAME} v{lic.APP_VERSION}")
        cv.addWidget(w)
        w, _ = _row("解码内核", "libVLC（本机 VLC / 便携版）")
        cv.addWidget(w)
        v.addWidget(f)

        # ---- 卡片 2：授权状态 ----
        f, cv = _card("🔐  授权状态")
        st = lic.status_text()
        w, self.lic_state = _row("当前状态", st["state"])
        cv.addWidget(w)
        w, self.lic_days = _row("剩余天数", st["days"])
        cv.addWidget(w)
        w, self.lic_expire = _row("到期时间", st["expire"])
        cv.addWidget(w)
        w, act = _row("激活 / 续期", "点击授权 →", "rowValueBlue")
        cv.addWidget(w)
        act.setCursor(Qt.PointingHandCursor)
        act.mousePressEvent = lambda _=False: self._open_activate()
        self._apply_status(st)
        v.addWidget(f)

        # ---- 卡片 3：管理授权码 ----
        f, cv = _card("🔑  管理授权码", admin=True)
        d = QLabel("管理员可生成新的授权码（需输入管理密码）")
        d.setObjectName("desc")
        cv.addWidget(d)
        btn = QPushButton("🔑  进入管理后台")
        btn.setObjectName("btnPurple")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self._open_admin)
        cv.addWidget(btn)
        v.addWidget(f)

        # ---- 卡片 4：支持作者 ----
        f, cv = _card("☕  支持作者")
        d = QLabel("如果本工具对您有帮助，欢迎打赏支持持续开发。扫码即可捐赠，感谢您的支持！")
        d.setObjectName("desc")
        d.setWordWrap(True)
        cv.addWidget(d)
        img = QLabel()
        img.setAlignment(Qt.AlignCenter)
        pix = QPixmap(asset_path("qrcode.jpg"))
        if not pix.isNull():
            img.setPixmap(pix.scaledToWidth(220, Qt.SmoothTransformation))
        else:
            img.setText("（未找到 qrcode.jpg）")
            img.setObjectName("desc")
        cv.addWidget(img)
        tip = QLabel("支付宝扫码支持 · 林老板")
        tip.setObjectName("desc")
        tip.setAlignment(Qt.AlignCenter)
        cv.addWidget(tip)
        v.addWidget(f)

        # ---- 卡片 5：软件功能定制 ----
        f, cv = _card("🛠️  软件功能定制", admin=True)
        d = QLabel(
            "💡 专业定制开发服务\n\n"
            "✅ 视频播放器 / 桌面工具定制\n"
            "✅ 数据分析与监控软件开发\n"
            "✅ Android / iOS / 桌面应用开发\n"
            "✅ 网站建设与管理系统\n"
            "✅ 其他定制化需求\n\n"
            f"📱 联系作者：QQ {lic.CONTACT['qq']}（备注\"软件定制\"优先通过）")
        d.setObjectName("desc")
        d.setWordWrap(True)
        cv.addWidget(d)
        v.addWidget(f)

        # ---- 卡片 6：免责声明 ----
        f, cv = _card("⚠️  免责声明")
        d = QLabel("本软件仅供学习与个人使用，请支持正版影音内容。"
                   "软件按\"现状\"提供，作者不对因使用本软件产生的任何直接或间接损失承担责任。")
        d.setObjectName("desc")
        d.setWordWrap(True)
        cv.addWidget(d)
        v.addWidget(f)

        v.addStretch(1)

    # ---------------- 状态刷新 ----------------
    def _apply_status(self, st: dict):
        self.lic_state.setText(st["state"])
        self.lic_state.setStyleSheet(
            f"color: {C_GREEN if st['valid'] else C_RED}; font-weight: 700;"
            "font-size: 13px; background: transparent;")
        self.lic_days.setText(st["days"])
        if st["valid"]:
            color = C_RED if st["left"] <= 3 else C_GREEN
        else:
            color = C_SUB
        self.lic_days.setStyleSheet(
            f"color: {color}; font-weight: 700; font-size: 13px; background: transparent;")
        self.lic_expire.setText(st["expire"])

    def refresh_status(self):
        self._apply_status(lic.status_text())

    # ---------------- 入口 ----------------
    def _open_activate(self):
        dlg = ActivateDialog(self)
        if dlg.exec() == QDialog.Accepted and self.on_activated:
            try:
                self.on_activated()
            except Exception:
                pass
        self.refresh_status()

    def _open_admin(self):
        dlg = AdminPwdDialog(self)
        if dlg.exec() == QDialog.Accepted:
            panel = AdminPanelDialog(self)
            panel.exec()


class ActivateDialog(QDialog):
    """激活 / 续期弹窗。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("激活 / 续期")
        self.setStyleSheet(DIALOG_QSS)
        self.setModal(True)
        self.setFixedWidth(440)

        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(10)

        t = QLabel(f"⚡ {lic.APP_NAME} · 用户验证")
        t.setStyleSheet("font-size: 17px; font-weight: 700; color: #fff;")
        sub = QLabel(f"v{lic.APP_VERSION} · 试用 {lic.TRIAL_DAYS} 天 · 激活码联系作者获取")
        sub.setObjectName("desc")
        v.addWidget(t)
        v.addWidget(sub)

        st = lic.status_text()
        status = QLabel(f"当前：{st['state']}"
                        + (f" · 剩余 {st['days']}" if st["valid"] else " · 请输入授权码激活"))
        status.setObjectName("desc")
        status.setStyleSheet(f"color: {C_GOLD};")
        v.addWidget(status)

        self.input = QLineEdit()
        self.input.setObjectName("codeInput")
        self.input.setPlaceholderText("输入授权码…（RADAR-XXXX-XXXX-XXXX）")
        self.input.returnPressed.connect(self._do_activate)
        v.addWidget(self.input)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn = QPushButton("激活")
        btn.setObjectName("btnBlue")
        btn.clicked.connect(self._do_activate)
        paste = QPushButton("📋 粘贴")
        paste.setObjectName("btnGhost")
        paste.clicked.connect(self._do_paste)
        row.addWidget(btn, 1)
        row.addWidget(paste, 1)
        v.addLayout(row)

        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)

        box = QLabel(
            f"授权到期或无效？\n联系人：{lic.CONTACT['name']} · QQ："
            f"<a style='color:{C_GOLD}' href='#'>{lic.CONTACT['qq']}</a>")
        box.setObjectName("desc")
        box.setWordWrap(True)
        box.setTextFormat(Qt.RichText)
        v.addWidget(box)
        self.resize(440, self.sizeHint().height())

    def _do_paste(self):
        txt = QApplication.clipboard().text().strip()
        if txt:
            self.input.setText(txt)

    def _do_activate(self):
        res = lic.activate(self.input.text())
        if res.get("valid"):
            self.msg.setStyleSheet(f"color: {C_GREEN};")
            self.msg.setText(f"✅ 激活成功，有效期 {res['days']} 天")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(900, self.accept)
        else:
            self.msg.setStyleSheet(f"color: {C_RED};")
            self.msg.setText("❌ " + res.get("msg", "授权码无效"))


class AdminPwdDialog(QDialog):
    """管理密码校验。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理密码")
        self.setStyleSheet(DIALOG_QSS)
        self.setModal(True)
        self.setFixedWidth(360)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(10)
        t = QLabel("🔑 管理密码")
        t.setStyleSheet("font-size: 17px; font-weight: 700; color: #fff;")
        sub = QLabel("生成授权码需验证身份")
        sub.setObjectName("desc")
        self.input = QLineEdit()
        self.input.setObjectName("pwdInput")
        self.input.setEchoMode(QLineEdit.Password)
        self.input.setPlaceholderText("请输入管理密码…")
        self.input.returnPressed.connect(self._check)
        btn = QPushButton("确认")
        btn.setObjectName("btnBlue")
        btn.clicked.connect(self._check)
        self.msg = QLabel("")
        v.addWidget(t)
        v.addWidget(sub)
        v.addWidget(self.input)
        v.addWidget(btn)
        v.addWidget(self.msg)

    def _check(self):
        if lic.check_admin_pwd(self.input.text()):
            self.accept()
        else:
            self.msg.setStyleSheet(f"color: {C_RED};")
            self.msg.setText("密码错误，请重试")
            self.input.clear()


class AdminPanelDialog(QDialog):
    """管理后台：生成一码一用授权码。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理后台 · 生成授权码")
        self.setStyleSheet(DIALOG_QSS)
        self.setModal(True)
        self.setFixedWidth(460)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(10)

        t = QLabel("🔑 管理后台 · 生成授权码")
        t.setStyleSheet("font-size: 17px; font-weight: 700; color: #fff;")
        sub = QLabel("一码一用 · 首次激活时生效")
        sub.setObjectName("desc")
        v.addWidget(t)
        v.addWidget(sub)

        la = QLabel("有效期（天，1-3650）")
        la.setObjectName("desc")
        self.days = QSpinBox()
        self.days.setRange(1, 3650)
        self.days.setValue(365)
        self.days.setStyleSheet(
            "background:#0f141d;border:1px solid #2a3140;border-radius:8px;"
            f"padding:8px;color:{C_TXT};font-size:14px;")
        la2 = QLabel("备注（可选，如：VIP用户张三）")
        la2.setObjectName("desc")
        self.note = QLineEdit()
        self.note.setObjectName("codeInput")
        self.note.setPlaceholderText("备注…")
        v.addWidget(la)
        v.addWidget(self.days)
        v.addWidget(la2)
        v.addWidget(self.note)

        row = QHBoxLayout()
        gen = QPushButton("生成授权码")
        gen.setObjectName("btnBlue")
        gen.clicked.connect(self._gen)
        close = QPushButton("关闭")
        close.setObjectName("btnGhost")
        close.clicked.connect(self.reject)
        row.addWidget(gen, 1)
        row.addWidget(close, 1)
        v.addLayout(row)

        self.box = QFrame()
        self.box.setObjectName("codeBox")
        bv = QVBoxLayout(self.box)
        bv.setContentsMargins(14, 12, 14, 12)
        self.code = QLabel("")
        self.code.setObjectName("resultCode")
        self.code.setAlignment(Qt.AlignCenter)
        self.code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.meta = QLabel("")
        self.meta.setObjectName("desc")
        self.meta.setAlignment(Qt.AlignCenter)
        cp = QPushButton("📋 复制授权码")
        cp.setObjectName("btnGhost")
        cp.clicked.connect(self._copy)
        bv.addWidget(self.code)
        bv.addWidget(self.meta)
        bv.addWidget(cp)
        self.box.hide()
        v.addWidget(self.box)

    def _gen(self):
        item = lic.generate_code(self.days.value(), self.note.text().strip())
        self.code.setText(item["code"])
        meta = f"有效期 {item['days']} 天"
        if item["note"]:
            meta += f" · {item['note']}"
        self.meta.setText(meta + " · 一码一用")
        self.box.show()
        self._last = item["code"]

    def _copy(self):
        QApplication.clipboard().setText(getattr(self, "_last", ""))
