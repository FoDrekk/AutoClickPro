"""Run the update check off the GUI thread without blocking application exit."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from autoclick_pro.updater import UpdateError, UpdateInfo

_logger = logging.getLogger("autoclick_pro")

Checker = Callable[[], UpdateInfo | None]


class UpdateChecker(QObject):
    """Emits exactly one of ``finished`` or ``failed`` per ``start()``."""

    finished = Signal(object)  # UpdateInfo, or None when up to date.
    failed = Signal(str)

    def __init__(self, checker: Checker, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._checker = checker
        self._lock = threading.Lock()
        self._running = False

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def start(self) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
        # A daemon thread cannot hold the process open if the network stalls.
        threading.Thread(target=self._run, name="UpdateCheck", daemon=True).start()
        return True

    def _run(self) -> None:
        try:
            result = self._checker()
        except UpdateError as exc:
            self._finish(failed=str(exc))
        except Exception as exc:  # A bug here must never take the app down.
            _logger.exception("Update check crashed")
            self._finish(failed=f"Update check failed: {exc}")
        else:
            self._finish(result=result)

    def _finish(self, *, result: UpdateInfo | None = None, failed: str | None = None) -> None:
        with self._lock:
            self._running = False
        try:
            if failed is not None:
                self.failed.emit(failed)
            else:
                self.finished.emit(result)
        except RuntimeError:
            pass  # The window was closed while the check was in flight.
