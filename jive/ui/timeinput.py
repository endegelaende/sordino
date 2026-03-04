"""
jive.ui.timeinput — Time picker widget for the Jivelite Python3 port.

Ported from ``Timeinput.lua`` (309 LOC) in the original jivelite project.

A Timeinput helper creates hour, minute, and optional AM/PM scroll-wheel
menus inside a given Window, allowing the user to pick a time by
scrolling through values.  Supports both 12-hour and 24-hour formats.

The widget creates three (or two for 24h) SimpleMenu instances arranged
side-by-side, with navigation between them via ``go`` and ``back``
actions.  The menus use ``snapToItemEnabled`` for a slot-machine feel
and ``itemsBeforeScroll`` to keep the selected value centered.

Architecture:

* The hour menu contains many copies of the hours (100× for 12h,
  50× for 24h) so that the user can scroll freely without hitting
  boundaries.  The initial selection is set to the middle of this
  large list, offset by the initial hour value.
* The minute menu similarly contains 20 copies of 0–59.
* For 12h mode, an AM/PM menu with 6 items (padded with empty strings)
  is shown.
* Focus moves hour → minute → (ampm) → done via ``go`` actions,
  and back via ``back`` actions.

Usage::

    from jive.ui.timeinput import Timeinput

    window = Window("time_input")
    ti = Timeinput(window, my_submit_callback,
                   init_time={"hour": 14, "minute": 30})
    window.show()

    # When the user finishes, my_submit_callback(hour, minute, ampm)
    # is called with the selected values as strings.

Copyright 2010 Logitech. All Rights Reserved. (original Lua implementation)
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
    Union,
)

from jive.ui.constants import EVENT_CONSUME
from jive.ui.group import Group
from jive.ui.icon import Icon
from jive.ui.label import Label
from jive.ui.simplemenu import SimpleMenu
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event
    from jive.ui.window import Window

__all__ = ["Timeinput"]

log = logger("jivelite.ui")


def _minute_string(minute: int) -> str:
    """Format a minute value as a zero-padded two-digit string."""
    if minute < 10:
        return "0" + str(minute)
    return str(minute)


class Timeinput:
    """
    Time-picker helper that populates a Window with hour/minute(/ampm)
    scroll-wheel menus.

    Parameters
    ----------
    window : Window
        The window to populate with time-input widgets.
    submit_callback : callable
        Called as ``submit_callback(hour, minute, ampm)`` when the user
        confirms the time selection.  ``hour`` and ``minute`` are
        strings; ``ampm`` is ``"AM"``, ``"PM"``, or ``None`` (24h mode).
    init_time : dict, optional
        Initial time values.  Keys: ``"hour"`` (int), ``"minute"`` (int),
        ``"ampm"`` (``"AM"`` or ``"PM"`` or ``None``).
    """

    __slots__ = (
        "window",
        "submit_callback",
        "init_hour",
        "init_minute",
        "init_ampm",
        "hour_menu",
        "minute_menu",
        "ampm_menu",
        "background",
        "menu_box",
    )

    def __init__(
        self,
        window: Window,
        submit_callback: Callable[..., Any],
        init_time: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.window: Window = window
        self.submit_callback: Callable[..., Any] = submit_callback

        self.init_hour: Optional[int] = None
        self.init_minute: Optional[int] = None
        self.init_ampm: Optional[str] = None

        if init_time and isinstance(init_time, dict):
            raw_hour = init_time.get("hour")
            if raw_hour is not None:
                try:
                    self.init_hour = int(raw_hour)
                except (ValueError, TypeError) as exc:
                    log.debug("init_hour parse: %s", exc)

            raw_minute = init_time.get("minute")
            if raw_minute is not None:
                try:
                    self.init_minute = int(raw_minute)
                except (ValueError, TypeError) as exc:
                    log.debug("init_minute parse: %s", exc)

            self.init_ampm = init_time.get("ampm")

        # Menu references (populated in _add_time_input_widgets)
        self.hour_menu: Optional[SimpleMenu] = None
        self.minute_menu: Optional[SimpleMenu] = None
        self.ampm_menu: Optional[SimpleMenu] = None
        self.background: Optional[Icon] = None
        self.menu_box: Optional[Icon] = None

        # Register the finish_operation action on the window
        self.window.add_action_listener(
            "finish_operation", self, self._done_action_wrapper
        )

        # Replace now-playing button with finish action
        self._replace_now_playing_button()

        # Build the time-input UI
        self._add_time_input_widgets()

    # ------------------------------------------------------------------
    # Done action
    # ------------------------------------------------------------------

    def _done_action_wrapper(self, obj: Any, event: Any = None) -> int:
        """Action listener wrapper for finish_operation."""
        return self._done_action()

    def _done_action(self) -> int:
        """
        Collect the selected time values and call the submit callback.
        """
        hour_text = self._get_middle_item_text(self.hour_menu)
        minute_text = self._get_middle_item_text(self.minute_menu)

        ampm_text: Optional[str] = None
        if self.ampm_menu is not None:
            ampm_text = self._get_middle_item_text(self.ampm_menu)

        self.window.hide()
        self.submit_callback(hour_text, minute_text, ampm_text)

        return int(EVENT_CONSUME)

    @staticmethod
    def _get_middle_item_text(menu: Optional[SimpleMenu]) -> str:
        """
        Get the text of the middle (selected) item in a SimpleMenu.

        Falls back to reading the ``selected`` attribute and using
        ``get_item()`` or list-based access.
        """
        if menu is None:
            return ""

        # Try the getMiddleIndex / getItem pattern first
        if hasattr(menu, "get_middle_index") and hasattr(menu, "get_item"):
            try:
                mid = menu.get_middle_index()
                item = menu.get_item(mid)
                if isinstance(item, dict):
                    return str(item.get("text", ""))
                return str(item)
            except (IndexError, AttributeError, TypeError) as exc:
                log.debug("get_middle_index fallback: %s", exc)

        # Fallback: use selected index and list access
        selected = getattr(menu, "selected", None)
        items = getattr(menu, "_items", None) or getattr(menu, "list", None)

        if selected is not None and items is not None:
            idx = selected - 1  # 1-based to 0-based
            if 0 <= idx < len(items):
                item = items[idx]
                if isinstance(item, dict):
                    return str(item.get("text", ""))
                return str(item)

        return ""

    # ------------------------------------------------------------------
    # Now-playing button replacement
    # ------------------------------------------------------------------

    def _replace_now_playing_button(self) -> None:
        """
        Replace the right-side button with a finish_operation action.
        """
        log.debug("replaceNowPlayingButton")
        if hasattr(self.window, "set_button_action"):
            self.window.set_button_action(
                "rbutton",
                "finish_operation",
                "finish_operation",
                "finish_operation",
                True,
            )
        elif hasattr(self.window, "setButtonAction"):
            self.window.setButtonAction(
                "rbutton",
                "finish_operation",
                "finish_operation",
                "finish_operation",
                True,
            )

    # ------------------------------------------------------------------
    # Style change helper
    # ------------------------------------------------------------------

    @staticmethod
    def _style_changed() -> None:
        """Trigger a framework-wide style refresh."""
        try:
            from jive.ui.framework import framework as fw

            fw.style_changed()
        except (ImportError, AttributeError) as exc:
            log.debug("import fallback: %s", exc)

    # ------------------------------------------------------------------
    # Build time-input widgets
    # ------------------------------------------------------------------

    def _add_time_input_widgets(self) -> None:
        """
        Build hour, minute, and (optionally) AM/PM menus and add them
        to the window.
        """
        hours: List[str] = []
        hour_menu_middle: int = 1

        # Determine 12h vs 24h mode
        is_12h = self.init_ampm is not None

        if is_12h:
            self.background = Icon("time_input_background_12h")
            self.menu_box = Icon("time_input_menu_box_12h")

            # 12h hour menu: 100 copies of 1..12
            hour_copies = 100
            for i in range(1, hour_copies + 1):
                for j in range(1, 13):
                    value = str(j)
                    # Blank out the edges to prevent visual artifacts
                    if (i == 1 and j < 3) or (i == hour_copies and j > 10):
                        value = ""
                    hours.append(value)
            hour_menu_middle = 12 * (hour_copies // 2) + 1

            # AM/PM menu
            self.ampm_menu = SimpleMenu("ampmUnselected")
            if hasattr(self.ampm_menu, "set_disable_vertical_bump"):
                self.ampm_menu.set_disable_vertical_bump(True)
            elif hasattr(self.ampm_menu, "setDisableVerticalBump"):
                self.ampm_menu.setDisableVerticalBump(True)

            if self.init_ampm == "AM":
                ampm_items = ["", "", "AM", "PM", "", ""]
            else:
                ampm_items = ["", "", "PM", "AM", "", ""]

            for t in ampm_items:
                self.ampm_menu.add_item(
                    {
                        "text": t,
                        "callback": lambda: int(EVENT_CONSUME),
                    }
                )

            # Configure AM/PM menu properties
            if hasattr(self.ampm_menu, "items_before_scroll"):
                self.ampm_menu.items_before_scroll = 2
            elif hasattr(self.ampm_menu, "itemsBeforeScroll"):
                self.ampm_menu.itemsBeforeScroll = 2

            if hasattr(self.ampm_menu, "snap_to_item_enabled"):
                self.ampm_menu.snap_to_item_enabled = True
            elif hasattr(self.ampm_menu, "snapToItemEnabled"):
                self.ampm_menu.snapToItemEnabled = True

            self.ampm_menu.selected = 3

            if hasattr(self.ampm_menu, "set_hide_scrollbar"):
                self.ampm_menu.set_hide_scrollbar(True)
            elif hasattr(self.ampm_menu, "setHideScrollbar"):
                self.ampm_menu.setHideScrollbar(True)

        else:
            # 24h mode
            self.background = Icon("time_input_background_24h")
            self.menu_box = Icon("time_input_menu_box_24h")

            hour_copies = 50
            for i in range(1, hour_copies + 1):
                for j in range(0, 24):
                    value = str(j)
                    if (i == 1 and j < 2) or (i == hour_copies and j > 21):
                        value = ""
                    hours.append(value)
            hour_menu_middle = 24 * (hour_copies // 2) + 1

        # ---- Hour menu (common to 12h and 24h) ----
        self.hour_menu = SimpleMenu("hour")
        if hasattr(self.hour_menu, "set_disable_vertical_bump"):
            self.hour_menu.set_disable_vertical_bump(True)
        elif hasattr(self.hour_menu, "setDisableVerticalBump"):
            self.hour_menu.setDisableVerticalBump(True)

        for hour_text in hours:
            self.hour_menu.add_item(
                {
                    "text": hour_text,
                    "callback": lambda: int(EVENT_CONSUME),
                }
            )

        # Configure hour menu
        if hasattr(self.hour_menu, "items_before_scroll"):
            self.hour_menu.items_before_scroll = 2
        elif hasattr(self.hour_menu, "itemsBeforeScroll"):
            self.hour_menu.itemsBeforeScroll = 2

        if hasattr(self.hour_menu, "snap_to_item_enabled"):
            self.hour_menu.snap_to_item_enabled = True
        elif hasattr(self.hour_menu, "snapToItemEnabled"):
            self.hour_menu.snapToItemEnabled = True

        # Set initial hour selection
        if self.init_hour is not None:
            if is_12h:
                # Subtract 1 for 12h (1-based hours)
                self.hour_menu.selected = hour_menu_middle + self.init_hour - 1
            else:
                self.hour_menu.selected = hour_menu_middle + self.init_hour
        else:
            self.hour_menu.selected = hour_menu_middle

        # ---- Minute menu ----
        self.minute_menu = SimpleMenu("minuteUnselected")
        if hasattr(self.minute_menu, "set_disable_vertical_bump"):
            self.minute_menu.set_disable_vertical_bump(True)
        elif hasattr(self.minute_menu, "setDisableVerticalBump"):
            self.minute_menu.setDisableVerticalBump(True)

        minutes: List[str] = []
        minute_copies = 20
        for i in range(1, minute_copies + 1):
            for j in range(0, 60):
                value = _minute_string(j)
                if (i == 1 and j < 2) or (i == minute_copies and j > 57):
                    value = ""
                minutes.append(value)
        minute_menu_middle = 60 * (minute_copies // 2) + 1

        for minute_text in minutes:
            self.minute_menu.add_item(
                {
                    "text": minute_text,
                    "callback": lambda: int(EVENT_CONSUME),
                }
            )

        # Configure minute menu
        if hasattr(self.minute_menu, "items_before_scroll"):
            self.minute_menu.items_before_scroll = 2
        elif hasattr(self.minute_menu, "itemsBeforeScroll"):
            self.minute_menu.itemsBeforeScroll = 2

        if self.init_minute is not None:
            self.minute_menu.selected = minute_menu_middle + self.init_minute
        else:
            self.minute_menu.selected = minute_menu_middle

        if hasattr(self.minute_menu, "snap_to_item_enabled"):
            self.minute_menu.snap_to_item_enabled = True
        elif hasattr(self.minute_menu, "snapToItemEnabled"):
            self.minute_menu.snapToItemEnabled = True

        # Hide scrollbars
        if hasattr(self.hour_menu, "set_hide_scrollbar"):
            self.hour_menu.set_hide_scrollbar(True)
        elif hasattr(self.hour_menu, "setHideScrollbar"):
            self.hour_menu.setHideScrollbar(True)

        if hasattr(self.minute_menu, "set_hide_scrollbar"):
            self.minute_menu.set_hide_scrollbar(True)
        elif hasattr(self.minute_menu, "setHideScrollbar"):
            self.minute_menu.setHideScrollbar(True)

        # ---- Action listeners for navigation between menus ----

        # Hour: back → hide window
        self.hour_menu.add_action_listener(
            "back",
            self,
            lambda obj, event: self._on_hour_back(),
        )

        # Hour: go → focus minute
        self.hour_menu.add_action_listener(
            "go",
            self,
            lambda obj, event: self._on_hour_go(),
        )

        # Minute: go → focus ampm (12h) or submit (24h)
        self.minute_menu.add_action_listener(
            "go",
            self,
            lambda obj, event: self._on_minute_go(),
        )

        # Minute: back → focus hour
        self.minute_menu.add_action_listener(
            "back",
            self,
            lambda obj, event: self._on_minute_back(),
        )

        if self.ampm_menu is not None:
            # AMPM: go → submit
            self.ampm_menu.add_action_listener(
                "go",
                self,
                lambda obj, event: self._on_ampm_go(),
            )

            # AMPM: back → focus minute
            self.ampm_menu.add_action_listener(
                "back",
                self,
                lambda obj, event: self._on_ampm_back(),
            )

        # ---- Add widgets to window ----
        if self.background is not None:
            self.window.add_widget(self.background)
        if self.menu_box is not None:
            self.window.add_widget(self.menu_box)
        self.window.add_widget(self.minute_menu)
        self.window.add_widget(self.hour_menu)
        if self.ampm_menu is not None:
            self.window.add_widget(self.ampm_menu)

        # Focus the hour menu initially
        if hasattr(self.window, "focus_widget"):
            self.window.focus_widget(self.hour_menu)
        elif hasattr(self.window, "focusWidget"):
            self.window.focusWidget(self.hour_menu)

    # ------------------------------------------------------------------
    # Navigation action handlers
    # ------------------------------------------------------------------

    def _on_hour_back(self) -> int:
        """Hour menu back action: hide the window."""
        self.window.hide()
        return int(EVENT_CONSUME)

    def _on_hour_go(self) -> int:
        """Hour menu go action: switch focus to minute menu."""
        if self.hour_menu is not None:
            self.hour_menu.set_style("hourUnselected")
        if self.minute_menu is not None:
            self.minute_menu.set_style("minute")
        self._style_changed()
        if hasattr(self.window, "focus_widget"):
            self.window.focus_widget(self.minute_menu)
        elif hasattr(self.window, "focusWidget"):
            self.window.focusWidget(self.minute_menu)
        return int(EVENT_CONSUME)

    def _on_minute_go(self) -> int:
        """Minute menu go action: focus ampm (12h) or submit (24h)."""
        if self.ampm_menu is not None:
            self.ampm_menu.set_style("ampm")
            if self.minute_menu is not None:
                self.minute_menu.set_style("minuteUnselected")
            self._style_changed()
            if hasattr(self.window, "focus_widget"):
                self.window.focus_widget(self.ampm_menu)
            elif hasattr(self.window, "focusWidget"):
                self.window.focusWidget(self.ampm_menu)
        else:
            # 24h mode: submit directly
            hour_text = self._get_middle_item_text(self.hour_menu)
            minute_text = self._get_middle_item_text(self.minute_menu)
            self.window.hide()
            self.submit_callback(hour_text, minute_text, None)
        return int(EVENT_CONSUME)

    def _on_minute_back(self) -> int:
        """Minute menu back action: switch focus back to hour menu."""
        if self.hour_menu is not None:
            self.hour_menu.set_style("hour")
        if self.minute_menu is not None:
            self.minute_menu.set_style("minuteUnselected")
        self._style_changed()
        if hasattr(self.window, "focus_widget"):
            self.window.focus_widget(self.hour_menu)
        elif hasattr(self.window, "focusWidget"):
            self.window.focusWidget(self.hour_menu)
        return int(EVENT_CONSUME)

    def _on_ampm_go(self) -> int:
        """AMPM menu go action: submit the time."""
        hour_text = self._get_middle_item_text(self.hour_menu)
        minute_text = self._get_middle_item_text(self.minute_menu)
        ampm_text = self._get_middle_item_text(self.ampm_menu)
        self.window.hide()
        self.submit_callback(hour_text, minute_text, ampm_text)
        return int(EVENT_CONSUME)

    def _on_ampm_back(self) -> int:
        """AMPM menu back action: switch focus back to minute menu."""
        if self.ampm_menu is not None:
            self.ampm_menu.set_style("ampmUnselected")
        if self.minute_menu is not None:
            self.minute_menu.set_style("minute")
        self._style_changed()
        if hasattr(self.window, "focus_widget"):
            self.window.focus_widget(self.minute_menu)
        elif hasattr(self.window, "focusWidget"):
            self.window.focusWidget(self.minute_menu)
        return int(EVENT_CONSUME)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_hour_menu(self) -> Optional[SimpleMenu]:
        """Return the hour SimpleMenu."""
        return self.hour_menu

    def get_minute_menu(self) -> Optional[SimpleMenu]:
        """Return the minute SimpleMenu."""
        return self.minute_menu

    def get_ampm_menu(self) -> Optional[SimpleMenu]:
        """Return the AM/PM SimpleMenu (None for 24h mode)."""
        return self.ampm_menu

    def is_12h(self) -> bool:
        """Return ``True`` if in 12-hour mode."""
        return self.ampm_menu is not None

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        mode = "12h" if self.is_12h() else "24h"
        return (
            f"Timeinput(mode={mode}, "
            f"init_hour={self.init_hour}, "
            f"init_minute={self.init_minute}, "
            f"init_ampm={self.init_ampm!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()
