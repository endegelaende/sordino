"""
jive.applets.HDGridSkin.HDGridSkinMeta --- Meta class for HDGridSkin.

Ported from ``share/jive/applets/HDGridSkin/HDGridSkinMeta.lua``
in the original jivelite project.

HDGridSkin is an HD grid skin for 1080p resolution displays.  It
registers a single 1080p grid skin variant with JiveMain.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["HDGridSkinMeta"]

log = logger("applet.HDGridSkin")


class HDGridSkinMeta(AppletMeta):
    """Meta-information for the HDGridSkin applet.

    Registers the 1080p grid skin with JiveMain so that it appears
    as a user-selectable skin option.
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
        """Register the HDGridSkin with JiveMain."""
        jive_main = self._get_jive_main()
        if jive_main is None:
            log.warn("HDGridSkinMeta: jiveMain not available for skin registration")
            return

        jive_main.register_skin(
            str(self.string("HD_GRID_SKIN_1080")),
            "HDGridSkin",
            "skin_1080p",
            "HDGridSkin-1080",
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
