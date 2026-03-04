"""
jive.applets.ScreenSavers.ScreenSaversMeta — Meta class for ScreenSavers.

Ported from ``share/jive/applets/ScreenSavers/ScreenSaversMeta.lua`` (~65 LOC)
in the original jivelite project.

ScreenSavers is the screensaver manager applet.  Its Meta class:

* Declares version compatibility (1, 1)
* Provides default settings (screensaver choices per mode + timeout)
* Registers services: ``addScreenSaver``, ``removeScreenSaver``,
  ``restartScreenSaverTimer``, ``isScreensaverActive``,
  ``deactivateScreensaver``, ``activateScreensaver``
* Adds a "Screensavers" menu item under the ``screenSettings`` node

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["ScreenSaversMeta"]

log = logger("applet.ScreenSavers")


class ScreenSaversMeta(AppletMeta):
    """Meta-information for the ScreenSavers applet.

    Registers screensaver management services and a settings menu item.
    The applet is loaded on demand when the user opens the settings or
    when a screensaver needs to be activated.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        """Return ``(min_version, max_version)`` of Jive supported."""
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        """Return default settings for ScreenSavers.

        Settings keys:

        * ``whenStopped`` — screensaver key when player is stopped
        * ``whenPlaying`` — screensaver key when player is playing
        * ``whenOff`` — screensaver key when soft-power is off
        * ``timeout`` — idle timeout in milliseconds before activating
        """
        return {
            "whenStopped": "Clock:openDetailedClock",
            "whenPlaying": "NowPlaying:openScreensaver",
            "whenOff": "false:false",
            "timeout": 30000,
        }

    def register_applet(self) -> None:
        """Register ScreenSavers services and settings menu item.

        Registers the following services:

        * ``addScreenSaver`` — register a screensaver
        * ``removeScreenSaver`` — unregister a screensaver
        * ``restartScreenSaverTimer`` — restart the idle timer
        * ``isScreensaverActive`` — query whether a screensaver is active
        * ``deactivateScreensaver`` — close the active screensaver
        * ``activateScreensaver`` — activate the screensaver for the
          current mode

        Also adds a "Screensavers" menu item under ``screenSettings``.
        """
        self.register_service("addScreenSaver")
        self.register_service("removeScreenSaver")
        self.register_service("restartScreenSaverTimer")
        self.register_service("isScreensaverActive")
        self.register_service("deactivateScreensaver")
        self.register_service("activateScreensaver")

        # Add settings menu item
        jive_main = self._get_jive_main()
        if jive_main is not None:
            jive_main.add_item(
                self.menu_item(
                    id="appletScreenSavers",
                    node="screenSettings",
                    label="SCREENSAVERS",
                    closure=lambda applet, menu_item: applet.open_settings(menu_item),
                )
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

    @staticmethod
    def _get_jive_main() -> Any:
        """Try to obtain the JiveMain singleton."""
        try:
            from jive.jive_main import jive_main

            return jive_main
        except (ImportError, AttributeError) as exc:
            log.debug("_get_jive_main: jive_main not available: %s", exc)
        try:
            import jive.jive_main as _mod

            return getattr(_mod, "jive_main", None)
        except ImportError:
            return None
