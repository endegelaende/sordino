"""
jive.applets.slim_browser.scanner — Track position scanner popup.

Ported from ``share/jive/applets/SlimBrowser/Scanner.lua`` (~373 LOC)
in the original jivelite project.

This class manages the track-position scanner popup that appears when
the user holds down forward/rewind keys or uses the scroll wheel to
seek within a track. It handles:

* Opening/closing a scanner slider popup
* Elapsed time display and updates
* Seek acceleration based on key-repeat speed
* Auto-invoke of gototime after user stops seeking
* Different auto-invoke intervals for local vs remote tracks

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
import time as _time
from typing import TYPE_CHECKING, Any, Callable, List, Optional

from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.slim.player import Player

__all__ = ["Scanner"]

log = logger("applet.SlimBrowser")

# Tuning constants
POSITION_STEP = 5
POPUP_AUTOCLOSE_INTERVAL = 10000  # close popup after this much inactivity (ms)
AUTOINVOKE_INTERVAL_LOCAL = (
    400  # invoke gotoTime after this much inactivity for local tracks
)
AUTOINVOKE_INTERVAL_REMOTE = 2000  # and this much for remote streams
ACCELERATION_INTERVAL = 350  # events faster than this cause acceleration
ACCELERATION_INTERVAL_SLOW = 200  # but less so unless faster than this


def _seconds_to_string(seconds: float) -> str:
    """Convert seconds to a human-readable time string (H:MM:SS or M:SS)."""
    seconds = max(0, seconds)
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    # Lua original guards against string.format failing for 0 < secs < 1
    if hrs > 0:
        return f"{hrs}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


class Scanner:
    """Manages the track-position scanner popup and seeking.

    Instantiated once per ``SlimBrowserApplet`` and kept alive for the
    duration of the applet's lifetime.  The popup is opened on demand
    when the user holds fwd/rew keys, and auto-hides after inactivity.

    Parameters
    ----------
    applet : object
        The parent ``SlimBrowserApplet`` (or any object that provides
        a ``string(token)`` method for localisation).
    """

    def __init__(self, applet: Any) -> None:
        self.applet = applet
        self.player: Optional[Any] = None

        # Seek state
        self.delta: int = 0
        self.elapsed: float = 0.0
        self.duration: float = 0.0
        self.autoinvoke_time: int = AUTOINVOKE_INTERVAL_LOCAL

        # Acceleration state
        self.accel_count: int = 0
        self.accel_delta: int = 0
        self.last_update: int = 0

        # Popup widgets (set when popup is open)
        self.popup: Any = None
        self.title: Any = None
        self.heading: Any = None
        self.slider: Any = None
        self.scanner_group: Any = None

        # Timers
        self.display_timer: Any = None
        self.auto_invoke_timer: Any = None
        self.hold_timer: Any = None

        # Lazy-init flag
        self._timers_initialized = False

    # ------------------------------------------------------------------
    # Lazy initialisation of timers
    # ------------------------------------------------------------------

    def _ensure_timers(self) -> None:
        """Create the timers if not yet done."""
        if self._timers_initialized:
            return
        self._timers_initialized = True

        try:
            from jive.ui.timer import Timer as UiTimer

            self.display_timer = UiTimer(1000, self._update_elapsed_time)
            self.auto_invoke_timer = UiTimer(
                AUTOINVOKE_INTERVAL_LOCAL, self._goto_time, once=True
            )
            self.hold_timer = UiTimer(100, self._update_selected_time)
        except (ImportError, TypeError):
            self.display_timer = _TimerStub(1000, self._update_elapsed_time)
            self.auto_invoke_timer = _TimerStub(
                AUTOINVOKE_INTERVAL_LOCAL, self._goto_time
            )
            self.hold_timer = _TimerStub(100, self._update_selected_time)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_player(self, player: Any) -> None:
        """Set the current player."""
        self.player = player

    # Alias for Lua-style callers
    def setPlayer(self, player: Any) -> None:
        self.set_player(player)

    # ------------------------------------------------------------------
    # Display update
    # ------------------------------------------------------------------

    def _update_display(self) -> None:
        """Refresh the popup widgets with current elapsed time."""
        if self.title is not None:
            self.title.setValue(self._applet_string("SLIMBROWSER_SCANNER"))

        if self.slider is not None:
            self.slider.setValue(int(self.elapsed))

        str_elapsed = _seconds_to_string(self.elapsed)
        if self.heading is not None:
            self.heading.setValue(str_elapsed)

    # ------------------------------------------------------------------
    # Elapsed time update (called by display timer)
    # ------------------------------------------------------------------

    def _update_elapsed_time(self) -> None:
        """Periodically update elapsed time from the player."""
        if self.popup is None:
            if self.display_timer is not None and hasattr(self.display_timer, "stop"):
                self.display_timer.stop()
            if self.hold_timer is not None and hasattr(self.hold_timer, "stop"):
                self.hold_timer.stop()
            return

        track_info = self._get_track_elapsed()
        if track_info is not None:
            self.elapsed, self.duration = track_info
        self._update_display()

    # ------------------------------------------------------------------
    # Popup management
    # ------------------------------------------------------------------

    def _open_popup(self) -> None:
        """Open the scanner slider popup, if not already open."""
        if self.popup is not None or self.player is None:
            return

        self._ensure_timers()

        # Get a local copy of elapsed time and duration
        track_info = self._get_track_elapsed()
        if track_info is None:
            return
        self.elapsed, self.duration = track_info

        if self.elapsed is None or self.duration is None:
            return

        # Check if track is seekable
        seekable = True
        if hasattr(self.player, "isTrackSeekable"):
            seekable = self.player.isTrackSeekable()
        elif hasattr(self.player, "is_track_seekable"):
            seekable = self.player.is_track_seekable()
        if not seekable:
            return

        try:
            from jive.ui.constants import (
                ACTION,
                EVENT_CONSUME,
                EVENT_KEY_ALL,
                EVENT_SCROLL,
            )
            from jive.ui.group import Group
            from jive.ui.label import Label
            from jive.ui.popup import Popup
            from jive.ui.slider import Slider
            from jive.ui.window import Window
        except ImportError:
            log.info("Scanner popup: UI not available")
            return

        popup = Popup("scanner_popup")
        if hasattr(popup, "setAutoHide"):
            popup.setAutoHide(False)
        if hasattr(popup, "setAlwaysOnTop"):
            popup.setAlwaysOnTop(True)

        title = Label("heading", "")
        popup.addWidget(title)  # type: ignore[attr-defined]

        def _slider_callback(
            slider_widget: Any, value: int, done: bool = False
        ) -> None:
            self.delta = value - int(self.elapsed)
            self.elapsed = value
            self._update_selected_time()

        slider = Slider(
            "scanner_slider",
            0,
            int(self.duration),
            int(self.elapsed),
            _slider_callback,
        )
        self.heading = title
        self.scanner_group = Group("slider_group", {"slider": slider})

        popup.addWidget(self.scanner_group)  # type: ignore[attr-defined]

        # Event listener
        event_mask = 0
        for flag in (ACTION, EVENT_KEY_ALL, EVENT_SCROLL):
            if isinstance(flag, int):
                event_mask |= flag

        if event_mask and hasattr(popup, "addListener"):
            popup.addListener(event_mask, lambda evt: self.event(evt))

        # We handle events ourselves
        popup.brieflyHandler = False  # type: ignore[attr-defined]

        # Store references
        self.popup = popup
        self.title = title
        self.slider = slider

        # Start display timer
        if self.display_timer is not None and hasattr(self.display_timer, "restart"):
            self.display_timer.restart()

        # Determine auto-invoke interval based on player type
        is_remote = False
        if hasattr(self.player, "isRemote"):
            is_remote = self.player.isRemote()
        elif hasattr(self.player, "is_remote"):
            is_remote = self.player.is_remote()

        if is_remote:
            self.autoinvoke_time = AUTOINVOKE_INTERVAL_REMOTE
        else:
            self.autoinvoke_time = AUTOINVOKE_INTERVAL_LOCAL

        if hasattr(popup, "focusWidget"):
            popup.focusWidget(None)

        self._update_display()

        def _on_dismiss() -> None:
            # Check if popup is still on the window stack
            try:
                from jive.ui.framework import framework as _fw

                if _fw is not None and hasattr(_fw, "windowStack"):
                    stack = _fw.windowStack
                    on_stack = any(w is popup for w in stack)
                    if not on_stack:
                        self.popup = None
            except ImportError:
                self.popup = None

        if hasattr(popup, "showBriefly"):
            popup.showBriefly(
                POPUP_AUTOCLOSE_INTERVAL,
                _on_dismiss,
                getattr(Window, "transitionNone", None),
                getattr(Window, "transitionNone", None),
            )

    # ------------------------------------------------------------------
    # Selected time update (called when user is seeking)
    # ------------------------------------------------------------------

    def _update_selected_time(self) -> None:
        """Update the display when the user changes the seek position."""
        if self.popup is None:
            if self.display_timer is not None and hasattr(self.display_timer, "stop"):
                self.display_timer.stop()
            if self.hold_timer is not None and hasattr(self.hold_timer, "stop"):
                self.hold_timer.stop()
            return

        if self.delta == 0:
            return

        # Stop tracking actual playing position while user is seeking
        if self.display_timer is not None and hasattr(self.display_timer, "stop"):
            self.display_timer.stop()

        # Keep the popup window open
        if hasattr(self.popup, "showBriefly"):
            self.popup.showBriefly()

        # Acceleration
        now = self._get_ticks()
        interval = now - self.last_update
        if self.accel_delta != self.delta or interval > ACCELERATION_INTERVAL:
            self.accel_count = 0

        max_accel = 50
        if self.duration > 0:
            max_accel = min(self.duration / 15, 50)  # type: ignore[assignment]
        self.accel_count = min(self.accel_count + 1, max_accel)
        self.accel_delta = self.delta
        self.last_update = now

        # Calculate acceleration factor
        if interval > ACCELERATION_INTERVAL_SLOW:
            accel = self.accel_count / 15
        else:
            accel = self.accel_count / 10

        new = abs(self.elapsed) + self.delta * accel * POSITION_STEP

        if new > self.duration:
            new = self.duration
        elif new < 0:
            new = 0

        self.elapsed = new
        self._update_display()

        # Restart auto-invoke timer
        if self.auto_invoke_timer is not None and hasattr(
            self.auto_invoke_timer, "restart"
        ):
            self.auto_invoke_timer.restart(self.autoinvoke_time)

    # ------------------------------------------------------------------
    # Goto time (send seek command to player)
    # ------------------------------------------------------------------

    def _goto_time(self) -> None:
        """Send the gototime command to the player."""
        if self.auto_invoke_timer is not None and hasattr(
            self.auto_invoke_timer, "stop"
        ):
            self.auto_invoke_timer.stop()

        if self.popup is None:
            return

        if self.player is not None:
            if hasattr(self.player, "gototime"):
                self.player.gototime(int(self.elapsed))
            elif hasattr(self.player, "goto_time"):
                self.player.goto_time(int(self.elapsed))

        if self.display_timer is not None and hasattr(self.display_timer, "restart"):
            self.display_timer.restart()

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    def event(self, event: Any) -> int:
        """Handle an input event for the scanner.

        Returns an event consumption constant.
        """
        self._ensure_timers()

        # Deactivate screensaver
        try:
            from jive.applet_manager import applet_manager

            if applet_manager is not None:
                applet_manager.call_service("deactivateScreensaver")
                applet_manager.call_service("restartScreenSaverTimer")
        except (ImportError, AttributeError) as exc:
            log.debug("event: screensaver service not available: %s", exc)

        # Import constants
        try:
            from jive.ui.constants import (
                ACTION,
                EVENT_CONSUME,
                EVENT_KEY_DOWN,
                EVENT_KEY_HOLD,
                EVENT_KEY_PRESS,
                EVENT_KEY_UP,
                EVENT_SCROLL,
                EVENT_UNUSED,
                KEY_BACK,
                KEY_FWD,
                KEY_FWD_SCAN,
                KEY_GO,
                KEY_REW,
                KEY_REW_SCAN,
            )
        except ImportError:
            EVENT_SCROLL = 0x00000800  # type: ignore[assignment]
            ACTION = 0x00080000  # type: ignore[assignment]
            EVENT_KEY_PRESS = 0x00000002  # type: ignore[assignment]
            EVENT_KEY_DOWN = 0x00000001  # type: ignore[assignment]
            EVENT_KEY_UP = 0x00000004  # type: ignore[assignment]
            EVENT_KEY_HOLD = 0x00000008  # type: ignore[assignment]
            EVENT_CONSUME = 0x02  # type: ignore[assignment]
            EVENT_UNUSED = 0x00  # type: ignore[assignment]
            KEY_GO = 0x00000010  # type: ignore[assignment]
            KEY_BACK = 0x00000020  # type: ignore[assignment]
            KEY_FWD = 0x00000080  # type: ignore[assignment]
            KEY_REW = 0x00000040  # type: ignore[assignment]
            KEY_FWD_SCAN = 0x00010000  # type: ignore[assignment]
            KEY_REW_SCAN = 0x00020000  # type: ignore[assignment]

        # Determine if popup is already visible
        on_screen = True
        if self.popup is None:
            on_screen = False
            self._open_popup()

        evt_type = 0
        if hasattr(event, "getType"):
            evt_type = event.getType()
        elif hasattr(event, "get_type"):
            evt_type = event.get_type()
        elif hasattr(event, "type"):
            evt_type = event.type

        # --- Scroll events ---
        if evt_type == EVENT_SCROLL:
            scroll = 0
            if hasattr(event, "getScroll"):
                scroll = event.getScroll()
            elif hasattr(event, "get_scroll"):
                scroll = event.get_scroll()
            elif hasattr(event, "scroll"):
                scroll = event.scroll

            if scroll > 0:
                self.delta = 1
            elif scroll < 0:
                self.delta = -1
            else:
                self.delta = 0
            self._update_selected_time()

        # --- Action events ---
        elif evt_type == ACTION:
            action_name = ""
            if hasattr(event, "getAction"):
                action_name = event.getAction() or ""
            elif hasattr(event, "get_action"):
                action_name = event.get_action() or ""
            elif hasattr(event, "action"):
                action_name = event.action or ""

            # GO closes the popup & executes any pending change
            if action_name == "go":
                if (
                    self.auto_invoke_timer is not None
                    and hasattr(self.auto_invoke_timer, "isRunning")
                    and self.auto_invoke_timer.isRunning()
                ):
                    self._goto_time()
                if self.popup is not None and hasattr(self.popup, "showBriefly"):
                    self.popup.showBriefly(0)
                return EVENT_CONSUME

            # BACK closes the popup & cancels any pending change
            if action_name == "back":
                if self.auto_invoke_timer is not None and hasattr(
                    self.auto_invoke_timer, "stop"
                ):
                    self.auto_invoke_timer.stop()
                if self.popup is not None and hasattr(self.popup, "showBriefly"):
                    self.popup.showBriefly(0)
                return EVENT_CONSUME

            if action_name == "scanner_fwd":
                self.delta = 1
                if on_screen:
                    self._update_selected_time()
                return EVENT_CONSUME

            if action_name == "scanner_rew":
                self.delta = -1
                if on_screen:
                    self._update_selected_time()
                return EVENT_CONSUME

            # Forward other actions to the lower window
            lower = None
            if self.popup is not None and hasattr(self.popup, "getLowerWindow"):
                lower = self.popup.getLowerWindow()
            if self.popup is not None and hasattr(self.popup, "showBriefly"):
                self.popup.showBriefly(0)
            if lower is not None:
                try:
                    from jive.ui.framework import framework as _fw

                    if _fw is not None and hasattr(_fw, "dispatchEvent"):
                        _fw.dispatchEvent(lower, event)
                except ImportError as exc:
                    log.debug("event: framework not available for dispatch: %s", exc)

            return EVENT_CONSUME

        # --- Key press events ---
        elif evt_type == EVENT_KEY_PRESS:
            return EVENT_UNUSED

        # --- Key down / key up / key hold ---
        else:
            keycode = 0
            if hasattr(event, "getKeycode"):
                keycode = event.getKeycode()
            elif hasattr(event, "get_keycode"):
                keycode = event.get_keycode()
            elif hasattr(event, "keycode"):
                keycode = event.keycode

            scan_keys = KEY_FWD | KEY_REW | KEY_FWD_SCAN | KEY_REW_SCAN

            # Only interested in scan/fwd/rew keys
            if (keycode & scan_keys) == 0:
                return EVENT_CONSUME

            # Stop seeking on key up
            if evt_type == EVENT_KEY_UP:
                self.delta = 0
                self.muting = False
                if self.hold_timer is not None and hasattr(self.hold_timer, "stop"):
                    self.hold_timer.stop()
                return EVENT_CONSUME

            # Start seeking on key down or hold
            if evt_type == EVENT_KEY_DOWN or evt_type == EVENT_KEY_HOLD:
                if keycode in (KEY_FWD, KEY_FWD_SCAN):
                    self.delta = 1
                elif keycode in (KEY_REW, KEY_REW_SCAN):
                    self.delta = -1
                else:
                    self.delta = 0

                if self.hold_timer is not None and hasattr(self.hold_timer, "restart"):
                    self.hold_timer.restart()
                if on_screen:
                    self._update_selected_time()

                return EVENT_CONSUME

        return EVENT_CONSUME

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_track_elapsed(self) -> Optional[Tuple[Any, Any]]:  # type: ignore[name-defined]
        """Return ``(elapsed, duration)`` from the player, or ``None``."""
        if self.player is None:
            return None

        elapsed = None
        duration = None

        if hasattr(self.player, "getTrackElapsed"):
            result = self.player.getTrackElapsed()
            if isinstance(result, (list, tuple)) and len(result) >= 2:
                elapsed, duration = result[0], result[1]
            elif result is not None:
                elapsed = result
        elif hasattr(self.player, "get_track_elapsed"):
            result = self.player.get_track_elapsed()
            if isinstance(result, (list, tuple)) and len(result) >= 2:
                elapsed, duration = result[0], result[1]
            elif result is not None:
                elapsed = result

        if elapsed is None or duration is None:
            return None

        return (float(elapsed), float(duration))

    @staticmethod
    def _get_ticks() -> int:
        """Return the current tick count in milliseconds."""
        try:
            from jive.ui.framework import framework as _fw

            if _fw is not None and hasattr(_fw, "getTicks"):
                return _fw.getTicks()  # type: ignore[no-any-return]
            if _fw is not None and hasattr(_fw, "get_ticks"):
                return _fw.get_ticks()
        except ImportError as exc:
            log.debug("_get_ticks: framework not available: %s", exc)
        return int(_time.monotonic() * 1000)

    def _applet_string(self, token: str) -> str:
        """Get a localised string from the parent applet."""
        if self.applet is not None and hasattr(self.applet, "string"):
            result = self.applet.string(token)
            return str(result) if result is not None else token
        return token


# ======================================================================
# Stub for headless / test mode
# ======================================================================


class _TimerStub:
    """Minimal timer stub when UI is not available."""

    def __init__(
        self,
        interval: int,
        callback: Callable[[], None],
        once: bool = False,
    ) -> None:
        self.interval = interval
        self.callback = callback
        self.once = once
        self._running = False

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def restart(self, interval: Optional[int] = None) -> None:
        if interval is not None:
            self.interval = interval
        self._running = True

    def isRunning(self) -> bool:
        return self._running
