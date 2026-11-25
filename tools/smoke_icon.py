import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from resources import asset_path
app = QApplication([])
ico = QIcon(asset_path("app.ico"))
print("icon null:", ico.isNull())
print("sizes:", [(s.width(), s.height()) for s in ico.availableSizes()])
from main_window import MainWindow
w = MainWindow(None)
print("win icon null:", w.windowIcon().isNull())
print("SMOKE_OK")
