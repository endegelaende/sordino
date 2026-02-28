"""
jive.applets.slim_browser.volume — Player volume popup handler.

Ported from ``share/jive/applets/SlimBrowser/Volume.lua`` (~574 LOC) in
the original jivelite project.

This class manages the volume popup UI that appears when the user
adjusts volume via hardware keys, IR remote, or scroll wheel. It
handles:

* Opening/closing a volume slider popup
* Volume acceleration for key repeats and IR
* Rate-limiting volume updates to the server
* Mute/unmute toggling
* Fixed-volume (digital volume control disabled) detection
* Small-knob (volume knob) acceleration
* Offline mode for local players without server connectivity

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.slim.player import Player

__all__ = ["Volume"]

log = logger("applet.SlimBrowser")

# Number of volume steps per unit change
VOLUME_STEP = 100 / 40

# Acceleration constant for small (dedicated) volume knob
SMALL_KNOB_ACCEL_CONSTANT = 22


class Volume:
    """Manages player volume display and interaction.

    Instantiated once per ``SlimBrowserApplet`` and kept alive for the
    duration of the applet's lifetime.  The popup is opened on demand
    and auto-hides after a brief timeout.

    Parameters
    ----------
    applet : object
        The parent ``SlimBrowserApplet`` (or any object that provides
        a ``string(token)`` method for localisation).
    """

    def __init__(self, applet: Any) -> None:
        self.applet = applet
        self.player: Optional[Any] = None

        # Volume state
        self.delta: int = 0
        self.volume: int = 0
        self.muting: bool = False
        self.offline: bool = False

        # Acceleration state
        self.accel_count: int = 0
        self.accel_delta: int = 0
        self.last_update: int = 0

        # Rate-limiter
        self.rate_limit_delta: int = 0
        self.rate_limiter_cleanup_timer: Any = None

        # Popup widgets (set when popup is open)
        self.popup: Any = None
        self.title: Any = None
        self.icon: Any = None
        self.slider: Any = None

        # IR acceleration helper
        self.ir_accel: Any = None

        # Timer for key-repeat volume changes
        self.timer: Any = None

        # Small-knob acceleration points
        self._small_knob_points: List[int] = []

        # Lazy-init timer and IR accel
        self._timer_initialized = False

    # ------------------------------------------------------------------
    # Lazy initialisation of timer / IR accel
    # ------------------------------------------------------------------

    def _ensure_timer(self) -> None:
        """Create the repeat timer and IR accel helper if not yet done."""
        if self._timer_initialized:
            return
        self._timer_initialized = True

        try:
            from jive.ui.timer import Timer as UiTimer

            self.timer = UiTimer(100, self._timer_callback)
        except ImportError:
            self.timer = _TimerStub(100, self._timer_callback)

        try:
            from jive.ui.irmenuaccel import IRMenuAccel

            self.ir_accel = IRMenuAccel("volup", "voldown")
            # Kick in acceleration sooner than default
            if hasattr(self.ir_accel, "setCyclesBeforeAccelerationStarts"):
                self.ir_accel.setCyclesBeforeAccelerationStarts(2)
            elif hasattr(self.ir_accel, "set_cycles_before_acceleration_starts"):
                self.ir_accel.set_cycles_before_acceleration_starts(2)
        except ImportError:
            self.ir_accel = None

    def _timer_callback(self) -> None:
        """Called by the repeat timer to keep updating volume."""
        self._update_volume()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_player(self, player: Any) -> None:
        """Set the current player."""
        self.player = player

    # Alias
    def setPlayer(self, player: Any) -> None:
        self.set_player(player)

    def set_offline(self, offline: bool) -> None:
        """Enable or disable offline mode.

        In offline mode, volume commands are applied locally without
        sending them to the server.
        """
        self.offline = offline

    # Alias
    def setOffline(self, offline: bool) -> None:
        self.set_offline(offline)

    # ------------------------------------------------------------------
    # Display update
    # ------------------------------------------------------------------

    def _update_display(self) -> None:
        """Refresh the popup widgets with the current volume."""
        vol = self._get_volume()
        if vol is None:
            return

        if int(vol) <= 0:
            if self.title is not None:
                self.title.setValue(self._applet_string("SLIMBROWSER_MUTED"))
            if self.icon is not None:
                self.icon.setStyle("icon_popup_mute")
            if self.slider is not None:
                self.slider.setValue(0)
        else:
            if self.title is not None:
                self.title.setValue(str(int(vol)))
            if self.icon is not None:
                self.icon.setStyle("icon_popup_volume")
            if self.slider is not None:
                self.slider.setValue(int(vol))

    # ------------------------------------------------------------------
    # Volume getter
    # ------------------------------------------------------------------

    def _get_volume(self) -> Optional[int]:
        """Return the current volume value, or ``None``."""
        if self.player is None:
            return None

        is_local = False
        if hasattr(self.player, "isLocal"):
            is_local = self.player.isLocal()
        elif hasattr(self.player, "is_local"):
            is_local = self.player.is_local()

        if is_local:
            # Check capture play mode
            capture = False
            if hasattr(self.player, "getCapturePlayMode"):
                capture = self.player.getCapturePlayMode()
            elif hasattr(self.player, "get_capture_play_mode"):
                capture = self.player.get_capture_play_mode()

            if capture:
                if hasattr(self.player, "getCaptureVolume"):
                    return self.player.getCaptureVolume()
                elif hasattr(self.player, "get_capture_volume"):
                    return self.player.get_capture_volume()

            # Use local player volume
            if hasattr(self.player, "getVolume"):
                return self.player.getVolume()
            elif hasattr(self.player, "get_volume"):
                return self.player.get_volume()
            return None
        else:
            # Use self.volume which is updated with server
            return self.volume

    # ------------------------------------------------------------------
    # Popup management
    # ------------------------------------------------------------------

    def _open_popup(self) -> None:
        """Open the volume slider popup, if not already open."""
        if self.popup is not None or self.player is None:
            return

        # Don't show popup if fixed volume
        use_vol = 1
        if hasattr(self.player, "useVolumeControl"):
            use_vol = self.player.useVolumeControl()
        elif hasattr(self.player, "use_volume_control"):
            use_vol = self.player.use_volume_control()
        if use_vol == 0:
            return

        # Get a local copy of the volume
        vol = None
        if hasattr(self.player, "getVolume"):
            vol = self.player.getVolume()
        elif hasattr(self.player, "get_volume"):
            vol = self.player.get_volume()
        if vol is None:
            return
        self.volume = int(vol)

        try:
            from jive.ui.constants import (
                ACTION,
                EVENT_CONSUME,
                EVENT_IR_DOWN,
                EVENT_IR_REPEAT,
                EVENT_KEY_ALL,
                EVENT_SCROLL,
            )
            from jive.ui.framework import framework as _fw
            from jive.ui.group import Group
            from jive.ui.icon import Icon
            from jive.ui.label import Label
            from jive.ui.popup import Popup
            from jive.ui.slider import Slider
            from jive.ui.window import Window
        except ImportError:
            log.info("Volume popup: UI not available")
            return

        popup = Popup("slider_popup")
        if hasattr(popup, "setAutoHide"):
            popup.setAutoHide(False)
        if hasattr(popup, "setAlwaysOnTop"):
            popup.setAlwaysOnTop(True)

        title = Label("heading", "")
        popup.addWidget(title)

        icon = Icon("icon_popup_volume")
        popup.addWidget(icon)

        def _slider_callback(
            slider_widget: Any, value: int, done: bool = False
        ) -> None:
            self.delta = value - self.volume
            self._update_volume(direct_set=value)

        slider = Slider("volume_slider", -1, 100, self.volume, _slider_callback)

        popup.addWidget(Group("slider_group", {"slider": slider}))

        if hasattr(popup, "focusWidget"):
            popup.focusWidget(None)

        # Event listener
        import operator

        event_mask = 0
        for flag in (
            ACTION,
            EVENT_KEY_ALL,
            EVENT_IR_DOWN,
            EVENT_IR_REPEAT,
            EVENT_SCROLL,
        ):
            if isinstance(flag, int):
                event_mask |= flag

        if event_mask and hasattr(popup, "addListener"):
            popup.addListener(event_mask, lambda evt: self.event(evt))

        # Disable briefly handler
        popup.brieflyHandler = False

        self.popup = popup
        self.title = title
        self.icon = icon
        self.slider = slider

        self._update_display()

        def _on_dismiss() -> None:
            # Check if popup is still on the window stack
            if hasattr(_fw, "windowStack"):
                stack = _fw.windowStack
                on_stack = any(w is popup for w in stack)
                if not on_stack:
                    self.popup = None

        if hasattr(popup, "showBriefly"):
            popup.showBriefly(
                3000,
                _on_dismiss,
                getattr(Window, "transitionNone", None),
                getattr(Window, "transitionNone", None),
            )

    # ------------------------------------------------------------------
    # Volume update logic
    # ------------------------------------------------------------------

    def _update_volume(
        self,
        mute: bool = False,
        direct_set: Optional[int] = None,
        no_accel: bool = False,
        min_accel_delta: Optional[int] = None,
    ) -> None:
        """Core volume update logic.

        Handles muting, acceleration, rate-limiting, and sending the
        volume command to the player.
        """
        # Bug 15826: IR Blaster support for fab4
        if self.player is not None:
            dvc = 1
            if hasattr(self.player, "getDigitalVolumeControl"):
                dvc = self.player.getDigitalVolumeControl()
            elif hasattr(self.player, "get_digital_volume_control"):
                dvc = self.player.get_digital_volume_control()

            model = ""
            if hasattr(self.player, "getModel"):
                model = self.player.getModel() or ""
            elif hasattr(self.player, "get_model"):
                model = self.player.get_model() or ""

            if dvc == 0 and model == "fab4":
                # Send command directly without updating local volume
                if hasattr(self.player, "volume"):
                    self.player.volume(100 + self.delta, True)

        if self.popup is None:
            if self.timer is not None and hasattr(self.timer, "stop"):
                self.timer.stop()
            return

        # Don't update if fixed volume
        use_vol = 1
        if self.player is not None:
            if hasattr(self.player, "useVolumeControl"):
                use_vol = self.player.useVolumeControl()
            elif hasattr(self.player, "use_volume_control"):
                use_vol = self.player.use_volume_control()
        if use_vol == 0:
            return

        # Keep popup open
        if hasattr(self.popup, "showBriefly"):
            self.popup.showBriefly()

        # Handle capture play mode for local players
        is_local = False
        if self.player is not None:
            if hasattr(self.player, "isLocal"):
                is_local = self.player.isLocal()
            elif hasattr(self.player, "is_local"):
                is_local = self.player.is_local()

        if is_local and self.player is not None:
            capture = False
            if hasattr(self.player, "getCapturePlayMode"):
                capture = self.player.getCapturePlayMode()
            elif hasattr(self.player, "get_capture_play_mode"):
                capture = self.player.get_capture_play_mode()

            if capture:
                if direct_set is not None:
                    new = int(direct_set)
                else:
                    new = abs(self._get_volume() or 0) + self.delta
                new = self._coerce_volume(new)
                if hasattr(self.player, "captureVolume"):
                    self.player.captureVolume(new)
                elif hasattr(self.player, "capture_volume"):
                    self.player.capture_volume(new)
                self._update_display()
                return

        # Ignore updates while muting
        if self.muting:
            self._update_display()
            return

        # Mute?
        if mute:
            self.muting = True
            if hasattr(self.player, "mute"):
                self.volume = self.player.mute(True) or 0
            self.rate_limit_delta = 0
            self._update_display()
            return

        # Calculate new volume
        new: int
        if direct_set is not None:
            new = int(direct_set)
        else:
            if no_accel:
                if self.volume == 0 and self.delta > 1:
                    self.delta = 1

                new = abs(self.volume) + self.delta

                now = self._get_ticks()
                new = new + self.rate_limit_delta
                self.rate_limit_delta = 0
                self.last_update = now
            else:
                # Acceleration
                now = self._get_ticks()
                if self.accel_delta != self.delta or (now - self.last_update) > 350:
                    self.accel_count = 0

                self.accel_count = min(self.accel_count + 1, 20)
                self.accel_delta = self.delta
                self.last_update = now

                # Calculate accelerated change
                accel = self.accel_count / 5.5

                if self.delta == 0:
                    new = abs(self.volume)
                    self.rate_limit_delta = 0
                else:
                    direction = abs(self.delta) // self.delta if self.delta != 0 else 0
                    change = direction * int(abs(self.delta) * accel * VOLUME_STEP)
                    if change == 0 and min_accel_delta is not None:
                        new = abs(self.volume) + min_accel_delta
                    else:
                        new = abs(self.volume) + change

        new = self._coerce_volume(new)

        # Offline mode
        if self.offline:
            log.debug("Setting offline volume: %d", new)
            if is_local and self.player is not None:
                if hasattr(self.player, "volumeLocal"):
                    self.player.volumeLocal(new, True)
                elif hasattr(self.player, "volume_local"):
                    self.player.volume_local(new, True)
                self.volume = new
                self._update_display()
            else:
                log.warn("offline mode not allowed when player is not local")
            return

        # Send volume to player
        remote_volume = None
        if self.player is not None and hasattr(self.player, "volume"):
            remote_volume = self.player.volume(new)

        if remote_volume is None:
            # Player suppressed volume due to rate limiting
            self.rate_limit_delta = abs(new) - abs(self.volume)
        else:
            self.volume = remote_volume

        self._update_display()

        # Rate limiter cleanup timer
        if self.rate_limiter_cleanup_timer is None:
            delay = 350  # default
            try:
                from jive.slim.player import Player as _P

                if hasattr(_P, "getRateLimitTime"):
                    delay = _P.getRateLimitTime()
                elif hasattr(_P, "get_rate_limit_time"):
                    delay = _P.get_rate_limit_time()
            except ImportError:
                pass

            try:
                from jive.ui.timer import Timer as UiTimer

                self.rate_limiter_cleanup_timer = UiTimer(
                    delay, self._rate_limit_cleanup, once=True
                )
            except (ImportError, TypeError):
                self.rate_limiter_cleanup_timer = _TimerStub(
                    delay, self._rate_limit_cleanup
                )

        if hasattr(self.rate_limiter_cleanup_timer, "restart"):
            self.rate_limiter_cleanup_timer.restart()

    def _rate_limit_cleanup(self) -> None:
        """Send any accumulated rate-limited volume delta."""
        if self.rate_limit_delta and self.rate_limit_delta != 0:
            cleanup_vol = abs(self.volume) + self.rate_limit_delta
            self.rate_limit_delta = 0
            cleanup_vol = self._coerce_volume(cleanup_vol)

            log.debug("Sending cleanup volume: %d", cleanup_vol)

            returned = None
            if self.player is not None and hasattr(self.player, "volume"):
                returned = self.player.volume(cleanup_vol, True)
            if returned is None:
                log.warn(
                    "timer-set volume value should always go through, "
                    "since send param is 'true'"
                )
                return
            self.volume = returned
            self._update_display()

    # ------------------------------------------------------------------
    # Volume coercion
    # ------------------------------------------------------------------

    def _coerce_volume(self, volume: int) -> int:
        """Clamp volume to valid range [0, 100].

        When decreasing, allow stopping at volume 1 (lowest audible
        level) before jumping to 0.
        """
        if volume > 100:
            return 100
        if volume > 0 and self.delta < 0 and volume <= abs(self.delta):
            return 1
        if volume < 0:
            return 0
        return volume

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    def event(self, event: Any) -> int:
        """Handle an input event for volume control.

        Returns an event consumption constant.
        """
        self._ensure_timer()

        # Deactivate screensaver
        try:
            from jive.applet_manager import applet_manager

            if applet_manager is not None:
                applet_manager.call_service("deactivateScreensaver")
                applet_manager.call_service("restartScreenSaverTimer")
        except (ImportError, AttributeError):
            pass

        # Import constants
        try:
            from jive.ui.constants import (
                ACTION,
                EVENT_CONSUME,
                EVENT_IR_ALL,
                EVENT_IR_DOWN,
                EVENT_IR_REPEAT,
                EVENT_KEY_DOWN,
                EVENT_KEY_PRESS,
                EVENT_KEY_UP,
                EVENT_SCROLL,
                EVENT_UNUSED,
                KEY_GO,
                KEY_VOLUME_DOWN,
                KEY_VOLUME_UP,
            )
        except ImportError:
            EVENT_SCROLL = 0x00000800
            EVENT_IR_ALL = 0x0000F000
            EVENT_IR_DOWN = 0x00001000
            EVENT_IR_REPEAT = 0x00004000
            ACTION = 0x00080000
            EVENT_KEY_PRESS = 0x00000002
            EVENT_KEY_DOWN = 0x00000001
            EVENT_KEY_UP = 0x00000004
            EVENT_CONSUME = 0x02
            EVENT_UNUSED = 0x00
            KEY_VOLUME_DOWN = 0x00000400
            KEY_VOLUME_UP = 0x00000200

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

            # Check for dedicated volume knob
            has_knob = False
            try:
                from jive.system import System

                has_knob = System.hasVolumeKnob()
            except (ImportError, AttributeError):
                pass

            if not has_knob:
                if scroll > 0:
                    self.delta = 1
                elif scroll < 0:
                    self.delta = -1
                else:
                    self.delta = 0
                self._update_volume()
            else:
                # Dedicated volume knob — don't use scroll for volume
                if self.popup is not None and hasattr(self.popup, "showBriefly"):
                    self.popup.showBriefly(0)
                return EVENT_CONSUME

        # --- IR events ---
        elif evt_type & EVENT_IR_ALL > 0 if isinstance(evt_type, int) else False:
            is_volup = False
            is_voldown = False
            if hasattr(event, "isIRCode"):
                is_volup = event.isIRCode("volup")
                is_voldown = event.isIRCode("voldown")
            elif hasattr(event, "is_ir_code"):
                is_volup = event.is_ir_code("volup")
                is_voldown = event.is_ir_code("voldown")

            if is_volup or is_voldown:
                if evt_type in (EVENT_IR_DOWN, EVENT_IR_REPEAT):
                    if self.ir_accel is not None:
                        value = self.ir_accel.event(event, 1, 1, 1, 100)
                        if value != 0:
                            self.delta = value
                            self._update_volume(no_accel=True)
                            self.delta = 0
                return EVENT_CONSUME
            # Non-volume IR — pass through
            return EVENT_UNUSED

        # --- Action events ---
        elif evt_type == ACTION:
            action_name = ""
            if hasattr(event, "getAction"):
                action_name = event.getAction() or ""
            elif hasattr(event, "get_action"):
                action_name = event.get_action() or ""
            elif hasattr(event, "action"):
                action_name = event.action or ""

            if action_name == "volume_up":
                self.delta = 1
                self._update_volume(no_accel=True)
                self.delta = 0
                return EVENT_CONSUME

            if action_name == "volume_down":
                self.delta = -1
                self._update_volume(no_accel=True)
                self.delta = 0
                return EVENT_CONSUME

            if action_name == "mute":
                self._update_volume(mute=(self.volume >= 0))
                self.muting = False
                return EVENT_CONSUME

            # GO / back close the popup
            if action_name in ("go", "back"):
                if self.popup is not None and hasattr(self.popup, "showBriefly"):
                    self.popup.showBriefly(0)
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
                except ImportError:
                    pass

            return EVENT_CONSUME

        # --- Key press events ---
        elif evt_type == EVENT_KEY_PRESS:
            keycode = 0
            if hasattr(event, "getKeycode"):
                keycode = event.getKeycode()
            elif hasattr(event, "get_keycode"):
                keycode = event.get_keycode()
            elif hasattr(event, "keycode"):
                keycode = event.keycode

            # Volume knob handling
            has_knob = False
            try:
                from jive.system import System

                has_knob = System.hasVolumeKnob()
            except (ImportError, AttributeError):
                pass

            if (keycode & (KEY_VOLUME_UP | KEY_VOLUME_DOWN)) != 0 and has_knob:
                if keycode == KEY_VOLUME_UP:
                    ticks = 0
                    if hasattr(event, "getTicks"):
                        ticks = event.getTicks()
                    elif hasattr(event, "get_ticks"):
                        ticks = event.get_ticks()
                    self.delta = self._get_small_knob_delta(1, ticks)
                    self._update_volume(no_accel=True)
                    self.delta = 0
                elif keycode == KEY_VOLUME_DOWN:
                    ticks = 0
                    if hasattr(event, "getTicks"):
                        ticks = event.getTicks()
                    elif hasattr(event, "get_ticks"):
                        ticks = event.get_ticks()
                    self.delta = self._get_small_knob_delta(-1, ticks)
                    self._update_volume(no_accel=True)
                    self.delta = 0
                return EVENT_CONSUME

            # Volume+ and volume- pressed simultaneously = mute
            if keycode & (KEY_VOLUME_UP | KEY_VOLUME_DOWN) == (
                KEY_VOLUME_UP | KEY_VOLUME_DOWN
            ):
                self._update_volume(mute=(self.volume >= 0))
                return EVENT_CONSUME

            # Other keys — pass through
            if (keycode & (KEY_VOLUME_UP | KEY_VOLUME_DOWN)) == 0:
                return EVENT_UNUSED

            # Key press handled by down event
            return EVENT_CONSUME

        # --- Key down / key up ---
        else:
            keycode = 0
            if hasattr(event, "getKeycode"):
                keycode = event.getKeycode()
            elif hasattr(event, "get_keycode"):
                keycode = event.get_keycode()
            elif hasattr(event, "keycode"):
                keycode = event.keycode

            # Only interested in volume keys
            if (keycode & (KEY_VOLUME_UP | KEY_VOLUME_DOWN)) == 0:
                return EVENT_UNUSED

            # Stop volume update on key up
            if evt_type == EVENT_KEY_UP:
                self.delta = 0
                self.muting = False
                if self.timer is not None and hasattr(self.timer, "stop"):
                    self.timer.stop()
                return EVENT_CONSUME

            # Start volume update on key down
            if evt_type == EVENT_KEY_DOWN:
                if keycode == KEY_VOLUME_UP:
                    self.delta = 1
                elif keycode == KEY_VOLUME_DOWN:
                    self.delta = -1
                else:
                    self.delta = 0

                if self.timer is not None and hasattr(self.timer, "restart"):
                    self.timer.restart()
                self._update_volume(min_accel_delta=self.delta)
                return EVENT_CONSUME

        return EVENT_CONSUME

    # ------------------------------------------------------------------
    # Small knob acceleration
    # ------------------------------------------------------------------

    def _get_small_knob_delta(self, direction: int, event_time: int) -> int:
        """Calculate accelerated delta for a dedicated volume knob.

        Uses a moving time window to calculate velocity, then applies
        acceleration.
        """
        delta = direction  # default: non-accelerated

        self._small_knob_points.append(event_time)

        # Remove stale points
        while len(self._small_knob_points) > 1:
            total_time = self._small_knob_points[-1] - self._small_knob_points[0]
            if total_time > 150:
                self._small_knob_points.pop(0)
            else:
                break

        # Need three points for acceleration to kick in
        if len(self._small_knob_points) > 2:
            total_time = self._small_knob_points[-1] - self._small_knob_points[0]
            if total_time > 0:
                velocity = len(self._small_knob_points) / total_time
                delta_real = SMALL_KNOB_ACCEL_CONSTANT * velocity
                if delta_real < 1:
                    delta_real = 1
                delta = int(delta_real) * direction
                log.debug("Using accelerated delta: %d", delta)

        return delta

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_ticks() -> int:
        """Return the current tick count in milliseconds."""
        try:
            from jive.ui.framework import framework as _fw

            if _fw is not None and hasattr(_fw, "getTicks"):
                return _fw.getTicks()
            if _fw is not None and hasattr(_fw, "get_ticks"):
                return _fw.get_ticks()
        except ImportError:
            pass
        import time

        return int(time.monotonic() * 1000)

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
