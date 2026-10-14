"""Rotating file log plus hooks that record otherwise-silent crashes."""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

logger = logging.getLogger("autoclick_pro")


def setup_logging(path: Path) -> None:
    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return
    try:
        handler: logging.Handler = RotatingFileHandler(
            path, maxBytes=512_000, backupCount=2, encoding="utf-8"
        )
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def install_excepthooks(report: Callable[[str], None] | None = None) -> None:
    """Log uncaught exceptions; the windowed build has no console to show them."""

    def _hook(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logger.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
        if report is not None:
            try:
                report(f"{exc_type.__name__}: {exc}")
            except Exception:
                logger.exception("Could not report unhandled exception")

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is None:
            return
        logger.critical(
            "Unhandled exception in thread %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _hook
    threading.excepthook = _thread_hook
