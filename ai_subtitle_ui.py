"""AI 字幕 UI：对话配置 + 后台线程，避免识别时卡住界面。"""
from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
    QTextEdit, QVBoxLayout,
)

import ai_subtitle
from ai_subtitle import (
    AsrError, AsrResult, WHISPER_LANGS, Translator,
    is_model_ready, write_srt,
)


# ================================================================ 后台线程
class AiSubtitleWorker(QThread):
    """在子线程里跑 Whisper 识别 + 翻译，避免界面卡死。"""
    progress = Signal(int, str)     # 0-100, 描述
    partial = Signal(object, str)   # 前置片段就绪：segments, srt 路径（可立即挂载）
    finished = Signal(object, str)  # AsrResult, srt 路径
    failed = Signal(str)

    def __init__(self, media: str, size: str, src_lang: str, dst_lang: str,
                 bilingual: bool, device: str, out_srt: str = "",
                 parent=None, workers: int = 0, beam_size: int = 5,
                 temp_fallback: bool = False, front_seconds: float = 0.0,
                 chunk_seconds: float = 60.0):
        super().__init__(parent)
        self.media = media
        self.size = size
        self.src_lang = src_lang
        self.dst_lang = dst_lang
        self.bilingual = bilingual
        self.device = device
        self.out_srt = out_srt
        self.workers = int(workers or 0)
        self.beam_size = int(beam_size or 5)
        self.temp_fallback = bool(temp_fallback)
        self.front_seconds = float(front_seconds or 0)
        self.chunk_seconds = float(chunk_seconds or 0)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            res, srt = ai_subtitle.generate_subtitles(
                self.media, size=self.size, src_lang=self.src_lang,
                dst_lang=self.dst_lang, bilingual=self.bilingual,
                device=self.device, out_srt=self.out_srt,
                workers=self.workers, beam_size=self.beam_size,
                temp_fallback=self.temp_fallback,
                front_seconds=self.front_seconds,
                chunk_seconds=self.chunk_seconds,
                on_partial=lambda segs, p: self.partial.emit(segs, p),
                cancel_check=lambda: self._cancel,
                progress_cb=lambda p, m: self.progress.emit(p, m))
            if self._cancel:
                self.failed.emit("已取消")
                return
            self.finished.emit(res, srt)
        except AsrError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(f"AI 字幕生成失败：{e}")


class ModelDownloadWorker(QThread):
    """预下载 Whisper 模型 / 翻译包。"""
    progress = Signal(int, str)
    finished = Signal(bool, str)

    def __init__(self, kind: str, key: str, arg: str = "", parent=None):
        super().__init__(parent)
        self.kind = kind      # 'whisper' | 'argos'
        self.key = key        # 模型尺寸 / 源语言
        self.arg = arg        # 目标语言（argos）

    def run(self):
        try:
            if self.kind == "whisper":
                ai_subtitle.ensure_whisper_model(
                    self.key, lambda p, m: self.progress.emit(p, m))
                self.finished.emit(True, f"Whisper {self.key} 模型已就绪")
            else:
                Translator().install_pair(
                    self.key, self.arg,
                    lambda p, m: self.progress.emit(p, m))
                self.finished.emit(True,
                                   f"翻译包 {self.key}→{self.arg} 安装完成")
        except Exception as e:
            self.finished.emit(False, str(e))


# ================================================================ 配置对话框
# ================================================================ 模型管理
class AiModelManagerDialog(QDialog):
    """Whisper 模型 / Argos 翻译包的下载与查看。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 模型管理")
        self.resize(520, 420)
        lay = QVBoxLayout(self)

        self.tabs_tip = QLabel("所有模型保存在程序目录 models/ 下，下载一次即可永久离线使用。")
        self.tabs_tip.setWordWrap(True)
        lay.addWidget(self.tabs_tip)

        gb1 = QGroupBox("语音识别模型（Whisper）")
        v1 = QVBoxLayout(gb1)
        self.whisper_combo = QComboBox()
        self.whisper_combo.addItems(list(ai_subtitle.WHISPER_REPOS.keys()))
        r1 = QHBoxLayout()
        r1.addWidget(self.whisper_combo, 1)
        b_down1 = QPushButton("下载 / 校验")
        b_down1.clicked.connect(self._download_whisper)
        r1.addWidget(b_down1)
        v1.addLayout(r1)
        self.w_state = QLabel("")
        v1.addWidget(self.w_state)
        lay.addWidget(gb1)

        gb2 = QGroupBox("翻译语言包（Argos，离线）")
        v2 = QVBoxLayout(gb2)
        r2 = QHBoxLayout()
        self.src_cb = QComboBox()
        self.dst_cb = QComboBox()
        for cb in (self.src_cb, self.dst_cb):
            cb.addItems([k for k in WHISPER_LANGS.keys() if k != "自动检测"])
        self.src_cb.setCurrentText("中文")
        self.dst_cb.setCurrentText("英语")
        r2.addWidget(QLabel("从")); r2.addWidget(self.src_cb)
        r2.addWidget(QLabel("到")); r2.addWidget(self.dst_cb)
        b_down2 = QPushButton("下载语言包")
        b_down2.clicked.connect(self._download_argos)
        r2.addWidget(b_down2)
        v2.addLayout(r2)
        self.a_state = QLabel("")
        self.a_state.setWordWrap(True)
        v2.addWidget(self.a_state)
        lay.addWidget(gb2)

        self.pb = QProgressBar()
        lay.addWidget(self.pb)
        lay.addWidget(QDialogButtonBox(QDialogButtonBox.Close,
                                       rejected=self.reject))
        self.worker: Optional[ModelDownloadWorker] = None
        self._refresh_states()

    def _refresh_states(self):
        s = self.whisper_combo.currentText()
        self.w_state.setText(f"{s}：{'已下载 ✓' if is_model_ready(s) else '未下载'}"
                             f"（目录：{ai_subtitle.whisper_model_dir(s)}）")
        try:
            pairs = Translator().available_pairs()
            self.a_state.setText("已安装：" + ("、".join(f"{a}→{b}({n})"
                                              for a, b, n in pairs) or "无"))
        except Exception as e:
            self.a_state.setText("读取已安装语言包失败：" + str(e)[:120])

    def _run_worker(self, w: ModelDownloadWorker):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "提示", "有任务正在进行中")
            return
        self.worker = w
        w.progress.connect(self.pb.setValue)
        w.finished.connect(lambda ok, msg: (self.pb.setValue(100 if ok else 0),
                                            QMessageBox.information(
                                                self, "完成" if ok else "失败", msg),
                                            self._refresh_states()))
        w.start()

    def _download_whisper(self):
        size = self.whisper_combo.currentText()
        if is_model_ready(size):
            r = QMessageBox.question(self, "已存在",
                                     f"{size} 模型已下载，是否重新下载？")
            if r != QMessageBox.Yes:
                return
        self._run_worker(ModelDownloadWorker("whisper", size, "", self))

    def _download_argos(self):
        src = WHISPER_LANGS.get(self.src_cb.currentText(), "")
        dst = WHISPER_LANGS.get(self.dst_cb.currentText(), "")
        if not src or not dst:
            QMessageBox.warning(self, "提示", "请选择语言")
            return
        if src == dst:
            QMessageBox.warning(self, "提示", "源语言与目标语言不能相同")
            return
        self._run_worker(ModelDownloadWorker("argos", src, dst, self))


class AiSubtitleDialog(QDialog):
    """AI 字幕设置对话框：模型 / 语言 / 双语 / 输出。

    点「开始生成」后对话框**立即关闭**，任务以信号移交主窗口后台执行，
    进度显示在主窗口状态栏——设置界面不用一直开着等。
    """

    started = Signal(object)   # AiSubtitleWorker（parent=None，由主窗口持有）

    def __init__(self, media_path: str = "", parent=None, settings=None):
        super().__init__(parent)
        self.setWindowTitle("AI 字幕：自动识别人声并翻译")
        self.resize(560, 520)
        self.media_path = media_path
        self.settings = settings
        self.worker: Optional[AiSubtitleWorker] = None
        self.result_srt = ""
        self.result_res: Optional[AsrResult] = None

        lay = QVBoxLayout(self)

        # --- 素材 ---
        gb_file = QGroupBox("媒体文件")
        fl = QFormLayout(gb_file)
        row = QHBoxLayout()
        self.path_edit = QTextEdit()
        self.path_edit.setMaximumHeight(46)
        self.path_edit.setPlainText(media_path or "")
        btn_pick = QPushButton("选择…")
        btn_pick.clicked.connect(self._pick_file)
        row.addWidget(self.path_edit, 1)
        row.addWidget(btn_pick, 0)
        fl.addRow("源文件:", row)
        lay.addWidget(gb_file)

        # --- 识别参数 ---
        gb_asr = QGroupBox("语音识别（Whisper / 离线）")
        fl2 = QFormLayout(gb_asr)

        self.size_combo = QComboBox()
        self.size_combo.addItems(["tiny（最快，75MB）", "base（145MB）",
                                  "small（推荐，480MB）", "medium（1.5GB）",
                                  "large-v3（3GB，需较好显卡）"])
        self.size_combo.setCurrentIndex(2)
        fl2.addRow("模型精度:", self.size_combo)

        # 默认中文：省掉自动检测，中文片识别更快更准（需要时再手动改成自动检测）
        self.src_combo = QComboBox()
        self.src_combo.addItems(list(WHISPER_LANGS.keys()))
        self.src_combo.setCurrentText("中文")
        fl2.addRow("源语言:", self.src_combo)

        self.dev_combo = QComboBox()
        self.dev_combo.addItems(["auto（自动）", "cpu（纯 CPU）", "cuda（NVIDIA 显卡）"])
        fl2.addRow("运行设备:", self.dev_combo)

        # 识别档位：beam 搜索宽度，直接决定速度（长片差距很大）
        self.speed_combo = QComboBox()
        self.speed_combo.addItem("快速（推荐：不重试难句）", 0)
        self.speed_combo.addItem("稳健（难句自动升温重试，慢很多）", 1)
        self.speed_combo.setToolTip(
            "Whisper 遇到低置信度句子会把温度从 0 逐档升到 1 反复重解码；\n"
            "实测同一段 200 秒讲课语音：不回退 46 秒，回退 252 秒（慢 5.5 倍），\n"
            "而清晰语音的识别质量几乎不变。只有音频很嘈杂时才建议选'稳健'。")
        fl2.addRow("识别模式:", self.speed_combo)

        # 分段并行：长片提速（切成 N 段同时识别，再合并）
        self.workers_combo = QComboBox()
        self.workers_combo.addItem("自动（按 CPU 核数，推荐）", 0)
        self.workers_combo.addItem("不分段（单路，最省内存）", 1)
        self.workers_combo.addItem("2 段并行", 2)
        self.workers_combo.addItem("4 段并行（长片快）", 4)
        self.workers_combo.addItem("8 段并行（核多才行）", 8)
        self.workers_combo.setToolTip(
            "把音频切成多段同时识别再合并，1 小时以上的长片能快好几倍；\n"
            "每段会各占一份内存，笔记本内存小就选 2 段或不分段。\n\n"
            "注意：勾了上面的「分段实时出字幕」时按顺序逐段识别（为了字幕能\n"
            "持续出现），这项并行设置不参与；想追求整片最快就取消勾选它。")
        fl2.addRow("分段并行:", self.workers_combo)
        lay.addWidget(gb_asr)

        # --- 翻译 ---
        gb_tr = QGroupBox("字幕翻译（Argos 离线 / Whisper 译英）")
        fl3 = QFormLayout(gb_tr)
        self.dst_combo = QComboBox()
        self.dst_combo.addItem("不翻译")
        self.dst_combo.addItems([k for k in WHISPER_LANGS.keys() if k != "自动检测"])
        self.dst_combo.setCurrentText("不翻译")
        fl3.addRow("目标语言:", self.dst_combo)

        self.chunk_cb = QCheckBox("分段实时出字幕（每段识别完就立刻显示，边看边等）")
        self.chunk_cb.setChecked(True)
        self.chunk_cb.setToolTip(
            "按固定时长把片子切成小段**顺序**识别：第一段一出就挂上字幕，\n"
            "后面每段完成都会刷新一次字幕——保证从第一分钟起画面里一直有字幕。\n"
            "关掉则等整片识别完一次性出字幕。")
        self.chunk_combo = QComboBox()
        for sec in (30, 60, 120):
            self.chunk_combo.addItem(f"{sec} 秒一段", sec)
        self.chunk_combo.setCurrentIndex(1)      # 默认 60 秒
        self.chunk_combo.setToolTip(
            "段越短字幕出得越快、越连贯（但重挂次数多、整体略慢）；\n"
            "段越长整体识别略快，但第一段字幕要等更久。60 秒是平衡点。")
        self.chunk_cb.toggled.connect(self.chunk_combo.setEnabled)
        self.bi_cb = QCheckBox("双语字幕（原文在上，译文在下）")
        self.bi_cb.setChecked(True)
        fl3.addRow("", self.bi_cb)
        fl3.addRow("", self.chunk_cb)
        fl3.addRow("", self.chunk_combo)

        self.pkg_label = QLabel("")
        self.pkg_label.setWordWrap(True)
        fl3.addRow("状态:", self.pkg_label)
        lay.addWidget(gb_tr)

        # --- 输出 ---
        gb_out = QGroupBox("输出")
        fl4 = QFormLayout(gb_out)
        row2 = QHBoxLayout()
        self.out_edit = QTextEdit()
        self.out_edit.setMaximumHeight(40)
        row2.addWidget(self.out_edit, 1)
        btn_out = QPushButton("另存为…")
        btn_out.clicked.connect(self._pick_out)
        row2.addWidget(btn_out, 0)
        fl4.addRow("字幕文件:", row2)
        lay.addWidget(gb_out)

        # --- 进度 ---
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.tip = QLabel("提示：首次使用需下载模型，之后完全离线可用。")
        self.tip.setWordWrap(True)
        lay.addWidget(self.progress)
        lay.addWidget(self.tip)

        # --- 按钮 ---
        self.btns = QDialogButtonBox()
        self.run_btn = self.btns.addButton("开始生成", QDialogButtonBox.AcceptRole)
        self.cancel_btn = self.btns.addButton("取消", QDialogButtonBox.RejectRole)
        self.cancel_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._start)
        self.cancel_btn.clicked.connect(self._cancel)
        lay.addWidget(self.btns)

        self.size_combo.currentIndexChanged.connect(self._refresh_tip)
        self.dst_combo.currentIndexChanged.connect(self._refresh_tip)
        self._apply_saved_defaults()
        self._refresh_tip()

    def _apply_saved_defaults(self):
        """套用上次用过的配置（settings）；默认源语言=中文。"""
        s = self.settings
        if not s:
            return
        for combo, val, fallback in (
                (self.src_combo, getattr(s, "ai_src_lang", ""), "中文"),
                (self.dst_combo, getattr(s, "ai_dst_lang", ""), "不翻译"),
                (self.size_combo, getattr(s, "ai_model", ""), "small（推荐，480MB）"),
        ):
            if val and combo.findText(val) >= 0:
                combo.setCurrentText(val)
            elif combo.findText(fallback) >= 0:
                combo.setCurrentText(fallback)
        self.bi_cb.setChecked(bool(getattr(s, "ai_bilingual", True)))
        self.chunk_cb.setChecked(bool(getattr(s, "ai_chunk_live", True)))
        cs = int(getattr(s, "ai_chunk_seconds", 60) or 60)
        j = self.chunk_combo.findData(cs)
        self.chunk_combo.setCurrentIndex(j if j >= 0 else 1)
        self.chunk_combo.setEnabled(self.chunk_cb.isChecked())
        fb = 1 if getattr(s, "ai_temp_fallback", False) else 0
        i2 = self.speed_combo.findData(fb)
        self.speed_combo.setCurrentIndex(i2 if i2 >= 0 else 0)
        w = int(getattr(s, "ai_workers", 0) or 0)
        i = self.workers_combo.findData(w)
        self.workers_combo.setCurrentIndex(i if i >= 0 else 0)

    def _save_defaults(self):
        """记住本次配置，下次打开就是这套（不用每次改）。"""
        s = self.settings
        if not s:
            return
        s.ai_src_lang = self.src_combo.currentText()
        s.ai_dst_lang = self.dst_combo.currentText()
        s.ai_model = self.size_combo.currentText()
        s.ai_bilingual = self.bi_cb.isChecked()
        s.ai_workers = self.workers
        s.ai_temp_fallback = self.temp_fallback
        s.ai_chunk_live = self.chunk_cb.isChecked()
        s.ai_chunk_seconds = self.chunk_seconds
        try:
            s.save()
        except Exception:
            pass

    # ---------------- 辅助 ----------------
    @property
    def model_size(self) -> str:
        return self.size_combo.currentText().split("（")[0].strip()

    @property
    def device(self) -> str:
        return self.dev_combo.currentText().split("（")[0].strip()

    @property
    def temp_fallback(self) -> bool:
        try:
            return bool(int(self.speed_combo.currentData() or 0))
        except Exception:
            return False

    @property
    def workers(self) -> int:
        try:
            return int(self.workers_combo.currentData() or 0)
        except Exception:
            return 0

    @property
    def chunk_seconds(self) -> float:
        """逐段实时的段长；未勾选返回 0（= 整片识别完再出字幕）。"""
        if not self.chunk_cb.isChecked():
            return 0.0
        try:
            return float(int(self.chunk_combo.currentData() or 60))
        except Exception:
            return 60.0

    def _default_srt(self, dst: str, bilingual: bool) -> str:
        base = os.path.splitext(self.media_path)[0]
        if dst:
            base += ".双语" if bilingual else ".译文"
        return base + ".srt"

    def _refresh_tip(self):
        size = self.model_size
        ready = is_model_ready(size)
        lines = []
        lines.append(f"模型 {size}：{'已就绪' if ready else '未下载（启动时自动下载）'}")
        dst = WHISPER_LANGS.get(self.dst_combo.currentText(), "")
        # 目标语言=不翻译时双语无从谈起，禁用勾选避免配置矛盾
        self.bi_cb.setEnabled(bool(dst))
        if dst:
            if dst == "en":
                lines.append("目标英文：使用 Whisper 内置翻译（无需额外模型）")
            else:
                src = WHISPER_LANGS.get(self.src_combo.currentText(), "") or "识别语言"
                try:
                    inst = Translator().is_pair_installed(src, dst) if src != "识别语言" else False
                except Exception:
                    inst = False
                lines.append(f"需要 Argos 翻译包 {src}→{dst}："
                             f"{'已安装' if inst else '首次生成时自动下载'}")
        self.pkg_label.setText(" / ".join(lines))

    def _pick_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择视频 / 音频", "")
        if f:
            self.path_edit.setPlainText(f)
            self.media_path = f
            self._refresh_tip()

    def _pick_out(self):
        f, _ = QFileDialog.getSaveFileName(self, "保存字幕", "", "SRT 字幕 (*.srt)")
        if f:
            if not f.lower().endswith(".srt"):
                f += ".srt"
            self.out_edit.setPlainText(f)

    # ---------------- 执行 ----------------
    def _start(self):
        self.media_path = self.path_edit.toPlainText().strip()
        if not self.media_path or not os.path.exists(self.media_path):
            QMessageBox.warning(self, "提示", "请先选择要识别的视频 / 音频文件")
            return
        out = self.out_edit.toPlainText().strip()
        if not out:
            dst = WHISPER_LANGS.get(self.dst_combo.currentText(), "")
            out = self._default_srt(dst, self.bi_cb.isChecked())
            self.out_edit.setPlainText(out)

        # worker 不以对话框为父：对话框随即销毁，任务由主窗口接管
        worker = AiSubtitleWorker(
            self.media_path, self.model_size,
            WHISPER_LANGS.get(self.src_combo.currentText(), ""),
            WHISPER_LANGS.get(self.dst_combo.currentText(), ""),
            self.bi_cb.isChecked(), self.device, out, None,
            workers=self.workers, beam_size=5,
            temp_fallback=self.temp_fallback,
            front_seconds=0.0,
            chunk_seconds=self.chunk_seconds)
        self.result_srt = out
        self.worker = worker
        self._save_defaults()     # 记住本次配置，下次默认就是这套
        self.started.emit(worker)
        self.accept()   # 立即关闭设置界面，后台继续跑

    def _cancel(self):
        self.reject()
