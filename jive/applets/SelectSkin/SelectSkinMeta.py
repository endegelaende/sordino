"""
jive.applets.SelectSkin.SelectSkinMeta — Meta class for SelectSkin.

Ported from ``share/jive/applets/SelectSkin/SelectSkinMeta.lua`` (~100 LOC)
in the original jivelite project.

SelectSkin is the skin selection applet.  Its Meta class:

* Declares version compatibility (1, 1)
* Provides empty default settings
* Registers services: ``getSelectedSkinNameForType``,
  ``selectSkinStartup``
* Adds a "Select Skin" menu item under the ``screenSettings`` node
* Configures the initial skin on startup (from settings or default)
* Subscribes to ``notify_skinSelected`` and ``notify_serverConnected``
  to push artwork specs to the server
* Removes the menu item if only one skin is registered

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["SelectSkinMeta"]

log = logger("applet.SelectSkin")

# Default thumbnail size for menu artwork spec
_THUMB_SIZE_MENU: int = 40


class SelectSkinMeta(AppletMeta):
    """Meta-information for the SelectSkin applet.

    Registers skin selection services, adds a settings menu item,
    configures the initial skin on startup, and pushes artwork specs
    to connected servers when the skin changes.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        """Return ``(min_version, max_version)`` of Jive supported."""
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        """Return default settings for SelectSkin (empty)."""
        return {}

    def register_applet(self) -> None:
        """Register SelectSkin services and menu item.

        Registers:

        * ``getSelectedSkinNameForType`` — returns the selected skin
          name for a given skin type (touch / remote / skin).
        * ``selectSkinStartup`` — opens the skin selection screen
          during initial setup.

        Also adds a "Select Skin" menu item under ``screenSettings``
        and subscribes to network notifications for artwork spec
        updates.
        """
        jive_main = self._get_jive_main()
        if jive_main is not None:
            jive_main.add_item(
                self.menu_item(
                    id="appletSelectSkin",
                    node="screenSettings",
                    label="SELECT_SKIN",
                    closure=lambda applet, menu_item: applet.select_skin_entry_point(
                        menu_item
                    ),
                )
            )

        self.register_service("getSelectedSkinNameForType")
        self.register_service("selectSkinStartup")

        # Subscribe to notifications
        jnt = self._get_jnt()
        if jnt is not None:
            jnt.subscribe(self)

    def configure_applet(self) -> None:
        """Configure the initial skin on startup.

        If no skin has been saved in settings, uses the default skin
        from JiveMain.  Applies the saved skin and removes the menu
        item if only one skin is registered.
        """
        settings = self.get_settings()
        jive_main = self._get_jive_main()

        if jive_main is None:
            return

        if settings is None:
            settings = {}
            self._settings = settings

        # Set default skin if not yet saved
        if not settings.get("skin"):
            default_skin = None
            if hasattr(jive_main, "get_default_skin"):
                default_skin = jive_main.get_default_skin()
            elif hasattr(jive_main, "getDefaultSkin"):
                default_skin = jive_main.getDefaultSkin()
            settings["skin"] = default_skin

        # Apply the saved skin
        skin_id = settings.get("skin")
        if skin_id:
            if hasattr(jive_main, "set_selected_skin"):
                jive_main.set_selected_skin(skin_id)
            elif hasattr(jive_main, "setSelectedSkin"):
                jive_main.setSelectedSkin(skin_id)

        # Remove the menu item if only one skin is registered
        skin_count = 0
        if hasattr(jive_main, "skin_iterator"):
            for _ in jive_main.skin_iterator():
                skin_count += 1
        elif hasattr(jive_main, "skinIterator"):
            for _ in jive_main.skinIterator():
                skin_count += 1

        if skin_count <= 1:
            if hasattr(jive_main, "remove_item_by_id"):
                jive_main.remove_item_by_id("appletSelectSkin")
            elif hasattr(jive_main, "removeItemById"):
                jive_main.removeItemById("appletSelectSkin")

    # ------------------------------------------------------------------
    # Notification handlers
    # ------------------------------------------------------------------

    def notify_skinSelected(self, *args: Any, **kwargs: Any) -> None:
        """Push artwork spec to the current server when skin changes."""
        server = self._get_current_server()
        if server is not None:
            self._artworkspec(server)

    def notify_serverConnected(self, server: Any, *args: Any, **kwargs: Any) -> None:
        """Push artwork spec to a newly connected server."""
        if server is not None:
            self._artworkspec(server)

    # ------------------------------------------------------------------
    # Artwork spec helper
    # ------------------------------------------------------------------

    def _artworkspec(self, server: Any) -> None:
        """Push the menu thumbnail artwork spec to *server*.

        Sends an ``artworkspec add`` request so the server knows
        what thumbnail size this skin needs.
        """
        jive_main = self._get_jive_main()

        size = _THUMB_SIZE_MENU
        if jive_main is not None:
            if hasattr(jive_main, "get_skin_param"):
                param = jive_main.get_skin_param("THUMB_SIZE_MENU")
                if param is not None:
                    size = int(param)
            elif hasattr(jive_main, "getSkinParam"):
                param = jive_main.getSkinParam("THUMB_SIZE_MENU")
                if param is not None:
                    size = int(param)

        spec = f"{size}x{size}_m"

        if hasattr(server, "request"):
            try:
                server.request(None, None, ["artworkspec", "add", spec, "jiveliteskin"])
            except Exception as exc:
                log.warn("Failed to send artworkspec to server: %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_applet_manager() -> Any:
        """Try to obtain the AppletManager singleton."""
        try:
            from jive.applet_manager import applet_manager

            return applet_manager
        except (ImportError, AttributeError):
            return None

    @staticmethod
    def _get_jive_main() -> Any:
        """Try to obtain the JiveMain singleton."""
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
    def _get_jnt() -> Any:
        """Try to obtain the NetworkThread singleton."""
        try:
            from jive.jive_main import jive_main as _jm
            if _jm is not None:
                return getattr(_jm, "jnt", None)
        except ImportError as exc:
            log.debug("_get_jnt: jive_main not importable: %s", exc)
        return None

    @staticmethod
    def _get_current_server() -> Any:
        """Try to obtain the currently connected SlimServer."""
        try:
            from jive.slim.slim_server import SlimServer

            if hasattr(SlimServer, "getCurrentServer"):
                return SlimServer.getCurrentServer()
            elif hasattr(SlimServer, "get_current_server"):
                return SlimServer.get_current_server()
        except (ImportError, AttributeError) as exc:
            log.debug("_get_current_server: SlimServer not available: %s", exc)
        return None
