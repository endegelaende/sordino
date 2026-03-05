"""
jive.slim.slim_server — SlimServer representation for LMS communication.

Ported from ``jive/slim/SlimServer.lua`` in the original jivelite project.

The SlimServer class represents a Lyrion Music Server (LMS, formerly
Logitech Media Server / SlimServer / SqueezeCenter) on the network.
It manages:

* **Connection** — Comet (Bayeux) long-poll connection for events and
  JSON-RPC requests, plus an HTTP pool for artwork fetching.
* **Players** — Tracks all players reported by this server via the
  ``serverstatus`` subscription.
* **Artwork** — Fetches, caches, and resizes album/artist artwork.
  Uses a two-level cache: raw bytes in ``ArtworkCache`` and decoded
  surfaces in a weak-reference ``image_cache``.
* **State** — Server version, upgrade info, PIN/linking, reconnection.
* **Notifications** — Fires events through the ``jnt`` (NetworkThread)
  notification bus: ``serverNew``, ``serverDelete``, ``serverConnected``,
  ``serverDisconnected``, ``serverLinked``, ``firmwareAvailable``,
  ``serverRescanning``, ``serverRescanDone``, ``serverAuthFailed``.

SlimServer objects are unique per server-ID.  Calling ``SlimServer(jnt,
id, ...)`` twice with the same *id* returns the **same** object.

Class-level state:

* ``_server_ids``     — weak dict of all SlimServer instances by ID
* ``_server_list``    — dict of currently active servers
* ``_current_server`` — the currently selected server (if any)
* ``_credentials``    — stored HTTP authentication credentials
* ``_locally_requested_servers`` — servers requested via local connect

Notifications emitted (via ``jnt.notify(...)``):

    serverNew, serverDelete,
    serverConnected, serverDisconnected,
    serverLinked, serverAuthFailed,
    serverRescanning, serverRescanDone,
    firmwareAvailable,
    playerNew, playerDelete

Usage::

    from jive.slim.slim_server import SlimServer

    server = SlimServer(jnt, "192.168.1.100", "My LMS", "8.5.0")
    server.update_address("192.168.1.100", 9000, "My LMS")
    server.connect()

    # Iterate over known servers:
    for sid, srv in SlimServer.iterate():
        print(srv.get_name())

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import re
import time
import weakref
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from jive.slim.artwork_cache import ArtworkCache
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.net.comet import Comet
    from jive.net.http_pool import HttpPool
    from jive.net.network_thread import NetworkThread
    from jive.slim.player import Player

__all__ = ["SlimServer"]

log = logger("squeezebox.server")
logcache = logger("squeezebox.server.cache")

# Time after which stale player data from non-current servers is ignored (ms)
SERVER_DISCONNECT_LAG_TIME: int = 10000

# Minimum server version that this client supports
_minimum_version: str = "7.4"


# ---------------------------------------------------------------------------
# Module-level server registries
# ---------------------------------------------------------------------------

# Weak-value dict: enforces one SlimServer instance per ID.
_server_ids: weakref.WeakValueDictionary[str, "SlimServer"] = weakref.WeakValueDictionary()

# Active servers (strong references, removed explicitly via free())
_server_list: Dict[str, "SlimServer"] = {}

# Currently selected server
_current_server: Optional["SlimServer"] = None

# Previous server (for switch detection)
_last_current_server: Optional["SlimServer"] = None

# Timestamp of the last server switch (ms)
_last_server_switch_t: Optional[int] = None

# Servers for which a local connection request has been made
_locally_requested_servers: List["SlimServer"] = []

# HTTP authentication credentials by server ID
_credentials: Dict[str, Dict[str, str]] = {}


def _get_ticks() -> int:
    """Return milliseconds since an arbitrary epoch (monotonic)."""
    try:
        from jive.ui.framework import framework as fw

        if fw is not None:
            ticks = fw.get_ticks()
            if ticks > 0:
                return ticks
    except (ImportError, AttributeError) as exc:
        log.debug("_get_ticks: framework not available: %s", exc)
    return int(time.monotonic() * 1000)


# ===================================================================
# SlimServer class
# ===================================================================


class SlimServer:
    """
    Represents and interfaces with a real LMS server on the network.

    Parameters
    ----------
    jnt : NetworkThread or None
        The network-thread coordinator (notification bus).
    server_id : str
        Unique server identifier (typically IP or UUID).
    name : str
        Human-readable server name.
    version : str or None
        Server software version string.
    """

    # ------------------------------------------------------------------
    # Construction (singleton-per-ID)
    # ------------------------------------------------------------------

    def __new__(
        cls,
        jnt: Optional[NetworkThread] = None,
        server_id: str = "",
        name: str = "",
        version: Optional[str] = None,
    ) -> "SlimServer":
        """Enforce one instance per server_id."""
        existing = _server_ids.get(server_id)
        if existing is not None and type(existing) is cls:
            return existing
        instance = super().__new__(cls)
        return instance

    def __init__(
        self,
        jnt: Optional[NetworkThread] = None,
        server_id: str = "",
        name: str = "",
        version: Optional[str] = None,
    ) -> None:
        # Guard against re-initialising an existing instance
        if hasattr(self, "_initialised") and self._initialised:
            return

        self._initialised: bool = True

        self.id: str = server_id
        self.name: str = name
        self.jnt: Optional[NetworkThread] = jnt

        # Connection
        self.last_seen: int = 0
        self.ip: Any = False  # str | False
        self.port: Any = False  # int | False
        self.mac: Optional[str] = None

        # State from server
        self.state: Dict[str, Any] = {}
        if version:
            self.state["version"] = version

        # Firmware upgrade
        self.upgrade_url: Any = False  # str | False
        self.upgrade_force: bool = False

        # Players tracked by this server
        self.players: Dict[str, Any] = {}  # player_id -> Player

        # Comet connection (created lazily or set externally)
        self._comet: Optional[Any] = None  # Comet instance

        # Network state
        # 'disconnected' | 'connecting' | 'connected'
        self.netstate: str = "disconnected"

        # User-activated requests
        self.user_requests: List[Any] = []

        # Artwork state
        self._artwork_pool: Any = False  # HttpPool | False

        # Raw artwork LRU cache
        self.artwork_cache: ArtworkCache = ArtworkCache()

        # Icons waiting for a given cache key:  icon -> cacheKey
        self.artwork_thumb_icons: Dict[Any, str] = {}

        # Queue of artwork to fetch (LIFO)
        self.artwork_fetch_queue: List[Dict[str, Any]] = []
        self.artwork_fetch_count: int = 0

        # Decoded image cache (weak-value dict)
        self.image_cache: weakref.WeakValueDictionary[str, Any] = weakref.WeakValueDictionary()

        # PIN for SqueezeNetwork linking
        self.pin: Any = False  # str | False

        # App parameters (e.g., Facebook icon)
        self.app_parameters: Dict[str, Dict[str, Any]] = {}

        # HTTP auth
        self.realm: Optional[str] = None
        self.auth_failure_count: int = 0

        # Artwork fetch task — mirrors Lua: obj.artworkFetchTask = Task("artwork", obj, processArtworkQueue)
        try:
            from jive.ui.task import PRIORITY_LOW, Task

            self._artwork_fetch_task: Optional[Any] = Task(
                "artwork", self, _process_artwork_queue_gen, priority=PRIORITY_LOW
            )
        except (ImportError, Exception) as exc:
            log.warning("SlimServer.__init__: could not create artwork fetch task: %s", exc)
            self._artwork_fetch_task = None

        # Register in weak dict
        _server_ids[self.id] = self

        # Subscribe to jnt notifications
        if self.jnt:
            self.jnt.subscribe(self)

        # Set up Comet subscriptions (serverstatus etc.) early — matching
        # the Lua original which subscribes in __init.  The subscriptions
        # are queued as "pending" and sent automatically when the Comet
        # connection is established.
        self._setup_subscriptions()

    # ------------------------------------------------------------------
    # Comet property (lazy / injectable)
    # ------------------------------------------------------------------

    @property
    def comet(self) -> Any:
        """
        The Comet connection for this server.

        If no Comet instance was provided, one is created lazily
        using the server name.
        """
        if self._comet is None:
            try:
                from jive.net.comet import Comet

                self._comet = Comet(self.jnt, self.name)
            except ImportError:
                raise RuntimeError("Comet class not available — cannot create connection")
        return self._comet

    @comet.setter
    def comet(self, value: Any) -> None:
        self._comet = value

    # ------------------------------------------------------------------
    # Artwork pool property
    # ------------------------------------------------------------------

    @property
    def artwork_pool(self) -> Any:
        return self._artwork_pool

    @artwork_pool.setter
    def artwork_pool(self, value: Any) -> None:
        self._artwork_pool = value

    # ------------------------------------------------------------------
    # Class-level iteration / current-server
    # ------------------------------------------------------------------

    @classmethod
    def iterate(cls) -> Iterator[Tuple[str, "SlimServer"]]:
        """Iterate over all active servers as ``(id, server)`` pairs."""
        yield from _server_list.items()

    @classmethod
    def get_current_server(cls) -> Optional["SlimServer"]:
        """Return the currently selected server (or ``None``)."""
        return _current_server

    @classmethod
    def add_locally_requested_server(cls, server: "SlimServer") -> None:
        """Record a server for which a local connection request was made."""
        _locally_requested_servers.append(server)

    @classmethod
    def set_current_server(cls, server: Optional["SlimServer"]) -> None:
        """
        Set the currently selected server.

        If the server has changed, records the switch timestamp so
        stale player data from old servers can be ignored.
        """
        global _current_server, _last_current_server, _last_server_switch_t

        if _last_current_server is not None and (
            (server is not None and _last_current_server is not server)
            or (server is None and _last_current_server is not None)
        ):
            log.debug("setting lastServerSwitchT for server: %s", server)
            _last_server_switch_t = _get_ticks()

        _last_current_server = _current_server
        _current_server = server

        # If the old server is no longer active, clean it up
        if _last_current_server is not None and _last_current_server.last_seen == 0:
            _last_current_server.free()

    @classmethod
    def get_server_by_address(cls, address: str) -> Optional["SlimServer"]:
        """Look up a server by its IP address."""
        for sid, server in _server_list.items():
            if server.ip == address:
                return server
        return None

    # ------------------------------------------------------------------
    # _getSink helper
    # ------------------------------------------------------------------

    def _get_sink(self, method_name: str) -> Optional[Callable[..., None]]:
        """
        Return a sink callback that dispatches to ``self.<method_name>()``.

        Returns ``None`` if the method doesn't exist.
        """
        func = getattr(self, method_name, None)
        if func is None or not callable(func):
            log.error("%s: no function called [%s]", self, method_name)
            return None

        def sink(chunk: Any = None, err: Any = None) -> None:
            if err:
                log.error("%s: %s during %s", self, err, method_name)
            elif chunk is not None:
                func(chunk)

        return sink

    # ------------------------------------------------------------------
    # _serverstatusSink — process serverstatus subscription data
    # ------------------------------------------------------------------

    def _serverstatus_sink(self, event: Any, err: Any = None) -> None:
        """
        Process the result of the ``serverstatus`` Comet subscription.

        Creates/updates/removes Player objects as reported by the server.
        """
        global _locally_requested_servers

        log.debug("%s:_serverstatus_sink()", self)

        data = event if isinstance(event, dict) else getattr(event, "data", event)
        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        if not isinstance(data, dict):
            log.error("%s: chunk with no data", self)
            return

        # Filter potentially stale player data
        now = _get_ticks()
        server_players: Optional[List[Dict[str, Any]]] = None

        if (
            _last_server_switch_t is not None
            and _last_server_switch_t + SERVER_DISCONNECT_LAG_TIME < now
        ):
            _locally_requested_servers = []

        players_loop = data.get("players_loop")
        if players_loop:
            server_players = []
            from jive.slim.player import Player as PlayerCls

            for player_info in players_loop:
                cur_player = PlayerCls.get_current_player()
                if (
                    (len(_locally_requested_servers) > 0 and self not in _locally_requested_servers)
                    or (len(_locally_requested_servers) == 0 and self is not _current_server)
                ) and (
                    _to_bool(player_info.get("connected"))
                    and cur_player is not None
                    and player_info.get("playerid") == cur_player.id
                    and _last_server_switch_t is not None
                    and _last_server_switch_t + SERVER_DISCONNECT_LAG_TIME > now
                ):
                    log.info(
                        "Ignoring potentially inaccurate player data for "
                        "current player from server %s",
                        self,
                    )
                else:
                    server_players.append(player_info)

        # Remove players_loop from data to avoid storing it twice
        data_without_players = {k: v for k, v in data.items() if k != "players_loop"}

        # Save old state
        old_state = self.state

        # Update in one shot
        self.state = data_without_players
        self.last_seen = _get_ticks()

        # Manage rescan
        if str(self.state.get("rescan", "")) != str(old_state.get("rescan", "")):
            if not self.state.get("rescan"):
                if self.jnt:
                    self.jnt.notify("serverRescanning", self)
            else:
                if self.jnt:
                    self.jnt.notify("serverRescanDone", self)

        # Update players
        # Copy all players we know about
        self_players = set(self.players.keys())
        pin: Any = False

        player_count = _to_int(data.get("player count", 0))

        if player_count > 0 and server_players is not None:
            from jive.slim.player import Player as PlayerCls

            for player_info in server_players:
                player_id = player_info.get("playerid", "")
                if not player_id:
                    continue

                if player_info.get("pin"):
                    pin = player_info["pin"]

                # Remove from our tracking set
                self_players.discard(player_id)

                # Create new players if needed
                if player_id not in self.players:
                    # Check if this is the local player
                    local_mac = self._get_local_mac()
                    if local_mac and player_id == local_mac:
                        from jive.slim.local_player import LocalPlayer

                        self.players[player_id] = LocalPlayer(self.jnt, player_id)
                    else:
                        self.players[player_id] = PlayerCls(self.jnt, player_id)

                player = self.players[player_id]

                # Sequence number handling
                use_sequence_number = False
                is_sequence_number_in_sync = True
                if player.is_local_player() and player_info.get("seq_no") is not None:
                    use_sequence_number = True
                    if not player.is_sequence_number_in_sync(int(player_info["seq_no"])):
                        is_sequence_number_in_sync = False

                # Bug 16295: Only use serverstatus data for the current player
                # when it indicates a server change or connected status change.
                cur_player = PlayerCls.get_current_player()
                if (
                    cur_player is not player
                    or player.get_slim_server() is not self
                    or player.is_connected() != _to_bool(player_info.get("connected"))
                ):
                    player.update_player_info(
                        self,
                        player_info,
                        use_sequence_number,
                        is_sequence_number_in_sync,
                    )
        else:
            log.debug("%s: has no players!", self)

        # PIN check
        if self.pin != pin:
            self.pin = pin
            if self.jnt:
                self.jnt.notify("serverLinked", self)

        # Remove players that are no longer reported
        for player_id in self_players:
            player = self.players.get(player_id)
            if player:
                player.free(self)
                del self.players[player_id]

    def _get_local_mac(self) -> Optional[str]:
        """
        Get the local device MAC address, if available.

        This is used to identify the local player in the server's
        player list.  Returns ``None`` if the System module is not
        available.
        """
        # Stub — will be wired when System module is ported
        return None

    # ------------------------------------------------------------------
    # Upgrade sink (stub — not relevant to desktop/jivelite)
    # ------------------------------------------------------------------

    def _upgrade_sink(self, chunk: Any, err: Any = None) -> None:
        """Process firmware upgrade data (stub — not used on desktop)."""
        if err:
            log.warn("Error in upgrade sink: %s", err)
            return

        data = chunk if isinstance(chunk, dict) else getattr(chunk, "data", chunk)
        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        if not isinstance(data, dict):
            return

        url = None
        if data.get("relativeFirmwareUrl"):
            url = f"http://{self.ip}:{self.port}{data['relativeFirmwareUrl']}"
        elif data.get("firmwareUrl"):
            url = data["firmwareUrl"]

        old_url = self.upgrade_url
        old_force = self.upgrade_force

        self.upgrade_url = url or False
        self.upgrade_force = False

        log.info("%s firmware=%s force=%s", self.name, self.upgrade_url, self.upgrade_force)

        if old_url != self.upgrade_url or old_force != self.upgrade_force:
            if self.jnt:
                self.jnt.notify("firmwareAvailable", self)

    # ------------------------------------------------------------------
    # Player management (package-private)
    # ------------------------------------------------------------------

    def _delete_player(self, player: Any) -> None:
        """Remove a player from this server's tracking."""
        self.players.pop(player.get_id(), None)

    def _add_player(self, player: Any) -> None:
        """Add a player to this server's tracking."""
        self.players[player.get_id()] = player

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------

    def set_credentials(
        self,
        cred: Dict[str, str],
        cred_id: Optional[str] = None,
    ) -> None:
        """
        Set HTTP authentication credentials.

        Parameters
        ----------
        cred : dict
            Must contain ``realm``, ``username``, ``password``.
        cred_id : str or None
            If ``None``, apply to this server (object method).
            If given, store globally by ID (class-level storage).
        """
        if cred_id is None:
            cred_id = self.id
            self.auth_failure_count = 0

            # Set credentials on SocketHttp
            try:
                from jive.net.socket_http import SocketHttp

                SocketHttp.set_credentials(
                    ipport=(self.ip, self.port) if self.ip else ("", 0),
                    realm=cred.get("realm", ""),
                    username=cred.get("username", ""),
                    password=cred.get("password", ""),
                )
            except (ImportError, AttributeError, TypeError) as exc:
                log.debug("_handle_credential: could not set credentials: %s", exc)

            # Force reconnection
            self.reconnect()

        _credentials[cred_id] = cred

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def _setup_subscriptions(self) -> None:
        """
        Set up the initial Comet subscriptions (serverstatus, etc.).

        Called after the Comet connection is available.
        """
        self.comet.aggressive_reconnect(True)

        sink = self._get_sink("_serverstatus_sink")
        if sink:
            self.comet.subscribe(
                "/slim/serverstatus",
                sink,
                None,
                ["serverstatus", 0, 50, "subscribe:60"],
            )

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def update_init(self, init: Dict[str, Any]) -> None:
        """
        Update server on start-up.

        Parameters
        ----------
        init : dict
            Must contain ``ip`` and optionally ``mac``.
        """
        if self.id in _server_list:
            # Already initialised
            return

        self.ip = init.get("ip", False)
        self.mac = init.get("mac")
        self.last_seen = 0  # Don't timeout
        _server_list[self.id] = self

    def get_init(self) -> Dict[str, Any]:
        """Return the state needed for ``update_init``."""
        return {
            "ip": self.ip,
            "mac": self.mac,
        }

    # ------------------------------------------------------------------
    # updateAddress
    # ------------------------------------------------------------------

    def update_address(
        self,
        ip: str,
        port: Any,
        name: Optional[str] = None,
    ) -> None:
        """
        Update (or initially set) the IP address and port for the server.

        If the address has changed, the old connection is closed and
        a new one is opened.
        """
        # Port may arrive as a string from TLV discovery parsing
        port = int(port)

        if self.ip != ip or self.port != port or (name and self.name != name):
            log.debug(
                "%s: address set to %s:%s netstate=%s name=%s",
                self,
                ip,
                port,
                self.netstate,
                name,
            )

            old_state = self.netstate

            # Close old connections
            self.disconnect()

            # Open new connection
            self.ip = ip
            self.port = port
            if name:
                self.name = name

            # HTTP authentication
            cred = _credentials.get(self.id)
            if cred:
                self.auth_failure_count = 0
                try:
                    from jive.net.socket_http import SocketHttp

                    SocketHttp.set_credentials(
                        ipport=(ip, port),
                        realm=cred.get("realm", ""),
                        username=cred.get("username", ""),
                        password=cred.get("password", ""),
                    )
                except (ImportError, AttributeError, TypeError) as exc:
                    log.debug("_connect: could not set credentials: %s", exc)

            if not self.is_squeeze_network():
                # Create artwork HTTP pool
                try:
                    from jive.net.http_pool import HttpPool
                    from jive.ui.task import PRIORITY_LOW

                    self._artwork_pool = HttpPool(self.jnt, self.name, ip, port, 2, 1, PRIORITY_LOW)
                except (ImportError, AttributeError):
                    log.debug("HttpPool not available — artwork pool disabled")

            # Set Comet endpoint
            self.comet.set_endpoint(ip, port, "/cometd")

            # Reconnect if we were already connected
            if old_state != "disconnected":
                self.connect()

        old_last_seen = self.last_seen
        self.last_seen = _get_ticks()

        # Server is now active
        if old_last_seen == 0:
            _server_list[self.id] = self
            if self.jnt:
                self.jnt.notify("serverNew", self)

    # ------------------------------------------------------------------
    # free / teardown
    # ------------------------------------------------------------------

    def free(self) -> None:
        """
        Delete this server: clear caches, close connections, free players.
        """
        log.debug("%s:free", self)

        # Clear artwork cache
        self.artwork_cache.free()
        self.artwork_thumb_icons = {}

        # Server is gone
        self.last_seen = 0
        if self.jnt:
            self.jnt.notify("serverDelete", self)

        if self is _current_server:
            # Don't delete state if this is the current server
            return

        # Close connections
        self.disconnect()

        # Delete players
        for player_id, player in list(self.players.items()):
            player.free(self)
        self.players = {}

        self.upgrade_url = False
        self.upgrade_force = False
        self.app_parameters = {}

        # Remove from active list
        _server_list.pop(self.id, None)

    # ------------------------------------------------------------------
    # Wake-on-LAN
    # ------------------------------------------------------------------

    def wake_on_lan(self) -> None:
        """Send a Wake-on-LAN packet to this server."""
        if not self.mac or self.is_squeeze_network():
            log.warn(
                "wake_on_lan(): SKIPPING WOL, mac=%s, isSqueezeNetwork=%s",
                self.mac,
                self.is_squeeze_network(),
            )
            return

        log.info("wake_on_lan(): Sending WOL to %s", self.mac)

        try:
            from jive.net.wake_on_lan import WakeOnLan

            wol = WakeOnLan(self.jnt)
            wol.wake_on_lan(self.mac)
        except (ImportError, Exception) as exc:
            log.warn("wake_on_lan() failed: %s", exc)

    # ------------------------------------------------------------------
    # Connect / Disconnect / Reconnect
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Connect to the server via Comet."""
        if self.netstate in ("connected", "connecting"):
            return

        if not self.ip:
            log.debug("Server IP address is not known")
            return

        log.debug("%s:connect", self)

        self.auth_failure_count = 0
        self.netstate = "connecting"

        # Artwork pool connects on demand
        self.comet.connect()

    def _disconnect_server_internals(self) -> None:
        """Internal disconnect — close Comet and artwork pool."""
        self.netstate = "disconnected"

        if not self.is_squeeze_network() and self._artwork_pool:
            try:
                self._artwork_pool.close()
            except Exception as exc:
                log.warning("_disconnect_server_internals: error closing artwork pool: %s", exc)

        try:
            self.comet.disconnect()
        except Exception as exc:
            log.warning("_disconnect_server_internals: error disconnecting comet: %s", exc)

    def disconnect(self) -> None:
        """Force disconnect from the server."""
        if self.netstate == "disconnected":
            return

        log.debug("%s:disconnect", self)
        self._disconnect_server_internals()

    def reconnect(self) -> None:
        """Force reconnection to the server."""
        log.debug("%s:reconnect", self)
        self.disconnect()
        self.connect()

    def set_idle_timeout(self, idle_timeout: int) -> None:
        """
        Set idle timeout — disconnect after this many seconds of
        inactivity.
        """
        self.comet.set_idle_timeout(idle_timeout)

    # ------------------------------------------------------------------
    # Comet event handlers (notification listeners)
    # ------------------------------------------------------------------

    def notify_cometConnected(self, comet: Any) -> None:
        """Handle Comet connected event."""
        if self._comet is not comet:
            return

        log.info("connected %s", self.name)
        self.netstate = "connected"
        self.auth_failure_count = 0

        if self.jnt:
            self.jnt.notify("serverConnected", self)

        # Auto-discover server MAC via ARP (stub)
        if self.jnt and hasattr(self.jnt, "arp"):

            def arp_callback(chunk: Any = None, err: Any = None) -> None:
                if err:
                    log.debug("arp: %s", err)
                else:
                    log.info("self.mac being set to %s", chunk)
                    self.mac = chunk

            self.jnt.arp(self.ip, arp_callback)

    def notify_cometDisconnected(self, comet: Any, idle_timeout_triggered: bool = False) -> None:
        """Handle Comet disconnected event."""
        if self._comet is not comet:
            return

        log.info(
            "disconnected %s idleTimeoutTriggered=%s",
            self.name,
            idle_timeout_triggered,
        )

        if idle_timeout_triggered:
            log.info("idle disconnected %s", self.name)
            self._disconnect_server_internals()
        else:
            if self.netstate == "connected":
                log.debug("%s disconnected", self)
                self.netstate = "connecting"

        if self.jnt:
            self.jnt.notify("serverDisconnected", self, len(self.user_requests))

    def notify_cometHttpError(self, comet: Any, comet_request: Any = None) -> None:
        """Handle Comet HTTP error (401 auth challenges)."""
        if comet_request is None:
            return

        status = None
        try:
            status = comet_request.t_get_response_status()
        except Exception as exc:
            log.warning("notify_cometHttpError: could not get response status: %s", exc)

        if status == 401:
            authenticate = None
            try:
                authenticate = comet_request.t_get_response_header("WWW-Authenticate")
            except Exception as exc:
                log.warning(
                    "notify_cometHttpError: could not get WWW-Authenticate header: %s",
                    exc,
                )

            if authenticate:
                match = re.search(r'Basic realm="(.*?)"', authenticate)
                if match:
                    self.realm = match.group(1)

            if not self.is_connected():
                if self.auth_failure_count is None:
                    self.auth_failure_count = 0
                if self.auth_failure_count > 0:
                    log.info(
                        "failed auth. Count: %d server: %s state: %s",
                        self.auth_failure_count,
                        self,
                        self.netstate,
                    )
                    if self.jnt:
                        self.jnt.notify("serverAuthFailed", self, self.auth_failure_count)
                self.auth_failure_count += 1

    # ------------------------------------------------------------------
    # SqueezeNetwork (always False — SN is defunct)
    # ------------------------------------------------------------------

    @staticmethod
    def is_squeeze_network() -> bool:
        """Always ``False`` — SqueezeNetwork is no longer operational."""
        return False

    # ------------------------------------------------------------------
    # PIN / linking
    # ------------------------------------------------------------------

    def get_pin(self) -> Any:
        """Return the PIN for player linking (or ``False``/``None``)."""
        return self.pin

    def is_sp_registered_with_sn(self) -> Optional[bool]:
        """Check SP registration with SN (legacy, mostly stub)."""
        if self._comet is None:
            log.info("not registered: no comet")
            return None
        client_id = getattr(self._comet, "client_id", None)
        if client_id is None:
            log.info("not registered: no clientId")
            return None
        if isinstance(client_id, str) and client_id[:2] == "1X":
            log.debug("not registered: %s", client_id)
            return False
        log.debug("registered: %s", client_id)
        return True

    def linked(self, pin: Any) -> None:
        """
        Called once the server or player are linked on SqueezeNetwork.
        """
        if self.pin == pin:
            self.pin = False

        for player in self.players.values():
            if hasattr(player, "get_pin") and player.get_pin() == pin:
                player.clear_pin()

    # ------------------------------------------------------------------
    # Artwork fetching
    # ------------------------------------------------------------------

    def artwork_thumb_cached(
        self,
        icon_id: str,
        size: str,
        img_format: Optional[str] = None,
    ) -> bool:
        """Return ``True`` if artwork for the given icon/size is cached."""
        cache_key = f"{icon_id}@{size}/{img_format or ''}"
        return self.artwork_cache.get(cache_key) is not None

    def cancel_artwork(self, icon: Any) -> None:
        """Cancel loading artwork for the given icon widget."""
        if icon is not None:
            try:
                if icon.get_image():
                    icon.set_value(None)
            except Exception as exc:
                log.warning("cancel_artwork: error clearing icon image: %s", exc)
            self.artwork_thumb_icons.pop(icon, None)

    def cancel_all_artwork(self) -> None:
        """Cancel all pending artwork fetches."""
        for entry in self.artwork_fetch_queue:
            cache_key = entry.get("key")
            if cache_key:
                self.artwork_cache.set(cache_key, None)

                for icon, key in list(self.artwork_thumb_icons.items()):
                    if key == cache_key:
                        del self.artwork_thumb_icons[icon]

        self.artwork_fetch_queue = []

    def fetch_artwork(
        self,
        icon_id: str,
        icon: Any = None,
        size: Any = "200",
        img_format: Optional[str] = None,
    ) -> None:
        """
        Fetch artwork for the given icon ID.

        Checks the image cache and artwork cache before making a
        network request.  If the artwork needs fetching, it is queued.

        Parameters
        ----------
        icon_id : str
            The artwork identifier (cover ID, URL, or path).
        icon : widget or None
            The Icon widget to update when artwork arrives.
        size : str or int
            Size specification (e.g., ``"200"``, ``"200x200"``, or ``56``).
            Integers are automatically converted to strings (Lua does
            this implicitly).
        img_format : str or None
            Image format hint (e.g., ``"png"``).
        """
        # Lua auto-converts numbers to strings; Python doesn't.
        size = str(size)
        icon_id = str(icon_id)

        logcache.debug("%s:fetch_artwork(%s, %s, %s)", self, icon_id, size, img_format)

        cache_key = f"{icon_id}@{size}/{img_format or ''}"

        # Check decoded image cache (weak refs)
        image = self.image_cache.get(cache_key)
        if image is not None:
            logcache.debug("..image in cache")
            if image is True:
                # Already being requested
                if icon is not None:
                    _safe_set_value(icon, None)
                    self.artwork_thumb_icons[icon] = cache_key
                return
            else:
                if icon is not None:
                    _safe_set_value(icon, image)
                    self.artwork_thumb_icons.pop(icon, None)
                return

        # Check compressed artwork cache
        artwork = self.artwork_cache.get(cache_key)
        if artwork is not None:
            if artwork is True:
                logcache.debug("..artwork already requested")
                if icon is not None:
                    _safe_set_value(icon, None)
                    self.artwork_thumb_icons[icon] = cache_key
                return
            else:
                logcache.debug("..artwork in cache")
                if icon is not None:
                    image = self._load_artwork_image(cache_key, artwork, size)  # type: ignore[arg-type]
                    _safe_set_value(icon, image)
                    self.artwork_thumb_icons.pop(icon, None)
                return

        # Build the artwork URL
        url = self._build_artwork_url(icon_id, size, img_format)

        # Mark as loading
        self.artwork_cache.set(cache_key, True)
        if icon is not None:
            _safe_set_value(icon, None)
            self.artwork_thumb_icons[icon] = cache_key

        logcache.debug("..fetching artwork")

        # Queue the fetch (LIFO)
        self.artwork_fetch_queue.append(
            {
                "key": cache_key,
                "id": icon_id,
                "url": url,
                "size": size,
            }
        )

        # Wake the fetch task
        if self._artwork_fetch_task is not None:
            try:
                self._artwork_fetch_task.add_task()
            except Exception as exc:
                log.warning("fetch_artwork: could not wake fetch task: %s", exc)

    def _build_artwork_url(
        self,
        icon_id: str,
        size: str,
        img_format: Optional[str] = None,
    ) -> str:
        """
        Build the URL for fetching artwork from the server.

        Handles cover IDs, remote URLs (with imageproxy), contributor
        artwork, and static paths.
        """
        # Parse size specification
        m = re.match(r"(\d+)x(\d+)", size)
        if m:
            size_w = m.group(1)
            size_h = m.group(2)
        else:
            size_w = size
            size_h = size

        resize_frag = f"_{size_w}x{size_h}_m"

        if re.match(r"^[0-9a-fA-F\-]+$", icon_id):
            # Hex digit = coverid or remote track id
            url = f"/music/{icon_id}/cover{resize_frag}"
            if img_format:
                url += f".{img_format}"
        elif icon_id.startswith("http"):
            # Remote URL
            if re.match(r"^http://\d", icon_id) and (
                re.match(r"^http://192\.168", icon_id)
                or re.match(r"^http://172\.16\.", icon_id)
                or re.match(r"^http://10\.", icon_id)
            ):
                # Private IP — use directly
                url = icon_id
            elif self.is_more_recent(self.get_version() or "", "7.8.0"):
                # Use server imageproxy
                from urllib.parse import quote

                url = f"/imageproxy/{quote(icon_id, safe='')}/image{resize_frag}"
            else:
                url = icon_id
        elif icon_id.startswith("contributor/") and "image" in icon_id:
            url = icon_id + resize_frag
        else:
            # Static path with size inserted before extension
            url = re.sub(r"(.+)(\.(?:\w+))$", rf"\1{resize_frag}\2", icon_id)
            if not url.startswith("/"):
                url = "/" + url

        logcache.debug("%s:fetch_artwork(%s => %s)", self, icon_id, url)
        return url

    def _load_artwork_image(self, cache_key: str, chunk: bytes, size: str) -> Optional[Any]:
        """
        Convert raw artwork bytes to a resized Surface.

        Returns the Surface or ``None`` on error.
        """
        try:
            from jive.ui.surface import Surface

            image = Surface.load_image_data(chunk, len(chunk))
            w, h = image.get_size()

            if w == 0 or h == 0:
                self.image_cache[cache_key] = True
                return None

            # Parse size
            m = re.match(r"(\d+)x(\d+)", size)
            if m:
                size_w = int(m.group(1))
                size_h = int(m.group(2))
            else:
                size_w = int(size)
                size_h = int(size)

            if w != size_w and h != size_h:
                image = image.resize(size_w, size_h, True)

            self.image_cache[cache_key] = image
            return image

        except Exception as exc:
            logcache.error("Failed to load artwork: %s", exc)
            return None

    def process_artwork_queue(self) -> None:
        """
        Process the artwork fetch queue (non-generator convenience wrapper).

        Drains up to 4 concurrent entries from the queue.  Called by
        the generator task ``_process_artwork_queue_gen`` but can also
        be invoked directly.
        """
        self._drain_artwork_queue()

    def _drain_artwork_queue(self) -> None:
        """Drain artwork queue entries up to the concurrency limit."""
        while self.artwork_fetch_count < 4 and self.artwork_fetch_queue:
            entry = self.artwork_fetch_queue.pop()
            url = entry.get("url", "")
            cache_key = entry.get("key", "")
            size = entry.get("size", "200")

            logcache.debug("Processing artwork: %s", cache_key)

            sink = self._get_artwork_thumb_sink(cache_key, size, url)

            try:
                from jive.net.request_http import RequestHttp

                req = RequestHttp(sink, "GET", url)

                if url.startswith("http"):
                    # Remote server
                    from jive.net.socket_http import SocketHttp

                    uri = req.get_uri()
                    http = SocketHttp(
                        self.jnt,
                        uri.get("host"),  # type: ignore[arg-type]
                        uri.get("port"),  # type: ignore[arg-type]
                        uri.get("host"),  # type: ignore[arg-type]
                    )
                    http.fetch(req)
                elif self._artwork_pool:
                    self._artwork_pool.queue(req)
                else:
                    log.error(
                        "Server %s cannot handle artwork for %s",
                        self.name,
                        url,
                    )
                    self.artwork_fetch_count -= 1

                self.artwork_fetch_count += 1

            except Exception as exc:
                log.error("Error processing artwork %s: %s", cache_key, exc, exc_info=True)

    def _get_artwork_thumb_sink(self, cache_key: str, size: str, url: str) -> Callable[..., None]:
        """Build a sink for artwork data."""

        def sink(chunk: Any = None, err: Any = None, request: Any = None) -> None:
            if err or chunk:
                self.artwork_fetch_count = max(0, self.artwork_fetch_count - 1)
                if self._artwork_fetch_task:
                    try:
                        self._artwork_fetch_task.add_task()
                    except Exception as exc:
                        log.warning(
                            "_get_artwork_thumb_sink: could not wake fetch task: %s",
                            exc,
                        )

            if err:
                logcache.debug("_get_artwork_thumb_sink(%s) error: %s", url, err)
                return

            if chunk:
                logcache.debug("_get_artwork_thumb_sink(%s, %s)", url, size)

                # Store compressed artwork
                self.artwork_cache.set(cache_key, chunk)

                # Decode and resize
                image = self._load_artwork_image(cache_key, chunk, size)

                # Update waiting icons
                for icon, key in list(self.artwork_thumb_icons.items()):
                    if key == cache_key:
                        _safe_set_value(icon, image)
                        del self.artwork_thumb_icons[icon]

        return sink

    # ------------------------------------------------------------------
    # App parameters
    # ------------------------------------------------------------------

    def get_app_parameters(self, app_type: str) -> Optional[Dict[str, Any]]:
        """Get app-specific parameters."""
        if not self.app_parameters:
            return None
        return self.app_parameters.get(app_type)

    def set_app_parameter(self, app_type: str, parameter: str, value: Any) -> None:
        """Set an app-specific parameter."""
        log.debug("Setting %s parameter %s to: %s", app_type, parameter, value)
        if app_type not in self.app_parameters:
            self.app_parameters[app_type] = {}
        self.app_parameters[app_type][parameter] = value

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"SlimServer({self.id!r})"

    def __str__(self) -> str:
        return f"SlimServer {{{self.name or self.id}}}"

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_version(self) -> Optional[str]:
        """Return the server version string."""
        return self.state.get("version")

    def is_compatible(self) -> Optional[bool]:
        """
        Return ``True`` if the server is compatible with this client,
        ``False`` if an upgrade is needed, or ``None`` if unknown.
        """
        if self.is_squeeze_network():
            return True

        version = self.state.get("version")
        if not version:
            return None

        return self.is_more_recent(version, _minimum_version)

    @staticmethod
    def is_more_recent(new: str, old: str) -> bool:
        """
        Compare two version strings (dotted numeric).

        Returns ``True`` if *new* is strictly more recent than *old*.
        """
        new_parts = new.split(".")
        old_parts = old.split(".")

        for i, part in enumerate(new_parts):
            old_val = int(old_parts[i]) if i < len(old_parts) else 0
            try:
                new_val = int(part)
            except ValueError:
                new_val = 0
            if new_val > old_val:
                return True
            if new_val < old_val:
                return False

        return False

    @classmethod
    def set_minimum_version(cls, min_version: str) -> None:
        """Set the minimum useable server version."""
        global _minimum_version
        _minimum_version = min_version

    def get_ip_port(self) -> Tuple[Any, Any]:
        """Return ``(ip, port)``."""
        return self.ip, self.port

    def get_name(self) -> str:
        """Return the server name."""
        return self.name

    def get_id(self) -> str:
        """Return the server ID."""
        return self.id

    def get_last_seen(self) -> int:
        """Return the timestamp of the last server indication."""
        return self.last_seen

    def is_connected(self) -> bool:
        """Return ``True`` if the Comet connection is established."""
        return self.netstate == "connected"

    def is_password_protected(self) -> Tuple[bool, Optional[str]]:
        """Return ``(True, realm)`` if a password is needed."""
        if self.realm and self.netstate != "connected":
            return True, self.realm
        return False, None

    def get_upgrade_url(self) -> Tuple[Any, bool]:
        """Return ``(upgrade_url, force_flag)``."""
        return self.upgrade_url, self.upgrade_force

    def all_players(self) -> Iterator[Tuple[str, Any]]:
        """Iterate over all players on this server."""
        yield from self.players.items()

    # ------------------------------------------------------------------
    # User requests
    # ------------------------------------------------------------------

    def user_request(self, func: Optional[Callable[..., None]], *args: Any) -> Optional[Any]:
        """
        Send a user-initiated request.

        If not connected, attempts to reconnect and sends WOL.
        """
        if self.netstate != "connected":
            self.wake_on_lan()
            self.connect()

        req_record: Dict[str, Any] = {"func": func, "args": args}
        self.user_requests.append(req_record)

        def wrapper_callback(*cb_args: Any, **cb_kwargs: Any) -> None:
            if req_record in self.user_requests:
                self.user_requests.remove(req_record)
            if func:
                func(*cb_args, **cb_kwargs)

        req_id = self.comet.request(wrapper_callback, *args)
        req_record["comet_request_id"] = req_id
        return req_id

    def remove_all_user_requests(self) -> None:
        """Remove all pending user requests."""
        for req_record in self.user_requests:
            req_id = req_record.get("comet_request_id")
            if req_id is not None:
                try:
                    self.comet.remove_request(req_id)
                except Exception:
                    log.warn("Couldn't remove request")
        self.user_requests = []

    def request(self, *args: Any) -> None:
        """Send a background (non-user) request."""
        self.comet.request(*args)

    # Lua-compatible camelCase aliases
    userRequest = user_request
    fetchArtwork = fetch_artwork
    artworkThumbCached = artwork_thumb_cached
    cancelArtwork = cancel_artwork
    cancelAllArtwork = cancel_all_artwork
    processArtworkQueue = process_artwork_queue
    getVersion = get_version
    isMoreRecent = is_more_recent
    isSqueezeNetwork = is_squeeze_network
    getAppParameters = get_app_parameters
    setAppParameter = set_app_parameter
    getCurrentServer = get_current_server
    setCurrentServer = set_current_server
    removeAllUserRequests = remove_all_user_requests
    updateAddress = update_address


# ===================================================================
# Module-level helpers
# ===================================================================


def _to_bool(value: Any) -> bool:
    """Convert a Lua-style value to Python bool."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    try:
        return int(value) == 1
    except (ValueError, TypeError):
        return bool(value)


def _to_int(value: Any, default: int = 0) -> int:
    """Convert to int with a default."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _process_artwork_queue_gen(server: "SlimServer") -> Any:
    """Generator task function for artwork fetching.

    Mirrors Lua ``processArtworkQueue`` — runs in an infinite loop,
    drains the queue each time it is woken via ``addTask()``, then
    yields ``False`` to suspend until woken again.
    """
    while True:
        server._drain_artwork_queue()
        yield False  # suspend until addTask() wakes us


def _safe_set_value(icon: Any, image: Any) -> None:
    """Safely call ``icon.set_value(image)`` if the method exists.

    After setting the value, marks the parent Group and grandparent
    Menu for re-layout so the new artwork size is picked up and the
    widget is redrawn immediately.
    """
    setter = getattr(icon, "set_value", None) or getattr(icon, "setValue", None)
    if setter and callable(setter):
        try:
            setter(image)
            # Walk up: Icon → Group (parent) → Menu (grandparent).
            # re_layout() is needed (not just re_draw()) because the
            # icon size changes from 0x0 to e.g. 72x72 and the Group
            # must recalculate child positions.
            parent = getattr(icon, "parent", None)
            if parent is not None and hasattr(parent, "re_layout"):
                parent.re_layout()
                grandparent = getattr(parent, "parent", None)
                if grandparent is not None and hasattr(grandparent, "re_layout"):
                    grandparent.re_layout()
        except Exception as exc:
            log.warning("_safe_set_value: error setting icon value: %s", exc)


def reset_server_globals() -> None:
    """
    Reset all module-level server state.

    **For testing only** — clears all server registries.
    """
    global _current_server, _last_current_server, _last_server_switch_t
    _server_ids.clear()
    _server_list.clear()
    _current_server = None
    _last_current_server = None
    _last_server_switch_t = None
    _locally_requested_servers.clear()
    _credentials.clear()
