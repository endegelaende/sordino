"""
jive.ui.scrollaccel — Accelerated scroll event filter for the Jivelite Python3 port.

Ported from ``ScrollAccel.lua`` in the original jivelite project.

A ScrollAccel extends :class:`~jive.ui.scrollwheel.ScrollWheel` and adds
acceleration to scroll events.  The longer the user scrolls in the same
direction without pausing, the faster the scroll delta increases.

Acceleration tiers (based on consecutive scroll count):

* 1–10: 1× (no acceleration — delegates to ScrollWheel)
* 11–20: 2×
* 21–30: 4×
* 31–40: 8×
* 41–50: 16×
* 50+: max(list_size / 50, |scroll| × 16)

Acceleration resets when:

* The scroll direction changes
* More than 250 ms passes between scroll events (per unit of scroll)

Usage::

    accel = ScrollAccel()

    # In a scroll event handler:
    delta = accel.event(scroll_event, list_top, list_index,
                        list_visible, list_size)
    # delta may be > 1 when accelerated

Copyright 2010 Logitech. All Rights Reserved. (original Lua/C code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
from typing import (
    TYPE_CHECKING,
    Callable,
    Optional,
)

from jive.ui.scrollwheel import ScrollWheel
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event

__all__ = ["ScrollAccel"]

log = logger("jivelite.ui")


class ScrollAccel(ScrollWheel):
    """
    Accelerated scroll event filter.

    Extends :class:`ScrollWheel` with acceleration that increases the
    scroll delta the longer the user scrolls in the same direction
    without pausing.

    Parameters
    ----------
    item_available : callable, optional
        A function ``item_available(list_top, list_visible) -> bool``
        that returns ``True`` if the items starting at *list_top* for
        *list_visible* count are loaded and available.  Defaults to a
        function that always returns ``True``.
    """

    __slots__ = ("_list_index", "_scroll_dir", "_scroll_last_t", "_scroll_accel")

    def __init__(
        self,
        item_available: Optional[Callable[[int, int], bool]] = None,
    ) -> None:
        super().__init__(item_available)

        self._list_index: int = 1
        self._scroll_dir: int = 0
        self._scroll_last_t: int = 0
        self._scroll_accel: Optional[int] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def event(
        self,
        event: Event,
        list_top: int,
        list_index: int,
        list_visible: int,
        list_size: int,
    ) -> int:
        """
        Process a scroll event and return the (possibly accelerated) delta.

        Parameters
        ----------
        event : Event
            The scroll event (must support ``get_scroll()`` and
            ``get_ticks()``).
        list_top : int
            1-based index of the item at the top of the visible area.
        list_index : int
            1-based index of the currently selected item.
        list_visible : int
            Number of items visible on screen at once.
        list_size : int
            Total number of items in the list.

        Returns
        -------
        int
            The number of items to move by.  Positive values scroll down,
            negative values scroll up.  May be larger than 1 when
            acceleration is active.
        """
        scroll = event.get_scroll()

        # Update timing state
        now = event.get_ticks()
        abs_scroll = abs(scroll)
        if abs_scroll == 0:
            abs_scroll = 1
        time_delta = (now - self._scroll_last_t) / abs_scroll

        direction = 1 if scroll > 0 else -1

        self._list_index = list_index or 1
        self._scroll_last_t = now

        # Reset acceleration if direction changed or user paused scrolling
        if direction != self._scroll_dir or time_delta > 250:
            self._scroll_accel = None
            self._scroll_dir = direction

            # Delegate to base class for non-accelerated single-step
            return super().event(event, list_top, list_index, list_visible, list_size)

        self._scroll_dir = direction

        # Increment the acceleration counter
        if self._scroll_accel is not None:
            self._scroll_accel += 1
        else:
            self._scroll_accel = 1

        # Apply acceleration tiers (matching the Lua original)
        accel = self._scroll_accel
        if accel > 50:
            delta = direction * max(
                math.ceil(list_size / 50),
                abs(scroll) * 16,
            )
        elif accel > 40:
            delta = scroll * 16
        elif accel > 30:
            delta = scroll * 8
        elif accel > 20:
            delta = scroll * 4
        elif accel > 10:
            delta = scroll * 2
        else:
            delta = scroll

        # Check that the target data is loaded before allowing the jump
        target_top = list_top + delta + (list_index - list_top)
        if not self._check_item_available(target_top, list_visible, list_size):
            # FIXME: ideally we should look ahead and limit acceleration
            # so as not to reach un-loaded parts of the list.
            delta = 0

        return delta

    # ------------------------------------------------------------------
    # State inspection
    # ------------------------------------------------------------------

    @property
    def scroll_accel(self) -> Optional[int]:
        """
        Return the current acceleration counter.

        ``None`` when acceleration is inactive, otherwise a positive
        integer indicating how many consecutive same-direction scroll
        events have been seen.
        """
        return self._scroll_accel

    @property
    def scroll_dir(self) -> int:
        """
        Return the last scroll direction.

        ``+1`` for down, ``-1`` for up, ``0`` for no scroll yet.
        """
        return self._scroll_dir

    def reset(self) -> None:
        """
        Reset the acceleration state.

        This is useful when the list content changes or the widget
        regains focus.
        """
        self._scroll_accel = None
        self._scroll_dir = 0
        self._scroll_last_t = 0

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        accel_str = str(self._scroll_accel) if self._scroll_accel is not None else "off"
        return f"ScrollAccel(accel={accel_str}, dir={self._scroll_dir})"

    def __str__(self) -> str:
        return self.__repr__()
