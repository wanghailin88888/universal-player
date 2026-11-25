"""主题：深色 / 浅色（参考 Screenbox 的现代观感）。

深色用 Fusion + 全套 QPalette + 少量 QSS 统一控件观感；
浅色回退系统默认。设置里可随时切换并记忆。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette


def apply_theme(app, dark: bool):
    app.setStyle("Fusion")
    if not dark:
        # 浅色：清掉自定义样式，交回系统配色
        app.setStyleSheet("")
        app.setPalette(app.style().standardPalette())
        return

    pal = QPalette()
    BG      = QColor(32, 33, 36)     # 主背景
    PANEL   = QColor(43, 45, 48)     # 面板/输入框
    PANEL2  = QColor(54, 56, 60)     # 悬停/按钮
    TXT     = QColor(232, 233, 235)
    DIM     = QColor(150, 152, 158)
    LINE    = QColor(64, 66, 70)
    ACCENT  = QColor(217, 58, 43)    # 中国红（与图标呼应）

    pal.setColor(QPalette.Window, BG)
    pal.setColor(QPalette.WindowText, TXT)
    pal.setColor(QPalette.Base, PANEL)
    pal.setColor(QPalette.AlternateBase, PANEL2)
    pal.setColor(QPalette.ToolTipBase, PANEL2)
    pal.setColor(QPalette.ToolTipText, TXT)
    pal.setColor(QPalette.Text, TXT)
    pal.setColor(QPalette.Button, PANEL2)
    pal.setColor(QPalette.ButtonText, TXT)
    pal.setColor(QPalette.BrightText, QColor(255, 90, 70))
    pal.setColor(QPalette.Link, ACCENT)
    pal.setColor(QPalette.Highlight, ACCENT)
    pal.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    pal.setColor(QPalette.PlaceholderText, DIM)
    for group in (QPalette.Disabled,):
        pal.setColor(group, QPalette.WindowText, DIM)
        pal.setColor(group, QPalette.Text, DIM)
        pal.setColor(group, QPalette.ButtonText, DIM)
    app.setPalette(pal)

    app.setStyleSheet(f"""
        QMainWindow, QDialog {{ background: {BG.name()}; }}
        QStatusBar {{ background: {PANEL.name()}; color: {DIM.name()};
                      border-top: 1px solid {LINE.name()}; }}
        QMenuBar {{ background: {BG.name()}; border-bottom: 1px solid {LINE.name()}; }}
        QMenuBar::item {{ padding: 4px 10px; }}
        QMenuBar::item:selected {{ background: {PANEL2.name()}; }}
        QMenu {{ background: {PANEL.name()}; border: 1px solid {LINE.name()}; }}
        QMenu::item {{ padding: 5px 28px; }}
        QMenu::item:selected {{ background: {PANEL2.name()}; }}
        QMenu::separator {{ height: 1px; background: {LINE.name()};
                            margin: 4px 8px; }}
        QToolButton {{ background: transparent; border: none; border-radius: 4px;
                       padding: 4px; color: {TXT.name()}; }}
        QToolButton:hover {{ background: {PANEL2.name()}; }}
        QToolButton:pressed {{ background: {LINE.name()}; }}
        QLabel {{ color: {TXT.name()}; }}
        QSlider::groove:horizontal {{ height: 4px; border-radius: 2px;
             background: {LINE.name()}; }}
        QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -5px 0;
             border-radius: 6px; background: {TXT.name()}; }}
        QSlider::handle:horizontal:hover {{ background: #ffffff; }}
        QSlider::sub-page:horizontal {{ background: {ACCENT.name()};
             border-radius: 2px; }}
        QDockWidget {{ color: {TXT.name()};
             titlebar-close-icon: none; }}
        QDockWidget::title {{ background: {PANEL.name()}; padding: 6px; }}
        QListWidget, QTreeWidget, QListView {{ background: {PANEL.name()};
             border: none; alternate-background-color: {PANEL2.name()}; }}
        QListWidget::item {{ padding: 6px 8px; }}
        QListWidget::item:selected {{ background: {PANEL2.name()};
             color: {TXT.name()}; }}
        QListWidget::item:hover {{ background: {PANEL2.name()}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
             background: {PANEL.name()}; border: 1px solid {LINE.name()};
             border-radius: 4px; padding: 4px 8px; color: {TXT.name()}; }}
        QPushButton {{ background: {PANEL2.name()}; border: 1px solid {LINE.name()};
             border-radius: 4px; padding: 5px 16px; color: {TXT.name()}; }}
        QPushButton:hover {{ background: {LINE.name()}; }}
        QPushButton:default {{ background: {ACCENT.name()};
             border-color: {ACCENT.name()}; color: white; }}
        QCheckBox, QRadioButton {{ color: {TXT.name()}; }}
        QTabBar::tab {{ background: {PANEL.name()}; color: {DIM.name()};
             padding: 6px 14px; border: 1px solid {LINE.name()}; }}
        QTabBar::tab:selected {{ color: {TXT.name()};
             border-bottom: 2px solid {ACCENT.name()}; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; }}
        QScrollBar::handle:vertical {{ background: {LINE.name()};
             border-radius: 5px; min-height: 30px; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
        QScrollBar:horizontal {{ background: transparent; height: 10px; }}
        QScrollBar::handle:horizontal {{ background: {LINE.name()};
             border-radius: 5px; min-width: 30px; }}
    """)
