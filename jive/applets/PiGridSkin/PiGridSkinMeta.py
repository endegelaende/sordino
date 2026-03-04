"""
jive.applets.PiGridSkin.PiGridSkinMeta -- Meta class for PiGridSkin.

Ported from ``share/jive/applets/PiGridSkin/PiGridSkinMeta.lua`` (~70 LOC)
in the original jivelite project.

PiGridSkin is a grid-layout skin that inherits from JogglerSkin.  It
registers multiple resolution variants:

* 800x480   -- default
* 1024x600
* 1280x800
* 1366x768
* Custom    -- user-defined via ``JL_SCREEN_WIDTH`` / ``JL_SCREEN_HEIGHT``
              environment variables (landscape only, ratio >= 1.2)

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Version 1.1 (25th January 2017) Michael Herger
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["PiGridSkinMeta"]

log = logger("applet.PiGridSkin")


class PiGridSkinMeta(AppletMeta):
    """Meta-information for the PiGridSkin applet.

    Registers the grid skin (and resolution variants) with JiveMain.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        """Return ``(min_version, max_version)`` of Jive supported."""
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        """Return default settings (empty dict -- no settings needed)."""
        return {}

    def register_applet(self) -> None:
        """Register the PiGridSkin and its resolution variants."""
        # Access jiveMain -- try the global singleton
        jive_main = self._get_jive_main()
        if jive_main is None:
            log.warn("PiGridSkinMeta: jiveMain not available for skin registration")
            return

        # Register the default 800x480 skin
        jive_main.register_skin(
            str(self.string("PIGRID_SKIN")),
            "PiGridSkin",
            "skin",
            "PiGridSkin",
        )

        # Register 1024x600 variant
        jive_main.register_skin(
            str(self.string("PIGRID_SKIN_1024_600")),
            "PiGridSkin",
            "skin1024x600",
            "PiGridSkin_1024x600",
        )

        # Register 1280x800 variant
        jive_main.register_skin(
            str(self.string("PIGRID_SKIN_1280_800")),
            "PiGridSkin",
            "skin1280x800",
            "PiGridSkin_1280x800",
        )

        # Register 1366x768 variant
        jive_main.register_skin(
            str(self.string("PIGRID_SKIN_1366_768")),
            "PiGridSkin",
            "skin1366x768",
            "PiGridSkin_1366x768",
        )

        # Allow user to define a custom screen size via environment variables
        screen_width = 0
        screen_height = 0
        try:
            screen_width = int(os.environ.get("JL_SCREEN_WIDTH", "0"))
        except (ValueError, TypeError) as exc:
            log.debug("register_applet: failed to parse JL_SCREEN_WIDTH: %s", exc)
        try:
            screen_height = int(os.environ.get("JL_SCREEN_HEIGHT", "0"))
        except (ValueError, TypeError) as exc:
            log.debug("register_applet: failed to parse JL_SCREEN_HEIGHT: %s", exc)

        # This skin only works in landscape mode with a decent ratio of >= 1.2
        if (
            screen_width > 300
            and screen_height > 200
            and screen_width / screen_height >= 1.2
        ):
            custom_label = (
                f"{self.string('PIGRID_SKIN_CUSTOM')} ({screen_width}x{screen_height})"
            )
            jive_main.register_skin(
                custom_label,
                "PiGridSkin",
                "skinCustom",
                "PiGridSkin_Custom",
            )
        elif screen_width > 0 or screen_height > 0:
            log.warn(
                "Custom screen size ratio (width/height) must be >= 1.2, is %s",
                screen_width / screen_height if screen_height > 0 else "inf",
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_jive_main() -> Any:
        """Try to obtain the JiveMain singleton.

        Returns ``None`` if not yet initialised.
        """
        try:
            from jive.jive_main import jive_main as _jm

            return _jm
        except (ImportError, AttributeError) as exc:
            log.debug("_get_jive_main: primary import failed: %s", exc)

        # Fallback: check for a module-level variable
        try:
            import jive.jive_main as _jm_mod

            return getattr(_jm_mod, "jive_main", None)
        except ImportError:
            return None
