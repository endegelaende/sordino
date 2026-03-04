"""
applets.SlimMenus.SlimMenusApplet — Server-driven home-menu management.

Ported from ``applets/SlimMenus/SlimMenusApplet.lua`` in the original
jivelite Lua project.

SlimMenus manages the lifecycle of server-provided menu items in the
JiveMain home menu.  It:

- Subscribes to ``/slim/menustatus/<playerId>`` on the current server
  to receive real-time menu additions, removals, and updates.
- Fetches the initial menu tree from connected servers via the
  ``menu 0 100 direct:1`` JSON-RPC request.
- Merges server-provided nodes and items into the JiveMain home menu,
  applying compatibility transformations (style mapping, node remapping,
  item filtering).
- Handles server/player changes by tearing down old menus and
  requesting new ones from the new server.
- Provides the ``goHome``, ``hideConnectingToPlayer``, and
  ``warnOnAnyNetworkFailure`` services.

States / flow
-------------
1. On ``notify_playerCurrent`` the applet subscribes to menustatus
   for the new player and requests the initial menu (``menu 0 100``).
2. Menu items arrive via ``_menu_sink``, are massaged for compatibility,
   and inserted into the home menu via ``jiveMain.add_item`` /
   ``jiveMain.add_node``.
3. When the player or server changes, all previously-added items are
   removed and new ones are requested.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import copy
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
)

from jive.applet import Applet
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.slim.player import Player
    from jive.slim.slim_server import SlimServer

__all__ = ["SlimMenusApplet"]

log = logger("applet.SlimMenus")


# ── Compatibility maps ───────────────────────────────────────────────────
# Legacy map of item styles to new style names.
# WARNING — duplicated in SlimBrowserApplet (matches Lua original).
_STYLE_MAP: Dict[str, str] = {
    "itemplay": "item_play",
    "itemadd": "item_add",
    "itemNoAction": "item_no_arrow",
    "albumitem": "item",
    "albumitemplay": "item_play",
}

# Legacy map of item id/nodes → (new_id, new_node, weight, is_a_node).
_ITEM_MAP: Dict[str, Tuple[str, str, Optional[int], bool]] = {
    # nodes
    "myMusic": ("_myMusic", "hidden", None, True),
    "music_services": ("_music_services", "hidden", None, False),
    "music_stores": ("_music_stores", "hidden", None, False),
    # items
    "settingsPlaylistMode": (
        "settingsPlaylistMode",
        "advancedSettingsBetaFeatures",
        100,
        False,
    ),
    "playerDisplaySettings": (
        "playerDisplaySettings",
        "settingsBrightness",
        105,
        False,
    ),
}

# ID mismatches between server versions.
_ID_MISMATCH_MAP: Dict[str, str] = {
    "ondemand": "music_services",
}

# IDs that should be filtered out (not shown in the home menu).
_FILTERED_IDS: Set[str] = {
    "radios",
    "music_services",
    "_music_services",
    "music_stores",
    "_music_stores",
    "settingsAudio",
}

# Nodes that should be filtered out.
_FILTERED_NODES: Set[str] = {
    "music_services",
    "_music_services",
    "music_stores",
    "_music_stores",
}


# ── Helpers ──────────────────────────────────────────────────────────────


def _safe_deref(struct: Any, *keys: str) -> Any:
    """
    Safely dereference nested dicts.

    ``_safe_deref(d, "a", "b", "c")`` is equivalent to
    ``d["a"]["b"]["c"]`` but returns ``None`` if any intermediate
    key is missing or the value is not a dict.
    """
    res = struct
    for k in keys:
        if not isinstance(res, dict):
            return None
        res = res.get(k)
        if res is None:
            return None
    return res


def _get_applet_manager() -> Any:
    """Return the global AppletManager, or ``None``."""
    try:
        from jive.jive_main import jive_main as _jm

        if _jm is not None:
            return getattr(_jm, "applet_manager", None)
    except ImportError:
        log.debug("_get_applet_manager: jive_main not yet available")
    return None


def _get_jive_main() -> Any:
    """Return the JiveMain singleton, or ``None``."""
    try:
        from jive.jive_main import jive_main as _jm

        return _jm
    except ImportError:
        return None


def _get_jnt() -> Any:
    """Return the notification hub / network thread, or ``None``."""
    try:
        from jive.jive_main import jive_main as _jm

        if _jm is not None:
            return getattr(_jm, "jnt", None)
    except ImportError:
        log.debug("_get_jnt: jive_main not yet available")
    return None


def _get_system() -> Any:
    """Return the System *instance*, or ``None``.

    In the Lua original, ``System`` is a module-level singleton.
    In Python, the single ``System`` instance is owned by
    ``AppletManager`` (which receives it from ``JiveMain``).
    """
    try:
        from jive.applet_manager import applet_manager as _mgr

        if _mgr is not None and hasattr(_mgr, "system") and _mgr.system is not None:
            return _mgr.system
    except (ImportError, AttributeError):
        pass

    # Fallback: try JiveMain directly
    try:
        from jive.jive_main import jive_main as _jm

        if _jm is not None and hasattr(_jm, "_system"):
            return _jm._system
    except (ImportError, AttributeError):
        pass

    return None


def _massage_item(item: Dict[str, Any]) -> None:
    """
    Apply compatibility transformations to a menu item dict *in place*.

    Mirrors the Lua ``_massageItem`` function.
    """
    item_id = item.get("id")

    # Fix ID mismatches
    if item_id and item_id in _ID_MISMATCH_MAP:
        log.debug("fixing mismatch item: %s", item_id)
        item["id"] = _ID_MISMATCH_MAP[item_id]
        item_id = item["id"]

    # Apply item map transformations
    if item_id and item_id in _ITEM_MAP:
        new_id, new_node, weight, is_a_node = _ITEM_MAP[item_id]
        item["id"] = new_id
        item["node"] = new_node
        if weight is not None:
            item["weight"] = weight
        if is_a_node:
            item["isANode"] = True

    # Blank node → hidden
    if item.get("node") == "":
        item["node"] = "hidden"
        item["hiddenWeight"] = item.get("weight", 50)

    # Apply node map transformations
    node = item.get("node")
    if node and node in _ITEM_MAP:
        item["node"] = _ITEM_MAP[node][0]


def _get_app_type(request: Any) -> Optional[str]:
    """
    Extract the app type from a request command list.

    Returns the first element of the list, or ``None``.
    """
    if not request or not isinstance(request, (list, tuple)) or len(request) == 0:
        return None
    return request[0]  # type: ignore[no-any-return]


# ══════════════════════════════════════════════════════════════════════════
# SlimMenusApplet
# ══════════════════════════════════════════════════════════════════════════


class SlimMenusApplet(Applet):
    """
    Manages server-driven home-menu items.

    This is a resident applet — it is loaded eagerly by ``SlimMenusMeta``
    and remains active for the lifetime of the application.  It subscribes
    to server notifications and keeps the JiveMain home menu in sync with
    the server's menu tree.
    """

    def __init__(self) -> None:
        super().__init__()

        # Current player and server being tracked.
        self._player: Any = False
        self._server: Any = False

        # Whether we are still waiting for the initial menu response.
        self.waiting_for_player_menu_status: bool = True

        # Server → {item_id → item_dict} cache for each server's menu.
        self.server_home_menu_items: Dict[Any, Dict[str, Dict[str, Any]]] = {}

        # Items currently added to the home menu by this applet.
        self._player_menus: Dict[str, Dict[str, Any]] = {}

        # Screensaver registrations from the server.
        self._player_screensaver_registrations: Dict[str, Dict[str, Any]] = {}

        # Whether the "My Apps" node has been added.
        self.my_apps_node: bool = False

        # Network/server error state.
        self.network_error: Any = False
        self.server_error: bool = False

        # Whether a player/server change is in progress.
        self.player_or_server_change_in_progress: bool = False

        # Whether server init is complete.
        self.server_init_complete: bool = False

        # Flag that menu data has been received.
        self._menu_received: bool = False

        # Currently locked menu item (if any).
        self._locked_item: Any = False

        # Popup references.
        self._updating_player_popup: Any = False
        self._updating_prompt_popup: Any = False

        # Diagnostic window (if shown).
        self.diag_window: Any = None

    # ------------------------------------------------------------------
    # Applet lifecycle
    # ------------------------------------------------------------------

    def init(self, **kwargs: Any) -> "SlimMenusApplet":  # type: ignore[override]
        """
        Initialise the applet.

        Subscribes to the notification hub so that server/player
        connection events are received.
        """
        jnt = _get_jnt()
        if jnt is not None:
            try:
                jnt.subscribe(self)
            except Exception as exc:
                log.debug("Could not subscribe to jnt: %s", exc)

        self.waiting_for_player_menu_status = True
        self.server_home_menu_items = {}

        return self

    def free(self) -> bool:
        """
        Free the applet — tear down menus, unsubscribe from player.

        Mirrors the Lua ``free`` function.  Returns ``True`` to allow
        freeing (but as a resident applet this is rarely called except
        on player change).
        """
        self.server_home_menu_items = {}
        self.waiting_for_player_menu_status = True

        # Unsubscribe from the current player's menustatus
        if self._player and self._player is not False:
            try:
                player_id = self._get_player_id(self._player)
                if player_id:
                    self._player.unsubscribe(f"/slim/menustatus/{player_id}")
            except Exception as exc:
                log.error(
                    "free: failed to unsubscribe player menustatus: %s",
                    exc,
                    exc_info=True,
                )

        # Remove player menus from the home menu
        jm = _get_jive_main()
        if jm is not None:
            try:
                jm.set_title(None)
            except (AttributeError, TypeError) as exc:
                log.warning("free: failed to clear title: %s", exc)

        self.my_apps_node = False

        for item_id, item in list(self._player_menus.items()):
            self._remove_item_from_home(item)
        self._player_menus = {}

        for ss_id in list(self._player_screensaver_registrations.keys()):
            mgr = _get_applet_manager()
            if mgr is not None:
                try:
                    mgr.call_service("unregisterRemoteScreensaver", ss_id)
                except Exception as exc:
                    log.error(
                        "free: failed to unregister screensaver %s: %s",
                        ss_id,
                        exc,
                        exc_info=True,
                    )
        self._player_screensaver_registrations = {}

        # Unlock any locked item
        if self._locked_item and self._locked_item is not False:
            jm = _get_jive_main()
            if jm is not None:
                try:
                    jm.unlock_item(self._locked_item)
                except (AttributeError, TypeError) as exc:
                    log.warning("free: failed to unlock item: %s", exc)
            self._locked_item = False

        self._hide_player_updating()

        self._player = False
        self._server = False

        return True

    # ------------------------------------------------------------------
    # Service methods
    # ------------------------------------------------------------------

    def goHome(self) -> None:
        """
        Navigate to the home screen (service method).

        Delegates to ``jiveMain.go_home()``.
        """
        jm = _get_jive_main()
        if jm is not None:
            try:
                jm.go_home()
            except (AttributeError, TypeError) as exc:
                log.error("goHome: failed to navigate home: %s", exc, exc_info=True)

    # snake_case alias
    go_home = goHome

    def hideConnectingToPlayer(self) -> None:
        """
        Dismiss the "connecting to player" popup (service method).

        This is a no-op stub in the headless port — the real UI popup
        is only relevant when a display is available.
        """
        self._hide_player_updating()

    # snake_case alias
    hide_connecting_to_player = hideConnectingToPlayer

    def warnOnAnyNetworkFailure(
        self,
        success_callback: Optional[Callable[[], None]] = None,
        failure_callback: Optional[Callable[[Any], None]] = None,
    ) -> None:
        """
        Check for network failures before proceeding (service method).

        In the full UI this creates a Task that checks the active
        network interface.  In headless mode we simply call the
        success callback immediately.
        """
        if success_callback is not None:
            try:
                success_callback()
            except Exception as exc:
                log.error("warnOnAnyNetworkFailure success callback error: %s", exc)

    # snake_case alias
    warn_on_any_network_failure = warnOnAnyNetworkFailure

    # ------------------------------------------------------------------
    # My Music / Other Library selectors
    # ------------------------------------------------------------------

    def myMusicSelector(self, *args: Any) -> None:
        """
        Handle the "My Music" menu item selection.

        In the full implementation this checks for known servers,
        possibly switches the music source, and opens the ``_myMusic``
        node.  In the headless/minimal port we open the node directly
        if possible.
        """
        jm = _get_jive_main()
        mgr = _get_applet_manager()

        # Check for "new device, no server" situation
        if mgr is not None:
            initial_server = mgr.call_service("getInitialSlimServer")
            if initial_server is None and not self._any_known_squeeze_centers():
                log.info("No known SqueezeCenter, cannot open My Music")
                return

        if jm is not None:
            try:
                if self._server and hasattr(self._server, "name"):
                    self._update_my_music_title(self._server.name)
                jm.open_node_by_id("_myMusic")
            except (AttributeError, TypeError) as exc:
                log.warning("myMusicSelector: failed to open _myMusic node: %s", exc)

    # snake_case alias
    my_music_selector = myMusicSelector

    def otherLibrarySelector(self, *args: Any) -> None:
        """Handle the "Switch Library" menu item selection."""
        jm = _get_jive_main()
        if jm is not None:
            try:
                if self._server and hasattr(self._server, "name"):
                    self._update_my_music_title(self._server.name)
                jm.open_node_by_id("_myMusic", True)
            except (AttributeError, TypeError) as exc:
                log.warning(
                    "otherLibrarySelector: failed to open _myMusic node: %s", exc
                )

    # snake_case alias
    other_library_selector = otherLibrarySelector

    # ------------------------------------------------------------------
    # Notification handlers
    # ------------------------------------------------------------------

    def notify_networkOrServerNotOK(self, iface: Any = None) -> None:
        """Handle network or server failure notification."""
        log.warn("notify_networkOrServerNotOK")
        if (
            iface is not None
            and hasattr(iface, "isNetworkError")
            and iface.isNetworkError()
        ):
            self.network_error = iface
        else:
            self.network_error = False
            self.server_error = True

    def notify_networkAndServerOK(self, iface: Any = None) -> None:
        """Handle network and server recovery notification."""
        self.network_error = False
        self.server_error = False

        if self.diag_window is not None:
            try:
                self.diag_window.hide()
            except (AttributeError, TypeError) as exc:
                log.error(
                    "notify_networkAndServerOK: failed to hide diag window: %s",
                    exc,
                    exc_info=True,
                )
            self.diag_window = None

    def notify_serverConnected(self, server: Any) -> None:
        """
        Handle server connection notification.

        When a server connects, fetch its menu if it's relevant
        (SqueezeNetwork or the player's last SqueezeCenter).
        """
        log.debug("***serverConnected %s", server)

        mgr = _get_applet_manager()
        if mgr is None:
            return

        current_player = mgr.call_service("getCurrentPlayer")
        last_sc = None
        if current_player is not None:
            try:
                last_sc = current_player.get_last_squeeze_center()
            except (AttributeError, TypeError) as exc:
                log.debug(
                    "notify_serverConnected: get_last_squeeze_center unavailable, trying fallback: %s",
                    exc,
                )
                try:
                    last_sc = current_player.getLastSqueezeCenter()
                except (AttributeError, TypeError) as exc2:
                    log.error(
                        "notify_serverConnected: failed to get last SqueezeCenter: %s",
                        exc2,
                        exc_info=True,
                    )

        is_sn = False
        if hasattr(server, "is_squeeze_network"):
            try:
                is_sn = server.is_squeeze_network()
            except (AttributeError, TypeError) as exc:
                log.error(
                    "notify_serverConnected: is_squeeze_network call failed: %s",
                    exc,
                    exc_info=True,
                )
        elif hasattr(server, "isSqueezeNetwork"):
            try:
                is_sn = server.isSqueezeNetwork()
            except (AttributeError, TypeError) as exc:
                log.error(
                    "notify_serverConnected: isSqueezeNetwork call failed: %s",
                    exc,
                    exc_info=True,
                )

        if (is_sn or server == last_sc) and server is not self._server:
            self._fetch_server_menu(server)

        # Bug 15633: re-issue request if we are waiting and the server reconnected
        if (
            self.waiting_for_player_menu_status
            and self._server
            and server is self._server
            and self._player
            and self._player is not False
        ):
            try:
                is_connected = (
                    self._player.is_connected()
                    if hasattr(self._player, "is_connected")
                    else self._player.isConnected()
                    if hasattr(self._player, "isConnected")
                    else False
                )
                if is_connected:
                    player_id = self._get_player_id(self._player)
                    if player_id and self._server:
                        self._request_initial_menus(self._server, player_id, True)
            except Exception as exc:
                log.debug("serverConnected re-request failed: %s", exc)

    def notify_playerNewName(self, player: Any, new_name: str) -> None:
        """
        Handle player name change notification.

        Updates the home-menu title to reflect the new name.
        """
        log.debug("SlimMenusApplet:notify_playerNewName(%s, %s)", player, new_name)

        if self._player is player:
            jm = _get_jive_main()
            if jm is not None:
                try:
                    jm.set_title(new_name)
                except (AttributeError, TypeError) as exc:
                    log.error(
                        "notify_playerNewName: failed to set title to %r: %s",
                        new_name,
                        exc,
                        exc_info=True,
                    )

    def notify_playerNeedsUpgrade(
        self, player: Any, needs_upgrade: bool, is_upgrading: bool
    ) -> None:
        """
        Handle player upgrade notification.

        In the full UI this shows upgrade popups.  In headless mode
        this is a no-op log message.
        """
        if self._player is not player:
            return

        try:
            if hasattr(player, "is_needs_upgrade"):
                needs = player.is_needs_upgrade()
            elif hasattr(player, "isNeedsUpgrade"):
                needs = player.isNeedsUpgrade()
            else:
                needs = needs_upgrade

            if needs:
                log.info("Player needs upgrade")
            else:
                self._hide_player_updating()
        except Exception as exc:
            log.error(
                "notify_playerNeedsUpgrade: failed to check upgrade status: %s",
                exc,
                exc_info=True,
            )

    def notify_playerDelete(self, player: Any) -> None:
        """
        Handle player deletion notification.

        Unsubscribes from the player's menustatus.
        """
        log.debug("notify_playerDelete(%s)", player)

        if self._player is player:
            if self._player and self._player is not False:
                try:
                    player_id = self._get_player_id(self._player)
                    if player_id:
                        self._player.unsubscribe(f"/slim/menustatus/{player_id}")
                except Exception as exc:
                    log.error(
                        "notify_playerDelete: failed to unsubscribe menustatus: %s",
                        exc,
                        exc_info=True,
                    )
            self.player_or_server_change_in_progress = True

    def notify_playerCurrent(self, player: Any) -> None:
        """
        Handle current-player change notification.

        This is the main driver: when the current player changes
        the applet tears down old menus, subscribes to the new
        player's menustatus, and requests the initial menu tree.
        """
        log.info("SlimMenusApplet:notify_playerCurrent(%s)", player)

        # Has the player actually changed?
        if self._player is player and not self.waiting_for_player_menu_status:
            if player is not None and player is not False:
                player_server = self._get_player_server(player)
                if (
                    player_server is self._server
                    and not self.player_or_server_change_in_progress
                ):
                    log.debug(
                        "player and server didn't change, not changing menus: %s",
                        player,
                    )
                    return
                else:
                    # Server changed — remove existing menus
                    self.my_apps_node = False
                    jm = _get_jive_main()
                    for item_id, item in list(self._player_menus.items()):
                        self._remove_item_from_home(item)

                    self._server = self._get_player_server(player)

                    player_name = self._get_player_name(player)
                    if self._server:
                        server_name = self._get_server_name(self._server)
                        self._update_my_music_title(server_name)

                    if jm is not None:
                        try:
                            jm.set_title(player_name)
                        except (AttributeError, TypeError) as exc:
                            log.error(
                                "notify_playerCurrent: failed to set title during server change: %s",
                                exc,
                                exc_info=True,
                            )
            else:
                return

        if player is not None and player is not False:
            player_server = self._get_player_server(player)
            if player_server is None:
                log.info(
                    "player changed from %s to %s but server not yet present",
                    self._player,
                    player,
                )

        if self._player is not player:
            # Free current player since it has changed
            if self._player and self._player is not False:
                self.free()

            # Re-cache home menu items from other servers
            if self.server_init_complete:
                mgr = _get_applet_manager()
                if mgr is not None:
                    last_sc = None
                    if player:
                        try:
                            last_sc = (
                                player.get_last_squeeze_center()
                                if hasattr(player, "get_last_squeeze_center")
                                else player.getLastSqueezeCenter()
                                if hasattr(player, "getLastSqueezeCenter")
                                else None
                            )
                        except (AttributeError, TypeError) as exc:
                            log.error(
                                "notify_playerCurrent: failed to get last SqueezeCenter: %s",
                                exc,
                                exc_info=True,
                            )

                    try:
                        for _id, server in (
                            mgr.call_service("iterateSqueezeCenters") or ()
                        ):
                            is_compatible = self._server_is_compatible(server)
                            is_sn = self._server_is_squeeze_network(server)
                            if (
                                is_compatible
                                and (is_sn or server is last_sc)
                                and server is not self._server
                            ):
                                self._fetch_server_menu(server)
                    except Exception as exc:
                        log.debug("Re-cache server menus error: %s", exc)

        # Nothing to do if we don't have a player
        if not player or player is False:
            return

        if not self._server and not self.server_init_complete:
            self.server_init_complete = True
            mgr = _get_applet_manager()
            if mgr is not None:
                self._server = mgr.call_service("getInitialSlimServer")
                log.info("No server, fetching initial server: %s", self._server)

        player_server = self._get_player_server(player)

        # Can't subscribe to menustatus without a server
        if player_server is None:
            return

        # Server must be connected
        if not self._server_is_connected(player_server):
            log.info("player changed to %s but server not yet connected", player)
            return

        self.player_or_server_change_in_progress = False

        log.info(
            "player changed from %s to %s for server %s",
            self._player,
            player,
            player_server,
        )

        self._player = player
        self._server = player_server

        player_id = self._get_player_id(self._player)

        if player_id:
            self.waiting_for_player_menu_status = True
            log.info("Subscribing to /slim/menustatus/%s", player_id)

            # Subscribe to menustatus notifications
            try:
                cmd = ["menustatus"]
                self._player.subscribe(
                    f"/slim/menustatus/{player_id}",
                    self._menu_sink(True, None),
                    player_id,
                    cmd,
                )
            except Exception as exc:
                log.debug("menustatus subscribe failed: %s", exc)

            # Request initial menus from the connected server
            self._request_initial_menus(self._server, player_id, True)

        # Reset menu received flag
        self._menu_received = False

        # Track last SqueezeCenter for local players
        if player and self._server:
            try:
                is_local = (
                    player.is_local()
                    if hasattr(player, "is_local")
                    else player.isLocal()
                    if hasattr(player, "isLocal")
                    else False
                )
                is_sn = self._server_is_squeeze_network(self._server)
                if is_local and not is_sn:
                    if hasattr(player, "set_last_squeeze_center"):
                        player.set_last_squeeze_center(self._server)
                    elif hasattr(player, "setLastSqueezeCenter"):
                        player.setLastSqueezeCenter(self._server)
            except Exception as exc:
                log.error(
                    "notify_playerCurrent: failed to track last SqueezeCenter: %s",
                    exc,
                    exc_info=True,
                )

        # Update UI title
        jm = _get_jive_main()
        if jm is not None and self._server:
            try:
                player_name = self._get_player_name(self._player)
                server_name = self._get_server_name(self._server)
                self._update_my_music_title(server_name)
                jm.set_title(player_name)
            except (AttributeError, TypeError) as exc:
                log.error(
                    "notify_playerCurrent: failed to set UI title: %s",
                    exc,
                    exc_info=True,
                )

        # Display upgrade popups if needed (Lua passes only player here;
        # the handler queries the player object directly for upgrade status)
        self.notify_playerNeedsUpgrade(player, False, False)

    # ------------------------------------------------------------------
    # Menu sink — processes incoming menu data
    # ------------------------------------------------------------------

    def _menu_sink(
        self,
        is_current_server: bool,
        server: Any,
    ) -> Callable[..., None]:
        """
        Return a sink closure that processes menu data from the server.

        Mirrors the Lua ``_menuSink`` function.

        Parameters
        ----------
        is_current_server:
            Whether the data is from the currently selected server.
        server:
            The server that sent the data.  ``None`` for menustatus
            notifications (which come from the connected server).
        """
        applet = self

        def sink(chunk: Dict[str, Any], err: Any = None) -> None:
            is_menu_status_response = server is None

            menu_items: List[Dict[str, Any]]
            menu_directive: Optional[str] = None
            player_id: Optional[str] = None

            if is_menu_status_response:
                # menustatus notification for the connected player
                if not applet._player or applet._player is False:
                    log.warn("catch race condition if we've switched player")
                    return

                data = chunk.get("data", [])
                if isinstance(data, list) and len(data) >= 2:
                    menu_items = data[1] if isinstance(data[1], list) else [data[1]]
                else:
                    menu_items = []
                    return

                if len(data) >= 3:
                    menu_directive = data[2]
                if len(data) >= 4:
                    player_id = data[3]

                our_id = applet._get_player_id(applet._player)
                if player_id and player_id != "all" and player_id != our_id:
                    log.debug("menu notification not for this player")
                    return

                if applet._server and menu_directive == "add":
                    applet._add_server_home_menu_items(applet._server, menu_items)
            else:
                # Response from a "menu" command for a non-connected server
                data = chunk.get("data", {})
                if isinstance(data, dict):
                    menu_items = data.get("item_loop", [])
                elif isinstance(data, list) and len(data) > 0:
                    menu_items = data
                else:
                    menu_items = []

                applet._add_server_home_menu_items(server, menu_items)

            if not isinstance(menu_items, list):
                menu_items = list(menu_items) if menu_items else []

            # Mark that we've received menu data
            applet._menu_received = True

            log.info(
                "_menu_sink(%d items) server=%s directive=%s is_current=%s",
                len(menu_items),
                server,
                menu_directive,
                is_current_server,
            )

            jm = _get_jive_main()
            mgr = _get_applet_manager()

            for v in menu_items:
                if not isinstance(v, dict):
                    continue

                add_app_to_home = False

                item: Dict[str, Any] = {
                    "id": v.get("id"),
                    "node": v.get("node"),
                    "isApp": v.get("isApp"),
                    "iconStyle": v.get("iconStyle"),
                    "style": v.get("style"),
                    "text": v.get("text"),
                    "homeMenuText": v.get("homeMenuText"),
                    "weight": v.get("weight"),
                    "window": v.get("window"),
                    "windowStyle": v.get("windowStyle"),
                    "sound": "WINDOWSHOW",
                    "screensavers": v.get("screensavers"),
                }

                # Handle "My Apps" items
                if item.get("isApp") == 1:
                    if not applet.my_apps_node:
                        applet._add_my_apps_node()
                    if item.get("node") == "home":
                        add_app_to_home = True
                    item["node"] = "myApps"

                # Determine icon
                item_icon = None
                v_window = v.get("window")
                if isinstance(v_window, dict):
                    item_icon = v_window.get("icon-id") or v_window.get("icon")
                else:
                    item_icon = v.get("icon-id") or v.get("icon")

                if not isinstance(v.get("window"), dict):
                    v["window"] = {}
                if not v["window"].get("windowId"):
                    v["window"]["windowId"] = v.get("id")

                if item_icon:
                    # Fetch artwork from the relevant server
                    icon_server = server if server else applet._server
                    if icon_server and jm is not None:
                        try:
                            from jive.ui.icon import Icon

                            thumb_size = 56  # default
                            try:
                                thumb_size = jm.get_skin_param("THUMB_SIZE_MENU") or 56
                            except (AttributeError, TypeError) as exc:
                                log.warning(
                                    "_menu_sink: failed to get THUMB_SIZE_MENU skin param: %s",
                                    exc,
                                )

                            item_icon_widget = Icon("icon")
                            try:
                                icon_server.fetch_artwork(
                                    item_icon, item_icon_widget, thumb_size, "png"
                                )
                            except (AttributeError, TypeError) as exc:
                                log.debug(
                                    "_menu_sink: fetch_artwork unavailable, trying fallback: %s",
                                    exc,
                                )
                                try:
                                    icon_server.fetchArtwork(
                                        item_icon, item_icon_widget, thumb_size, "png"
                                    )
                                except (AttributeError, TypeError) as exc2:
                                    log.warning(
                                        "_menu_sink: failed to fetch artwork for icon %s: %s",
                                        item_icon,
                                        exc2,
                                    )
                            item["icon"] = item_icon_widget
                        except ImportError as exc:
                            log.debug("_menu_sink: Icon widget not available: %s", exc)

                    # Store app parameter
                    app_type = _get_app_type(_safe_deref(v, "actions", "go", "cmd"))
                    if app_type and icon_server:
                        try:
                            icon_server.set_app_parameter(app_type, "iconId", item_icon)
                        except (AttributeError, TypeError) as exc:
                            log.debug(
                                "_menu_sink: set_app_parameter unavailable, trying fallback: %s",
                                exc,
                            )
                            try:
                                icon_server.setAppParameter(
                                    app_type, "iconId", item_icon
                                )
                            except (AttributeError, TypeError) as exc2:
                                log.warning(
                                    "_menu_sink: failed to set app parameter iconId for %s: %s",
                                    app_type,
                                    exc2,
                                )
                else:
                    # Make an icon style from the ID
                    if item.get("id") and not item.get("iconStyle"):
                        item["iconStyle"] = f"hm_{item['id']}"

                # Register remote screensavers
                if (
                    is_current_server
                    and item.get("screensavers")
                    and isinstance(item["screensavers"], list)
                ):
                    for server_data in item["screensavers"]:
                        if isinstance(server_data, dict):
                            cmd_list = server_data.get("cmd", [])
                            server_data["id"] = " ".join(str(c) for c in cmd_list)
                            server_data["playerId"] = applet._get_player_id(
                                applet._player
                            )
                            server_data["server"] = applet._server
                            server_data["appParameters"] = None
                            app_type = _get_app_type(
                                _safe_deref(v, "actions", "go", "cmd")
                            )
                            if app_type and applet._server:
                                try:
                                    server_data["appParameters"] = (
                                        applet._server.get_app_parameters(app_type)
                                    )
                                except (AttributeError, TypeError) as exc:
                                    log.warning(
                                        "_menu_sink: failed to get app parameters for %s: %s",
                                        app_type,
                                        exc,
                                    )
                            applet._register_remote_screensaver(server_data)

                # Map legacy styles
                if item.get("style") and item["style"] in _STYLE_MAP:
                    item["style"] = _STYLE_MAP[item["style"]]

                # Apply compatibility transformations
                _massage_item(item)

                # ── Filtering ────────────────────────────────────────
                item_id = item.get("id")
                item_node = item.get("node")

                if not item_id:
                    log.info("no id for menu item: %s", item.get("text"))
                    continue

                # Filter out items we handle locally
                if item_id in _FILTERED_IDS:
                    continue
                if item_node and item_node in _FILTERED_NODES:
                    continue

                # Skip opmlmyapps when My Apps node is active
                if item_id == "opmlmyapps" and applet.my_apps_node:
                    continue

                # Skip playerpower on devices with soft-power
                system = _get_system()
                if item_id == "playerpower" and system is not None:
                    try:
                        machine = (
                            system.get_machine()
                            if hasattr(system, "get_machine")
                            else None
                        )
                        if system.has_soft_power() and machine != "squeezeplay":
                            continue
                    except (AttributeError, TypeError) as exc:
                        log.warning(
                            "_menu_sink: failed to check soft power for playerpower filter: %s",
                            exc,
                        )

                # Skip items only applicable to current server
                if item_id == "settingsPlayerNameChange" and not is_current_server:
                    continue
                if item_id == "settingsSleep" and not is_current_server:
                    continue

                # Skip alarm settings when time input is disabled
                if item_id == "settingsAlarm" and jm is not None:
                    try:
                        if jm.get_skin_param_or_nil("disableTimeInput"):
                            continue
                    except (AttributeError, TypeError) as exc:
                        log.warning(
                            "_menu_sink: failed to check disableTimeInput skin param: %s",
                            exc,
                        )

                # ── Process item ─────────────────────────────────────

                if v.get("isANode") or item.get("isANode"):
                    # It's a node
                    if item_id != "_myMusic":
                        applet._add_node(item, is_current_server)
                    else:
                        log.info("Eliminated myMusic node from server, handled locally")

                elif menu_directive == "remove":
                    # Remove directive
                    if jm is not None:
                        try:
                            jm.remove_item_by_id(item_id)
                        except (AttributeError, TypeError) as exc:
                            log.warning(
                                "_menu_sink: failed to remove item %s: %s", item_id, exc
                            )

                elif is_current_server and _safe_deref(v, "actions", "do", "choices"):
                    # Choice item (e.g. repeat mode selection)
                    selected_index = 1
                    if v.get("selectedIndex"):
                        try:
                            selected_index = int(v["selectedIndex"])
                        except (ValueError, TypeError) as exc:
                            log.debug(
                                "_menu_sink: failed to parse selectedIndex %r: %s",
                                v.get("selectedIndex"),
                                exc,
                            )

                    item["style"] = "item_choice"
                    item["removeOnServerChange"] = True

                    # Store the choice data for later use
                    item["_choice_strings"] = v.get("choiceStrings", [])
                    item["_choice_actions"] = _safe_deref(v, "actions", "do", "choices")
                    item["_selected_index"] = selected_index

                    applet._add_item(item, is_current_server, add_app_to_home)

                else:
                    # Standard action item
                    # Store the full server data for browserActionRequest
                    item["_server_data"] = v

                    if _safe_deref(v, "actions", "play"):
                        item["isPlayableItem"] = True

                    def _make_callback(
                        _v: Dict[str, Any], _item: Dict[str, Any]
                    ) -> Callable[..., None]:
                        def _cb(*args: Any, **kwargs: Any) -> None:
                            no_locking = kwargs.get("noLocking", False)
                            if len(args) > 2:
                                no_locking = args[2]

                            _mgr = _get_applet_manager()
                            if _mgr is not None:
                                try:
                                    # Lua passes a loadedCallback that
                                    # unlocks the item after the browse
                                    # window is shown.  Without it,
                                    # _on_loaded never pushes/shows the
                                    # new window.
                                    def _loaded_cb(step: Any = None) -> None:
                                        jm2 = _get_jive_main()
                                        if jm2 is not None and hasattr(
                                            jm2, "unlock_item"
                                        ):
                                            jm2.unlock_item(_item)

                                    _mgr.call_service(
                                        "browserActionRequest",
                                        None,
                                        _v,
                                        _loaded_cb,
                                    )
                                except Exception as exc2:
                                    log.debug(
                                        "browserActionRequest failed: %s",
                                        exc2,
                                    )

                        return _cb

                    item["callback"] = _make_callback(v, item)

                    applet._add_item(item, is_current_server, add_app_to_home)

            # Signal that menus are loaded
            if applet._menu_received and is_current_server:
                log.info(
                    "hiding 'connecting' popup after menu response from %s",
                    applet._server,
                )
                applet.waiting_for_player_menu_status = False

                jnt_obj = _get_jnt()
                if jnt_obj is not None:
                    try:
                        jnt_obj.notify("playerLoaded", applet._player)
                    except Exception as exc:
                        log.error(
                            "_menu_sink: failed to send playerLoaded notification: %s",
                            exc,
                            exc_info=True,
                        )

                _mgr = _get_applet_manager()
                if _mgr is not None:
                    try:
                        _mgr.call_service("hideConnectingToServer")
                    except Exception as exc:
                        log.error(
                            "_menu_sink: failed to call hideConnectingToServer service: %s",
                            exc,
                            exc_info=True,
                        )

        return sink

    # ------------------------------------------------------------------
    # Menu manipulation helpers
    # ------------------------------------------------------------------

    def _add_node(self, node: Dict[str, Any], is_current_server: bool) -> None:
        """
        Add a node to the home menu.

        Only the current server may replace existing nodes.
        """
        jm = _get_jive_main()
        if jm is None:
            return

        if is_current_server:
            try:
                jm.add_node(node)
            except (AttributeError, TypeError) as exc:
                log.warning(
                    "_add_node: failed to add node %s (current server): %s",
                    node.get("id"),
                    exc,
                )
        else:
            # Only add if it doesn't exist yet
            try:
                exists = False
                menu_table = jm.get_menu_table()
                if isinstance(menu_table, dict):
                    exists = node.get("id", "") in menu_table
                if not exists:
                    try:
                        jm.add_node(node)
                    except (AttributeError, TypeError) as exc:
                        log.warning(
                            "_add_node: failed to add new node %s: %s",
                            node.get("id"),
                            exc,
                        )
            except (AttributeError, TypeError) as exc:
                log.warning(
                    "_add_node: failed to check menu table for node %s, adding anyway: %s",
                    node.get("id"),
                    exc,
                )
                try:
                    jm.add_node(node)
                except (AttributeError, TypeError) as exc2:
                    log.warning(
                        "_add_node: fallback add_node also failed for %s: %s",
                        node.get("id"),
                        exc2,
                    )

    def _add_item(
        self,
        item: Dict[str, Any],
        is_current_server: bool,
        add_to_home: bool = False,
    ) -> None:
        """
        Add an item to the home menu.

        Only the current server may replace existing items.
        """
        item_id = item.get("id")
        if not item_id:
            return

        jm = _get_jive_main()
        if jm is None:
            return

        if is_current_server or item_id not in self._player_menus:
            self._player_menus[item_id] = item
            try:
                jm.add_item(item)
            except (AttributeError, TypeError) as exc:
                log.warning("_add_item: failed to add item %s: %s", item_id, exc)

            if add_to_home:
                # Create a copy for the home node
                custom_home_item = dict(item)
                custom_home_item["id"] = f"hm_{item_id}"
                custom_home_item["node"] = "home"
                try:
                    jm.add_item(custom_home_item)
                except (AttributeError, TypeError) as exc:
                    log.warning(
                        "_add_item: failed to add home copy hm_%s: %s", item_id, exc
                    )
        else:
            log.debug("item already present: %s", item_id)

    def _remove_item_from_home(self, item: Dict[str, Any]) -> None:
        """Remove an item from the home menu."""
        jm = _get_jive_main()
        if jm is None:
            return
        try:
            jm.remove_item(item)
        except (AttributeError, TypeError) as exc:
            # Fallback: try by ID
            item_id = item.get("id", "")
            log.debug(
                "_remove_item_from_home: remove_item failed for %s, trying by id: %s",
                item_id,
                exc,
            )
            if item_id:
                try:
                    jm.remove_item_by_id(item_id)
                except (AttributeError, TypeError) as exc2:
                    log.warning(
                        "_remove_item_from_home: failed to remove item %s: %s",
                        item_id,
                        exc2,
                    )

    def _register_remote_screensaver(self, server_data: Dict[str, Any]) -> None:
        """Register a remote screensaver if not already registered."""
        ss_id = server_data.get("id")
        if not ss_id:
            return

        existing = self._player_screensaver_registrations.get(ss_id)

        # Re-register if from a different server
        if existing and existing.get("server") is not server_data.get("server"):
            log.debug("ss already registered from different server: %s", ss_id)
            mgr = _get_applet_manager()
            if mgr is not None:
                try:
                    mgr.call_service("unregisterRemoteScreensaver", ss_id)
                except Exception as exc:
                    log.error(
                        "_register_remote_screensaver: failed to unregister existing screensaver %s: %s",
                        ss_id,
                        exc,
                        exc_info=True,
                    )
            self._player_screensaver_registrations.pop(ss_id, None)
            existing = None

        if not existing:
            self._player_screensaver_registrations[ss_id] = server_data
            mgr = _get_applet_manager()
            if mgr is not None:
                try:
                    mgr.call_service("registerRemoteScreensaver", server_data)
                except Exception as exc:
                    log.error(
                        "_register_remote_screensaver: failed to register screensaver %s: %s",
                        ss_id,
                        exc,
                        exc_info=True,
                    )
        else:
            log.debug("ss already registered: %s", ss_id)

    def _add_my_apps_node(self) -> None:
        """Add the "My Apps" node to the home menu."""
        jm = _get_jive_main()
        if jm is None:
            return

        my_apps: Dict[str, Any] = {
            "id": "myApps",
            "iconStyle": "hm_myApps",
            "node": "home",
            "text": self._get_string("MENUS_MY_APPS", "My Apps"),
            "weight": 30,
        }
        try:
            jm.add_node(my_apps)
        except (AttributeError, TypeError) as exc:
            log.warning("_add_my_apps_node: failed to add myApps node: %s", exc)

        self._player_menus["myApps"] = my_apps

        # Remove old-style My Apps item
        try:
            jm.remove_item_by_id("opmlmyapps")
        except (AttributeError, TypeError) as exc:
            log.warning(
                "_add_my_apps_node: failed to remove old opmlmyapps item: %s", exc
            )

        self.my_apps_node = True

    def _add_server_home_menu_items(
        self, server: Any, menu_items: List[Dict[str, Any]]
    ) -> None:
        """Cache server menu items for server-capability lookups."""
        if server not in self.server_home_menu_items:
            self.server_home_menu_items[server] = {}

        for v in menu_items:
            if not isinstance(v, dict):
                continue
            item_id = v.get("id")
            if item_id:
                log.debug("adding cached item: %s for server: %s", item_id, server)
                self.server_home_menu_items[server][item_id] = v
            else:
                log.info("No id for: %s", v.get("text"))

    def _update_my_music_title(self, server_name: Optional[str]) -> None:
        """Update the "My Music" node title with the server name."""
        jm = _get_jive_main()
        if jm is None:
            return

        try:
            menu_table = jm.get_menu_table()
            if not isinstance(menu_table, dict):
                return

            my_music_node = menu_table.get("_myMusic")
            if my_music_node is None or not isinstance(my_music_node, dict):
                return

            if "originalNodeText" not in my_music_node:
                my_music_node["originalNodeText"] = my_music_node.get("text", "")

            if not server_name or server_name == "mysqueezebox.com":
                my_music_node["text"] = my_music_node.get(
                    "originalNodeText", "My Music"
                )
            else:
                my_music_node["text"] = server_name
        except (AttributeError, TypeError) as exc:
            log.warning(
                "_update_my_music_title: failed to update My Music title: %s", exc
            )

    # ------------------------------------------------------------------
    # Server menu fetching
    # ------------------------------------------------------------------

    def _fetch_server_menu(self, server: Any) -> None:
        """
        Fetch the menu from a (non-current) server.

        Sends a ``menu 0 100 direct:1`` request to the server.
        """
        log.debug("Fetching menu for server: %s", server)

        # Check SN registration
        is_sn = self._server_is_squeeze_network(server)
        if is_sn:
            is_connected = self._server_is_connected(server)
            is_registered = False
            try:
                is_registered = (
                    server.is_sp_registered_with_sn()
                    if hasattr(server, "is_sp_registered_with_sn")
                    else server.isSpRegisteredWithSn()
                    if hasattr(server, "isSpRegisteredWithSn")
                    else True
                )
            except (AttributeError, TypeError) as exc:
                log.error(
                    "_fetch_server_menu: failed to check SN registration: %s",
                    exc,
                    exc_info=True,
                )
                is_registered = True

            if not is_connected or not is_registered:
                log.info(
                    "not registered or not connected with SN: connected=%s",
                    is_connected,
                )
                return

        # Determine player ID
        player_id = None
        if self._player and self._player is not False:
            player_id = self._get_player_id(self._player)
        else:
            mgr = _get_applet_manager()
            if mgr is not None:
                current = mgr.call_service("getCurrentPlayer")
                if current is not None:
                    player_id = self._get_player_id(current)
                else:
                    # Fallback to local player
                    try:
                        from jive.slim.player import Player

                        local = Player.get_local_player()
                        if local is not None:
                            player_id = self._get_player_id(local)
                    except (ImportError, AttributeError) as exc:
                        log.error(
                            "_fetch_server_menu: failed to get local player: %s",
                            exc,
                            exc_info=True,
                        )

        if player_id:
            self._request_initial_menus(server, player_id, False)

    def _request_initial_menus(
        self, server: Any, player_id: str, is_connected_server: bool
    ) -> None:
        """
        Send a ``menu 0 100 direct:1`` request to *server*.

        The response is processed through a sink that massages items
        and merges them into the home menu.
        """

        def _sink_set_server_menu_chunk(chunk: Dict[str, Any], err: Any = None) -> None:
            data = chunk.get("data", {})
            if isinstance(data, dict):
                menu_items = data.get("item_loop", [])
            elif isinstance(data, list):
                menu_items = data
            else:
                menu_items = []

            for item in menu_items:
                if isinstance(item, dict):
                    _massage_item(item)

            self._merge_server_menu_to_home(server, menu_items, is_connected_server)

        try:
            if hasattr(server, "user_request"):
                server.user_request(
                    _sink_set_server_menu_chunk,
                    player_id,
                    ["menu", 0, 100, "direct:1"],
                )
            elif hasattr(server, "userRequest"):
                server.userRequest(
                    _sink_set_server_menu_chunk,
                    player_id,
                    ["menu", 0, 100, "direct:1"],
                )
            else:
                log.debug("server has no user_request method")
        except Exception as exc:
            log.debug("_request_initial_menus failed: %s", exc)

    def _merge_server_menu_to_home(
        self,
        server: Any,
        menu_items: List[Dict[str, Any]],
        is_connected_server: bool,
    ) -> None:
        """
        Merge server menu items into the home menu.

        Creates a wrapper chunk and passes it through ``_menu_sink``.
        """
        log.debug("MERGE menus: %s", server)

        chunk: Dict[str, Any] = {
            "data": {"item_loop": menu_items},
        }

        sink = self._menu_sink(is_connected_server, server)
        try:
            sink(chunk)
        except Exception as exc:
            log.error("_merge_server_menu_to_home error: %s", exc)

    # ------------------------------------------------------------------
    # Server capability checks
    # ------------------------------------------------------------------

    def _can_squeeze_center_serve(self, item: Dict[str, Any]) -> bool:
        """Check whether a SqueezeCenter can serve the given item."""
        if not self._server:
            return False

        is_sn = self._server_is_squeeze_network(self._server)
        if is_sn:
            # Get last SC
            if self._player and self._player is not False:
                try:
                    sc = (
                        self._player.get_last_squeeze_center()
                        if hasattr(self._player, "get_last_squeeze_center")
                        else self._player.getLastSqueezeCenter()
                        if hasattr(self._player, "getLastSqueezeCenter")
                        else None
                    )
                except (AttributeError, TypeError) as exc:
                    log.error(
                        "_can_squeeze_center_serve: failed to get last SqueezeCenter: %s",
                        exc,
                        exc_info=True,
                    )
                    sc = None
            else:
                sc = None
        else:
            sc = self._server

        return self._can_server_serve(sc, item)

    def _can_squeeze_network_serve(self, item: Dict[str, Any]) -> bool:
        """Check whether SqueezeNetwork can serve the given item."""
        sn = self._get_squeeze_network()
        return self._can_server_serve(sn, item)

    def _can_server_serve(self, server: Any, item: Dict[str, Any]) -> bool:
        """Check whether a server has the given menu item cached."""
        if server is None:
            return False

        menu_items = self.server_home_menu_items.get(server)
        if not menu_items:
            log.error(
                "server can not serve, menus not here yet. item: %s server: %s",
                item.get("id"),
                server,
            )
            return False

        item_id = item.get("id")
        if item_id and item_id in menu_items:
            log.debug("Server can serve item: %s server: %s", item_id, server)
            return True

        log.debug("Server can not serve item: %s server: %s", item_id, server)
        return False

    def _get_squeeze_network(self) -> Any:
        """Return the SqueezeNetwork server from the cached servers, if any."""
        for server in self.server_home_menu_items:
            if self._server_is_squeeze_network(server):
                return server
        return None

    def _any_known_squeeze_centers(self) -> bool:
        """Check whether any non-SN servers are known."""
        mgr = _get_applet_manager()
        if mgr is None:
            return False

        # Check poll list for non-broadcast addresses
        try:
            poll = mgr.call_service("getPollList")
            if poll:
                for address in poll:
                    if address and address != "255.255.255.255":
                        return True
        except Exception as exc:
            log.error(
                "_any_known_squeeze_centers: failed to check poll list: %s",
                exc,
                exc_info=True,
            )

        # Check discovered servers
        try:
            for _id, server in mgr.call_service("iterateSqueezeCenters") or ():
                if not self._server_is_squeeze_network(server):
                    return True
        except Exception as exc:
            log.error(
                "_any_known_squeeze_centers: failed to iterate SqueezeCenters: %s",
                exc,
                exc_info=True,
            )

        return False

    # ------------------------------------------------------------------
    # Popup helpers (stubs for headless mode)
    # ------------------------------------------------------------------

    def _hide_player_updating(self) -> None:
        """Hide the player-updating popup (if shown)."""
        if self._updating_player_popup and self._updating_player_popup is not False:
            try:
                self._updating_player_popup.hide()
            except (AttributeError, TypeError) as exc:
                log.warning(
                    "_hide_player_updating: failed to hide player popup: %s", exc
                )
            self._updating_player_popup = False

        if self._updating_prompt_popup and self._updating_prompt_popup is not False:
            try:
                self._updating_prompt_popup.hide()
            except (AttributeError, TypeError) as exc:
                log.warning(
                    "_hide_player_updating: failed to hide prompt popup: %s", exc
                )
            self._updating_prompt_popup = False

    # ------------------------------------------------------------------
    # Player / server attribute helpers (duck-typing)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_player_id(player: Any) -> Optional[str]:
        """Extract the player ID via duck-typing."""
        if player is None or player is False:
            return None
        for attr in ("get_id", "getId"):
            fn = getattr(player, attr, None)
            if fn is not None:
                try:
                    return fn()  # type: ignore[no-any-return]
                except (AttributeError, TypeError) as exc:
                    log.debug("_get_player_id: %s() failed: %s", attr, exc)
        return getattr(player, "id", None)

    @staticmethod
    def _get_player_name(player: Any) -> Optional[str]:
        """Extract the player name via duck-typing."""
        if player is None or player is False:
            return None
        for attr in ("get_name", "getName"):
            fn = getattr(player, attr, None)
            if fn is not None:
                try:
                    return fn()  # type: ignore[no-any-return]
                except (AttributeError, TypeError) as exc:
                    log.debug("_get_player_name: %s() failed: %s", attr, exc)
        return getattr(player, "name", None)

    @staticmethod
    def _get_player_server(player: Any) -> Any:
        """Extract the player's server via duck-typing."""
        if player is None or player is False:
            return None
        for attr in ("get_slim_server", "getSlimServer"):
            fn = getattr(player, attr, None)
            if fn is not None:
                try:
                    return fn()
                except (AttributeError, TypeError) as exc:
                    log.debug("_get_player_server: %s() failed: %s", attr, exc)
        return None

    @staticmethod
    def _get_server_name(server: Any) -> Optional[str]:
        """Extract the server name via duck-typing."""
        if server is None or server is False:
            return None
        for attr in ("get_name", "getName"):
            fn = getattr(server, attr, None)
            if fn is not None:
                try:
                    return fn()  # type: ignore[no-any-return]
                except (AttributeError, TypeError) as exc:
                    log.debug("_get_server_name: %s() failed: %s", attr, exc)
        return getattr(server, "name", None)

    @staticmethod
    def _server_is_squeeze_network(server: Any) -> bool:
        """Check if a server is SqueezeNetwork."""
        if server is None or server is False:
            return False
        for attr in ("is_squeeze_network", "isSqueezeNetwork"):
            fn = getattr(server, attr, None)
            if fn is not None:
                try:
                    return fn()  # type: ignore[no-any-return]
                except (AttributeError, TypeError) as exc:
                    log.debug("_server_is_squeeze_network: %s() failed: %s", attr, exc)
        return False

    @staticmethod
    def _server_is_connected(server: Any) -> bool:
        """Check if a server is connected."""
        if server is None or server is False:
            return False
        for attr in ("is_connected", "isConnected"):
            fn = getattr(server, attr, None)
            if fn is not None:
                try:
                    return fn()  # type: ignore[no-any-return]
                except (AttributeError, TypeError) as exc:
                    log.debug("_server_is_connected: %s() failed: %s", attr, exc)
        return False

    @staticmethod
    def _server_is_compatible(server: Any) -> bool:
        """Check if a server is compatible."""
        if server is None or server is False:
            return False
        for attr in ("is_compatible", "isCompatible"):
            fn = getattr(server, attr, None)
            if fn is not None:
                try:
                    return fn()  # type: ignore[no-any-return]
                except (AttributeError, TypeError) as exc:
                    log.debug("_server_is_compatible: %s() failed: %s", attr, exc)
        # If no compatibility check is available, assume compatible
        return True

    # ------------------------------------------------------------------
    # String helpers
    # ------------------------------------------------------------------

    def _get_string(self, token: str, fallback: str = "") -> str:
        """Resolve a localisation token, falling back to *fallback*."""
        strings_table = getattr(self, "_strings_table", None)
        if strings_table is not None:
            try:
                resolved = strings_table.str(token)
                if resolved:
                    return resolved  # type: ignore[no-any-return]
            except (AttributeError, TypeError) as exc:
                log.debug(
                    "_get_string: failed to resolve token %r from strings_table: %s",
                    token,
                    exc,
                )

        # Try the entry's strings table
        if self._entry is not None:
            st = self._entry.get("strings_table")
            if st is not None:
                try:
                    resolved = st.str(token)
                    if resolved:
                        return resolved  # type: ignore[no-any-return]
                except (AttributeError, TypeError) as exc:
                    log.debug(
                        "_get_string: failed to resolve token %r from entry strings: %s",
                        token,
                        exc,
                    )

        return fallback

    # Lua compatibility alias
    string = _get_string

    # ------------------------------------------------------------------
    # Settings helpers (match Applet base class pattern)
    # ------------------------------------------------------------------

    def get_settings(self) -> Dict[str, Any]:
        """Return the applet's settings dict."""
        mgr = _get_applet_manager()
        if mgr is not None:
            try:
                db = mgr.get_applet_db()
                entry = db.get("SlimMenus", {})
                settings = entry.get("settings")
                if settings is not None:
                    return settings  # type: ignore[no-any-return]
            except Exception as exc:
                log.error(
                    "get_settings: failed to retrieve applet settings: %s",
                    exc,
                    exc_info=True,
                )

        if self._settings is None:
            self._settings = {}
        return self._settings

    # Lua alias
    getSettings = get_settings

    def store_settings(self) -> None:
        """Persist settings via the AppletManager."""
        mgr = _get_applet_manager()
        if mgr is not None:
            try:
                mgr._store_settings("SlimMenus")
            except Exception as exc:
                log.error(
                    "store_settings: failed to persist SlimMenus settings: %s",
                    exc,
                    exc_info=True,
                )

    # Lua alias
    storeSettings = store_settings

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        player_name = self._get_player_name(self._player) if self._player else None
        server_name = self._get_server_name(self._server) if self._server else None
        menu_count = len(self._player_menus)
        return (
            f"SlimMenusApplet(player={player_name!r}, "
            f"server={server_name!r}, menus={menu_count})"
        )
