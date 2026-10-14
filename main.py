"""AutoClick Pro entry point."""

import os
import sys
import tempfile

from PySide6.QtCore import QLockFile, QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from autoclick_pro import __version__ as APP_VERSION
from autoclick_pro.main_window import MainWindow, set_app_theme


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _apply_saved_theme(app: QApplication) -> None:
    theme = str(QSettings("AutoClick Pro", "AutoClick Pro").value("theme", "dark"))
    set_app_theme(app, theme if theme in {"dark", "light", "system"} else "dark")


def main() -> int:
    _enable_dpi_awareness()
    app = QApplication(sys.argv)
    lock = QLockFile(os.path.join(tempfile.gettempdir(), "autoclick_pro.lock"))
    if not lock.tryLock(100):
        QMessageBox.warning(None, "AutoClick Pro", "AutoClick Pro is already running.")
        return 0
    _apply_saved_theme(app)
    app.setApplicationName("AutoClick Pro")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("AutoClick Pro")
    window = MainWindow()
    window.setWindowTitle(f"AutoClick Pro {APP_VERSION}")
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
