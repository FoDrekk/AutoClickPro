"""AutoClick Pro entry point."""

import os
import sys
import tempfile
from typing import Any

from PySide6.QtCore import QLockFile, QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from autoclick_pro import __version__ as APP_VERSION
from autoclick_pro import diagnostics
from autoclick_pro.app_logging import install_excepthooks, logger, setup_logging
from autoclick_pro.paths import log_path, settings_path
from autoclick_pro.settings_store import SettingsStore
from autoclick_pro.ui.main_window import MainWindow
from autoclick_pro.ui.theme import set_app_theme


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


def _legacy_qsettings() -> dict[str, Any] | None:
    """Read settings saved by 1.x (Windows registry) for one-time migration."""
    qs = QSettings("AutoClick Pro", "AutoClick Pro")
    keys = qs.childKeys()
    if not keys and not qs.childGroups():
        return None
    settings = {key: qs.value(key) for key in keys}
    profiles: dict[str, dict[str, Any]] = {}
    qs.beginGroup("profiles")
    for name in qs.childGroups():
        qs.beginGroup(name)
        profiles[name] = {key: qs.value(key) for key in qs.childKeys()}
        qs.endGroup()
    qs.endGroup()
    return {"settings": settings, "profiles": profiles}


def _report_crash(summary: str) -> None:
    if QApplication.instance() is None:
        return
    QMessageBox.critical(
        None,
        "AutoClick Pro error",
        f"An unexpected error occurred:\n\n{summary}\n\nDetails were written to {log_path()}.",
    )


def main() -> int:
    setup_logging(log_path())
    install_excepthooks(_report_crash)
    _enable_dpi_awareness()
    app = QApplication(sys.argv)
    app.setApplicationName("AutoClick Pro")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("AutoClick Pro")
    lock = QLockFile(os.path.join(tempfile.gettempdir(), "autoclick_pro.lock"))
    if not lock.tryLock(100):
        QMessageBox.warning(None, "AutoClick Pro", "AutoClick Pro is already running.")
        return 0
    store = SettingsStore.load(settings_path(), legacy_loader=_legacy_qsettings)
    set_app_theme(app, store.settings["theme"])
    # After the lock, so a second instance cannot clobber the first one's crash log.
    previous_crash = diagnostics.take_previous_crash(diagnostics.crash_log_path())
    diagnostics.enable_fault_handler(diagnostics.crash_log_path())
    logger.info("AutoClick Pro %s starting", APP_VERSION)
    if previous_crash is not None:
        logger.warning("The previous run ended unexpectedly; crash report: %s", previous_crash)
    window = MainWindow(store)
    window.show()
    if previous_crash is not None:
        window.notify_previous_crash(previous_crash)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
