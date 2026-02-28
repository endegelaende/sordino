"""
jive.iconbar — Status icon bar at the bottom of the screen.

Ported from ``jive/Iconbar.lua`` in the original jivelite project.

The Iconbar displays status icons at the bottom of the screen including:

* **Playmode** — stop, play, pause
* **Repeat** — off, single track (1), all tracks (2)
* **Shuffle** — off, by track (1), by album (2)
* **Battery** — none, charging, AC, 0-4 levels
* **Wireless** — none, error, ethernet, signal strength 0-4
* **Sleep** — on/off
* **Alarm** — on/off
* **Time** — current time display, refreshed every second

The Iconbar refreshes itself every second via a timer.

Usage::

    from jive.iconbar import Iconbar

    iconbar = Iconbar(jnt)

    # Update playmode icon
    iconbar.set_playmode("play")

    # Update wireless signal strength
    iconbar.set_wireless_signal(3)

    # Force update
    iconbar.update()

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Optional, Union

from jive.utils.log import logger

if TYPE_CHECKING:
    pass

__all__ = ["Iconbar"]

log = logger("jivelite.iconbar")


class _IconStub:
    """Minimal stub for Icon widget when UI is not yet available.

    Holds a style name string.  When the real UI is wired up, these
    are replaced with actual ``Icon`` widget instances.
    """

    __slots__ = ("_style",)

    def __init__(self, style: str = "") -> None:
        self._style = style

    def set_style(self, style: str) -> None:
        self._style = style

    def get_style(self) -> str:
        return self._style

    # Lua-compatible camelCase aliases
    setStyle = set_style
    getStyle = get_style

    def __repr__(self) -> str:
        return f"_IconStub({self._style!r})"


class _LabelStub:
    """Minimal stub for Label widget when UI is not yet available."""

    __slots__ = ("_style", "_value")

    def __init__(self, style: str = "", value: str = "") -> None:
        self._style = style
        self._value = value

    def set_value(self, value: str) -> None:
        self._value = value

    def get_value(self) -> str:
        return self._value

    def set_style(self, style: str) -> None:
        self._style = style

    # Lua-compatible camelCase aliases
    setValue = set_value
    getValue = get_value
    setStyle = set_style

    def add_timer(self, interval_ms: int, callback: Any) -> None:
        """Stub — real timer is set up when wired to the UI."""
        pass

    def __repr__(self) -> str:
        return f"_LabelStub({self._style!r}, {self._value!r})"


class _GroupStub:
    """Minimal stub for Group widget when UI is not yet available."""

    __slots__ = ("_style", "_widgets")

    def __init__(self, style: str = "", widgets: Optional[dict] = None) -> None:
        self._style = style
        self._widgets = widgets or {}

    def __repr__(self) -> str:
        return f"_GroupStub({self._style!r})"


class Iconbar:
    """Icon bar at the bottom of the screen.

    Manages a set of status icons and a time label that are displayed
    in the UI framework's global widget area.

    Parameters
    ----------
    jnt:
        The network thread / notification hub.  Used to emit
        ``networkAndServerOK`` / ``networkOrServerNotOK`` notifications
        when the combined network+server state changes.
    use_stubs:
        If ``True`` (default), use lightweight stub objects for icons/labels
        instead of importing the real UI widgets.  Set to ``False`` when
        the full UI framework is initialized.
    """

    def __init__(self, jnt: Any = None, *, use_stubs: bool = True) -> None:
        log.debug("Iconbar.__init__()")

        self.jnt = jnt

        # --- Icon widgets (stubs or real) ---
        if use_stubs:
            self.icon_playmode = _IconStub("button_playmode_OFF")
            self.icon_repeat = _IconStub("button_repeat_OFF")
            self.icon_shuffle = _IconStub("button_shuffle_OFF")
            self.icon_battery = _IconStub("button_battery_NONE")
            self.icon_wireless = _IconStub("button_wireless_NONE")
            self.icon_sleep = _IconStub("button_sleep_OFF")
            self.icon_alarm = _IconStub("button_alarm_OFF")
            self.button_time = _LabelStub("button_time", "XXXX")
            self.iconbar_group = _GroupStub(
                "iconbar_group",
                {
                    "play": self.icon_playmode,
                    "repeat_mode": self.icon_repeat,
                    "shuffle": self.icon_shuffle,
                    "alarm": self.icon_alarm,
                    "sleep": self.icon_sleep,
                    "battery": self.icon_battery,
                    "wireless": self.icon_wireless,
                },
            )
        else:
            self._init_real_widgets()

        # --- State tracking ---
        self.wireless_signal: Optional[Union[str, int]] = None
        self.iface: Optional[str] = None
        self.server_error: Optional[str] = None
        self._old_network_and_server_state: Optional[bool] = None

        # Debug overlay
        self._debug_timeout: Optional[float] = None

        # Initial update
        self.update()

    def _init_real_widgets(self) -> None:
        """Initialize with real UI widgets.

        Called when ``use_stubs=False``.  Imports the actual UI widget
        classes and creates instances.  Also registers widgets with
        the Framework and sets up the 1-second timer.
        """
        try:
            from jive.ui.framework import framework
            from jive.ui.group import Group
            from jive.ui.icon import Icon
            from jive.ui.label import Label

            self.icon_playmode = Icon("button_playmode_OFF")
            self.icon_repeat = Icon("button_repeat_OFF")
            self.icon_shuffle = Icon("button_shuffle_OFF")
            self.icon_battery = Icon("button_battery_NONE")
            self.icon_wireless = Icon("button_wireless_NONE")
            self.icon_sleep = Icon("button_sleep_OFF")
            self.icon_alarm = Icon("button_alarm_OFF")
            self.button_time = Label("button_time", "XXXX")

            self.iconbar_group = Group(
                "iconbar_group",
                {
                    "play": self.icon_playmode,
                    "repeat_mode": self.icon_repeat,
                    "shuffle": self.icon_shuffle,
                    "alarm": self.icon_alarm,
                    "sleep": self.icon_sleep,
                    "battery": self.icon_battery,
                    "wireless": self.icon_wireless,
                },
            )

            framework.add_widget(self.iconbar_group)
            framework.add_widget(self.button_time)

            self.button_time.add_timer(1000, lambda: self.update())
        except ImportError:
            log.warn("Real UI widgets not available, falling back to stubs")
            self.icon_playmode = _IconStub("button_playmode_OFF")
            self.icon_repeat = _IconStub("button_repeat_OFF")
            self.icon_shuffle = _IconStub("button_shuffle_OFF")
            self.icon_battery = _IconStub("button_battery_NONE")
            self.icon_wireless = _IconStub("button_wireless_NONE")
            self.icon_sleep = _IconStub("button_sleep_OFF")
            self.icon_alarm = _IconStub("button_alarm_OFF")
            self.button_time = _LabelStub("button_time", "XXXX")
            self.iconbar_group = _GroupStub("iconbar_group")

    # ------------------------------------------------------------------
    # Playmode
    # ------------------------------------------------------------------

    def set_playmode(self, val: Optional[str] = None) -> None:
        """Set the playmode icon.

        Parameters
        ----------
        val:
            One of ``None`` (off), ``"stop"``, ``"play"``, ``"pause"``.
        """
        log.debug("Iconbar.set_playmode(%s)", val)
        style = "button_playmode_" + (val or "OFF").upper()
        self.icon_playmode.set_style(style)

    # Lua-compatible camelCase alias
    setPlaymode = set_playmode

    # ------------------------------------------------------------------
    # Repeat
    # ------------------------------------------------------------------

    def set_repeat(self, val: Optional[Union[str, int]] = None) -> None:
        """Set the repeat icon.

        Parameters
        ----------
        val:
            ``None`` (no repeat), ``1`` / ``"1"`` (single track),
            ``2`` / ``"2"`` (all tracks).
        """
        log.debug("Iconbar.set_repeat(%s)", val)
        style = "button_repeat_" + str(val or "OFF").upper()
        self.icon_repeat.set_style(style)

    # Lua-compatible camelCase alias
    setRepeat = set_repeat

    # ------------------------------------------------------------------
    # Alarm
    # ------------------------------------------------------------------

    def set_alarm(self, val: Optional[str] = None) -> None:
        """Set the alarm icon.

        Parameters
        ----------
        val:
            ``None`` or ``"OFF"`` (alarm off), ``"ON"`` (alarm on).
        """
        log.debug("Iconbar.set_alarm(%s)", val)
        style = "button_alarm_" + (val or "OFF").upper()
        self.icon_alarm.set_style(style)

    # Lua-compatible camelCase alias
    setAlarm = set_alarm

    # ------------------------------------------------------------------
    # Sleep
    # ------------------------------------------------------------------

    def set_sleep(self, val: Optional[str] = None) -> None:
        """Set the sleep icon.

        Parameters
        ----------
        val:
            ``None`` or ``"OFF"`` (sleep off), ``"ON"`` (sleep on).
        """
        log.debug("Iconbar.set_sleep(%s)", val)
        style = "button_sleep_" + (val or "OFF").upper()
        self.icon_sleep.set_style(style)

    # Lua-compatible camelCase alias
    setSleep = set_sleep

    # ------------------------------------------------------------------
    # Shuffle
    # ------------------------------------------------------------------

    def set_shuffle(self, val: Optional[Union[str, int]] = None) -> None:
        """Set the shuffle icon.

        Parameters
        ----------
        val:
            ``None`` (no shuffle), ``1`` / ``"1"`` (by track),
            ``2`` / ``"2"`` (by album).
        """
        log.debug("Iconbar.set_shuffle(%s)", val)
        style = "button_shuffle_" + str(val or "OFF").upper()
        self.icon_shuffle.set_style(style)

    # Lua-compatible camelCase alias
    setShuffle = set_shuffle

    # ------------------------------------------------------------------
    # Battery
    # ------------------------------------------------------------------

    def set_battery(self, val: Optional[Union[str, int]] = None) -> None:
        """Set the battery icon.

        Parameters
        ----------
        val:
            ``None`` (no battery), ``"CHARGING"``, ``"AC"``, or
            ``0``-``4`` for battery level.
        """
        log.debug("Iconbar.set_battery(%s)", val)
        style = "button_battery_" + str(val or "NONE").upper()
        self.icon_battery.set_style(style)

    # Lua-compatible camelCase alias
    setBattery = set_battery

    # ------------------------------------------------------------------
    # Wireless signal
    # ------------------------------------------------------------------

    def set_wireless_signal(
        self,
        val: Optional[Union[str, int]] = None,
        iface: Optional[str] = None,
    ) -> None:
        """Set the wireless/network signal icon.

        Parameters
        ----------
        val:
            Wireless: ``"ERROR"`` or ``0``, ``1``, ``2``, ``3``, ``4``
            Ethernet: ``"ETHERNET_ERROR"`` or ``"ETHERNET"``
        iface:
            Network interface name (for notification purposes).

        The icon style is determined by the combination of network
        state and ``server_error`` state.
        """
        log.debug("Iconbar.set_wireless_signal(%s)", val)

        network_and_server_state = False

        self.wireless_signal = val
        self.iface = iface

        # No ethernet link, ip, gateway or dns
        if val == "ETHERNET_ERROR":
            self.icon_wireless.set_style("button_ethernet_ERROR")
        # No wireless link, ip, gateway or dns
        elif val == "ERROR" or val == 0:
            self.icon_wireless.set_style("button_wireless_ERROR")
        # Ethernet ok, but no server connection
        elif (val == "ETHERNET") and (
            self.server_error == "ERROR" or self.server_error is None
        ):
            self.icon_wireless.set_style("button_ethernet_SERVERERROR")
        # Wireless ok, but no server connection
        elif (val != "ETHERNET") and (
            self.server_error == "ERROR" or self.server_error is None
        ):
            self.icon_wireless.set_style("button_wireless_SERVERERROR")
        # Ethernet and server connection ok
        elif val == "ETHERNET":
            network_and_server_state = True
            self.icon_wireless.set_style("button_ethernet")
        # Wireless and server connection ok, show signal strength
        else:
            network_and_server_state = True
            self.icon_wireless.set_style("button_wireless_" + str(val or "NONE"))

        # Send notification about network and server state
        if self._old_network_and_server_state != network_and_server_state:
            if network_and_server_state:
                log.debug("Network and server ok")
                if self.jnt is not None:
                    self.jnt.notify("networkAndServerOK", iface)
            else:
                log.debug("Network or server not ok")
                if self.jnt is not None:
                    self.jnt.notify("networkOrServerNotOK", iface)

        self._old_network_and_server_state = network_and_server_state

    # Lua-compatible camelCase alias
    setWirelessSignal = set_wireless_signal

    # ------------------------------------------------------------------
    # Server error
    # ------------------------------------------------------------------

    def set_server_error(self, val: Optional[str] = None) -> None:
        """Set the server connection error state.

        Parameters
        ----------
        val:
            ``None``, ``"OK"``, or ``"ERROR"``.

        This triggers a re-evaluation of the wireless icon to reflect
        the combined network+server state.
        """
        self.server_error = val
        self.set_wireless_signal(self.wireless_signal, self.iface)

    # Lua-compatible camelCase alias
    setServerError = set_server_error

    # ------------------------------------------------------------------
    # Debug overlay
    # ------------------------------------------------------------------

    def show_debug(self, value: str, elapsed: int = 10) -> None:
        """Show a debug value in place of the time for *elapsed* seconds.

        Parameters
        ----------
        value:
            The string to display in the time label.
        elapsed:
            Number of seconds to show the debug value.
        """
        self.button_time.set_value(value)
        self._debug_timeout = time.monotonic() + elapsed

    # Lua-compatible camelCase alias
    showDebug = show_debug

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self) -> None:
        """Update the iconbar (called every second by the timer).

        Updates the time display unless a debug overlay is active.
        """
        log.debug("Iconbar.update()")

        if self._debug_timeout is not None and time.monotonic() < self._debug_timeout:
            return

        self._debug_timeout = None

        # Update the time display
        self.button_time.set_value(self._get_current_time())

    # ------------------------------------------------------------------
    # Time formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _get_current_time() -> str:
        """Return the current time as a formatted string.

        Uses the same format as the original Lua code's
        ``datetime:getCurrentTime()`` — typically ``HH:MM``.
        """
        try:
            from jive.utils.datetime_utils import get_current_time

            return get_current_time()
        except ImportError:
            return time.strftime("%H:%M")

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Iconbar("
            f"playmode={self.icon_playmode!r}, "
            f"wireless={self.icon_wireless!r}, "
            f"server_error={self.server_error!r})"
        )

    def __str__(self) -> str:
        return repr(self)
