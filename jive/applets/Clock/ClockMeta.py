"""
jive.applets.Clock.ClockMeta — Meta class for Clock.

Ported from ``share/jive/applets/Clock/ClockMeta.lua`` (~65 LOC)
in the original jivelite project.

The Meta class:

* Declares version compatibility (1, 1)
* Has no default settings (empty dict)
* Does not register anything in ``register_applet()``
* In ``configure_applet()``, registers 6 screensavers via the
  ``addScreenSaver`` service:
  - Analog Clock
  - Digital Clock
  - Digital Clock (Black)
  - Digital Clock (Transparent)
  - Dot Matrix Clock
  - Word Clock

The Lua original::

    function configureApplet(self)
        appletManager:callService("addScreenSaver",
            self:string("SCREENSAVER_CLOCK_STYLE_ANALOG"),
            "Clock", "openAnalogClock", _, _, 23)
        appletManager:callService("addScreenSaver",
            self:string("SCREENSAVER_CLOCK_STYLE_DIGITAL"),
            "Clock", "openDetailedClock", _, _, 24)
        -- ... etc for all 6 screensavers
    end

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["ClockMeta"]

log = logger("applet.Clock")


class ClockMeta(AppletMeta):
    """Meta-information for the Clock applet.

    Registers six screensaver variants (Analog, Digital, Digital Black,
    Digital Transparent, Dot Matrix, Word Clock) during the configure
    phase so the ScreenSavers service is available.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        """Return ``(min_version, max_version)`` of Jive supported."""
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        """Return default settings — none needed for Clock."""
        return {}

    def register_applet(self) -> None:
        """Nothing to register at this stage — configuration is deferred
        to :meth:`configure_applet` so that ScreenSavers is available."""

    # ------------------------------------------------------------------
    # Cross-applet configuration
    # ------------------------------------------------------------------

    def configure_applet(self) -> None:
        """Register all six clock screensavers via the ScreenSavers service.

        Mirrors the Lua ``configureApplet`` which calls
        ``addScreenSaver`` for each clock variant with a weight value
        that determines the default sort order.

        Screensavers registered:

        ======  ====================================  ====================  ======
        Weight  Label (string token)                  Method                Weight
        ======  ====================================  ====================  ======
        23      SCREENSAVER_CLOCK_STYLE_ANALOG         openAnalogClock       23
        24      SCREENSAVER_CLOCK_STYLE_DIGITAL        openDetailedClock     24
        25      SCREENSAVER_CLOCK_STYLE_DIGITAL_BLACK  openDetailedClockBlack 25
        26      SCREENSAVER_CLOCK_STYLE_DIGITAL_TRANSPARENT openDetailedClockTransparent 26
        27      SCREENSAVER_CLOCK_STYLE_DOTMATRIX      openStyledClock       27
        28      Word Clock                             openWordClock         28
        ======  ====================================  ====================  ======
        """
        mgr = self._get_applet_manager()
        if mgr is None:
            log.warn("configure_applet: AppletManager not available")
            return

        # Each tuple: (string_token, applet_name, method_name, weight)
        screensavers = [
            ("SCREENSAVER_CLOCK_STYLE_ANALOG", "Clock", "openAnalogClock", 23),
            ("SCREENSAVER_CLOCK_STYLE_DIGITAL", "Clock", "openDetailedClock", 24),
            (
                "SCREENSAVER_CLOCK_STYLE_DIGITAL_BLACK",
                "Clock",
                "openDetailedClockBlack",
                25,
            ),
            (
                "SCREENSAVER_CLOCK_STYLE_DIGITAL_TRANSPARENT",
                "Clock",
                "openDetailedClockTransparent",
                26,
            ),
            ("SCREENSAVER_CLOCK_STYLE_DOTMATRIX", "Clock", "openStyledClock", 27),
            ("Word Clock", "Clock", "openWordClock", 28),
        ]

        for token, applet_name, method, weight in screensavers:
            # Resolve the display label through the string table
            label = self.string(token)
            mgr.call_service(
                "addScreenSaver",
                label,  # display name
                applet_name,  # applet name
                method,  # open method
                None,  # settings method (unused)
                None,  # close window method (unused)
                weight,  # default weight / sort order
            )
            log.debug(
                "Registered screensaver: %s (%s.%s, weight=%d)",
                label,
                applet_name,
                method,
                weight,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_applet_manager() -> Any:
        """Try to obtain the AppletManager singleton."""
        try:
            from jive.applet_manager import applet_manager

            return applet_manager
        except (ImportError, AttributeError):
            return None
