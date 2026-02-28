"""
jive.applets.select_player.select_player_meta — Meta class for SelectPlayer.

Ported from ``share/jive/applets/SelectPlayer/SelectPlayerMeta.lua`` (~58 LOC)
in the original jivelite project.

SelectPlayer is the screen that lets the user choose which Squeezebox
player to control.  Its Meta class:

* Declares version compatibility (1, 1)
* Provides empty default settings
* Registers services: ``setupShowSelectPlayer``, ``selectPlayer``
* Loads the applet immediately (resident applet)

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["SelectPlayerMeta"]

log = logger("applet.SelectPlayer")


class SelectPlayerMeta(AppletMeta):
    """Meta-information for the SelectPlayer applet.

    Registers the ``setupShowSelectPlayer`` and ``selectPlayer``
    services, then immediately loads the applet since SelectPlayer
    is a resident applet that manages its own menu items based on
    the number of available players.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        """Return ``(min_version, max_version)`` of Jive supported."""
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        """Return default settings for SelectPlayer (empty)."""
        return {}

    def register_applet(self) -> None:
        """Register SelectPlayer services and load the applet.

        Registers:

        * ``setupShowSelectPlayer`` — opens the player-selection
          screen, optionally with a *setupNext* callback for use in
          setup wizards.
        * ``selectPlayer`` — programmatically selects a player and
          sets it as the current player.

        SelectPlayer is a resident applet — it is loaded immediately
        so that it can subscribe to player notifications and
        dynamically manage the "Choose Player" menu item.
        """
        self.register_service("setupShowSelectPlayer")
        self.register_service("selectPlayer")

        # SelectPlayer is a resident applet — load immediately
        applet_manager = self._get_applet_manager()
        if applet_manager is not None:
            applet_manager.load_applet("SelectPlayer")

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
