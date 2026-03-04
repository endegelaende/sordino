"""
jive.applets.HDSkin.HDSkinMeta --- Meta class for HDSkin.

Ported from ``share/jive/applets/HDSkin/HDSkinMeta.lua``
in the original jivelite project.

HDSkin is an HD skin supporting multiple resolutions: 1080p, 720p,
1280x1024, and VGA.  It registers all four resolution variants as
user-selectable skins with JiveMain.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["HDSkinMeta"]

log = logger("applet.HDSkin")


class HDSkinMeta(AppletMeta):
    """Meta-information for the HDSkin applet.

    Registers four HD skin resolution variants with JiveMain:
    1080p, 720p, 1280x1024, and VGA.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        """Return ``(min_version, max_version)`` of Jive supported."""
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        """Return default settings --- empty dict for this skin."""
        return {}

    def register_applet(self) -> None:
        """Register the HDSkin resolution variants with JiveMain."""
        jive_main = self._get_jive_main()
        if jive_main is None:
            log.warn("HDSkinMeta: jiveMain not available for skin registration")
            return

        jive_main.register_skin(
            str(self.string("HD_SKIN_1080")),
            "HDSkin",
            "skin_1080p",
            "HDSkin-1080",
        )
        jive_main.register_skin(
            str(self.string("HD_SKIN_720")),
            "HDSkin",
            "skin_720p",
            "HDSkin-720",
        )
        jive_main.register_skin(
            str(self.string("HD_SKIN_1280_1024")),
            "HDSkin",
            "skin_1280_1024",
            "HDSkin-1280-1024",
        )
        jive_main.register_skin(
            str(self.string("HD_SKIN_VGA")),
            "HDSkin",
            "skin_vga",
            "HDSkin-VGA",
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
            log.debug("_get_jive_main: jive_main not available: %s", exc)

        # Fallback: check for a module-level variable
        try:
            import jive.jive_main as _jm_mod

            return getattr(_jm_mod, "jive_main", None)
        except ImportError:
            return None
