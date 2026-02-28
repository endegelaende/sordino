"""
jive.ui.timer — Interval-based callback timer for the Jivelite Python3 port.

Ported from ``jive/ui/Timer.lua`` in the original jivelite project.

Timers are associated with widgets and only run while the widget is visible.
They can also be used standalone.  The timer queue is a sorted list (by
expiry time) that is processed each frame by ``Timer.run_timers(now)``.

Copyright 2010 Logitech. All Rights Reserved. (original Lua implementation)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import bisect
import time
from typing import Callable, ClassVar, Optional

from jive.utils.log import logger

__all__ = ["Timer"]

log = logger("jivelite.timer")

# ---------------------------------------------------------------------------
# Module-level startup reference (same epoch as event.py)
# ---------------------------------------------------------------------------

_startup_time_ns: int = time.monotonic_ns()


def _get_ticks() -> int:
    """Return milliseconds since startup."""
    return (time.monotonic_ns() - _startup_time_ns) // 1_000_000


# ---------------------------------------------------------------------------
# Timer class
# ---------------------------------------------------------------------------


class Timer:
    """
    An interval-based callback timer.

    Usage::

        timer = Timer(1000, lambda: print("hi"))
        timer.start()

        # in the event loop each frame:
        Timer.run_timers(now_ms)

        timer.stop()

    If *once* is ``True`` the callback fires only once per ``start()``
    call; otherwise it repeats at *interval* ms until ``stop()`` is called.

    The callback receives no arguments (unlike the Lua original which
    passes the Timer object).  If you need the timer inside the callback
    just capture it via closure.
    """

    __slots__ = ("interval", "callback", "once", "expires", "_key")

    # Class-level sorted timer queue.  Sorted by ``expires`` ascending.
    # We use a plain list + bisect rather than heapq so we can efficiently
    # ``remove()`` individual timers (stop) — the list stays small
    # (typically < 20 timers active at once).
    _timers: ClassVar[list[Timer]] = []

    # Monotonic counter to break ties in the sort when two timers have
    # the same expiry.  This ensures FIFO ordering for equal-expiry timers
    # and gives each timer a unique secondary sort key.
    _next_key: ClassVar[int] = 0

    def __init__(
        self,
        interval: int,
        callback: Callable[[], None],
        once: bool = False,
    ) -> None:
        if not isinstance(interval, (int, float)):
            raise TypeError(f"interval must be a number, got {type(interval).__name__}")
        if not callable(callback):
            raise TypeError("callback must be callable")

        self.interval: int = int(interval)
        self.callback: Callable[[], None] = callback
        self.once: bool = once
        self.expires: Optional[int] = None  # None ⇒ not running
        self._key: int = 0  # sort tiebreaker

    # ------------------------------------------------------------------
    # Sort support — timers are kept sorted by (expires, _key)
    # ------------------------------------------------------------------

    def _sort_tuple(self) -> tuple[int, int]:
        assert self.expires is not None
        return (self.expires, self._key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start (or re-insert) the timer.  First fire is *interval* ms from now."""
        now = _get_ticks()
        self._insert(now + self.interval)

    def stop(self) -> None:
        """Stop the timer.  Safe to call even if not running."""
        if self.expires is not None:
            try:
                Timer._timers.remove(self)
            except ValueError:
                pass
            self.expires = None

    def restart(self, interval: Optional[int] = None) -> None:
        """
        Restart the timer.  Optionally change the *interval* (ms).
        """
        self.stop()
        if interval is not None:
            self.interval = int(interval)
        self.start()

    def set_interval(self, interval: int) -> None:
        """
        Change the interval.  If the timer is already running it is
        restarted with the new interval.
        """
        if self.expires is not None:
            self.restart(interval)
        else:
            self.interval = int(interval)

    def is_running(self) -> bool:
        """Return ``True`` if the timer is currently active."""
        return self.expires is not None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _insert(self, expires: int) -> None:
        """Insert *self* into the sorted timer queue at *expires* ms."""
        # Remove first if already present (restart scenario)
        if self.expires is not None:
            try:
                Timer._timers.remove(self)
            except ValueError:
                pass

        self.expires = expires
        Timer._next_key += 1
        self._key = Timer._next_key

        # Binary-search insert to keep the list sorted by (expires, _key).
        # We build a list of sort tuples for bisect; since the list is
        # typically very short (< 20) this is fine.
        keys = [t._sort_tuple() for t in Timer._timers]
        idx = bisect.bisect_right(keys, self._sort_tuple())
        Timer._timers.insert(idx, self)

    # ------------------------------------------------------------------
    # Class-level timer processing  (called once per frame)
    # ------------------------------------------------------------------

    @classmethod
    def run_timers(cls, now: Optional[int] = None) -> None:
        """
        Process all timers that have expired by *now* (ms).

        If *now* is ``None`` the current tick count is used.

        This mirrors ``Timer:_runTimer(now)`` in the Lua original and
        should be called once per frame from the Framework event loop.
        """
        if now is None:
            now = _get_ticks()

        # Sanity check: a stopped timer should never be at the head
        if cls._timers and cls._timers[0].expires is None:
            log.error("stopped timer found in timer list — removing")
            cls._timers = [t for t in cls._timers if t.expires is not None]

        while (
            cls._timers
            and cls._timers[0].expires is not None
            and cls._timers[0].expires <= now
        ):
            timer = cls._timers.pop(0)

            # Schedule next fire *before* calling back (callback may
            # modify the timer, e.g. stop or restart it).
            if not timer.once:
                next_fire = timer.expires + timer.interval
                if next_fire < now:
                    # We fell behind — catch up instead of firing a burst.
                    next_fire = now + timer.interval
                timer._insert(next_fire)
            else:
                timer.expires = None

            # Invoke the callback — errors are caught so one bad timer
            # doesn't kill the whole timer queue.
            try:
                timer.callback()
            except Exception as exc:
                log.warn(f"timer error: {exc}")

    @classmethod
    def clear_all(cls) -> None:
        """
        Remove all timers from the queue.  Useful for testing and shutdown.
        """
        for t in cls._timers:
            t.expires = None
        cls._timers.clear()

    @classmethod
    def pending_count(cls) -> int:
        """Return the number of timers currently in the queue."""
        return len(cls._timers)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        state = "running" if self.expires is not None else "stopped"
        return (
            f"Timer(interval={self.interval}, once={self.once}, "
            f"state={state}, expires={self.expires})"
        )
