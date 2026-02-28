"""
jive.utils.log — Logging facility by category and level.

Ported from share/jive/jive/utils/log.lua

Provides category-based loggers with standard log levels.
Each category gets its own logger instance with independently
configurable log levels.

Usage:
    from jive.utils.log import logger

    log = logger("net.http")

    log.debug("connecting to %s", host)
    log.info("connected")
    log.warn("timeout after %d seconds", timeout)
    log.error("connection failed")

Log output format:
    HHMMSS:msec LEVEL (caller:line) - message

Copyright 2010 Logitech. All Rights Reserved.
This file is licensed under BSD. Please see the LICENSE file for details.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

# ─── Log Levels (matching Lua constants) ──────────────────────────────────────

DEBUG = "debug"
INFO = "info"
WARN = "warn"
ERROR = "error"

_LEVEL_MAP = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

_LEVEL_FROM_LOGGING = {
    logging.DEBUG: "debug",
    logging.INFO: "info",
    logging.WARNING: "warn",
    logging.ERROR: "error",
    logging.CRITICAL: "error",
}


# ─── Custom Formatter (matches jivelite log format) ───────────────────────────


class _JiveFormatter(logging.Formatter):
    """
    Formats log messages in the jivelite style:
        HHMMSS:msec LEVEL (filename:line) - message
    """

    def format(self, record: logging.LogRecord) -> str:
        # Time as HHMMSS:msec
        from datetime import datetime

        dt = datetime.fromtimestamp(record.created)
        time_str = dt.strftime("%H%M%S") + f":{int(dt.microsecond / 1000):03d}"

        # Level name, padded
        level = record.levelname[:5].ljust(5)

        # Caller info
        caller = f"{record.filename}:{record.lineno}"

        # Message
        msg = record.getMessage()

        return f"{time_str} {level} ({caller}) - {msg}"


# ─── Logger Registry ─────────────────────────────────────────────────────────

_loggers: dict[str, JiveLogger] = {}
_default_level: int = logging.WARNING


def _make_handler() -> logging.Handler:
    """Create a fresh stderr handler with Jive formatting.

    We intentionally create a *new* handler each time so that it
    references the *current* ``sys.stderr``.  This is important for
    test frameworks like pytest that temporarily replace sys.stderr
    to capture output — a cached handler would write to the old fd
    and the capture fixture would see nothing.
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JiveFormatter())
    return handler


# ─── JiveLogger ──────────────────────────────────────────────────────────────


class JiveLogger:
    """
    A category-based logger wrapping Python's logging module.

    Provides the same interface as the Lua jivelite logger:
        log:debug(...)  →  log.debug(...)
        log:info(...)   →  log.info(...)
        log:warn(...)   →  log.warn(...)
        log:error(...)  →  log.error(...)
    """

    def __init__(self, category: str, level: Optional[int] = None) -> None:
        self.category = category
        self._logger = logging.getLogger(f"jive.{category}")
        self._logger.propagate = False

        # Remove any stale handlers and always re-add so that pytest's
        # fd-level capture (capfd) picks up writes to the *current*
        # sys.stderr, not a stale reference cached by a previous handler.
        self._logger.handlers.clear()
        self._logger.addHandler(_make_handler())

        # Set initial level
        self._logger.setLevel(level if level is not None else _default_level)

    def debug(self, *args: object) -> None:
        """Log a debug message. Arguments are concatenated (matching Lua behavior)."""
        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug("%s", _concat_args(args), stacklevel=2)

    def info(self, *args: object) -> None:
        """Log an info message."""
        if self._logger.isEnabledFor(logging.INFO):
            self._logger.info("%s", _concat_args(args), stacklevel=2)

    def warn(self, *args: object) -> None:
        """Log a warning message."""
        if self._logger.isEnabledFor(logging.WARNING):
            self._logger.warning("%s", _concat_args(args), stacklevel=2)

    def error(self, *args: object) -> None:
        """Log an error message. Includes traceback (matching Lua behavior)."""
        if self._logger.isEnabledFor(logging.ERROR):
            self._logger.error("%s", _concat_args(args), stacklevel=2, exc_info=False)

    def set_level(self, level: str | int) -> None:
        """
        Set the log level for this category.

        Args:
            level: Either a string ("debug", "info", "warn", "error")
                   or a logging.* constant.
        """
        if isinstance(level, str):
            level = _LEVEL_MAP.get(level.lower(), logging.WARNING)
        self._logger.setLevel(level)

    def get_level(self) -> str:
        """Return the current log level as a string."""
        effective = self._logger.getEffectiveLevel()
        return _LEVEL_FROM_LOGGING.get(effective, "warn")

    def is_debug(self) -> bool:
        """Return True if debug logging is enabled."""
        return self._logger.isEnabledFor(logging.DEBUG)

    def __repr__(self) -> str:
        return f"JiveLogger({self.category!r}, level={self.get_level()!r})"


# ─── Module-Level API ─────────────────────────────────────────────────────────


def logger(category: str) -> JiveLogger:
    """
    Get or create a logger for the given category.

    This is the primary API — equivalent to Lua's:
        local log = require("jive.utils.log").logger("net.http")

    Args:
        category: Dot-separated category name (e.g. "net.http",
                  "squeezebox.player", "ui.framework").

    Returns:
        A JiveLogger instance for this category.
    """
    if category not in _loggers:
        _loggers[category] = JiveLogger(category)
    return _loggers[category]


def get_categories() -> list[str]:
    """
    Return a sorted list of all registered logger categories.

    Equivalent to Lua's log.getCategories().
    """
    return sorted(_loggers.keys())


def set_default_level(level: str | int) -> None:
    """
    Set the default log level for newly created loggers.

    Args:
        level: Either a string ("debug", "info", "warn", "error")
               or a logging.* constant.
    """
    global _default_level
    if isinstance(level, str):
        _default_level = _LEVEL_MAP.get(level.lower(), logging.WARNING)
    else:
        _default_level = level


def set_all_levels(level: str | int) -> None:
    """
    Set the log level for ALL existing loggers at once.

    Args:
        level: Either a string ("debug", "info", "warn", "error")
               or a logging.* constant.
    """
    set_default_level(level)
    for log in _loggers.values():
        log.set_level(level)


# ─── Internal Helpers ─────────────────────────────────────────────────────────


def _concat_args(args: tuple[object, ...]) -> str:
    """
    Concatenate log arguments into a single string.

    In Lua, log:debug("Welcome ", name, ", good ", time) concatenates
    all arguments. We replicate this behavior: all args are converted
    to strings and joined without separator.
    """
    if len(args) == 0:
        return ""
    if len(args) == 1:
        return str(args[0])
    return "".join(str(a) for a in args)
