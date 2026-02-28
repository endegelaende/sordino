"""
jive.ui.radio — RadioGroup and RadioButton widgets for the Jivelite Python3 port.

Ported from ``RadioGroup.lua`` and ``RadioButton.lua`` in the original
jivelite project.

A RadioGroup is a logical container that ensures mutual exclusion among
its RadioButton members — only one RadioButton in a group can be selected
at any time.

A RadioButton extends :class:`~jive.ui.icon.Icon` and uses ``img_on`` /
``img_off`` style keys to display the appropriate image based on whether
it is the currently selected button in its group.

Features:

* **Mutual exclusion** — selecting one RadioButton deselects the previously
  selected button in the same RadioGroup
* **Closure callback** — each RadioButton's closure is called when it
  becomes selected
* **Action handling** — responds to ``EVENT_ACTION`` and the ``play`` action
* **Sound** — plays the ``SELECT`` sound when the selection changes
* **Style images** — automatically switches between ``img_on`` and ``img_off``
  via the inherited Icon ``img_style_name`` mechanism

Usage::

    group = RadioGroup()

    rb1 = RadioButton(
        "radio",
        group,
        closure=lambda rb: print("Button 1 selected"),
        selected=False,
    )
    rb2 = RadioButton(
        "radio",
        group,
        closure=lambda rb: print("Button 2 selected"),
        selected=True,
    )

    # Programmatic selection
    rb1.set_selected()

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
)
from jive.ui.icon import Icon
from jive.ui.widget import Widget
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event

__all__ = ["RadioGroup", "RadioButton"]

log = logger("jivelite.ui")


# ---------------------------------------------------------------------------
# RadioGroup
# ---------------------------------------------------------------------------


class RadioGroup(Widget):
    """
    A logical container for :class:`RadioButton` widgets.

    Ensures that at most one RadioButton in the group is selected at any
    time.  RadioGroup is **not** a visual widget — it is not added to the
    widget tree.  It only manages the selection state of its member buttons.

    Usage::

        group = RadioGroup()

        # Pass *group* to each RadioButton constructor.
        btn1 = RadioButton("radio", group, closure=..., selected=True)
        btn2 = RadioButton("radio", group, closure=...)
    """

    def __init__(self) -> None:
        # Widget base class requires a style string.  RadioGroup uses an
        # empty string because it is never rendered.
        super().__init__("")

        # The currently selected RadioButton (or None).
        self.selected: Optional[RadioButton] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_selected(self) -> Optional["RadioButton"]:
        """
        Return the currently selected :class:`RadioButton`, or ``None``
        if no button is selected.
        """
        return self.selected

    getSelected = get_selected

    def set_selected(self, button: "RadioButton") -> None:
        """
        Select *button*, deselecting the previously selected button (if
        any).

        Parameters
        ----------
        button : RadioButton
            The button to select.  Must be a :class:`RadioButton` instance.

        Raises
        ------
        TypeError
            If *button* is not a :class:`RadioButton`.
        """
        if not isinstance(button, RadioButton):
            raise TypeError(
                f"button must be a RadioButton, got {type(button).__name__}"
            )

        if self.selected is button:
            return

        last_selected = self.selected
        self.selected = button

        if last_selected is not None:
            last_selected._set(False)
        if button is not None:
            button._set(True)

    setSelected = set_selected

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        sel_repr = repr(self.selected) if self.selected is not None else "None"
        return f"RadioGroup(selected={sel_repr})"

    def __str__(self) -> str:
        return self.__repr__()


# ---------------------------------------------------------------------------
# RadioButton
# ---------------------------------------------------------------------------


class RadioButton(Icon):
    """
    A radio button widget that belongs to a :class:`RadioGroup`.

    Only one RadioButton in a group can be selected at any time.  Selecting
    a new button deselects the previous one.

    Extends :class:`~jive.ui.icon.Icon` and switches between ``img_on``
    and ``img_off`` style images based on the selection state.

    Parameters
    ----------
    style : str
        The style key used to look up skin parameters.
    group : RadioGroup
        The group this button belongs to.
    closure : callable
        Called as ``closure(radio_button)`` whenever this button becomes
        the selected button in its group.
    selected : bool, optional
        If ``True``, this button is immediately selected in *group*
        (default ``False``).
    """

    def __init__(
        self,
        style: str,
        group: RadioGroup,
        closure: Callable[..., Any] = lambda rb: None,
        selected: bool = False,
    ) -> None:
        if not isinstance(style, str):
            raise TypeError(f"style must be a string, got {type(style).__name__}")
        if not isinstance(group, RadioGroup):
            raise TypeError(f"group must be a RadioGroup, got {type(group).__name__}")
        if not callable(closure):
            raise TypeError("closure must be callable")
        if selected is not None and not isinstance(selected, bool):
            raise TypeError(
                f"selected must be a bool or None, got {type(selected).__name__}"
            )

        super().__init__(style)

        self.img_style_name: str = "img_off"
        self.group: RadioGroup = group

        # Initialize closure to None first so that ``_set()`` (called by
        # ``group.set_selected()``) does not crash with AttributeError.
        self.closure: Optional[Callable[..., Any]] = None

        # Select *before* setting the real closure so that the initial
        # ``group.set_selected()`` does not fire the closure (matching
        # the Lua original which sets ``obj.closure`` after the initial
        # selection).
        if selected:
            group.set_selected(self)

        # Now store the real closure so future selections will invoke it.
        self.closure = closure

        # Listen for ACTION events (e.g. from GO key press forwarded by
        # a menu).
        self.add_listener(
            EVENT_ACTION,
            lambda event: self._action(),
        )

        # Also respond to the "play" action.
        self.add_action_listener("play", self, RadioButton._action)

    # ------------------------------------------------------------------
    # Action handler
    # ------------------------------------------------------------------

    def _action(self) -> int:
        """
        Select this radio button in its group.

        Plays the ``SELECT`` sound if the selection actually changed.
        """
        log.debug("RadioButton._action()")

        old_selected = self.group.selected
        self.group.set_selected(self)
        if old_selected is not self.group.selected:
            self.play_sound("SELECT")

        return EVENT_CONSUME

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_selected(self) -> bool:
        """
        Return ``True`` if this radio button is the currently selected
        button in its group, ``False`` otherwise.
        """
        return self.group.get_selected() is self

    isSelected = is_selected

    def set_selected(self) -> None:
        """
        Make this radio button the selected button in its group.

        The closure **is** called (via the group's ``set_selected``
        → ``_set(True)`` pathway).
        """
        self.group.set_selected(self)

    setSelected = set_selected

    # ------------------------------------------------------------------
    # Internal — called by RadioGroup to flip state
    # ------------------------------------------------------------------

    def _set(self, selected: bool) -> None:
        """
        Called by :class:`RadioGroup` to update this button's visual
        state and (when becoming selected) fire the closure.

        Parameters
        ----------
        selected : bool
            ``True`` if this button is now selected, ``False`` otherwise.
        """
        log.debug("RadioButton._set(%s)", selected)

        if selected:
            self.img_style_name = "img_on"
            if self.closure is not None:
                self.closure(self)
        else:
            self.img_style_name = "img_off"

        self.re_skin()

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        sel = self.is_selected()
        return f"RadioButton(selected={sel})"

    def __str__(self) -> str:
        return self.__repr__()
