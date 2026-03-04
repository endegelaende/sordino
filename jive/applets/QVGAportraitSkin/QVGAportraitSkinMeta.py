"""
jive.applets.QVGAportraitSkin.QVGAportraitSkinMeta --- Meta class for QVGAportraitSkin.

Ported from ``share/jive/applets/QVGAportraitSkin/QVGAportraitSkinMeta.lua``
in the original jivelite project.

QVGAportraitSkin is the skin for 240x320 portrait displays such as the
Squeezebox Controller in portrait orientation.  It registers itself as a
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

__all__ = ["QVGAportraitSkinMeta"]

log = logger("applet.QVGAportraitSkin")


class QVGAportraitSkinMeta(AppletMeta):
    """Meta-information for the QVGAportraitSkin applet.

    Registers the 240x320 portrait skin with JiveMain so that it appears
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
        """Register the QVGAportraitSkin with JiveMain."""
        jive_main = self._get_jive_main()
        if jive_main is None:
            log.warn(
                "QVGAportraitSkinMeta: jiveMain not available for skin registration"
            )
            return

        jive_main.register_skin(
            str(self.string("QVGAPORTRAIT_SKIN")),
            "QVGAportraitSkin",
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
