"""
jive.ui.scrollwheel — Non-accelerated scroll event filter for the Jivelite Python3 port.

Ported from ``ScrollWheel.lua`` in the original jivelite project.

A ScrollWheel filters scroll events and returns a normalised scroll
direction (``+1`` or ``-1``), ignoring the magnitude of the original
scroll amount.  This is the base class for scroll handling — subclasses
like :class:`~jive.ui.scrollaccel.ScrollAccel` add acceleration.

The optional *item_available* callback can be used to prevent scrolling
into regions of a list that have not yet been loaded (e.g. when items
are fetched lazily from a server).

Usage::

    wheel = ScrollWheel()

    # In a scroll event handler:
    delta = wheel.event(scroll_event, list_top, list_index,
                        list_visible, list_size)
    # delta is +1, -1, or 0

Copyright 2010 Logitech. All Rights Reserved. (original Lua/C code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Callable,
    Optional,
)

from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event

__all__ = ["ScrollWheel"]

log = logger("jivelite.ui")


class ScrollWheel:
    """
    Non-accelerated scroll event filter.

    Normalises scroll events to ``+1`` (down) or ``-1`` (up),
    regardless of the original scroll magnitude.

    Parameters
    ----------
    item_available : callable, optional
        A function ``item_available(list_top, list_visible) -> bool``
        that returns ``True`` if the items starting at *list_top* for
        *list_visible* count are loaded and available.  Defaults to a
        function that always returns ``True``.
    """

    __slots__ = ("_item_available",)

    def __init__(
        self,
        item_available: Optional[Callable[[int, int], bool]] = None,
    ) -> None:
        if item_available is not None and not callable(item_available):
            raise TypeError(
                f"item_available must be callable, got {type(item_available).__name__}"
            )
        self._item_available: Callable[[int, int], bool] = (
            item_available if item_available is not None else _default_item_available
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_item_available(
        self,
        list_top: int,
        list_visible: int,
        list_size: int,
    ) -> bool:
        """
        Check whether items in the given range are available.

        Clamps *list_top* and *list_visible* to valid bounds before
        calling the user-supplied ``item_available`` callback.

        Parameters
        ----------
        list_top : int
            1-based index of the first visible item.
        list_visible : int
            Number of items visible on screen.
        list_size : int
            Total number of items in the list.

        Returns
        -------
        bool
            ``True`` if the items are available.
        """
        # Clamp visible count to list size
        if list_visible > list_size:
            list_visible = list_size

        # Clamp top so that top + visible doesn't exceed size
        if list_top + list_visible > list_size:
            list_top = list_size - list_visible

        # Ensure top is at least 1 (1-based indexing, matching Lua)
        if list_top < 1:
            list_top = 1

        return self._item_available(list_top, list_visible)

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
        Process a scroll event and return the scroll delta.

        For non-accelerated scrolling, the delta is always ``+1``,
        ``-1``, or ``0`` (if items are not available).

        Parameters
        ----------
        event : Event
            The scroll event (must support ``get_scroll()``).
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
            ``+1`` to move selection down, ``-1`` to move up, or ``0``
            if scrolling is blocked (e.g. items not loaded).
        """
        scroll = event.get_scroll()

        # Normalise to direction only — +1 or -1
        direction = 1 if scroll > 0 else -1

        # Check that the target region is loaded before allowing scroll
        target_top = list_index + direction + (list_index - list_top)
        if not self._check_item_available(target_top, list_visible, list_size):
            direction = 0

        return direction

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def item_available(self) -> Callable[[int, int], bool]:
        """Return the current item-availability callback."""
        return self._item_available

    @item_available.setter
    def item_available(self, func: Callable[[int, int], bool]) -> None:
        """
        Replace the item-availability callback.

        Parameters
        ----------
        func : callable
            A function ``func(list_top, list_visible) -> bool``.
        """
        if not callable(func):
            raise TypeError(
                f"item_available must be callable, got {type(func).__name__}"
            )
        self._item_available = func

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"ScrollWheel()"

    def __str__(self) -> str:
        return self.__repr__()


# ======================================================================
# Module-level helpers
# ======================================================================


def _default_item_available(list_top: int, list_visible: int) -> bool:
    """Default item-availability function — always returns ``True``."""
    return True
