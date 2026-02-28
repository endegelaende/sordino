"""
applets.ChooseMusicSource.ChooseMusicSourceMeta — Meta-info for ChooseMusicSource.

Ported from ``applets/ChooseMusicSource/ChooseMusicSourceMeta.lua`` in the
original jivelite Lua project.

ChooseMusicSource allows users to select which Lyrion Music Server
(formerly SqueezeCenter / Logitech Media Server) a player should
connect to.  The meta class registers five services and configures the
poll list used by SlimDiscovery for server probing.

Services registered:

- ``selectCompatibleMusicSource`` — show only compatible servers
- ``selectMusicSource`` — show all discovered servers
- ``connectPlayerToServer`` — connect a player to a specific server
- ``hideConnectingToServer`` — dismiss the "connecting" popup
- ``showConnectToServer`` — show a "connecting to …" popup

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

log = logger("applet.ChooseMusicSource")

__all__ = ["ChooseMusicSourceMeta"]


class ChooseMusicSourceMeta(AppletMeta):
    """Meta-info for the ChooseMusicSource applet."""

    # ------------------------------------------------------------------
    # AppletMeta interface
    # ------------------------------------------------------------------

    def jive_version(self) -> tuple[int, int]:
        """Minimum and maximum supported Jive version."""
        return (1, 1)

    # Lua alias
    jiveVersion = jive_version

    def default_settings(self) -> Dict[str, Any]:
        """Return the default settings dict.

        The poll list contains broadcast and/or unicast addresses that
        SlimDiscovery should probe for servers.  The default is the
        broadcast address ``255.255.255.255`` which discovers servers
        on the local subnet.

        In the Lua original this is stored as a table mapping address
        strings to themselves.  We keep the same structure for
        compatibility with SlimDiscovery's ``setPollList`` service.
        """
        return {
            "poll": {"255.255.255.255": "255.255.255.255"},
        }

    # Lua alias
    defaultSettings = default_settings

    def register_applet(self) -> None:
        """Register services provided by ChooseMusicSource.

        Mirrors the Lua ``registerApplet`` which registers five
        services that other applets (especially SlimMenus and
        SlimDiscovery) depend on.
        """
        self.register_service("selectCompatibleMusicSource")
        self.register_service("selectMusicSource")
        self.register_service("connectPlayerToServer")
        self.register_service("hideConnectingToServer")
        self.register_service("showConnectToServer")

    # Lua alias
    registerApplet = register_applet

    def configure_applet(self) -> None:
        """Configure the applet after loading.

        Mirrors the Lua ``configureApplet`` which:

        1. Pushes the poll list from settings into SlimDiscovery via
           the ``setPollList`` service.
        2. Adds the "Remote Libraries" menu item to the
           ``networkSettings`` node so users can manage remote server
           addresses.
        """
        # ── Push poll list to SlimDiscovery ───────────────────────────
        mgr = self._get_applet_manager()
        if mgr is not None:
            try:
                if mgr.has_service("setPollList"):
                    poll = self.get_settings().get("poll", {})
                    mgr.call_service("setPollList", poll)
            except Exception as exc:
                log.debug("Could not set poll list: %s", exc)

        # ── Add "Remote Libraries" menu item ─────────────────────────
        jive_main = self._get_jive_main()
        if jive_main is not None:
            item = self.menu_item(
                "appletRemoteSlimservers",
                "networkSettings",
                "REMOTE_LIBRARIES",
                lambda applet, *args: applet.remoteServersWindow(*args),
                weight=11,
            )
            try:
                jive_main.add_item(item)
            except (AttributeError, TypeError) as exc:
                log.debug("Could not add Remote Libraries menu item: %s", exc)

    # Lua alias
    configureApplet = configure_applet

    # ------------------------------------------------------------------
    # Settings helper
    # ------------------------------------------------------------------

    def get_settings(self) -> Dict[str, Any]:
        """Return the applet's persisted settings, or defaults.

        Tries the AppletManager first (which handles persistence),
        then falls back to :meth:`default_settings`.
        """
        mgr = self._get_applet_manager()
        if mgr is not None:
            try:
                db = mgr.get_applet_db()
                entry = db.get("ChooseMusicSource", {})
                settings = entry.get("settings")
                if settings is not None:
                    return settings
            except Exception:
                pass
        return self.default_settings()

    # Lua alias
    getSettings = get_settings

    # ------------------------------------------------------------------
    # Menu-item builder helper
    # ------------------------------------------------------------------

    def menu_item(
        self,
        item_id: str,
        node: str,
        text_token: str,
        callback: Any = None,
        weight: int = 50,
        extras: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a home-menu item dict.

        Parameters
        ----------
        item_id:
            Unique identifier for the menu item.
        node:
            Parent node in the menu tree.
        text_token:
            Localisation token.  Resolved via the strings table if
            available; otherwise the raw token is used.
        callback:
            Callable ``callback(applet, ...)`` invoked on selection.
        weight:
            Sort weight (lower = higher in the menu).
        extras:
            Additional keys merged into the item dict.

        Returns
        -------
        dict
            A menu-item dict suitable for ``jiveMain.add_item()``.
        """
        # Resolve localised text
        text = text_token
        strings_table = getattr(self, "_strings_table", None)
        if strings_table is not None:
            try:
                resolved = strings_table.str(text_token)
                if resolved:
                    text = resolved
            except Exception:
                pass

        item: Dict[str, Any] = {
            "id": item_id,
            "node": node,
            "text": text,
            "weight": weight,
            "sound": "WINDOWSHOW",
        }

        if callback is not None:
            item["callback"] = callback

        icon_style = f"hm_{item_id}"
        item["iconStyle"] = icon_style

        if extras:
            item.update(extras)

        return item

    # Lua alias
    menuItem = menu_item

    # ------------------------------------------------------------------
    # Accessor helpers
    # ------------------------------------------------------------------

    def _get_applet_manager(self) -> Any:
        """Return the AppletManager, if available."""
        mgr = getattr(self, "_applet_manager", None)
        if mgr is not None:
            return mgr
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None:
                return getattr(_jm, "applet_manager", None)
        except ImportError:
            pass
        return None

    def _get_jive_main(self) -> Any:
        """Return the JiveMain singleton, if available."""
        try:
            from jive.jive_main import jive_main as _jm

            return _jm
        except ImportError:
            return None

    def _get_jnt(self) -> Any:
        """Return the notification hub / network thread, if available."""
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None:
                return getattr(_jm, "jnt", None)
        except ImportError:
            pass
        return None
