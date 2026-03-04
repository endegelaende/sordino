"""
jive.applets.LineIn.LineInMeta — Meta class for LineIn.

Ported from ``share/jive/applets/LineIn/LineInMeta.lua`` in the original
jivelite project.

The Meta class:

* Declares version compatibility (1, 1)
* Registers services for line-in menu item management and activation
* Loads the applet immediately (resident) during configure

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["LineInMeta"]

log = logger("applet.LineIn")


class LineInMeta(AppletMeta):
    """Meta-information for the LineIn applet."""

    def jive_version(self) -> Tuple[int, int]:
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        return None

    def register_applet(self) -> None:
        self.register_service("addLineInMenuItem")
        self.register_service("removeLineInMenuItem")
        self.register_service("activateLineIn")
        self.register_service("isLineInActive")
        self.register_service("getLineInNpWindow")

    def configure_applet(self) -> None:
        """Load the applet immediately so it stays resident."""
        mgr = self._get_applet_manager()
        if mgr is not None:
            mgr.load_applet("LineIn")

    @staticmethod
    def _get_applet_manager() -> Any:
        try:
            from jive.applet_manager import applet_manager
            return applet_manager
        except (ImportError, AttributeError):
            return None
