"""
jive.applets.QVGA240squareSkin.QVGA240squareSkinMeta --- Meta class for QVGA240squareSkin.

Ported from ``share/jive/applets/QVGA240squareSkin/QVGA240squareSkinMeta.lua``
in the original jivelite project.

QVGA240squareSkin is the skin for 240x240 square displays such as the
Pirate Audio boards for the Raspberry Pi.  It registers itself as a
user-selectable skin with JiveMain.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["QVGA240squareSkinMeta"]

log = logger("applet.QVGA240squareSkin")


class QVGA240squareSkinMeta(AppletMeta):
    """Meta-information for the QVGA240squareSkin applet.

    Registers the 240x240 square skin with JiveMain so that it appears
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
        """Register the QVGA240squareSkin with JiveMain."""
        jive_main = self._get_jive_main()
        if jive_main is None:
            log.warn(
                "QVGA240squareSkinMeta: jiveMain not available for skin registration"
            )
            return

        jive_main.register_skin(
            str(self.string("QVGA240SQUARE_SKIN")),
            "QVGA240squareSkin",
            "skin",
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
