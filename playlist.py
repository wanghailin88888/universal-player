"""播放列表数据模型。

支持：文件/文件夹（递归）收集、增删、清空、按循环模式取上下一首、
记录每首时长。基于 QAbstractListModel，直接喂给 QListView。
"""
from __future__ import annotations

import os
import random
from typing import List, Optional

from PySide6.QtCore import QAbstractListModel, Qt, QModelIndex

from settings import MEDIA_EXTS


class PlaylistItem:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.title = os.path.splitext(os.path.basename(path))[0]
        self.duration = 0  # ms，0 表示未知
        self.subtitle = ""  # 关联外部字幕（可选）


class PlaylistModel(QAbstractListModel):
    DurationRole = Qt.UserRole + 1
    PathRole = Qt.UserRole + 2
    TitleRole = Qt.UserRole + 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: List[PlaylistItem] = []
        self.loop_mode = "order"  # order | repeat_one | repeat_all | shuffle
        self._shuffle_order: List[int] = []

    # ---------- 模型接口 ----------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None
        item = self._items[index.row()]
        if role in (Qt.DisplayRole, self.TitleRole):
            return item.title
        if role == self.PathRole:
            return item.path
        if role == self.DurationRole:
            return item.duration
        return None

    def flags(self, index: QModelIndex):
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled

    # ---------- 增删改 ----------
    def add_files(self, paths: List[str]) -> List[str]:
        new_items: List[PlaylistItem] = []
        for p in paths:
            if os.path.isdir(p):
                new_items += self._scan_dir(p)
            elif os.path.isfile(p) and os.path.splitext(p)[1].lower() in MEDIA_EXTS:
                new_items.append(PlaylistItem(p))
        if new_items:
            start = len(self._items)
            self.beginInsertRows(QModelIndex(), start, start + len(new_items) - 1)
            self._items += new_items
            self.endInsertRows()
            self._rebuild_shuffle()
        return [it.path for it in new_items]

    def _scan_dir(self, d: str, recursive: bool = True) -> List[PlaylistItem]:
        items: List[PlaylistItem] = []
        try:
            for root, dirs, files in os.walk(d):
                for f in sorted(files):
                    if os.path.splitext(f)[1].lower() in MEDIA_EXTS:
                        items.append(PlaylistItem(os.path.join(root, f)))
                if not recursive:
                    break
        except Exception:
            pass
        return items

    def remove_at(self, row: int):
        if 0 <= row < len(self._items):
            self.beginRemoveRows(QModelIndex(), row, row)
            self._items.pop(row)
            self.endRemoveRows()
            self._rebuild_shuffle()

    def clear(self):
        self.beginResetModel()
        self._items = []
        self._shuffle_order = []
        self.endResetModel()

    # ---------- 查询 ----------
    def paths(self) -> List[str]:
        return [it.path for it in self._items]

    def item_at(self, row: int) -> Optional[PlaylistItem]:
        return self._items[row] if 0 <= row < len(self._items) else None

    def index_of_path(self, path: str) -> int:
        path = os.path.abspath(path)
        for i, it in enumerate(self._items):
            if it.path == path:
                return i
        return -1

    def set_duration(self, row: int, ms: int):
        if 0 <= row < len(self._items):
            self._items[row].duration = ms
            self.dataChanged.emit(self.index(row), self.index(row), [self.DurationRole])

    def set_subtitle(self, row: int, sub_path: str):
        if 0 <= row < len(self._items):
            self._items[row].subtitle = sub_path

    # ---------- 上下一首 ----------
    def _rebuild_shuffle(self):
        self._shuffle_order = list(range(len(self._items)))
        random.shuffle(self._shuffle_order)

    def next_index(self, current: int) -> int:
        n = len(self._items)
        if n == 0:
            return -1
        if self.loop_mode == "repeat_one":
            return current if current >= 0 else 0
        if self.loop_mode == "shuffle":
            if current < 0:
                return self._shuffle_order[0] if self._shuffle_order else 0
            try:
                pos = self._shuffle_order.index(current)
            except ValueError:
                pos = 0
            return self._shuffle_order[(pos + 1) % len(self._shuffle_order)]
        # order / repeat_all
        if current < 0:
            return 0
        nxt = current + 1
        if nxt >= n:
            return 0 if self.loop_mode == "repeat_all" else -1
        return nxt

    def prev_index(self, current: int) -> int:
        n = len(self._items)
        if n == 0:
            return -1
        if self.loop_mode == "repeat_one":
            return current if current >= 0 else 0
        if self.loop_mode == "shuffle":
            if current < 0:
                return self._shuffle_order[-1] if self._shuffle_order else 0
            try:
                pos = self._shuffle_order.index(current)
            except ValueError:
                pos = 0
            return self._shuffle_order[(pos - 1) % len(self._shuffle_order)]
        if current < 0:
            return n - 1
        prev = current - 1
        if prev < 0:
            return n - 1 if self.loop_mode == "repeat_all" else 0
        return prev
