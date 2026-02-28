"""
jive.ui.popup — Popup window widget for the Jivelite Python3 port.

Ported from ``Popup.lua`` in the original jivelite project.

A Popup is a transient :class:`~jive.ui.window.Window` subclass used for
modal overlay windows (e.g. "now playing" popups, volume indicators,
waiting spinners).  It appears on top of the current window with no
transition animation by default, and auto-hides on any button input.

Key behaviours that differ from a regular Window:

* **Transparent** — the window beneath is drawn first, then the popup
  on top (the popup does not fill the full screen)
* **Transient** — automatically removed from the stack when another
  window is pushed
* **Auto-hide** — closes on any key/mouse input by default
  (``hide_on_all_button_input``)
* **No screensaver** — the screensaver is suppressed while a popup is
  visible
* **No framework widgets** — the title bar / button bar from the
  framework is not shown
* **No transitions** — appears and disappears instantly by default
* **maskImg** — optional :class:`~jive.ui.tile.Tile` painted over any
  parts of the lower window visible behind the popup

Usage::

    popup = Popup("waiting_popup", "Please wait…")
    popup.show()

    # … later …
    popup.hide()

Copyright 2010 Logitech. All Rights Reserved. (original Lua/C code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Optional,
    Union,
)

from jive.ui.window import Window, transition_none
from jive.utils.log import logger

if TYPE_CHECKING:
    pass

__all__ = ["Popup"]

log = logger("jivelite.ui")


class Popup(Window):
    """
    A popup window widget — a transient, transparent overlay.

    Extends :class:`Window` with defaults suited for modal popups:
    transparent background, no transitions, auto-hide on button input,
    no screensaver, no framework widgets (title/button bar).

    Parameters
    ----------
    style : str
        The style key used to look up skin parameters.
    title : str, optional
        An optional title string for the popup.
    """

    def __init__(
        self,
        style: str,
        title: Optional[str] = None,
    ) -> None:
        if not isinstance(style, str):
            raise TypeError(f"style must be a string, got {type(style).__name__}")

        super().__init__(style, title)

        # Override default transitions — popups appear/disappear instantly
        self._DEFAULT_SHOW_TRANSITION = transition_none
        self._DEFAULT_HIDE_TRANSITION = transition_none

        # Popup-specific defaults (matching the Lua original)
        self.set_allow_screensaver(False)
        self.set_auto_hide(True)
        self.set_show_framework_widgets(False)
        self.set_transparent(True)
        self.set_transient(True)

        # By default, close popup on any key/mouse press
        self.hide_on_all_button_input()

    # ------------------------------------------------------------------
    # Layout override
    # ------------------------------------------------------------------

    def border_layout(self, fit_window: bool = False) -> None:
        """
        Perform border layout with ``fit_window=True``.

        Popups use fit-to-content sizing so they don't fill the entire
        screen — only the region needed by their child widgets.
        """
        super().border_layout(fit_window=True)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        title = self.get_title()
        title_part = f", title={title!r}" if title else ""
        return f"Popup(style={self.style!r}{title_part})"

    def __str__(self) -> str:
        return self.__repr__()
