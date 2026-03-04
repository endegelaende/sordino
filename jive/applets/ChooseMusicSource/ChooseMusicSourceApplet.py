"""
applets.ChooseMusicSource.ChooseMusicSourceApplet — Server selection & connection.

Ported from ``applets/ChooseMusicSource/ChooseMusicSourceApplet.lua`` in the
original jivelite Lua project.

ChooseMusicSource allows users to select which Lyrion Music Server
(formerly SqueezeCenter / Logitech Media Server) a player should
connect to.  It provides:

- A menu listing discovered and manually-configured servers.
- Services for connecting a player to a chosen server.
- Management of a poll list (IP addresses to probe for servers).
- UI for adding/removing remote server addresses.
- Connection timeout and retry logic.
- Server version compatibility checks.

States / flow
-------------
1. ``selectMusicSource()`` is called (either as a service or from
   another applet like SlimMenus).
2. The applet subscribes to jnt notifications and builds a list of
   discovered servers via ``iterateSqueezeCenters`` and the poll list.
3. When the user selects a server, ``selectServer()`` checks
   compatibility, password protection, and initiates the connection.
4. A "connecting" popup is shown while waiting for the player to
   connect to the new server.
5. On success the ``playerConnectedCallback`` is invoked; on failure
   a retry/choose-other dialog is shown.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
)

from jive.applet import Applet
from jive.utils.log import logger

__all__ = ["ChooseMusicSourceApplet"]

log = logger("applet.ChooseMusicSource")


# Connection timeout in seconds (matches Lua CONNECT_TIMEOUT = 20)
CONNECT_TIMEOUT = 20


# ── Module-level helpers ─────────────────────────────────────────────────


def _get_applet_manager() -> Any:
    """Return the global AppletManager, or ``None``."""
    try:
        from jive.jive_main import jive_main as _jm

        if _jm is not None:
            return getattr(_jm, "applet_manager", None)
    except ImportError as exc:
        log.debug("jive_main not importable in _get_applet_manager: %s", exc)
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
    except ImportError as exc:
        log.debug("jive_main not importable in _get_jnt: %s", exc)
    return None


def _get_iconbar() -> Any:
    """Return the Iconbar singleton, or ``None``."""
    try:
        from jive.jive_main import iconbar_instance

        return iconbar_instance
    except ImportError:
        return None


# ══════════════════════════════════════════════════════════════════════════
# ChooseMusicSourceApplet
# ══════════════════════════════════════════════════════════════════════════


class ChooseMusicSourceApplet(Applet):
    """
    Server selection and connection applet.

    This is a demand-loaded applet — it is loaded when its services are
    first called (e.g. from SlimMenus or SetupWelcome) and freed when
    the server selection flow completes.
    """

    def __init__(self) -> None:
        super().__init__()

        # ── Server menu state ────────────────────────────────────────
        # The SimpleMenu widget showing discovered servers.
        self.server_menu: Any = None

        # Mapping of server-id/address → menu item dict.
        self.server_list: Dict[str, Dict[str, Any]] = {}

        # Optional filter: only show these servers.
        self.included_servers: Optional[List[Any]] = None

        # Whether to filter out incompatible servers.
        self.offer_compatible_sources_only: bool = False

        # Whether to offer SqueezeNetwork.
        self.offer_sn: bool = False

        # ── Connection state ─────────────────────────────────────────
        # Callback invoked when a player has successfully connected.
        self.player_connected_callback: Optional[Callable[..., None]] = None

        # Title style override for windows.
        self.title_style: Optional[str] = None

        # The connecting popup window (if visible).
        self.connecting_popup: Any = None

        # What we're waiting for: {"player": ..., "server": ...}
        self.wait_for_connect: Optional[Dict[str, Any]] = None

        # Whether to ignore serverConnected notifications (after cancel).
        self.ignore_server_connected: bool = False

        # Whether to show a confirmation dialog on server change.
        self.confirm_on_change: bool = False

        # Remote servers management window.
        self._remote_servers_window: Any = None
        self._remote_servers_menu: Any = None

    # ------------------------------------------------------------------
    # Applet lifecycle
    # ------------------------------------------------------------------

    def init(self, **kwargs: Any) -> "ChooseMusicSourceApplet":  # type: ignore[override]
        """Initialise the applet."""
        return self

    def free(self) -> bool:
        """Free the applet — unsubscribe from jnt.

        Returns ``True`` to allow freeing.
        """
        if self.player_connected_callback:
            log.warn(
                "Unexpected free when playerConnectedCallback still exists "
                "(could happen on regular back)"
            )
        log.debug("Unsubscribing jnt")
        jnt = _get_jnt()
        if jnt is not None:
            try:
                jnt.unsubscribe(self)
            except Exception as exc:
                log.error("free: failed to unsubscribe from jnt: %s", exc, exc_info=True)
        return True

    # ------------------------------------------------------------------
    # Service: selectMusicSource / selectCompatibleMusicSource
    # ------------------------------------------------------------------

    def settingsShow(self) -> None:
        """Entry point from settings menu — delegates to ``selectMusicSource``.

        Mirrors the Lua ``settingsShow`` function.
        """
        log.debug("settingsShow called")
        self.selectMusicSource()

    # snake_case alias
    settings_show = settingsShow

    def selectCompatibleMusicSource(self, *args: Any, **kwargs: Any) -> None:
        """Service: show only compatible music sources."""
        self.offer_compatible_sources_only = True
        self.selectMusicSource(*args, **kwargs)

    # snake_case alias
    select_compatible_music_source = selectCompatibleMusicSource

    def selectMusicSource(
        self,
        player_connected_callback: Optional[Callable[..., None]] = None,
        title_style: Optional[str] = None,
        included_servers: Optional[List[Any]] = None,
        specific_server: Any = None,
        server_for_retry: Any = None,
        ignore_server_connected: bool = False,
        confirm_on_change: bool = False,
        offer_sn: bool = False,
    ) -> None:
        """
        Service: select a music source (server) for the current player.

        Parameters
        ----------
        player_connected_callback:
            Called when the player successfully connects to a server.
            If ``None``, defaults to ``goHome()``.
        title_style:
            Optional style override for the selection window title.
        included_servers:
            If set, only these servers are shown in the list.
        specific_server:
            If set, skip the list and connect directly to this server.
        server_for_retry:
            Server to offer as a "retry" option on failure.
        ignore_server_connected:
            If ``True``, don't auto-dismiss on serverConnected.
        confirm_on_change:
            If ``True``, ask for confirmation before switching.
        offer_sn:
            If ``True``, include SqueezeNetwork in the list.
        """
        if included_servers:
            self.included_servers = included_servers

        if player_connected_callback:
            self.player_connected_callback = player_connected_callback
        else:
            self.player_connected_callback = lambda *a: self._default_callback()

        if title_style:
            self.title_style = title_style

        jnt = _get_jnt()
        if jnt is not None:
            try:
                jnt.subscribe(self)
            except Exception as exc:
                log.error("selectMusicSource: failed to subscribe to jnt: %s", exc, exc_info=True)

        self.server_list = {}
        self.ignore_server_connected = ignore_server_connected
        self.confirm_on_change = confirm_on_change
        self.offer_sn = False  # SN support disabled (matches Lua: offerSn)

        if specific_server:
            log.debug("selecting specific server %s", specific_server)
            self.selectServer(specific_server, server_for_retry=server_for_retry)
            return

        offer_list_if_only_one = specific_server is False

        self._show_music_source_list(offer_list_if_only_one)

    # snake_case alias
    select_music_source = selectMusicSource

    def _default_callback(self) -> None:
        """Default callback: navigate home."""
        mgr = _get_applet_manager()
        if mgr is not None:
            try:
                mgr.call_service("goHome")
            except Exception as exc:
                log.error("_default_callback: failed to call goHome service: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Server list UI
    # ------------------------------------------------------------------

    def _show_music_source_list(self, offer_list_if_only_one: bool = False) -> None:
        """
        Build and show the server selection menu.

        Mirrors the Lua ``_showMusicSourceList`` function.
        """
        mgr = _get_applet_manager()

        self.server_menu = None
        self.server_list = {}

        # Subscribe to jnt for server add/remove notifications
        jnt = _get_jnt()
        if jnt is not None:
            try:
                jnt.subscribe(self)
            except Exception as exc:
                log.error("_show_music_source_list: failed to subscribe to jnt: %s", exc, exc_info=True)

        # ── Trigger server discovery ─────────────────────────────────
        if mgr is not None:
            try:
                mgr.call_service("discoverServers")
            except Exception as exc:
                log.error("_show_music_source_list: failed to call discoverServers: %s", exc, exc_info=True)

        # ── Polled servers (from settings) ───────────────────────────
        poll: Dict[str, str] = {}
        if mgr is not None:
            try:
                poll = mgr.call_service("getPollList") or {}
            except Exception as exc:
                log.error("_show_music_source_list: failed to get poll list: %s", exc, exc_info=True)

        log.debug("Polled Servers:")
        for address in poll:
            log.debug("\t%s", address)
            if address != "255.255.255.255":
                self._add_server_item(None, address)

        # ── Discovered servers ───────────────────────────────────────
        log.debug("Discovered Servers:")
        if mgr is not None:
            try:
                for address, server in mgr.call_service("iterateSqueezeCenters"):
                    log.debug("\t%s", server)
                    self._add_server_item(server, address)
            except Exception as exc:
                log.error("_show_music_source_list: failed to iterate squeeze centers: %s", exc, exc_info=True)

        # ── Auto-select if only one server ───────────────────────────
        if not offer_list_if_only_one:
            single_server = None
            for _id, item in self.server_list.items():
                if single_server is not None:
                    # More than one found
                    single_server = None
                    break
                single_server = item.get("server")

            if single_server is not None:
                log.info(
                    "Only one server found, select it directly: %s",
                    single_server,
                )
                self.selectServer(single_server)
                return

        # ── Build the window ─────────────────────────────────────────
        # In headless mode we just log and keep the server list for
        # programmatic access.  In full UI mode this would create a
        # Window + SimpleMenu.
        log.info(
            "Showing music source list (%d servers)",
            len(self.server_list),
        )

        try:
            from jive.ui.constants import EVENT_CONSUME, EVENT_WINDOW_POP
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.window import Window

            window = Window(
                "text_list",
                self._get_string("SLIMSERVER_SERVERS", "Libraries"),
                self.title_style,
            )
            menu = SimpleMenu("menu")
            menu.set_comparator(SimpleMenu.itemComparatorWeightAlpha)
            window.add_widget(menu)
            window.set_allow_screensaver(False)

            # Back action: cancel selection and hide the window
            def _back_action(*_args: Any) -> int:
                window.play_sound("WINDOWHIDE")
                self._cancel_select_server()
                window.hide()
                return int(EVENT_CONSUME)

            menu.add_action_listener("back", self, _back_action)

            self.server_menu = menu

            # Populate with current server list
            for _id, item in self.server_list.items():
                menu.add_item(item)

            # Periodic server discovery timer
            def _discover_timer() -> None:
                _mgr = _get_applet_manager()
                if _mgr is not None:
                    try:
                        _mgr.call_service("discoverServers")
                    except Exception as exc:
                        log.debug("_discover_timer: discoverServers failed: %s", exc)

            window.add_timer(1000, _discover_timer)

            # Store settings when window is closed
            def _on_pop(*_args: Any) -> int:
                self.store_settings()
                return int(EVENT_CONSUME)

            window.add_listener(int(EVENT_WINDOW_POP), _on_pop)

            # Flag the window so hideConnectingToServer can clean it up
            window._isChooseMusicSourceWindow = True  # type: ignore[attr-defined]

            # Show
            self.tie_and_show_window(window)

        except ImportError:
            # Headless mode — no UI framework available
            self.server_menu = _HeadlessMenu()
            for _id, item in self.server_list.items():
                self.server_menu.add_item(item)
            log.debug("Headless mode: server menu has %d items", len(self.server_list))

    # Lua alias
    _showMusicSourceList = _show_music_source_list

    # ------------------------------------------------------------------
    # Server item management
    # ------------------------------------------------------------------

    def _add_server_item(
        self, server: Any = None, address: Optional[str] = None
    ) -> None:
        """
        Add a server entry to the server list / menu.

        Mirrors the Lua ``_addServerItem`` function.
        """
        if not self.server_menu and not self.server_list:
            # We might be called before the menu is created; just
            # accumulate into server_list.
            pass

        # Filter: included_servers
        if self.included_servers and server is not None:
            if server not in self.included_servers:
                log.debug("server not in included list: %s", server)
                return

        # Filter: SqueezeNetwork
        if (
            server is not None
            and not self.offer_sn
            and hasattr(server, "is_squeeze_network")
        ):
            try:
                if server.is_squeeze_network():
                    log.debug("Exclude SN")
                    return
            except Exception as exc:
                log.warning("_add_server_item: failed to check is_squeeze_network: %s", exc)

        # Filter: compatible sources only
        if self.offer_compatible_sources_only and server is not None:
            try:
                if hasattr(server, "is_compatible") and not server.is_compatible():
                    log.info("Exclude non-compatible source: %s", server)
                    return
            except Exception as exc:
                log.warning("_add_server_item: failed to check is_compatible for %s: %s", server, exc)

        # Determine ID
        item_id: str
        if server is not None:
            try:
                item_id = server.get_ip_port()
            except (AttributeError, TypeError):
                try:
                    item_id = server.getIpPort()
                except (AttributeError, TypeError):
                    item_id = str(server)
        else:
            item_id = address or ""
            server = self._create_remote_server(address or "")

        log.debug("\tid for this server set to: %s", item_id)

        # Get current player for "checked" style
        mgr = _get_applet_manager()
        current_player = None
        if mgr is not None:
            try:
                current_player = mgr.call_service("getCurrentPlayer")
            except Exception as exc:
                log.error("_add_server_item: failed to get current player: %s", exc, exc_info=True)

        # Remove existing entry
        if item_id in self.server_list:
            if self.server_menu is not None:
                try:
                    self.server_menu.remove_item(self.server_list[item_id])
                except Exception as exc:
                    log.warning("_add_server_item: failed to remove existing menu item %s: %s", item_id, exc)

        if server is not None:
            # Also remove by server's ip:port if different
            try:
                server_ip_port = (
                    server.get_ip_port()
                    if hasattr(server, "get_ip_port")
                    else server.getIpPort()
                    if hasattr(server, "getIpPort")
                    else None
                )
                if server_ip_port and server_ip_port in self.server_list:
                    if self.server_menu is not None:
                        try:
                            self.server_menu.remove_item(
                                self.server_list[server_ip_port]
                            )
                        except Exception as exc:
                            log.warning("_add_server_item: failed to remove duplicate menu item by ip:port %s: %s", server_ip_port, exc)
            except (AttributeError, TypeError) as exc:
                log.warning("_add_server_item: failed to get server ip:port for dedup: %s", exc)

            # Build menu item
            server_name = self._get_server_name(server)
            item: Dict[str, Any] = {
                "server": server,
                "text": server_name,
                "sound": "WINDOWSHOW",
                "callback": lambda *a, s=server: self.selectServer(s),
                "weight": 1,
            }

            if self.server_menu is not None:
                try:
                    self.server_menu.add_item(item)
                except Exception as exc:
                    log.warning("_add_server_item: failed to add item to server menu: %s", exc)

            self.server_list[item_id] = item

            # Mark current server as checked
            if current_player is not None:
                try:
                    player_server = (
                        current_player.get_slim_server()
                        if hasattr(current_player, "get_slim_server")
                        else current_player.getSlimServer()
                        if hasattr(current_player, "getSlimServer")
                        else None
                    )
                    if player_server is server:
                        item["style"] = "item_checked"
                except Exception as exc:
                    log.warning("_add_server_item: failed to check current player server for %s: %s", item_id, exc)

    # Lua alias
    _addServerItem = _add_server_item

    def _del_server_item(
        self, server: Any = None, address: Optional[str] = None
    ) -> None:
        """Remove a server entry from the list/menu."""
        item_id = server or address
        if item_id is None:
            return

        sid = str(item_id)

        # Try server IP port as key
        if server is not None:
            try:
                sid = (
                    server.get_ip_port()
                    if hasattr(server, "get_ip_port")
                    else server.getIpPort()
                    if hasattr(server, "getIpPort")
                    else str(server)
                )
            except (AttributeError, TypeError) as exc:
                log.warning("_del_server_item: failed to get server ip:port: %s", exc)

        if sid in self.server_list:
            if self.server_menu is not None:
                try:
                    self.server_menu.remove_item(self.server_list[sid])
                except Exception as exc:
                    log.warning("_del_server_item: failed to remove item %s from menu: %s", sid, exc)
            del self.server_list[sid]

        # Re-add if server is on poll list
        if server is not None:
            mgr = _get_applet_manager()
            if mgr is not None:
                try:
                    poll = mgr.call_service("getPollList") or {}
                    server_address = (
                        server.get_ip_port()
                        if hasattr(server, "get_ip_port")
                        else str(server)
                    )
                    if server_address in poll:
                        self._add_server_item(None, server_address)
                except Exception as exc:
                    log.error("_del_server_item: failed to re-add server from poll list: %s", exc, exc_info=True)

    # Lua alias
    _delServerItem = _del_server_item

    def _create_remote_server(self, address: str) -> Any:
        """
        Create (or find) a SlimServer instance for a given address.

        Mirrors the Lua ``_createRemoteServer`` function.
        """
        try:
            from jive.slim.slim_server import SlimServer

            # Look for existing server with same address
            existing = SlimServer.get_server_by_address(address)
            if existing is not None:
                log.info("Using existing server with same ip address: %s", existing)
                return existing

            # Create new server
            jnt = _get_jnt()
            server = SlimServer(jnt, address, address)
            try:
                server.update_init({"ip": address}, 9000)  # type: ignore[call-arg]
            except (AttributeError, TypeError):
                try:
                    server.updateInit({"ip": address}, 9000)  # type: ignore[attr-defined]
                except (AttributeError, TypeError) as exc:
                    log.debug("_create_remote_server: server lacks updateInit for %s: %s", address, exc)
            return server
        except ImportError:
            log.debug("SlimServer not importable, returning stub")
            return _StubServer(address)

    # Lua alias
    _createRemoteServer = _create_remote_server

    # ------------------------------------------------------------------
    # Server selection
    # ------------------------------------------------------------------

    def selectServer(
        self,
        server: Any,
        password_entered: bool = False,
        server_for_retry: Any = None,
    ) -> None:
        """
        Handle server selection.

        Checks password protection and version compatibility before
        initiating the connection.

        Mirrors the Lua ``selectServer`` function.
        """
        # Check password
        if not password_entered:
            try:
                _pw_result = None
                if hasattr(server, "is_password_protected"):
                    _pw_result = server.is_password_protected()
                elif hasattr(server, "isPasswordProtected"):
                    _pw_result = server.isPasswordProtected()
                _is_pw = _pw_result[0] if isinstance(_pw_result, tuple) else bool(_pw_result)
                if _is_pw:
                    mgr = _get_applet_manager()
                    if mgr is not None:
                        try:
                            mgr.call_service(
                                "squeezeCenterPassword",
                                server,
                                lambda: self.selectServer(server, True),
                                self.title_style,
                            )
                            return
                        except Exception as exc:
                            log.error("selectServer: failed to call squeezeCenterPassword service: %s", exc, exc_info=True)
            except Exception as exc:
                log.error("selectServer: failed to check password protection for server: %s", exc, exc_info=True)

        # Check version compatibility
        version = self._get_server_version(server)
        if version is not None:
            compatible = True
            try:
                if hasattr(server, "is_compatible"):
                    compatible = server.is_compatible()
                elif hasattr(server, "isCompatible"):
                    compatible = server.isCompatible()
            except Exception as exc:
                log.warning("selectServer: failed to check server compatibility: %s", exc)

            if not compatible:
                self._server_version_error(server)
                return

        # Get current player
        mgr = _get_applet_manager()
        current_player = None
        if mgr is not None:
            try:
                current_player = mgr.call_service("getCurrentPlayer")
            except Exception as exc:
                log.error("selectServer: failed to get current player: %s", exc, exc_info=True)

        if current_player is None:
            log.warn("Unexpected nil player when waiting for new player or server")
            self._cancel_select_server()
            return

        # Already connected to this server?
        try:
            player_server = (
                current_player.get_slim_server()
                if hasattr(current_player, "get_slim_server")
                else current_player.getSlimServer()
                if hasattr(current_player, "getSlimServer")
                else None
            )
            player_connected = (
                current_player.is_connected()
                if hasattr(current_player, "is_connected")
                else current_player.isConnected()
                if hasattr(current_player, "isConnected")
                else False
            )

            if (
                player_server is server
                and player_connected
                and not self.ignore_server_connected
            ):
                if self.player_connected_callback:
                    callback = self.player_connected_callback
                    self.player_connected_callback = None
                    callback(server)
                return
        except Exception as exc:
            log.warning("selectServer: failed to check if already connected to server: %s", exc)

        # Confirmation dialog if switching while playing
        if self.confirm_on_change and not self._should_skip_confirm(
            current_player, server
        ):
            self._confirm_server_switch(current_player, server, server_for_retry)
        else:
            self.connectPlayerToServer(current_player, server)

    # snake_case alias
    select_server = selectServer

    def _should_skip_confirm(self, player: Any, server: Any) -> bool:
        """Return True if we should skip the switch confirmation."""
        try:
            player_server = (
                player.get_slim_server()
                if hasattr(player, "get_slim_server")
                else player.getSlimServer()
                if hasattr(player, "getSlimServer")
                else None
            )
            if player_server is None or player_server is server:
                return True

            play_mode = (
                player.get_play_mode()
                if hasattr(player, "get_play_mode")
                else player.getPlayMode()
                if hasattr(player, "getPlayMode")
                else None
            )
            if play_mode != "play":
                return True

            playlist_size = (
                player.get_playlist_size()
                if hasattr(player, "get_playlist_size")
                else player.getPlaylistSize()
                if hasattr(player, "getPlaylistSize")
                else 0
            )
            if not playlist_size or playlist_size == 0:
                return True
        except Exception:
            return True

        return False

    # ------------------------------------------------------------------
    # Connection flow
    # ------------------------------------------------------------------

    def connectPlayerToServer(self, player: Any, server: Any) -> None:
        """
        Service: connect a player to a server.

        Shows the connecting popup and initiates the connection.
        Mirrors the Lua ``connectPlayerToServer`` function.
        """
        log.info("connectPlayerToServer() %s %s", player, server)

        self._show_connect_to_server(player, server)

        # Check SN registration (not relevant for local servers)
        try:
            is_sn = (
                server.is_squeeze_network()
                if hasattr(server, "is_squeeze_network")
                else server.isSqueezeNetwork()
                if hasattr(server, "isSqueezeNetwork")
                else False
            )
        except Exception:
            is_sn = False

        if not is_sn:
            self._do_connect_player(player, server)
            return

        # SqueezeNetwork registration (rarely used)
        self._do_connect_player(player, server)

    # snake_case alias
    connect_player_to_server = connectPlayerToServer

    def _do_connect_player(self, player: Any, server: Any) -> None:
        """Tell the player to connect to the server."""
        self.wait_for_connect = {
            "player": player,
            "server": server,
        }

        try:
            if hasattr(player, "connect_to_server"):
                player.connect_to_server(server)
            elif hasattr(player, "connectToServer"):
                player.connectToServer(server)
            else:
                log.warn("Player does not have connectToServer method")
        except Exception as exc:
            log.error("Failed to connect player to server: %s", exc)

    def _show_connect_to_server(self, player: Any, server: Any) -> None:
        """
        Show the "Connecting to …" popup.

        Mirrors the Lua ``_showConnectToServer`` function.
        """
        if self.connecting_popup is not None:
            return

        server_name = self._get_server_name(server)
        log.info("Showing connecting popup for %s", server_name)

        timeout_counter = {"count": 0}

        try:
            from jive.ui.icon import Icon
            from jive.ui.label import Label
            from jive.ui.popup import Popup

            popup = Popup("waiting_popup")
            popup.add_widget(Icon("icon_connecting"))
            popup.set_auto_hide(False)

            status_label = Label(
                "text",
                self._get_string("SLIMSERVER_CONNECTING_TO", "Connecting to…"),
            )
            sub_label = Label("subtext", server_name)
            popup.add_widget(status_label)
            popup.add_widget(sub_label)

            def _on_timeout() -> None:
                mgr = _get_applet_manager()
                if mgr is not None:
                    try:
                        mgr.call_service("discoverServers")
                    except Exception as exc:
                        log.error("_on_timeout: failed to call discoverServers: %s", exc, exc_info=True)

                timeout_counter["count"] += 1
                has_failed = False
                try:
                    has_failed = (
                        player.has_connection_failed()
                        if hasattr(player, "has_connection_failed")
                        else player.hasConnectionFailed()
                        if hasattr(player, "hasConnectionFailed")
                        else False
                    )
                except Exception as exc:
                    log.warning("_on_timeout: failed to check connection failure status: %s", exc)

                if timeout_counter["count"] > CONNECT_TIMEOUT or has_failed:
                    log.warn(
                        "Connection failure or Timeout, count: %d",
                        timeout_counter["count"],
                    )
                    self._connect_player_failed(player, server)
                    if self.connecting_popup is not None:
                        self.connecting_popup.hide()
                        self.connecting_popup = None

            def _cancel_action(*_args: Any) -> None:
                timeout_counter["count"] = 1  # reset for next time
                self._connect_player_failed(player, server)
                if self.connecting_popup is not None:
                    self.connecting_popup.hide()
                    self.connecting_popup = None

            # Disable most input during connection
            popup.ignore_all_input_except([
                "back", "go_home", "go_home_or_now_playing",
                "volume_up", "volume_down", "stop", "pause", "power",
            ])
            popup.add_action_listener("back", self, _cancel_action)
            popup.add_action_listener("go_home", self, _cancel_action)
            popup.add_action_listener("go_home_or_now_playing", self, _cancel_action)

            popup.add_timer(1000, _on_timeout)

            popup._isChooseMusicSourceWindow = True  # type: ignore[attr-defined]

            self.connecting_popup = popup
            self.tie_and_show_window(popup)

        except ImportError:
            # Headless mode — just record state
            self.connecting_popup = _HeadlessPopup(server_name)
            log.debug(
                "Headless mode: connecting popup for %s (timeout %ds)",
                server_name,
                CONNECT_TIMEOUT,
            )

    # ------------------------------------------------------------------
    # Service: hideConnectingToServer
    # ------------------------------------------------------------------

    def hideConnectingToServer(self) -> None:
        """
        Service: hide the "connecting" popup and complete the flow.

        Mirrors the Lua ``hideConnectingToServer`` function.
        """
        log.info("Hiding popup, exists?: %s", self.connecting_popup)

        if self.connecting_popup is not None:
            log.info("connectingToServer popup hide")

            # Perform callback if we've successfully switched
            if self.wait_for_connect is not None:
                wfc_player = self.wait_for_connect.get("player")
                wfc_server = self.wait_for_connect.get("server")
                log.info("waiting for %s on %s", wfc_player, wfc_server)

                player_server = None
                try:
                    player_server = (
                        wfc_player.get_slim_server()  # type: ignore[union-attr]
                        if hasattr(wfc_player, "get_slim_server")
                        else wfc_player.getSlimServer()  # type: ignore[union-attr]
                        if hasattr(wfc_player, "getSlimServer")
                        else None
                    )
                except Exception as exc:
                    log.warning("hideConnectingToServer: failed to get player's server: %s", exc)

                if player_server is wfc_server:
                    # Check upgrade
                    try:
                        if getattr(wfc_server, "upgrade_force", False) or getattr(
                            wfc_server, "upgradeForce", False
                        ):
                            self._cancel_select_server(no_hide=True)
                            return
                    except Exception as exc:
                        log.warning("hideConnectingToServer: failed to check upgrade_force: %s", exc)

                    if self.player_connected_callback:
                        callback = self.player_connected_callback
                        self.player_connected_callback = None
                        callback(wfc_server)
                        self.ignore_server_connected = False
                else:
                    log.warn(
                        "server mismatch for player: %s  Expected: %s got: %s",
                        wfc_player,
                        wfc_server,
                        player_server,
                    )

                self.wait_for_connect = None

            try:
                self.connecting_popup.hide()
            except Exception as exc:
                log.warning("hideConnectingToServer: failed to hide connecting popup: %s", exc)
            self.connecting_popup = None

        # Pop any applet windows that are still on top (so when the current
        # server comes back on-line, ChooseMusicSource exits cleanly).
        # Mirrors the Lua while-loop over Framework.windowStack.
        try:
            from jive.ui.framework import framework as fw

            while (
                fw.window_stack
                and getattr(fw.window_stack[0], "_isChooseMusicSourceWindow", False)
            ):
                log.debug("Hiding ChooseMusicSource window")
                fw.window_stack[0].hide()
        except ImportError:
            log.debug("hideConnectingToServer: UI framework not available for window-stack cleanup")

    # snake_case alias
    hide_connecting_to_server = hideConnectingToServer

    # ------------------------------------------------------------------
    # Service: showConnectToServer
    # ------------------------------------------------------------------

    def showConnectToServer(
        self,
        player_connected_callback: Optional[Callable[..., None]] = None,
        server: Any = None,
    ) -> None:
        """Service: show the connecting popup for a given server."""
        log.debug("showConnectToServer %s", server)

        self.player_connected_callback = player_connected_callback

        mgr = _get_applet_manager()
        player = None
        if mgr is not None:
            try:
                player = mgr.call_service("getCurrentPlayer")
            except Exception as exc:
                log.error("showConnectToServer: failed to get current player: %s", exc, exc_info=True)

        if player is not None and server is not None:
            self._show_connect_to_server(player, server)

    # snake_case alias
    show_connect_to_server = showConnectToServer

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    def _cancel_select_server(self, no_hide: bool = False) -> None:
        """Cancel the server selection process."""
        log.info("Cancelling Server Selection")

        self.ignore_server_connected = True
        self.wait_for_connect = None
        self.player_connected_callback = None
        if not no_hide:
            self.hideConnectingToServer()

    # Lua alias
    _cancelSelectServer = _cancel_select_server

    # ------------------------------------------------------------------
    # Error dialogs
    # ------------------------------------------------------------------

    def _connect_player_failed(self, player: Any, server: Any) -> None:
        """Handle connection failure — show retry/choose-other dialog.

        Mirrors the Lua ``_connectPlayerFailed`` function (line ~727-771).
        Creates a window with an error message, a "Try Again" item and
        a "Choose Other Library" item.
        """
        server_name = self._get_server_name(server)
        log.warn("Connection to %s failed", server_name)

        try:
            from jive.ui.constants import EVENT_CONSUME
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.textarea import Textarea
            from jive.ui.window import Window

            window = Window(
                "error",
                self._get_string("SQUEEZEBOX_PROBLEM", "Problem Connecting"),
            )
            window.set_allow_screensaver(False)

            def _cancel_action(*_args: Any) -> int:
                self._cancel_select_server()
                window.hide()
                return int(EVENT_CONSUME)

            menu = SimpleMenu("menu")
            menu.add_item({
                "text": self._get_string("SQUEEZEBOX_TRY_AGAIN", "Try Again"),
                "sound": "WINDOWSHOW",
                "callback": lambda *a: (
                    self.connectPlayerToServer(player, server),
                    window.hide(),
                ),
            })
            menu.add_item({
                "text": self._get_string("CHOOSE_OTHER_LIBRARY", "Choose Other Library"),
                "sound": "WINDOWSHOW",
                "callback": lambda *a: self._show_music_source_list(),
            })

            menu.add_action_listener("back", self, _cancel_action)
            menu.add_action_listener("go_home", self, _cancel_action)

            # Determine help text token
            is_sn = False
            try:
                if hasattr(server, "is_squeeze_network"):
                    is_sn = server.is_squeeze_network()
                elif hasattr(server, "isSqueezeNetwork"):
                    is_sn = server.isSqueezeNetwork()
            except Exception as exc:
                log.debug("Could not check isSqueezeNetwork: %s", exc)

            if is_sn:
                help_text = self._get_string(
                    "SQUEEZEBOX_PROBLEM_HELP_GENERIC",
                    "There was a problem connecting. Please try again.",
                )
            else:
                help_text = self._get_string(
                    "SQUEEZEBOX_PROBLEM_HELP",
                    f"There was a problem connecting to {server_name}. "
                    "Please try again.",
                )

            help_widget = Textarea("help_text", help_text)
            menu.set_header_widget(help_widget)
            window.add_widget(menu)

            window._isChooseMusicSourceWindow = True  # type: ignore[attr-defined]
            self.tie_and_show_window(window)

        except ImportError:
            # Headless / no UI — just cancel
            log.debug("_connect_player_failed: UI framework not available, cancelling")
            self._cancel_select_server()

    # Lua alias
    _connectPlayerFailed = _connect_player_failed

    def _http_auth_error_window(self, server: Any) -> None:
        """Show the "Wrong Password" error dialog with a "Try Again" button.

        Mirrors the Lua ``_httpAuthErrorWindow`` function (line ~454-489).
        """
        server_name = self._get_server_name(server)
        log.warn("HTTP auth error for %s — showing error dialog", server_name)

        try:
            from jive.ui.constants import EVENT_CONSUME
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.textarea import Textarea
            from jive.ui.window import Window

            window = Window(
                "help_list",
                self._get_string("SWITCH_PASSWORD_WRONG", "Wrong Password"),
                "setuptitle",
            )
            window.set_auto_hide(True)

            textarea = Textarea(
                "help_text",
                self._get_string(
                    "SWITCH_PASSWORD_WRONG_BODY",
                    "The password you entered was incorrect.",
                ),
            )

            menu = SimpleMenu("menu")

            menu.add_item({
                "text": self._get_string("SQUEEZEBOX_TRY_AGAIN", "Try Again"),
                "sound": "WINDOWHIDE",
                "callback": lambda *a: (
                    _get_applet_manager().call_service(
                        "squeezeCenterPassword",
                        server,
                        lambda: self.selectServer(server, True),
                        self.title_style,
                    )
                    if _get_applet_manager() is not None
                    else None
                ),
            })

            def _cancel_action(*_args: Any) -> int:
                window.play_sound("WINDOWHIDE")
                self._cancel_select_server()
                return int(EVENT_CONSUME)

            menu.add_action_listener("back", self, _cancel_action)
            menu.add_action_listener("go_home", self, _cancel_action)

            menu.set_header_widget(textarea)
            window.add_widget(menu)

            window._isChooseMusicSourceWindow = True  # type: ignore[attr-defined]
            self.tie_and_show_window(window)

        except ImportError:
            log.debug("_http_auth_error_window: UI framework not available")

    # Lua alias
    _httpAuthErrorWindow = _http_auth_error_window

    def _server_version_error(self, server: Any) -> None:
        """Handle server version incompatibility."""
        server_name = self._get_server_name(server)
        version = self._get_server_version(server) or "unknown"
        log.warn(
            "Server %s has incompatible version: %s",
            server_name,
            version,
        )

    # Lua alias
    _serverVersionError = _server_version_error

    def _confirm_server_switch(
        self, player: Any, server: Any, server_for_retry: Any = None
    ) -> None:
        """Show confirmation dialog before switching servers."""
        server_name = self._get_server_name(server)
        log.info("Confirming switch to %s", server_name)

        # In headless mode, just connect
        self.connectPlayerToServer(player, server)

    # Lua alias
    _confirmServerSwitch = _confirm_server_switch

    # ------------------------------------------------------------------
    # Notification handlers
    # ------------------------------------------------------------------

    def notify_serverAuthFailed(self, server: Any, failure_count: int = 0) -> None:
        """Handle server auth failure notification.

        Mirrors the Lua ``notify_serverAuthFailed`` — on the first failure
        for the server we are currently connecting to, show the auth error
        dialog.
        """
        log.debug(
            "notify_serverAuthFailed: waitForConnect=%s server=%s",
            self.wait_for_connect,
            server,
        )

        if (
            self.wait_for_connect
            and self.wait_for_connect.get("server") is server
            and failure_count == 1
        ):
            self._http_auth_error_window(server)

    # snake_case alias
    notify_server_auth_failed = notify_serverAuthFailed

    def notify_serverNew(self, server: Any) -> None:
        """Handle new server notification — add to list."""
        self._add_server_item(server)

    # snake_case alias
    notify_server_new = notify_serverNew

    def notify_serverDelete(self, server: Any) -> None:
        """Handle server deletion notification — remove from list."""
        self._del_server_item(server)

    # snake_case alias
    notify_server_delete = notify_serverDelete

    def notify_serverConnected(self, server: Any) -> None:
        """Handle server connected notification."""
        if (
            not self.wait_for_connect
            or self.wait_for_connect.get("server") is not server
        ):
            return

        log.info("notify_serverConnected")

        iconbar = _get_iconbar()
        if iconbar is not None:
            try:
                iconbar.setServerError("OK")
            except (AttributeError, TypeError) as exc:
                log.error("notify_serverConnected: failed to set iconbar server status: %s", exc, exc_info=True)

        # Check if we should auto-dismiss
        if not self.ignore_server_connected:
            wfc_player = self.wait_for_connect.get("player")
            try:
                is_local = (
                    wfc_player.is_local()  # type: ignore[union-attr]
                    if hasattr(wfc_player, "is_local")
                    else wfc_player.isLocal()  # type: ignore[union-attr]
                    if hasattr(wfc_player, "isLocal")
                    else False
                )
            except Exception:
                is_local = False

            if self.connecting_popup and is_local:
                self._cancel_select_server()

    # snake_case alias
    notify_server_connected = notify_serverConnected

    def notify_playerNew(self, player: Any) -> None:
        """Handle new player notification — update server list.

        Only updates for the current player (mirrors Lua guard).
        """
        mgr = _get_applet_manager()
        if mgr is not None:
            try:
                current = mgr.call_service("getCurrentPlayer")
                if player is not current:
                    return
            except Exception as exc:
                log.error("notify_playerNew: failed to get current player: %s", exc, exc_info=True)

        self._update_server_list(player)

    # snake_case alias
    notify_player_new = notify_playerNew

    def notify_playerDelete(self, player: Any) -> None:
        """Handle player deletion notification — update server list."""
        mgr = _get_applet_manager()
        if mgr is not None:
            try:
                current = mgr.call_service("getCurrentPlayer")
                if player is not current:
                    return
            except Exception as exc:
                log.error("notify_playerDelete: failed to get current player: %s", exc, exc_info=True)
        self._update_server_list(player)

    # snake_case alias
    notify_player_delete = notify_playerDelete

    def notify_playerCurrent(self, player: Any) -> None:
        """Handle current player change notification."""
        self._update_server_list(player)

        if player is None:
            log.warn("Unexpected nil player when waiting for new player or server")
            self._cancel_select_server()

    # snake_case alias
    notify_player_current = notify_playerCurrent

    def _update_server_list(self, player: Any) -> None:
        """Update checked style on server list items."""
        if not self.server_list:
            return

        server_id = None
        try:
            player_server = (
                player.get_slim_server()
                if hasattr(player, "get_slim_server")
                else player.getSlimServer()
                if hasattr(player, "getSlimServer")
                else None
            )
            if player_server is not None:
                server_id = (
                    player_server.get_ip_port()
                    if hasattr(player_server, "get_ip_port")
                    else player_server.getIpPort()
                    if hasattr(player_server, "getIpPort")
                    else None
                )
        except Exception as exc:
            log.warning("_update_server_list: failed to get player server id: %s", exc)

        for item_id, item in self.server_list.items():
            if server_id == item_id:
                item["style"] = "item_checked"
            else:
                item.pop("style", None)

            if self.server_menu is not None:
                try:
                    if hasattr(self.server_menu, "updated_item"):
                        self.server_menu.updated_item(item)
                    elif hasattr(self.server_menu, "updatedItem"):
                        self.server_menu.updatedItem(item)
                except Exception as exc:
                    log.warning("_update_server_list: failed to update menu item %s: %s", item_id, exc)

    # Lua alias
    _updateServerList = _update_server_list

    # ------------------------------------------------------------------
    # Remote servers (poll list management)
    # ------------------------------------------------------------------

    def _add_remote_server(self, address: str) -> None:
        """Add an address to the poll list and persist settings."""
        log.debug("_addRemoteServer: %s", address)

        settings = self._get_settings()
        poll = settings.get("poll", {})
        poll[address] = address

        # Ensure broadcast is still in the list
        poll["255.255.255.255"] = "255.255.255.255"

        mgr = _get_applet_manager()
        if mgr is not None:
            try:
                mgr.call_service("setPollList", poll)
            except Exception as exc:
                log.error("_add_remote_server: failed to call setPollList service: %s", exc, exc_info=True)

        settings["poll"] = poll
        self._store_settings(settings)

    # Lua alias
    _addRemoteServer = _add_remote_server

    def _remove_remote_server(self, address: str) -> None:
        """Remove an address from the poll list and persist settings."""
        log.debug("_removeRemoteServer: %s", address)

        settings = self._get_settings()
        poll = settings.get("poll", {})
        poll.pop(address, None)

        settings["poll"] = poll
        self._store_settings(settings)

    # Lua alias
    _removeRemoteServer = _remove_remote_server

    def remoteServersWindow(self, *args: Any) -> None:
        """
        Show the remote server management window.

        Allows users to add/remove server addresses from the poll list.
        In headless mode this logs the current poll list.
        """
        settings = self._get_settings()
        poll = settings.get("poll", {})

        log.info("Remote servers window — current poll list:")
        for address in poll:
            if address != "255.255.255.255":
                log.info("  %s", address)

        # Full UI would create a Window + SimpleMenu here
        self._remote_servers_window = True

    # snake_case alias
    remote_servers_window = remoteServersWindow

    def _refresh_remote_servers_window(self) -> None:
        """Refresh the remote servers list window.

        Stub — mirrors the Lua ``_refreshRemoteServersWindow`` function.
        """
        log.debug("_refresh_remote_servers_window called (stub)")
        if self._remote_servers_window is None:
            return

        # Full implementation would rebuild the menu items in
        # self._remote_servers_window from the poll list.

    # Lua alias
    _refreshRemoteServersWindow = _refresh_remote_servers_window

    def remoteServerDetailWindow(self, address: str) -> None:
        """Show detail / remove dialog for a remote server address.

        Stub — mirrors the Lua ``remoteServerDetailWindow`` function.
        """
        log.debug("remoteServerDetailWindow called for %s (stub)", address)

    # snake_case alias
    remote_server_detail_window = remoteServerDetailWindow

    def addRemoteServerSuccessWindow(self, address: str) -> None:
        """Show success dialog after adding a remote server.

        Stub — mirrors the Lua ``addRemoteServerSuccessWindow`` function.
        """
        log.debug("addRemoteServerSuccessWindow called for %s (stub)", address)

    # snake_case alias
    add_remote_server_success_window = addRemoteServerSuccessWindow

    def _input_remote_server(self) -> None:
        """Show IP address input window for adding a remote server.

        Stub — mirrors the Lua ``_inputRemoteServer`` function.
        """
        log.debug("_input_remote_server called (stub)")

    # Lua alias
    _inputRemoteServer = _input_remote_server

    def get_poll_addresses(self) -> List[str]:
        """Return the list of non-broadcast poll addresses."""
        settings = self._get_settings()
        poll = settings.get("poll", {})
        return [a for a in poll if a != "255.255.255.255"]

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------

    def _get_settings(self) -> Dict[str, Any]:
        """Return the applet's settings dict."""
        mgr = _get_applet_manager()
        if mgr is not None:
            try:
                db = mgr.get_applet_db()
                entry = db.get("ChooseMusicSource", {})
                settings = entry.get("settings")
                if settings is not None:
                    return settings  # type: ignore[no-any-return]
            except Exception as exc:
                log.error("_get_settings: failed to retrieve settings from applet db: %s", exc, exc_info=True)

        if self._settings is None:
            self._settings = {"poll": {"255.255.255.255": "255.255.255.255"}}
        return self._settings

    def _store_settings(self, settings: Optional[Dict[str, Any]] = None) -> None:
        """Persist settings via the AppletManager."""
        if settings is not None:
            self._settings = settings

        mgr = _get_applet_manager()
        if mgr is not None:
            try:
                mgr._store_settings("ChooseMusicSource")
            except Exception as exc:
                log.error("_store_settings: failed to persist settings: %s", exc, exc_info=True)

    def get_settings(self) -> Dict[str, Any]:
        """Public settings accessor (Applet interface)."""
        return self._get_settings()

    # Lua alias
    getSettings = get_settings

    def store_settings(self) -> None:
        """Public settings persist (Applet interface)."""
        self._store_settings()

    # Lua alias
    storeSettings = store_settings

    # ------------------------------------------------------------------
    # Duck-typing helpers (server accessors)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_server_name(server: Any) -> str:
        """Safely extract a server's display name."""
        if server is None or server is False:
            return "Unknown"
        for attr in ("get_name", "getName", "name"):
            try:
                val = getattr(server, attr, None)
                if callable(val):
                    result = val()
                    if result:
                        return str(result)
                elif val is not None:
                    return str(val)
            except Exception as exc:
                log.debug("_get_server_name: failed via attr %s: %s", attr, exc)
                continue
        return str(server)

    @staticmethod
    def _get_server_version(server: Any) -> Optional[str]:
        """Safely extract a server's version string."""
        if server is None or server is False:
            return None
        for attr in ("get_version", "getVersion"):
            try:
                val = getattr(server, attr, None)
                if callable(val):
                    result = val()
                    if result:
                        return str(result)
            except Exception as exc:
                log.debug("_get_server_version: failed via attr %s: %s", attr, exc)
                continue
        try:
            state = getattr(server, "state", {})
            if isinstance(state, dict):
                v = state.get("version")
                if v:
                    return str(v)
        except Exception as exc:
            log.debug("_get_server_version: failed to read state dict: %s", exc)
        return None

    @staticmethod
    def _get_server_ip_port(server: Any) -> Optional[str]:
        """Safely extract a server's IP:port string."""
        if server is None or server is False:
            return None
        for attr in ("get_ip_port", "getIpPort"):
            try:
                val = getattr(server, attr, None)
                if callable(val):
                    result = val()
                    if result:
                        return str(result)
            except Exception as exc:
                log.debug("_get_server_ip_port: failed via attr %s: %s", attr, exc)
                continue
        return None

    # ------------------------------------------------------------------
    # String helper
    # ------------------------------------------------------------------

    def _get_string(self, token: str, fallback: str = "") -> str:
        """Resolve a localisation token, falling back to *fallback*."""
        strings_table = getattr(self, "_strings_table", None)
        if strings_table is not None:
            try:
                resolved = strings_table.str(token)
                if resolved:
                    return resolved  # type: ignore[no-any-return]
            except Exception as exc:
                log.debug("_get_string: failed to resolve token %r from _strings_table: %s", token, exc)

        if self._entry is not None:
            st = self._entry.get("strings_table")
            if st is not None:
                try:
                    resolved = st.str(token)
                    if resolved:
                        return resolved  # type: ignore[no-any-return]
                except Exception as exc:
                    log.debug("_get_string: failed to resolve token %r from entry strings_table: %s", token, exc)

        return fallback

    # Lua compatibility alias
    string = _get_string

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        n_servers = len(self.server_list)
        wfc = self.wait_for_connect is not None
        return f"ChooseMusicSourceApplet(servers={n_servers}, connecting={wfc})"


# ══════════════════════════════════════════════════════════════════════════
# Headless stubs
# ══════════════════════════════════════════════════════════════════════════


class _HeadlessMenu:
    """Minimal stub for a SimpleMenu in headless mode."""

    def __init__(self) -> None:
        self._items: List[Dict[str, Any]] = []

    def add_item(self, item: Dict[str, Any]) -> None:
        self._items.append(item)

    addItem = add_item

    def remove_item(self, item: Dict[str, Any]) -> None:
        try:
            self._items.remove(item)
        except ValueError as exc:
            log.debug("_HeadlessMenu.remove_item: item not in list: %s", exc)

    removeItem = remove_item

    def set_comparator(self, cmp: Any) -> None:
        pass

    setComparator = set_comparator

    def set_selected_item(self, item: Dict[str, Any]) -> None:
        pass

    setSelectedItem = set_selected_item

    def updated_item(self, item: Dict[str, Any]) -> None:
        pass

    updatedItem = updated_item

    def __len__(self) -> int:
        return len(self._items)


class _HeadlessPopup:
    """Minimal stub for a Popup in headless mode."""

    def __init__(self, server_name: str = "") -> None:
        self.server_name = server_name
        self.visible = True

    def hide(self) -> None:
        self.visible = False

    def __repr__(self) -> str:
        return f"_HeadlessPopup({self.server_name!r}, visible={self.visible})"


class _StubServer:
    """Minimal stub for a SlimServer when the real class is unavailable."""

    def __init__(self, address: str) -> None:
        self.address = address
        self.name = address
        self.id = address
        self.ip = address
        self.port = 9000
        self.state: Dict[str, Any] = {}

    def get_name(self) -> str:
        return self.name

    getName = get_name

    def get_ip_port(self) -> str:
        return f"{self.ip}:{self.port}"

    getIpPort = get_ip_port

    def get_version(self) -> Optional[str]:
        return self.state.get("version")

    getVersion = get_version

    def is_compatible(self) -> bool:
        return True

    isCompatible = is_compatible

    def is_squeeze_network(self) -> bool:
        return False

    isSqueezeNetwork = is_squeeze_network

    def is_password_protected(self) -> bool:
        return False

    isPasswordProtected = is_password_protected

    def is_connected(self) -> bool:
        return False

    isConnected = is_connected

    def update_init(self, data: Dict[str, Any], port: int) -> None:
        if "ip" in data:
            self.ip = data["ip"]
        self.port = port

    updateInit = update_init

    def __repr__(self) -> str:
        return f"_StubServer({self.address!r})"
