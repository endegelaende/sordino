"""
jive.applets.BlankScreenSaver.BlankScreenSaverMeta — Meta class for BlankScreenSaver.

Ported from ``share/jive/applets/BlankScreenSaver/BlankScreenSaverMeta.lua`` in the
original jivelite project.

The Meta class:

* Declares version compatibility (1, 1)
* In ``configure_applet()``, removes the legacy "BlankScreen" screensaver
  and registers this applet as "Blank Screen" via the ScreenSavers service.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["BlankScreenSaverMeta"]

log = logger("applet.BlankScreenSaver")


class BlankScreenSaverMeta(AppletMeta):
    """Meta-information for the BlankScreenSaver applet.

    Registers the blank-screen screensaver during the configure phase
    (after all applets have been registered), so the ScreenSavers
    service is guaranteed to be available.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        return (1, 1)

    def register_applet(self) -> None:
        """Nothing to register at this stage — configuration is deferred
        to :meth:`configure_applet` so that ScreenSavers is available."""

    # ------------------------------------------------------------------
    # Cross-applet configuration
    # ------------------------------------------------------------------

    def configure_applet(self) -> None:
        """Remove the legacy BlankScreen screensaver and register ours.

        Mirrors the Lua original which calls:

        * ``removeScreenSaver("BlankScreen", "openScreensaver")``
        * ``addScreenSaver("Blank Screen", "BlankScreenSaver",
          "openScreensaver", nil, nil, 100, "closeScreensaver")``
        """
        mgr = self._get_applet_manager()
        if mgr is None:
            log.warn("configure_applet: AppletManager not available")
            return

        # Remove the legacy screensaver (if registered)
        mgr.call_service("removeScreenSaver", "BlankScreen", "openScreensaver")

        # Register our replacement
        mgr.call_service(
            "addScreenSaver",
            "Blank Screen",  # display name
            "BlankScreenSaver",  # applet name
            "openScreensaver",  # open method
            None,  # settings method (unused)
            None,  # close window method (unused)
            100,  # default weight
            "closeScreensaver",  # close method
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
