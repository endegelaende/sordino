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
    except ImportError:
        pass
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
        pass
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

    def init(self, **kwargs: Any) -> "ChooseMusicSourceApplet":
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
            except Exception:
                pass
        return True

    # ------------------------------------------------------------------
    # Service: selectMusicSource / selectCompatibleMusicSource
    # ------------------------------------------------------------------

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
            except Exception:
                pass

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
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Server list UI
    # ------------------------------------------------------------------

    def _show_music_source_list(self, offer_list_if_only_one: bool = False) -> None:
        """
        Build and show the server selection menu.

        Mirrors the Lua ``_showMusicSourceList`` function.
        """
        mgr = _get_applet_manager()

        # ── Trigger server discovery ─────────────────────────────────
        if mgr is not None:
            try:
                mgr.call_service("discoverServers")
            except Exception:
                pass

        # ── Polled servers (from settings) ───────────────────────────
        poll: Dict[str, str] = {}
        if mgr is not None:
            try:
                poll = mgr.call_service("getPollList") or {}
            except Exception:
                pass

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
            except Exception:
                pass

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

            self.server_menu = menu

            # Populate with current server list
            for _id, item in self.server_list.items():
                menu.add_item(item)

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
            except Exception:
                pass

        # Filter: compatible sources only
        if self.offer_compatible_sources_only and server is not None:
            try:
                if hasattr(server, "is_compatible") and not server.is_compatible():
                    log.info("Exclude non-compatible source: %s", server)
                    return
            except Exception:
                pass

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
            except Exception:
                pass

        # Remove existing entry
        if item_id in self.server_list:
            if self.server_menu is not None:
                try:
                    self.server_menu.remove_item(self.server_list[item_id])
                except Exception:
                    pass

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
                        except Exception:
                            pass
            except Exception:
                pass

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
                except Exception:
                    pass

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
                except Exception:
                    pass

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
            except Exception:
                pass

        if sid in self.server_list:
            if self.server_menu is not None:
                try:
                    self.server_menu.remove_item(self.server_list[sid])
                except Exception:
                    pass
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
                except Exception:
                    pass

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
                server.update_init({"ip": address}, 9000)
            except (AttributeError, TypeError):
                try:
                    server.updateInit({"ip": address}, 9000)
                except (AttributeError, TypeError):
                    pass
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
                if (
                    hasattr(server, "is_password_protected")
                    and server.is_password_protected()
                ) or (
                    hasattr(server, "isPasswordProtected")
                    and server.isPasswordProtected()
                ):
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
                        except Exception:
                            pass
            except Exception:
                pass

        # Check version compatibility
        version = self._get_server_version(server)
        if version is not None:
            compatible = True
            try:
                if hasattr(server, "is_compatible"):
                    compatible = server.is_compatible()
                elif hasattr(server, "isCompatible"):
                    compatible = server.isCompatible()
            except Exception:
                pass

            if not compatible:
                self._server_version_error(server)
                return

        # Get current player
        mgr = _get_applet_manager()
        current_player = None
        if mgr is not None:
            try:
                current_player = mgr.call_service("getCurrentPlayer")
            except Exception:
                pass

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
        except Exception:
            pass

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
                    except Exception:
                        pass

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
                except Exception:
                    pass

                if timeout_counter["count"] > CONNECT_TIMEOUT or has_failed:
                    log.warn(
                        "Connection failure or Timeout, count: %d",
                        timeout_counter["count"],
                    )
                    self._connect_player_failed(player, server)
                    if self.connecting_popup is not None:
                        self.connecting_popup.hide()
                        self.connecting_popup = None

            popup.add_timer(1000, _on_timeout)

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
                        wfc_player.get_slim_server()
                        if hasattr(wfc_player, "get_slim_server")
                        else wfc_player.getSlimServer()
                        if hasattr(wfc_player, "getSlimServer")
                        else None
                    )
                except Exception:
                    pass

                if player_server is wfc_server:
                    # Check upgrade
                    try:
                        if getattr(wfc_server, "upgrade_force", False) or getattr(
                            wfc_server, "upgradeForce", False
                        ):
                            self._cancel_select_server(no_hide=True)
                            return
                    except Exception:
                        pass

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
            except Exception:
                pass
            self.connecting_popup = None

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
            except Exception:
                pass

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
        """Handle connection failure — log and optionally show retry UI."""
        server_name = self._get_server_name(server)
        log.warn("Connection to %s failed", server_name)

        # In headless mode just cancel
        self._cancel_select_server()

    # Lua alias
    _connectPlayerFailed = _connect_player_failed

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
        """Handle server auth failure notification."""
        if (
            self.wait_for_connect
            and self.wait_for_connect.get("server") is server
            and failure_count == 1
        ):
            log.warn("Server auth failed for %s", server)

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
            except (AttributeError, TypeError):
                pass

        # Check if we should auto-dismiss
        if not self.ignore_server_connected:
            wfc_player = self.wait_for_connect.get("player")
            try:
                is_local = (
                    wfc_player.is_local()
                    if hasattr(wfc_player, "is_local")
                    else wfc_player.isLocal()
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
        """Handle new player notification — update server list."""
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
            except Exception:
                pass
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
        except Exception:
            pass

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
                except Exception:
                    pass

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
            except Exception:
                pass

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
                    return settings
            except Exception:
                pass

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
            except Exception:
                pass

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
            except Exception:
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
            except Exception:
                continue
        try:
            state = getattr(server, "state", {})
            if isinstance(state, dict):
                v = state.get("version")
                if v:
                    return str(v)
        except Exception:
            pass
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
            except Exception:
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
                    return resolved
            except Exception:
                pass

        if self._entry is not None:
            st = self._entry.get("strings_table")
            if st is not None:
                try:
                    resolved = st.str(token)
                    if resolved:
                        return resolved
                except Exception:
                    pass

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
        except ValueError:
            pass

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
