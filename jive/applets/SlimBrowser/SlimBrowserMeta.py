"""
jive.applets.slim_browser.slim_browser_meta — Meta class for SlimBrowser.

Ported from ``share/jive/applets/SlimBrowser/SlimBrowserMeta.lua`` (~68 LOC)
in the original jivelite project.

SlimBrowser is the main music browser applet. Its Meta class:

* Declares version compatibility (1, 1)
* Registers multiple services:
  - ``showTrackOne`` — show info for the first playlist track
  - ``showPlaylist`` — show the current playlist
  - ``setPresetCurrentTrack`` — set a preset for the current track
  - ``squeezeNetworkRequest`` — make a request to SqueezeNetwork
  - ``browserJsonRequest`` — make a JSON request via the browser
  - ``browserActionRequest`` — make an action request via the browser
  - ``showCachedTrack`` — show a track from cached data
  - ``browserCancel`` — cancel a browser step
  - ``getAudioVolumeManager`` — get the Volume manager object
* Registers a dedicated log category for browser data
* Loads the SlimBrowser applet immediately (resident applet)

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["SlimBrowserMeta"]

log = logger("applet.SlimBrowser")


class SlimBrowserMeta(AppletMeta):
    """Meta-information for the SlimBrowser applet.

    Registers browser services and loads the applet immediately,
    since SlimBrowser is a resident applet that must always be
    available for music browsing and player control.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        """Return ``(min_version, max_version)`` of Jive supported."""
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        """Return default settings — none needed for SlimBrowser."""
        return None

    def register_applet(self) -> None:
        """Register SlimBrowser services and load the applet.

        SlimBrowser uses an extra log category for data logging,
        registers all its service entry points, and then loads
        itself immediately since it is a resident applet.
        """
        # Register the extra data logger
        logger("applet.SlimBrowser.data")

        # Register all services
        self.register_service("showTrackOne")
        self.register_service("showPlaylist")
        self.register_service("setPresetCurrentTrack")
        self.register_service("squeezeNetworkRequest")
        self.register_service("browserJsonRequest")
        self.register_service("browserActionRequest")
        self.register_service("showCachedTrack")
        self.register_service("browserCancel")
        self.register_service("getAudioVolumeManager")

        # SlimBrowser is a resident applet — load immediately
        applet_manager = self._get_applet_manager()
        if applet_manager is not None:
            applet_manager.load_applet("SlimBrowser")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_applet_manager() -> Any:
        """Try to obtain the AppletManager singleton.

        Returns ``None`` if not yet initialised.
        """
        try:
            from jive.applet_manager import applet_manager

            return applet_manager
        except (ImportError, AttributeError):
            return None
