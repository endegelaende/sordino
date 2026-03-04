"""
jive.applets.Screenshot.ScreenshotMeta — Meta class for Screenshot.

Ported from ``share/jive/applets/Screenshot/ScreenshotMeta.lua`` in the
original jivelite project.

The Meta class:

* Declares version compatibility (1, 1)
* In ``register_applet()``, eagerly loads the Screenshot applet so it
  becomes resident and listens for the ``take_screenshot`` action.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["ScreenshotMeta"]

log = logger("applet.Screenshot")


class ScreenshotMeta(AppletMeta):
    """Meta-information for the Screenshot applet.

    The Screenshot applet is a resident applet — it is loaded eagerly
    during registration and stays active for the lifetime of the
    application.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        return (1, 1)

    def register_applet(self) -> None:
        """Eagerly load the Screenshot applet so it becomes resident.

        Mirrors the Lua original::

            appletManager:loadApplet("Screenshot")
        """
        mgr = self._get_applet_manager()
        if mgr is not None:
            try:
                mgr.load_applet("Screenshot")
            except Exception as exc:
                log.warn("Failed to eagerly load Screenshot applet: %s", exc)
        else:
            log.warn("register_applet: AppletManager not available")

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
