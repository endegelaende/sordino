"""
jive.applets.joggler_skin.joggler_skin_meta — Meta class for JogglerSkin.

Ported from ``share/jive/applets/JogglerSkin/JogglerSkinMeta.lua`` (~84 LOC)
in the original jivelite project.

JogglerSkin is the primary skin for 800×480 landscape displays (O2 Joggler,
Raspberry Pi 7" touchscreen, etc.).  It registers multiple resolution
variants:

* 800×480   — default
* 1024×600
* 1280×800
* 1366×768
* Custom    — user-defined via ``JL_SCREEN_WIDTH`` / ``JL_SCREEN_HEIGHT``
              environment variables (landscape only, ratio ≥ 1.2)

The Meta also registers two services used by NowPlaying to query and set
which transport-control buttons are shown on the NowPlaying toolbar:

* ``getNowPlayingScreenButtons`` — returns the current button settings dict
* ``setNowPlayingScreenButtons`` — sets a specific button on/off

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Redesigned by Andy Davison (birdslikewires.co.uk)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["JogglerSkinMeta"]

log = logger("applet.JogglerSkin")


class JogglerSkinMeta(AppletMeta):
    """Meta-information for the JogglerSkin applet.

    Registers the skin (and resolution variants) with JiveMain, and
    provides two services for NowPlaying toolbar button configuration.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        """Return ``(min_version, max_version)`` of Jive supported."""
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        """Return default NowPlaying toolbar button settings.

        Each key corresponds to a toolbar button; ``True`` means the
        button is shown by default.
        """
        return {
            "rew": True,
            "play": True,
            "fwd": True,
            "repeatMode": False,
            "shuffleMode": False,
            "volDown": True,
            "volSlider": False,
            "volUp": True,
        }

    def register_applet(self) -> None:
        """Register the JogglerSkin and its resolution variants.

        Also registers the ``getNowPlayingScreenButtons`` and
        ``setNowPlayingScreenButtons`` services.
        """
        # Register services for NowPlaying toolbar button management
        self.register_service("getNowPlayingScreenButtons")
        self.register_service("setNowPlayingScreenButtons")

        # Access jiveMain — try the global singleton
        jive_main = self._get_jive_main()
        if jive_main is None:
            log.warn("JogglerSkinMeta: jiveMain not available for skin registration")
            return

        # Register the default 800×480 skin
        jive_main.register_skin(
            str(self.string("JOGGLER_SKIN")),
            "JogglerSkin",
            "skin",
        )

        # Register 1024×600 variant
        jive_main.register_skin(
            str(self.string("JOGGLER_SKIN_1024_600")),
            "JogglerSkin",
            "skin1024x600",
            "JogglerSkin_1024x600",
        )

        # Register 1280×800 variant
        jive_main.register_skin(
            str(self.string("JOGGLER_SKIN_1280_800")),
            "JogglerSkin",
            "skin1280x800",
            "JogglerSkin_1280x800",
        )

        # Register 1366×768 variant
        jive_main.register_skin(
            str(self.string("JOGGLER_SKIN_1366_768")),
            "JogglerSkin",
            "skin1366x768",
            "JogglerSkin_1366x768",
        )

        # Allow user to define a custom screen size via environment variables
        screen_width = 0
        screen_height = 0
        try:
            screen_width = int(os.environ.get("JL_SCREEN_WIDTH", "0"))
        except (ValueError, TypeError) as exc:
            log.debug("register_applet: invalid JL_SCREEN_WIDTH env var: %s", exc)
        try:
            screen_height = int(os.environ.get("JL_SCREEN_HEIGHT", "0"))
        except (ValueError, TypeError) as exc:
            log.debug("register_applet: invalid JL_SCREEN_HEIGHT env var: %s", exc)

        # This skin only works in landscape mode with a decent ratio of >= 1.2
        if (
            screen_width > 300
            and screen_height > 200
            and screen_width / screen_height >= 1.2
        ):
            custom_label = (
                f"{self.string('JOGGLER_SKIN_CUSTOM')} ({screen_width}x{screen_height})"
            )
            jive_main.register_skin(
                custom_label,
                "JogglerSkin",
                "skinCustom",
                "JogglerSkin_Custom",
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
        except ImportError as exc:
            log.debug("_get_jive_main: fallback import failed: %s", exc)
            return None
