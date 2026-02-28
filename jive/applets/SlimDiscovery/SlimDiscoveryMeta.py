"""
applets.SlimDiscovery.SlimDiscoveryMeta — SlimDiscovery meta-info.

Ported from ``applets/SlimDiscovery/SlimDiscoveryMeta.lua`` in the
original jivelite Lua project.

SlimDiscovery is responsible for:

- UDP broadcast discovery of Lyrion Music Servers (SqueezeCenter / LMS)
  on the local network (port 3483).
- Tracking the *current player* selection and persisting it across
  restarts.
- Providing services that other applets use to enumerate players and
  servers (``getCurrentPlayer``, ``setCurrentPlayer``,
  ``discoverPlayers``, ``iteratePlayers``, etc.).

The meta class registers all public services, supplies default
settings, and runs ``configureApplet`` to restore the previously
selected player/server from persisted settings.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

log = logger("applet.SlimDiscovery")

__all__ = ["SlimDiscoveryMeta"]


class SlimDiscoveryMeta(AppletMeta):
    """Meta-info for the SlimDiscovery applet."""

    # ------------------------------------------------------------------
    # AppletMeta interface
    # ------------------------------------------------------------------

    def jive_version(self) -> tuple[int, int]:
        """Minimum and maximum supported Jive version."""
        return (1, 1)

    # Lua alias
    jiveVersion = jive_version

    def default_settings(self) -> Dict[str, Any]:
        """Return the default settings dict for SlimDiscovery."""
        return {
            "currentPlayer": False,
        }

    # Lua alias
    defaultSettings = default_settings

    def register_applet(self) -> None:
        """Register all services provided by SlimDiscovery."""

        # Player management
        self.register_service("getCurrentPlayer")
        self.register_service("setCurrentPlayer")

        # Discovery triggers
        self.register_service("discoverPlayers")
        self.register_service("discoverServers")

        # Connection management
        self.register_service("connectPlayer")
        self.register_service("disconnectPlayer")

        # Iteration / queries
        self.register_service("iteratePlayers")
        self.register_service("iterateSqueezeCenters")
        self.register_service("countPlayers")

        # Poll-list management
        self.register_service("getPollList")
        self.register_service("setPollList")

        # Initial server lookup
        self.register_service("getInitialSlimServer")

    # Lua alias
    registerApplet = register_applet

    def configure_applet(self) -> None:
        """
        Restore the previously selected player and server from
        persisted settings.

        This mirrors the Lua ``configureApplet`` which:

        1. Loads the SlimDiscovery applet eagerly.
        2. If a server was previously saved, creates/retrieves the
           ``SlimServer`` singleton and updates its init data.
        3. If a player was previously saved, creates/retrieves the
           ``Player`` singleton and sets it as current.
        4. As a fallback, picks the first local player if one exists.
        """
        try:
            self._do_configure()
        except Exception as exc:
            log.error("SlimDiscoveryMeta.configureApplet failed: %s", exc)

    # Lua alias
    configureApplet = configure_applet

    # ------------------------------------------------------------------
    # Notification handlers
    # ------------------------------------------------------------------

    def notify_playerNew(self, player: Any) -> None:
        """
        Handle the edge-case SqueezeNetwork dummy player
        (``ff:ff:ff:ff:ff:ff``).

        When this MAC is seen after a firmware upgrade the choose-player
        menu is triggered.  In practice this is a legacy path.
        """
        try:
            player_id = (
                player.get_id()
                if hasattr(player, "get_id")
                else getattr(player, "id", None)
            )
        except Exception:
            return

        if player_id != "ff:ff:ff:ff:ff:ff":
            return

        # Unsubscribe from future events
        jnt = self._get_jnt()
        if jnt:
            jnt.unsubscribe(self)

        mgr = self._get_applet_manager()
        if mgr:
            mgr.call_service("setupShowSelectPlayer", lambda: None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _do_configure(self) -> None:
        """Core logic for ``configure_applet``."""
        mgr = self._get_applet_manager()
        if mgr is None:
            log.warn("No applet manager available during configure")
            return

        settings = self.get_settings()
        jnt = self._get_jnt()

        # -- Load the applet eagerly --
        slim_discovery = mgr.load_applet("SlimDiscovery")

        # -- Restore server --
        server: Any = None
        server_name: Optional[str] = settings.get("serverName")
        server_uuid: Optional[str] = settings.get("serverUuid")
        server_init: Optional[Dict[str, Any]] = settings.get("serverInit")

        if server_name:
            if not server_uuid:
                server_uuid = server_name

            try:
                from jive.slim.slim_server import SlimServer

                server = SlimServer(jnt, server_uuid, server_name)
                if server_init:
                    server.update_init(server_init)
                SlimServer.add_locally_requested_server(server)
            except Exception as exc:
                log.error("Failed to restore server %s: %s", server_name, exc)
        else:
            log.info("server not yet present")

        # -- Restore player --
        player: Any = None
        player_id: Optional[str] = settings.get("playerId")
        player_init: Optional[Dict[str, Any]] = settings.get("playerInit")
        current_player_legacy: Any = settings.get("currentPlayer")

        if player_id:
            try:
                from jive.slim.player import Player

                player = Player(jnt, player_id)
                if player_init:
                    player.update_init(None, player_init)
            except Exception as exc:
                log.error("Failed to restore player %s: %s", player_id, exc)

        elif current_player_legacy:
            # Legacy setting — just the player ID string
            try:
                from jive.slim.player import Player

                player = Player(jnt, current_player_legacy)
            except Exception as exc:
                log.error(
                    "Failed to restore legacy player %s: %s",
                    current_player_legacy,
                    exc,
                )

        # Fallback: pick the first local player if available
        if player is None:
            try:
                from jive.slim.player import Player

                for _i, candidate in Player.iterate():
                    if candidate.is_local():
                        log.info(
                            "Setting local player as current player since "
                            "no saved player found and a local player exists"
                        )
                        player = candidate
                        break
            except Exception:
                pass

        # Apply the selection
        if player is not None and slim_discovery is not None:
            try:
                slim_discovery.setCurrentPlayer(player)
            except Exception as exc:
                log.error("setCurrentPlayer failed: %s", exc)

        # Handle the SqueezeNetwork dummy-player edge case
        if current_player_legacy == "ff:ff:ff:ff:ff:ff":
            log.info("SqueezeNetwork dummy player found")
            settings["currentPlayer"] = "ff:ff:ff:ff:ff:fe"
            if jnt:
                jnt.subscribe(self)

    # ------------------------------------------------------------------
    # Accessor helpers
    # ------------------------------------------------------------------

    def _get_applet_manager(self) -> Any:
        """Return the AppletManager, if available."""
        try:
            from jive.applet_manager import AppletManager

            # The meta has a back-reference set by the manager
            mgr = getattr(self, "_applet_manager", None)
            if mgr is not None:
                return mgr
            # Fallback: try the global singleton
            from jive.jive_main import jive_main as _jm

            if _jm is not None:
                return getattr(_jm, "applet_manager", None)
        except ImportError:
            pass
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
