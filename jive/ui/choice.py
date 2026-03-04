"""
jive.ui.choice — Choice widget for the Jivelite Python3 port.

Ported from ``Choice.lua`` in the original jivelite project.

A Choice widget lets the user select a value from a list of options by
cycling through them.  It extends :class:`~jive.ui.label.Label` and
displays the currently selected option as text.

Each activation (GO key, action event) advances to the next option,
wrapping around to the first option after the last.

Features:

* **Cyclic selection** — options wrap around in both directions
* **Closure callback** — notified on selection change with
  ``(choice, selected_index)`` (1-based index, matching the Lua
  original)
* **Label display** — the selected option text is shown via the
  inherited Label rendering
* **Action handling** — responds to ``EVENT_ACTION`` and the ``go``
  action
* **Sound** — plays the ``SELECT`` sound on change

Usage::

    choice = Choice(
        "choice",
        options=["On", "Off"],
        closure=lambda ch, idx: print(f"Selected index: {idx}"),
        selected_index=1,  # 1-based, "On" is selected
    )

    # Programmatic change
    choice.set_selected_index(2)  # selects "Off"

    # Read current state
    print(choice.get_selected())        # "Off"
    print(choice.get_selected_index())  # 2

Copyright 2010 Logitech. All Rights Reserved. (original Lua/C code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    List,
    Optional,
    Sequence,
)

from jive.ui.constants import (
    EVENT_ACTION,
    EVENT_CONSUME,
    EVENT_UNUSED,
    LAYER_ALL,
)
from jive.ui.label import Label
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event

__all__ = ["Choice"]

log = logger("jivelite.ui")


class Choice(Label):
    """
    A cyclic option-selector widget.

    Extends :class:`Label` and displays the currently selected option
    as text.  Each activation advances to the next option, wrapping
    around after the last.

    Parameters
    ----------
    style : str
        The style key used to look up skin parameters.
    options : list of str
        The list of option strings to cycle through.
    closure : callable
        Called as ``closure(choice, selected_index)`` whenever the
        selected option changes.  *selected_index* is **1-based** to
        match the Lua original.
    selected_index : int, optional
        The initially selected option (1-based).  Defaults to ``1``
        (the first option).
    """

    __slots__ = ("_options", "_selected_index", "closure")

    def __init__(
        self,
        style: str,
        options: Sequence[str],
        closure: Callable[..., Any],
        selected_index: int = 1,
    ) -> None:
        if not isinstance(style, str):
            raise TypeError(f"style must be a string, got {type(style).__name__}")
        if not isinstance(options, (list, tuple)):
            raise TypeError(
                f"options must be a list or tuple, got {type(options).__name__}"
            )
        if not callable(closure):
            raise TypeError(f"closure must be callable, got {type(closure).__name__}")
        if not isinstance(selected_index, int):
            raise TypeError(
                f"selected_index must be an int, got {type(selected_index).__name__}"
            )

        # Store options as a mutable list (1-based indexing internally)
        self._options: List[str] = list(options)
        self._selected_index: int = selected_index
        self.closure: Callable[..., Any] = closure

        # Clamp the initial index into valid range
        if len(self._options) > 0:
            self._selected_index = self._coerce_index(selected_index)
        else:
            self._selected_index = 0

        # Initialise the Label with the selected option text
        initial_value = (
            self._options[self._selected_index - 1]
            if self._selected_index > 0 and len(self._options) > 0
            else ""
        )
        super().__init__(style, initial_value)

        # Listen for ACTION events
        self.add_listener(
            EVENT_ACTION,
            lambda event: self._key_press(event),
        )

        # Also respond to the "go" action
        self.add_action_listener("go", self, Choice._change_and_select)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _coerce_index(self, index: int) -> int:
        """
        Coerce *index* into the valid range ``[1, len(options)]``,
        wrapping around if out of bounds.

        Parameters
        ----------
        index : int
            A 1-based index that may be out of range.

        Returns
        -------
        int
            A valid 1-based index.  Returns 0 if options is empty.
        """
        n = len(self._options)
        if n == 0:
            return 0
        # Wrap around using modular arithmetic
        return ((index - 1) % n) + 1

    def _key_press(self, event: Event) -> int:
        """Handle an EVENT_ACTION by advancing the selection."""
        return self._change_and_select()

    def _change_and_select(self) -> int:
        """Advance to the next option, wrap around, and notify."""
        new_index = self._selected_index + 1
        self.set_selected_index(new_index)
        self.play_sound("SELECT")
        return EVENT_CONSUME

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_selected_index(self) -> int:
        """
        Return the 1-based index of the currently selected option.

        Returns
        -------
        int
            The selected index (1-based).  Returns 0 if options is empty.
        """
        return self._selected_index

    getSelectedIndex = get_selected_index

    def get_selected(self) -> Optional[str]:
        """
        Return the currently selected option string.

        Returns
        -------
        str or None
            The selected option text, or ``None`` if the options list
            is empty.
        """
        if self._selected_index <= 0 or len(self._options) == 0:
            return None
        return self._options[self._selected_index - 1]

    getSelected = get_selected

    def set_selected_index(self, selected_index: int) -> None:
        """
        Set the selected option by 1-based index.

        The index is coerced into the valid range by wrapping around
        (e.g. ``set_selected_index(len(options) + 1)`` selects the
        first option).

        This method calls the closure with the new selection.

        Parameters
        ----------
        selected_index : int
            The 1-based index of the option to select.
        """
        if not isinstance(selected_index, int):
            raise TypeError(
                f"selected_index must be an int, got {type(selected_index).__name__}"
            )

        coerced = self._coerce_index(selected_index)

        if self._selected_index == coerced:
            return

        self._selected_index = coerced

        # Update the displayed text
        if coerced > 0 and len(self._options) > 0:
            self.set_value(self._options[coerced - 1])

        # Notify the closure
        self.closure(self, self._selected_index)

    setSelectedIndex = set_selected_index

    # ------------------------------------------------------------------
    # Options management
    # ------------------------------------------------------------------

    @property
    def options(self) -> List[str]:
        """Return a copy of the current options list."""
        return list(self._options)

    @options.setter
    def options(self, new_options: Sequence[str]) -> None:
        """
        Replace the options list.

        The selected index is clamped to the new list size.

        Parameters
        ----------
        new_options : list of str
            The new options to use.
        """
        self._options = list(new_options)
        if len(self._options) == 0:
            self._selected_index = 0
            self.set_value("")
        else:
            self._selected_index = self._coerce_index(self._selected_index)
            self.set_value(self._options[self._selected_index - 1])

    def get_num_options(self) -> int:
        """Return the number of options."""
        return len(self._options)

    getNumOptions = get_num_options

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        selected = self.get_selected()
        return (
            f"Choice(index={self._selected_index}, "
            f"selected={selected!r}, "
            f"num_options={len(self._options)})"
        )

    def __str__(self) -> str:
        return self.__repr__()
