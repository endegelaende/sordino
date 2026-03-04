"""
jive.ui.checkbox — Checkbox widget for the Jivelite Python3 port.

Ported from ``Checkbox.lua`` in the original jivelite project.

A Checkbox widget displays a toggleable on/off state using images from
the active skin.  It extends :class:`~jive.ui.icon.Icon` and uses
``img_on`` / ``img_off`` style keys to display the appropriate image.

Features:

* **Toggle state** — ``is_selected()`` / ``set_selected()``
* **Closure callback** — notified on state change with ``(checkbox, is_selected)``
* **Action handling** — responds to ``EVENT_ACTION`` and the ``play`` action
* **Sound** — plays the ``SELECT`` sound on toggle
* **Style images** — automatically switches between ``img_on`` and ``img_off``
  via the inherited Icon ``img_style_name`` mechanism

Usage::

    checkbox = Checkbox(
        "checkbox",
        closure=lambda cb, sel: print(f"Selected: {sel}"),
        is_selected=True,
    )

    # Programmatic toggle
    checkbox.set_selected(False)

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
)

from jive.ui.constants import (
    EVENT_ACTION,
    EVENT_CONSUME,
    EVENT_UNUSED,
    LAYER_ALL,
)
from jive.ui.icon import Icon
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event

__all__ = ["Checkbox"]

log = logger("jivelite.ui")


class Checkbox(Icon):
    """
    A checkbox widget that toggles between selected and deselected states.

    Extends :class:`Icon` and switches between ``img_on`` and ``img_off``
    style images based on the current selection state.

    Parameters
    ----------
    style : str
        The style key used to look up skin parameters.
    closure : callable, optional
        Called as ``closure(checkbox, is_selected)`` whenever the checkbox
        state changes.  May be *None*.
    is_selected : bool, optional
        Initial selection state (default ``False``).
    """

    __slots__ = ("selected", "closure")

    def __init__(
        self,
        style: str,
        closure: Optional[Callable[..., Any]] = None,
        is_selected: bool = False,
    ) -> None:
        if not isinstance(style, str):
            raise TypeError(f"style must be a string, got {type(style).__name__}")
        if not isinstance(is_selected, bool):
            raise TypeError(
                f"is_selected must be a bool, got {type(is_selected).__name__}"
            )

        super().__init__(style)

        # Use a sentinel so that set_selected() doesn't short-circuit
        # on the initial call (even when is_selected is False).
        self.selected: bool = not is_selected
        self.closure: Optional[Callable[..., Any]] = None

        # Set initial state (without calling closure)
        self.set_selected(is_selected)

        # Now set the closure so future changes invoke it
        self.closure = closure

        # Listen for ACTION events (e.g. from GO key press forwarded by menu)
        self.add_listener(
            EVENT_ACTION,
            lambda event: self._action(),
        )

        # Also respond to the "play" action
        self.add_action_listener("play", self, Checkbox._action)

    # ------------------------------------------------------------------
    # Action handler
    # ------------------------------------------------------------------

    def _action(self) -> int:
        """Toggle the checkbox state and notify the closure."""
        self.set_selected(not self.selected)
        self.play_sound("SELECT")

        if self.closure is not None:
            self.closure(self, self.selected)

        return EVENT_CONSUME

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_selected(self) -> bool:
        """
        Return ``True`` if the checkbox is currently selected (checked),
        ``False`` otherwise.
        """
        return self.selected

    isSelected = is_selected

    def set_selected(self, is_selected: bool) -> None:
        """
        Set the checkbox state.

        Parameters
        ----------
        is_selected : bool
            ``True`` to check, ``False`` to uncheck.

        Notes
        -----
        If a closure is set and the state actually changes, the closure
        is **not** called by this method — only by user interaction
        (``_action``).  This matches the Lua original's behaviour where
        ``setSelected`` triggers a re-skin but does not fire the closure
        (the closure is only invoked from ``_action``).
        """
        if not isinstance(is_selected, bool):
            raise TypeError(
                f"is_selected must be a bool, got {type(is_selected).__name__}"
            )

        if self.selected == is_selected:
            return

        self.selected = is_selected

        if is_selected:
            self.img_style_name = "img_on"
        else:
            self.img_style_name = "img_off"

        self.re_skin()

    setSelected = set_selected

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Checkbox(selected={self.selected})"

    def __str__(self) -> str:
        return self.__repr__()
