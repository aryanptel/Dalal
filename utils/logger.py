"""
Rotating file logger for Dalal AI.

Logging must never be the reason the app fails to start.  ``setup_logger`` runs
at import time, so an unwritable log directory — a locked-down profile, a
read-only or OneDrive-redirected Documents folder, a stale handle on app.log —
used to raise during ``import utils.logger`` and kill the process before any
error handling existed.  Every step here degrades instead of raising.
"""

from __future__ import annotations

import logging
import sys
import os
from logging.handlers import RotatingFileHandler

from utils.paths import get_logs_dir

LOG_FILE_NAME = "app.log"


def _make_file_handler() -> logging.Handler | None:
    """Build the rotating file handler, or None if the filesystem says no."""
    try:
        log_file = os.path.join(get_logs_dir(), LOG_FILE_NAME)
        handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setLevel(logging.DEBUG)
        return handler
    except (OSError, ValueError):
        return None


def _make_console_handler() -> logging.Handler | None:
    """
    Build the console handler.

    A windowed (``console=False``) build can have ``sys.stdout is None``, and
    StreamHandler(None) raises on first use rather than at construction.
    """
    if getattr(sys, "stdout", None) is None:
        return None
    try:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        return handler
    except (OSError, ValueError):
        return None


def setup_logger() -> logging.Logger:
    """Initialise the global rotating logger, falling back to whatever works."""
    _logger = logging.getLogger("DalalAI")

    if _logger.hasHandlers():
        return _logger

    _logger.setLevel(logging.DEBUG)

    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(module)s:%(lineno)d | %(message)s"
    )
    console_formatter = logging.Formatter("%(levelname)s: %(message)s")

    file_handler = _make_file_handler()
    if file_handler is not None:
        file_handler.setFormatter(file_formatter)
        _logger.addHandler(file_handler)

    console_handler = _make_console_handler()
    if console_handler is not None:
        console_handler.setFormatter(console_formatter)
        _logger.addHandler(console_handler)

    if not _logger.handlers:
        # Nowhere to write: swallow records rather than let logging complain to
        # a stderr that may not exist either.
        _logger.addHandler(logging.NullHandler())

    return _logger


logger = setup_logger()


def handle_unhandled_exception(
    exc_type: type, exc_value: BaseException, exc_traceback: object
) -> None:
    """Global exception hook that logs unhandled exceptions."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = handle_unhandled_exception
