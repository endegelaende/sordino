"""
jive.ui.stickymenu — Sticky menu widget for the Jivelite Python3 port.

Ported from ``StickyMenu.lua`` in the original jivelite project.

A StickyMenu is a :class:`~jive.ui.simplemenu.SimpleMenu` subclass that
adds "sticky" scroll resistance — the user must scroll multiple times
in the same direction before the menu actually moves.  This is useful
for menus where accidental scrolling should be prevented (e.g. a
now-playing screen with large cover art).

The *multiplier* parameter controls how many scroll events are required
before the menu scrolls by one position.  For example, a multiplier of
``3`` means the user must scroll 3 times in the same direction before
the selection moves.

Features:

* **Sticky scrolling** — requires *multiplier* scroll events before
  moving, reducing accidental scroll on touch interfaces
* **Direction-aware** — sticky counters are tracked independently for
  up and down; changing direction resets the opposite counter
* **Header widget support** — delegates ``handleMenuHeaderWidgetScrollBy``
  to the header widget when present
* **Full SimpleMenu API** — inherits all item management, sorting,
  callback, and rendering features from SimpleMenu

Usage::

    menu = StickyMenu(
        "menu",
        multiplier=3,
        items=[
            {"text": "Item 1", "callback": callback1},
            {"text": "Item 2", "callback": callback2},
        ],
    )

Copyright 2010 Logitech. All Rights Reserved. (original Lua/C code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
)

from jive.ui.menu import Menu
from jive.ui.simplemenu import SimpleMenu
from jive.utils.log import logger

if TYPE_CHECKING:
    pass

__all__ = ["StickyMenu"]

log = logger("jivelite.ui")


class StickyMenu(SimpleMenu):
    """
    A menu with "sticky" scroll resistance.

    Extends :class:`SimpleMenu` and overrides ``scroll_by`` so that
    the user must scroll *multiplier* times in the same direction
    before the menu actually moves.

    Parameters
    ----------
    style : str
        The style key used to look up skin parameters.
    multiplier : int, optional
        How many scroll events are required before the menu scrolls
        by one position.  Defaults to ``1`` (no stickiness — behaves
        like a normal SimpleMenu).
    items : list of dict, optional
        Initial list of item dicts (see :class:`SimpleMenu` for the
        expected dict format).
    """

    def __init__(
        self,
        style: str,
        multiplier: int = 1,
        items: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> None:
        if not isinstance(style, str):
            raise TypeError(f"style must be a string, got {type(style).__name__}")
        if not isinstance(multiplier, int) or multiplier < 1:
            raise ValueError(
                f"multiplier must be a positive integer, got {multiplier!r}"
            )

        super().__init__(style)

        self._multiplier: int = multiplier
        self._sticky_down: int = 1
        self._sticky_up: int = 1

        # Set initial items if provided
        if items is not None:
            self.set_items(list(items))

    # ------------------------------------------------------------------
    # Scroll override
    # ------------------------------------------------------------------

    def scroll_by(
        self,
        scroll: int,
        allow_scroll_past: bool = False,
        update_scrollbar: bool = True,
    ) -> None:
        """
        Scroll the menu by *scroll* positions, applying sticky resistance.

        The menu only actually scrolls after *multiplier* consecutive
        scroll events in the same direction.  Scrolling in the opposite
        direction resets the counter for the previous direction.

        Parameters
        ----------
        scroll : int
            The number of positions to scroll.  Positive values scroll
            down, negative values scroll up.
        allow_scroll_past : bool, optional
            Whether to allow scrolling past list boundaries (passed
            through to the base ``Menu.scroll_by``).
        update_scrollbar : bool, optional
            Whether to update the scrollbar after scrolling (passed
            through to the base ``Menu.scroll_by``).
        """
        if scroll > 0:
            # Scrolling down — reset the upward sticky counter
            self._sticky_up = 1

            if self._sticky_down >= self._multiplier:
                # Enough scrolls accumulated — actually scroll
                log.debug(
                    "StickyMenu: scroll down (sticky_down=%d, multiplier=%d)",
                    self._sticky_down,
                    self._multiplier,
                )
                Menu.scroll_by(self, scroll, allow_scroll_past, update_scrollbar)

                # Notify header widget if present
                if self.header_widget is not None and hasattr(
                    self.header_widget, "handle_menu_header_widget_scroll_by"
                ):
                    self.header_widget.handle_menu_header_widget_scroll_by(scroll, self)

                self._sticky_down = 1
            else:
                self._sticky_down += 1
                log.debug(
                    "StickyMenu: don't scroll down yet %d (%d)",
                    self._sticky_down,
                    self._multiplier,
                )

        elif scroll < 0:
            # Scrolling up — reset the downward sticky counter
            self._sticky_down = 1

            if self._sticky_up >= self._multiplier:
                # Enough scrolls accumulated — actually scroll
                log.debug(
                    "StickyMenu: scroll up (sticky_up=%d, multiplier=%d)",
                    self._sticky_up,
                    self._multiplier,
                )
                Menu.scroll_by(self, scroll, allow_scroll_past, update_scrollbar)

                # Notify header widget if present
                if self.header_widget is not None and hasattr(
                    self.header_widget, "handle_menu_header_widget_scroll_by"
                ):
                    self.header_widget.handle_menu_header_widget_scroll_by(scroll, self)

                self._sticky_up = 1
            else:
                self._sticky_up += 1
                log.debug(
                    "StickyMenu: don't scroll up yet %d",
                    self._sticky_up,
                )

        # scroll == 0 — do nothing

    scrollBy = scroll_by

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def multiplier(self) -> int:
        """
        Return the sticky multiplier.

        This is the number of consecutive same-direction scroll events
        required before the menu actually moves.
        """
        return self._multiplier

    @multiplier.setter
    def multiplier(self, value: int) -> None:
        """
        Set the sticky multiplier.

        Parameters
        ----------
        value : int
            Must be a positive integer (>= 1).
        """
        if not isinstance(value, int) or value < 1:
            raise ValueError(f"multiplier must be a positive integer, got {value!r}")
        self._multiplier = value
        # Reset counters when multiplier changes
        self._sticky_down = 1
        self._sticky_up = 1

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def reset_sticky(self) -> None:
        """
        Reset the sticky scroll counters.

        This should be called when the menu content changes or the
        widget regains focus, so that the user doesn't have to
        "complete" a partially-accumulated sticky scroll.
        """
        self._sticky_down = 1
        self._sticky_up = 1

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        n = self.num_items()
        return (
            f"StickyMenu(multiplier={self._multiplier}, "
            f"items={n}, "
            f"sticky_down={self._sticky_down}, "
            f"sticky_up={self._sticky_up})"
        )

    def __str__(self) -> str:
        return self.__repr__()
