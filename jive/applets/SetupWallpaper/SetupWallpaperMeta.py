"""
jive.applets.SetupWallpaper.SetupWallpaperMeta — Meta class for SetupWallpaper.

Ported from ``share/jive/applets/SetupWallpaper/SetupWallpaperMeta.lua``
in the original jivelite project.

The Meta class:

* Declares version compatibility (1, 1)
* Provides default wallpaper setting per skin
* Registers ``showBackground`` and ``setBackground`` services
* Adds a "Wallpaper" menu item under ``screenSettings``
* Loads default wallpaper on configure

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["SetupWallpaperMeta"]

log = logger("applet.SetupWallpaper")


class SetupWallpaperMeta(AppletMeta):
    """Meta-information for the SetupWallpaper applet."""

    def jive_version(self) -> Tuple[int, int]:
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        return {
            "WQVGAsmallSkin": "fab4_encore.png",
            "WQVGAlargeSkin": "fab4_encore.png",
            "JogglerSkin": "jive_encore.png",
            "JogglerSkin_1024x600": "jive_encore.png",
            "JogglerSkin_1280x800": "jive_encore.png",
            "JogglerSkin_1366x768": "jive_encore.png",
            "HDSkin-VGA": "jive_encore.png",
            "HDSkin-720": "jive_encore.png",
            "HDSkin-1080": "jive_encore.png",
            "HDSkin-1280-1024": "jive_encore.png",
            "HDGridSkin-1080": "jive_encore.png",
            "PiGridSkin": "jive_encore.png",
            "PiGridSkin_1024x600": "jive_encore.png",
            "PiGridSkin_1280x800": "jive_encore.png",
            "PiGridSkin_1366x768": "jive_encore.png",
            "QVGAportraitSkin": "fab4_encore.png",
            "QVGAlandscapeSkin": "fab4_encore.png",
            "QVGA240squareSkin": "fab4_encore.png",
        }

    def register_applet(self) -> None:
        self.register_service("showBackground")
        self.register_service("setBackground")

        jive_main = self._get_jive_main()
        if jive_main is not None:
            jive_main.add_item(
                self.menu_item(
                    id="appletSetupWallpaper",
                    node="screenSettings",
                    label="WALLPAPER",
                    closure=lambda applet, menu_item: applet.settingsShow(menu_item),
                )
            )

    def configure_applet(self) -> None:
        """Load default wallpaper before connecting to a player."""
        mgr = self._get_applet_manager()
        if mgr is not None:
            try:
                mgr.call_service("setBackground", None)
            except Exception as exc:
                log.debug("configure_applet: setBackground failed: %s", exc)

    # ------------------------------------------------------------------
    # Singleton accessors
    # ------------------------------------------------------------------

    @staticmethod
    def _get_jive_main() -> Any:
        try:
            from jive.jive_main import jive_main

            return jive_main
        except (ImportError, AttributeError) as exc:
            log.debug("_get_jive_main: jive_main not available: %s", exc)
        try:
            import jive.jive_main as _mod

            return getattr(_mod, "jive_main", None)
        except ImportError:
            return None

    @staticmethod
    def _get_applet_manager() -> Any:
        try:
            from jive.applet_manager import applet_manager

            return applet_manager
        except (ImportError, AttributeError):
            return None
