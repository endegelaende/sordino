"""
jive.applets.qvga_base_skin.qvga_base_skin_meta — Meta class for QVGAbaseSkin.

Ported from ``share/jive/applets/QVGAbaseSkin/QVGAbaseSkinMeta.lua`` in the
original jivelite project.

QVGAbaseSkin is the base skin class for any 320×240 or 240×320 resolution
screen.  Its Meta is minimal — it declares version compatibility and empty
default settings, but does *not* register itself as a user-selectable skin
(child skins like QVGAlandscapeSkin / QVGAportraitSkin do that).

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["QVGAbaseSkinMeta"]

log = logger("applet.QVGAbaseSkin")


class QVGAbaseSkinMeta(AppletMeta):
    """Meta-information for the QVGAbaseSkin applet.

    This is the base skin for QVGA screens.  It does not register itself
    as a user-selectable skin — derived skins (landscape, portrait, etc.)
    do that.  It simply declares compatibility and provides empty default
    settings.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        """Return ``(min_version, max_version)`` of Jive supported."""
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        """Return default settings — empty dict for the base skin."""
        return {}

    def register_applet(self) -> None:
        """Register the applet.

        The base QVGA skin does *not* register itself as a selectable
        skin.  It serves only as a parent class / shared style provider
        for resolution-specific QVGA skins.
        """
        # Nothing to register — child skins call
        #   jiveMain.register_skin(...) in their own Meta classes.
        pass
