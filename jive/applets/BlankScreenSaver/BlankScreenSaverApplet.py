"""
jive.applets.BlankScreenSaver.BlankScreenSaverApplet — Blank Screen screensaver.

Ported from ``share/jive/applets/BlankScreenSaver/BlankScreenSaverApplet.lua``
in the original jivelite project.

This applet provides a screensaver that:

* Fills the screen with solid black
* Disables screen updates after a short delay (to save power / prevent burn-in)
* Re-enables screen updates on any motion event or when an overlay window appears
* Integrates with the ScreenSavers applet for proper lifecycle management

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Optional

from jive.applet import Applet
from jive.utils.log import logger

__all__ = ["BlankScreenSaverApplet"]

log = logger("applet.BlankScreenSaver")

# Delay (ms) before disabling screen updates after blanking
_SCREEN_OFF_DELAY_MS = 2000


class BlankScreenSaverApplet(Applet):
    """Display Off / Blank Screen screensaver applet.

    When activated, the screen is filled with black and after a short
    delay, screen updates are disabled entirely.  Any motion event
    will re-enable updates and dismiss the screensaver.

    The applet also handles overlay windows (e.g. volume popup) by
    temporarily re-enabling updates while the overlay is visible.
    """

    def __init__(self) -> None:
        super().__init__()
        self.window: Any = None
        self.bg: Any = None
        self.bgicon: Any = None
        self.sw: int = 0
        self.sh: int = 0
        self._screen_off_timer: Any = None

    # ------------------------------------------------------------------
    # Screensaver lifecycle (called by ScreenSavers applet)
    # ------------------------------------------------------------------

    def openScreensaver(self, menu_item: Any = None) -> None:
        """Open the blank screensaver.

        Creates a full-screen black window, disables framework widgets,
        and sets up listeners for motion (dismiss) and window
        active/hide (screen on/off).
        """
        log.info("open screensaver")

        fw = self._get_framework()
        if fw is None:
            log.warn("openScreensaver: Framework not available")
            return

        from jive.ui.constants import (
            EVENT_CONSUME,
            EVENT_HIDE,
            EVENT_MOTION,
            EVENT_UNUSED,
            EVENT_WINDOW_ACTIVE,
        )
        from jive.ui.icon import Icon
        from jive.ui.surface import Surface
        from jive.ui.timer import Timer
        from jive.ui.window import Window

        self.window = Window("text_list")

        # Create a solid black surface covering the entire screen
        self.sw, self.sh = fw.get_screen_size()
        self.bg = Surface.new_rgba(self.sw, self.sh)
        self.bg.filled_rectangle(0, 0, self.sw, self.sh, 0x000000FF)

        self.bgicon = Icon("icon", self.bg)
        self.window.add_widget(self.bgicon)

        self.window.set_show_framework_widgets(False)

        # Listener: toggle screen on/off when window becomes active/hidden
        def _on_active_hide(event: Any) -> int:
            etype = event.get_type() if hasattr(event, "get_type") else 0
            if etype == int(EVENT_WINDOW_ACTIVE):
                self._screen("off")
            else:
                self._screen("on")
            return int(EVENT_UNUSED)

        mask_active_hide = int(EVENT_WINDOW_ACTIVE) | int(EVENT_HIDE)
        self.window.add_listener(mask_active_hide, _on_active_hide)

        # Listener: dismiss screensaver on motion
        def _on_motion(event: Any) -> int:
            self._screen("on")
            self.window.hide()
            return int(EVENT_CONSUME)

        self.window.add_listener(int(EVENT_MOTION), _on_motion)

        # Register with the ScreenSavers manager
        mgr = self._get_applet_manager()
        if mgr is not None:
            ss_applet = mgr.get_applet_instance("ScreenSavers")
            if ss_applet is not None and hasattr(ss_applet, "screensaverWindow"):
                ss_applet.screensaverWindow(
                    self.window, None, None, None, "BlankScreenSaver"
                )

        # Create the screen-off timer (one-shot, 2 seconds)
        self._screen_off_timer = Timer(
            _SCREEN_OFF_DELAY_MS,
            lambda: self._set_update_screen(False),
            once=True,
        )

        # Show window with fade-in transition
        transition = getattr(Window, "transitionFadeIn", None)
        self.window.show(transition)

    def closeScreensaver(self) -> None:
        """Close the blank screensaver and re-enable screen updates."""
        log.info("close screensaver")
        self._screen("on")

    # ------------------------------------------------------------------
    # Overlay handling
    # ------------------------------------------------------------------

    def onOverlayWindowShown(self) -> None:
        """Called when an overlay window (e.g. volume popup) is shown."""
        self._screen("on")

    def onOverlayWindowHidden(self) -> None:
        """Called when an overlay window is hidden."""
        self._screen("off")

    # ------------------------------------------------------------------
    # Screen on/off control
    # ------------------------------------------------------------------

    def _screen(self, state: str) -> None:
        """Switch the screen on or off.

        When turning off, a timer is started that disables screen
        updates after :data:`_SCREEN_OFF_DELAY_MS` milliseconds.
        When turning on, the timer is cancelled and updates are
        re-enabled immediately.

        Parameters
        ----------
        state:
            ``"on"`` to enable updates, ``"off"`` to schedule disabling.
        """
        log.info("screen: %s", state)
        if state == "on":
            if self._screen_off_timer is not None:
                self._screen_off_timer.stop()
            self._set_update_screen(True)
        else:
            if self._screen_off_timer is not None:
                self._screen_off_timer.start()

    def _set_update_screen(self, enabled: bool) -> None:
        """Enable or disable framework screen updates."""
        fw = self._get_framework()
        if fw is not None:
            fw.set_update_screen(enabled)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def free(self) -> bool:
        """Allow the applet to be freed."""
        self._screen("on")
        if self._screen_off_timer is not None:
            self._screen_off_timer.stop()
            self._screen_off_timer = None
        self.window = None
        self.bg = None
        self.bgicon = None
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_framework() -> Any:
        """Try to obtain the Framework singleton."""
        try:
            from jive.ui.framework import framework

            return framework
        except (ImportError, AttributeError):
            return None

    @staticmethod
    def _get_applet_manager() -> Any:
        """Try to obtain the AppletManager singleton."""
        try:
            from jive.applet_manager import applet_manager

            return applet_manager
        except (ImportError, AttributeError):
            return None
