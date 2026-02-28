"""
applets.SlimDiscovery.SlimDiscoveryApplet — Server/player discovery.

Ported from ``applets/SlimDiscovery/SlimDiscoveryApplet.lua`` in the
original jivelite Lua project.

SlimDiscovery manages the lifecycle of server and player discovery:

States
------
- **disconnected** — no connections, no scanning.
- **searching** — not connected to a player; connects to all servers
  and scans for players.
- **connected** — connected to the current player's server; background
  UDP scanning continues for the server list.
- **probing_player** — connected, but probing all servers to refresh
  the player list (e.g. for the choose-player screen).
- **probing_server** — connected, but probing all servers to refresh
  the server list.

The applet sends UDP broadcast packets (port 3483) using the TLV
discovery protocol and parses the responses to create/update
``SlimServer`` singletons.

Services registered (via Meta):

- ``getCurrentPlayer`` / ``setCurrentPlayer``
- ``discoverPlayers`` / ``discoverServers``
- ``connectPlayer`` / ``disconnectPlayer``
- ``iteratePlayers`` / ``iterateSqueezeCenters`` / ``countPlayers``
- ``getPollList`` / ``setPollList``
- ``getInitialSlimServer``

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import struct
import time
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Tuple,
)

from jive.applet import Applet
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.net.network_thread import NetworkThread
    from jive.slim.player import Player
    from jive.slim.slim_server import SlimServer

__all__ = ["SlimDiscoveryApplet"]

log = logger("applet.SlimDiscovery")


# ── Constants ────────────────────────────────────────────────────────────
PORT = 3483  # UDP port used to discover servers
DISCOVERY_TIMEOUT = 120000  # ms before removing stale servers/players
DISCOVERY_PERIOD = 60000  # ms between discoveries (connected state)
SEARCHING_PERIOD = 10000  # ms between discoveries (searching state)

# Valid state names
_VALID_STATES = frozenset(
    {
        "disconnected",
        "searching",
        "connected",
        "probing_player",
        "probing_server",
    }
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _get_ticks() -> int:
    """Return monotonic milliseconds (matches Framework.get_ticks)."""
    try:
        from jive.ui.framework import Framework

        return Framework.get_ticks()
    except Exception:
        return int(time.monotonic() * 1000)


def _get_applet_manager() -> Any:
    """Return the global AppletManager, or ``None``."""
    try:
        from jive.jive_main import jive_main as _jm

        if _jm is not None:
            return getattr(_jm, "applet_manager", None)
    except ImportError:
        pass
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


def _get_jive_main() -> Any:
    """Return the JiveMain singleton, or ``None``."""
    try:
        from jive.jive_main import jive_main as _jm

        return _jm
    except ImportError:
        return None


def _get_system() -> Any:
    """Return the System singleton, or ``None``."""
    try:
        from jive.system import System

        return System.instance()
    except Exception:
        return None


# ── Discovery packet construction ────────────────────────────────────────


def _slim_discovery_source() -> bytes:
    """
    Build a TLV discovery request packet.

    Mirrors the Lua ``_slimDiscoverySource()`` function.  The packet
    begins with ``b'e'`` (new-style TLV discovery) followed by TLV
    entries requesting server information.

    TLV tags requested:

    - ``IPAD`` — IP address of server
    - ``NAME`` — name of server
    - ``JSON`` — JSON-RPC port
    - ``VERS`` — version string
    - ``UUID`` — server UUID
    - ``JVID`` — our device ID (6 bytes, placeholder)
    """
    parts: list[bytes] = [
        b"e",
        # IPAD — request IP address (length 0 = request)
        b"IPAD\x00",
        # NAME — request server name
        b"NAME\x00",
        # JSON — request JSON-RPC port
        b"JSON\x00",
        # VERS — request version
        b"VERS\x00",
        # UUID — request UUID
        b"UUID\x00",
        # JVID — our device ID (length 6 + 6 data bytes)
        b"JVID\x06\x12\x34\x56\x78\x12\x34",
    ]
    return b"".join(parts)


def _parse_tlv_response(data: bytes) -> Dict[str, str]:
    """
    Parse a TLV discovery response (starts with ``b'E'``).

    Returns a dict mapping tag names to decoded string values.
    """
    result: Dict[str, str] = {}
    ptr = 1  # skip the leading 'E'
    datalen = len(data)

    while ptr <= datalen - 5:
        tag = data[ptr : ptr + 4].decode("ascii", errors="replace")
        length = data[ptr + 4]
        value_bytes = data[ptr + 5 : ptr + 5 + length]
        ptr += 5 + length

        if tag and length >= 0:
            try:
                result[tag] = value_bytes.decode("utf-8", errors="replace")
            except Exception:
                result[tag] = value_bytes.hex()

    return result


# ══════════════════════════════════════════════════════════════════════════
# SlimDiscoveryApplet
# ══════════════════════════════════════════════════════════════════════════


class SlimDiscoveryApplet(Applet):
    """
    Discovers Lyrion Music Servers and manages the current player.

    This is the central applet for server/player lifecycle management.
    It sends periodic UDP broadcasts, processes responses, and
    transitions through a state machine that determines how aggressively
    it scans the network.
    """

    @property
    def applet_name(self) -> str:
        """Return the applet name from the manager entry, or a default."""
        if self._entry is not None:
            return self._entry.get("applet_name", "SlimDiscovery")
        return "SlimDiscovery"

    def __init__(self) -> None:
        super().__init__()

        # Poll list: list of broadcast/unicast addresses to probe.
        # Populated from ChooseMusicSource settings or defaults.
        self.poll: List[str] = ["255.255.255.255"]

        # UDP socket for discovery
        self.socket: Any = None

        # Discovery timer
        self.timer: Any = None

        # Wireless interface (optional, for player scanning)
        self.wireless: Any = None

        # Current state
        self.state: str = "searching"

        # Probing timeout (ticks)
        self.probe_until: int = 0

    # ------------------------------------------------------------------
    # Applet lifecycle
    # ------------------------------------------------------------------

    def init(self, **kwargs: Any) -> "SlimDiscoveryApplet":
        """
        Initialise the applet — called after loading.

        Creates the UDP socket, the discovery timer, and starts the
        initial discovery cycle.
        """
        # Try to get poll list from ChooseMusicSource settings
        mgr = _get_applet_manager()
        if mgr is not None:
            try:
                cms = mgr.load_applet("ChooseMusicSource")
                if cms is not None:
                    cms_settings = (
                        cms.get_settings() if hasattr(cms, "get_settings") else {}
                    )
                    if "poll" in cms_settings:
                        self.poll = cms_settings["poll"]
            except Exception:
                pass  # ChooseMusicSource may not be available

        # If poll list is still empty, ensure we at least broadcast
        if not self.poll:
            self.poll = ["255.255.255.255"]

        # Create the UDP socket
        jnt = _get_jnt()
        try:
            from jive.net.socket_udp import SocketUdp

            self.socket = SocketUdp(
                jnt,
                lambda chunk, err=None: self._slim_discovery_sink(chunk, err),
                "SlimDiscovery",
            )
        except Exception as exc:
            log.error("Failed to create discovery UDP socket: %s", exc)

        # Create the discovery timer
        try:
            from jive.ui.timer import Timer

            self.timer = Timer(
                DISCOVERY_PERIOD,
                lambda: self._discover(),
            )
        except Exception as exc:
            log.error("Failed to create discovery timer: %s", exc)

        # Initial state
        self.state = "searching"

        # Start discovering after a short delay (2s) to allow settings
        # to be loaded first — matches the Lua original's FIXME comment.
        if self.timer is not None:
            try:
                self.timer.restart(2000)
            except Exception:
                self.timer.start()

        # Subscribe to jnt notifications
        if jnt is not None:
            try:
                jnt.subscribe(self)
            except Exception as exc:
                log.debug("Could not subscribe to jnt: %s", exc)

        return self

    def free(self) -> bool:
        """
        Free the applet — stop timers, close socket, unsubscribe.

        Returns ``True`` to allow freeing.
        """
        if self.timer is not None:
            try:
                self.timer.stop()
            except Exception:
                pass
            self.timer = None

        if self.socket is not None:
            try:
                self.socket.free()
            except Exception:
                pass
            self.socket = None

        jnt = _get_jnt()
        if jnt is not None:
            try:
                jnt.unsubscribe(self)
            except Exception:
                pass

        return True

    # ------------------------------------------------------------------
    # Discovery sink — processes incoming UDP responses
    # ------------------------------------------------------------------

    def _slim_discovery_sink(
        self,
        chunk: Optional[Dict[str, Any]],
        err: Optional[str] = None,
    ) -> None:
        """
        Process an incoming UDP discovery response.

        Mirrors the Lua ``_slimDiscoverySink``.  Expects *chunk* to be
        a dict with ``data``, ``ip``, ``port`` keys (as delivered by
        ``SocketUdp``).
        """
        log.debug("_slim_discovery_sink()")

        if err:
            log.error("UDP discovery error: %s", err)
            return

        if not chunk or "data" not in chunk:
            log.error("bad udp packet?")
            return

        data: bytes = chunk["data"]
        if isinstance(data, str):
            data = data.encode("latin-1")

        # Only process TLV responses (leading 'E')
        if not data or data[0:1] != b"E":
            return

        ip: str = chunk.get("ip", "")

        # Parse TLV fields
        tlvs = _parse_tlv_response(data)

        name = tlvs.get("NAME")
        ipad = tlvs.get("IPAD", ip)
        json_port = tlvs.get("JSON")
        version = tlvs.get("VERS")
        uuid = tlvs.get("UUID")

        if name and ipad and json_port:
            if not uuid:
                uuid = name

            try:
                from jive.slim.slim_server import SlimServer

                jnt = _get_jnt()
                server = SlimServer(jnt, uuid, name, version)
                self._server_update_address(server, ipad, json_port, name)
            except Exception as exc:
                log.error("Failed to process discovery response: %s", exc)

    # ------------------------------------------------------------------
    # Server address update
    # ------------------------------------------------------------------

    def _server_update_address(
        self,
        server: Any,
        ip: str,
        port: Any,
        name: str,
    ) -> None:
        """
        Update a server's address and conditionally connect.

        Mirrors Lua ``_serverUpdateAddress``.
        """
        try:
            server.update_address(ip, port, name)
        except Exception as exc:
            log.error("server.update_address failed: %s", exc)

        if self.state in ("searching", "probing_player", "probing_server"):
            try:
                server.connect()
            except Exception as exc:
                log.debug("server.connect() failed: %s", exc)

    # ------------------------------------------------------------------
    # Wireless scan callback
    # ------------------------------------------------------------------

    def _scan_complete(self, scan_table: Dict[str, Any]) -> None:
        """
        Process results from a wireless network scan.

        Looks for Squeezebox SSIDs and registers corresponding players.
        """
        try:
            from jive.slim.player import Player
        except ImportError:
            return

        jnt = _get_jnt()

        for ssid, entry in scan_table.items():
            player_id = Player.ssid_is_squeezebox(ssid)
            if player_id:
                player = Player(jnt, player_id)
                last_scan = entry.get("lastScan", 0) if isinstance(entry, dict) else 0
                try:
                    player.update_ssid(ssid, last_scan)
                except Exception as exc:
                    log.debug("update_ssid failed: %s", exc)

    # ------------------------------------------------------------------
    # Cleanup routines
    # ------------------------------------------------------------------

    def _squeeze_center_cleanup(self) -> None:
        """
        Remove servers that have not been seen for ``DISCOVERY_TIMEOUT`` ms.

        Keeps the last-known remote server in the list so the user can
        still send Wake-on-LAN to it (Bug 14972).
        """
        now = _get_ticks()
        settings = self.get_settings()

        try:
            from jive.slim.slim_server import SlimServer
        except ImportError:
            return

        for _id, server in list(SlimServer.iterate()):
            try:
                is_conn = (
                    server.is_connected() if hasattr(server, "is_connected") else False
                )
                last_seen = (
                    server.get_last_seen() if hasattr(server, "get_last_seen") else now
                )

                if not is_conn and (now - last_seen) > DISCOVERY_TIMEOUT:
                    # Preserve last-known remote SC for WoL
                    s_id = getattr(server, "id", None)
                    s_name = getattr(server, "name", None)
                    s_mac = getattr(server, "mac", None)

                    if (
                        s_id == settings.get("serverUuid")
                        and s_name == settings.get("serverName")
                        and s_mac is not None
                    ):
                        log.debug(
                            "SC cleanup: Leave last known remote SC in list: %s",
                            server,
                        )
                    else:
                        log.debug("SC cleanup: Removing server %s", server)
                        server.free()
            except Exception as exc:
                log.debug("cleanup error for server: %s", exc)

    def _player_cleanup(self) -> None:
        """
        Remove unconfigured players not seen for ``DISCOVERY_TIMEOUT`` ms.

        Never removes the current player.
        """
        now = _get_ticks()

        try:
            from jive.slim.player import Player
        except ImportError:
            return

        current_player = Player.get_current_player()

        for _id, player in list(Player.iterate()):
            try:
                has_server = (
                    player.get_slim_server() is not None
                    if hasattr(player, "get_slim_server")
                    else False
                )
                last_seen = (
                    player.get_last_seen() if hasattr(player, "get_last_seen") else now
                )

                if (
                    not has_server
                    and current_player is not player
                    and (now - last_seen) > DISCOVERY_TIMEOUT
                ):
                    log.debug("Removing player %s", player)
                    player.free(False)
            except Exception as exc:
                log.debug("cleanup error for player: %s", exc)

    # ------------------------------------------------------------------
    # Main discovery cycle
    # ------------------------------------------------------------------

    def _discover(self) -> None:
        """
        Run one discovery cycle.

        Sends UDP broadcasts, optionally triggers wireless scanning,
        cleans up stale servers/players, and adjusts the timer period
        based on the current state.
        """
        # Broadcast discovery packets to all addresses in the poll list
        if self.socket is not None:
            for address in self.poll:
                log.debug("sending slim discovery to %s", address)
                try:
                    self.socket.send(_slim_discovery_source, address, PORT)
                except Exception as exc:
                    log.debug("discovery send failed to %s: %s", address, exc)

        # Wireless scanning when probing for players
        if self.state == "probing_player" and self.wireless is not None:
            try:
                self.wireless.scan(lambda scan_table: self._scan_complete(scan_table))
            except Exception:
                pass

        # Cleanup stale entries
        self._squeeze_center_cleanup()
        self._player_cleanup()

        # Check if probing should end
        if self.state in ("probing_player", "probing_server"):
            if _get_ticks() > self.probe_until:
                try:
                    from jive.slim.player import Player

                    current = Player.get_current_player()
                    if current is not None and current.is_connected():
                        self._set_state("connected")
                    else:
                        self._set_state("searching")
                except Exception:
                    self._set_state("searching")

        # Debug output
        if log.is_debug():
            self._debug()

        # Adjust timer period based on state
        if self.timer is not None:
            try:
                if self.state == "connected":
                    self.timer.restart(DISCOVERY_PERIOD)
                else:
                    self.timer.restart(SEARCHING_PERIOD)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _set_state(self, state: str) -> None:
        """
        Transition to a new discovery state.

        Mirrors Lua ``_setState``.
        """
        if state not in _VALID_STATES:
            log.error("unknown state=%s", state)
            return

        if self.state == state:
            # Same state — just restart timer
            if self.timer is not None:
                try:
                    self.timer.restart(0)
                except Exception:
                    pass
            return

        # Restart discovery if we were disconnected
        if self.state == "disconnected" and self.timer is not None:
            try:
                self.timer.restart(0)
            except Exception:
                pass

        self.state = state

        if state == "disconnected":
            if self.timer is not None:
                try:
                    self.timer.stop()
                except Exception:
                    pass
            self._disconnect()

        elif state == "searching":
            if self.timer is not None:
                try:
                    self.timer.restart(0)
                except Exception:
                    pass
            self._connect()

        elif state == "connected":
            self._idle_disconnect()

        elif state in ("probing_player", "probing_server"):
            self.probe_until = _get_ticks() + 60000
            if self.timer is not None:
                try:
                    self.timer.restart(0)
                except Exception:
                    pass
            self._connect()

        if log.is_debug():
            self._debug()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        """Connect to all known servers."""
        try:
            from jive.slim.slim_server import SlimServer

            for _id, server in SlimServer.iterate():
                try:
                    server.connect()
                except Exception as exc:
                    log.debug("connect to %s failed: %s", server, exc)
        except ImportError:
            pass

    def _disconnect(self) -> None:
        """Disconnect from all servers."""
        try:
            from jive.slim.slim_server import SlimServer

            for _id, server in SlimServer.iterate():
                try:
                    server.disconnect()
                except Exception as exc:
                    log.debug("disconnect from %s failed: %s", server, exc)
        except ImportError:
            pass

    def _idle_disconnect(self) -> None:
        """
        Disconnect from idle servers, keeping only the current server
        connected.
        """
        try:
            from jive.slim.slim_server import SlimServer

            current_server = SlimServer.get_current_server()

            for _id, server in SlimServer.iterate():
                try:
                    if server is not current_server:
                        server.set_idle_timeout(30)
                    else:
                        server.set_idle_timeout(0)
                        server.connect()
                except Exception as exc:
                    log.debug("idle_disconnect error for %s: %s", server, exc)
        except ImportError:
            pass

    # ------------------------------------------------------------------
    # Notification handlers
    # ------------------------------------------------------------------

    def notify_playerDisconnected(self, player: Any) -> None:
        """Restart discovery when the current player disconnects."""
        log.debug("playerDisconnected")
        try:
            from jive.slim.player import Player

            if Player.get_current_player() is not player:
                return
        except Exception:
            return

        self._set_state("searching")

    def notify_playerConnected(self, player: Any) -> None:
        """Stop discovery when the current player reconnects."""
        log.debug("playerConnected")
        try:
            from jive.slim.player import Player

            current = Player.get_current_player()
            if current is not player:
                return

            name = player.get_name() if hasattr(player, "get_name") else player
            log.info("connected %s", name)

            self._set_state("connected")

            # Refresh the current player so other applets see the update
            Player.set_current_player(current)
        except Exception as exc:
            log.debug("notify_playerConnected error: %s", exc)

    def notify_serverDisconnected(self, slimserver: Any) -> None:
        """Restart discovery if the current player's server disconnects."""
        log.debug("serverDisconnected %s", slimserver)
        try:
            from jive.slim.player import Player

            current = Player.get_current_player()
            if current is None:
                return

            player_server = (
                current.get_slim_server()
                if hasattr(current, "get_slim_server")
                else None
            )
            if player_server is not slimserver:
                return

            if self.state == "connected":
                self._set_state("searching")
        except Exception:
            pass

    def notify_serverConnected(self, slimserver: Any) -> None:
        """Stop discovery if the current player's server reconnects."""
        log.debug("serverConnected")
        try:
            from jive.slim.player import Player

            current = Player.get_current_player()
            if current is None:
                return

            player_server = (
                current.get_slim_server()
                if hasattr(current, "get_slim_server")
                else None
            )
            if player_server is not slimserver:
                return

            self._set_state("connected")
        except Exception:
            pass

    def notify_networkConnected(self) -> None:
        """Restart discovery on a new network connection."""
        log.debug("networkConnected")

        if self.state == "disconnected":
            return

        if self.state == "connected":
            # Force re-connection to the current player's server
            try:
                from jive.slim.player import Player

                current = Player.get_current_player()
                if current is not None:
                    server = (
                        current.get_slim_server()
                        if hasattr(current, "get_slim_server")
                        else None
                    )
                    if server is not None:
                        server.disconnect()
                        server.connect()
            except Exception:
                pass
        else:
            # Force re-connection to all servers
            self._disconnect()
            self._connect()

    def notify_playerPower(self, player: Any, power: Any) -> None:
        """
        Handle player power notifications.

        On devices with soft-power support, sync the UI power state
        with the player's power state.
        """
        try:
            from jive.slim.player import Player

            if Player.get_current_player() is not player:
                return

            system = _get_system()
            if system is None or not system.has_soft_power():
                return

            log.info("notify_playerPower: %s", power)

            jive_main = _get_jive_main()
            if jive_main is not None:
                if power:
                    jive_main.set_soft_power_state("on", True)
                else:
                    jive_main.set_soft_power_state("off", True)
        except Exception as exc:
            log.debug("notify_playerPower error: %s", exc)

    def notify_playerCurrent(self, player: Any) -> None:
        """
        Handle player-current-changed notification.

        Persists the player and server selection to settings and
        transitions the state machine.
        """
        settings = self.get_settings()
        save_settings = False

        # Player ID
        try:
            player_id: Any = (
                player.get_id() if (player and hasattr(player, "get_id")) else False
            )
        except Exception:
            player_id = False

        if settings.get("playerId") != player_id:
            settings["playerId"] = player_id
            if player and hasattr(player, "get_init"):
                try:
                    settings["playerInit"] = player.get_init()
                except Exception:
                    settings["playerInit"] = None
            # Legacy setting
            settings["currentPlayer"] = player_id
            save_settings = True

        # Server info
        server: Any = None
        if player and hasattr(player, "get_slim_server"):
            try:
                server = player.get_slim_server()
            except Exception:
                pass

        if server:
            try:
                server_init = server.get_init() if hasattr(server, "get_init") else None
                server_ip = (
                    server_init.get("ip") if isinstance(server_init, dict) else None
                )
                settings_ip = (
                    settings.get("serverInit", {}).get("ip")
                    if isinstance(settings.get("serverInit"), dict)
                    else None
                )
                ip_changed = server_ip != settings_ip

                server_mac = (
                    server_init.get("mac") if isinstance(server_init, dict) else None
                )
                settings_mac = (
                    settings.get("serverInit", {}).get("mac")
                    if isinstance(settings.get("serverInit"), dict)
                    else None
                )
                mac_changed = server_mac != settings_mac

                is_sn = (
                    server.is_squeeze_network()
                    if hasattr(server, "is_squeeze_network")
                    else False
                )

                server_name = server.get_name() if hasattr(server, "get_name") else None

                if (
                    settings.get("squeezeNetwork") != is_sn
                    or ip_changed
                    or mac_changed
                    or settings.get("serverName") != server_name
                ):
                    settings["squeezeNetwork"] = is_sn
                    if not is_sn:
                        settings["serverName"] = server_name
                        settings["serverUuid"] = (
                            server.get_id() if hasattr(server, "get_id") else None
                        )
                        settings["serverInit"] = server_init
                    save_settings = True
            except Exception as exc:
                log.debug("notify_playerCurrent server tracking error: %s", exc)

        if save_settings:
            try:
                self.store_settings()
            except Exception as exc:
                log.debug("Failed to store settings: %s", exc)

        # Transition state
        try:
            if player and hasattr(player, "is_connected") and player.is_connected():
                self._set_state("connected")
            else:
                self._set_state("searching")
        except Exception:
            self._set_state("searching")

    def notify_playerNewName(self, player: Any, player_name: str) -> None:
        """
        Persist a changed player name (e.g. the local player was renamed).
        """
        try:
            from jive.slim.player import Player

            if Player.get_current_player() is not player:
                return
        except Exception:
            return

        log.debug("playerNewName: setting new name for the local player")

        settings = self.get_settings()
        old_init = settings.get("playerInit", {})
        model = old_init.get("model") if isinstance(old_init, dict) else None

        settings["playerInit"] = {
            "name": player_name,
            "model": model,
        }

        try:
            self.store_settings()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Service methods
    # ------------------------------------------------------------------

    def getInitialSlimServer(self) -> Any:
        """
        Return the initial SlimServer based on saved settings.

        Looks up the server by name (or ``mysqueezebox.com`` if SN was
        selected).
        """
        settings = self.get_settings()
        server_name = settings.get("serverName")

        if settings.get("squeezeNetwork"):
            server_name = "mysqueezebox.com"

        if server_name:
            try:
                from jive.slim.slim_server import SlimServer

                for _id, server in SlimServer.iterate():
                    name = (
                        server.get_name()
                        if hasattr(server, "get_name")
                        else getattr(server, "name", None)
                    )
                    if name == server_name:
                        log.debug("found initial server: %s", server)
                        return server
            except ImportError:
                pass

        log.debug("could not find initial server")
        return None

    def getCurrentPlayer(self) -> Any:
        """Return the current player (service method)."""
        try:
            from jive.slim.player import Player

            return Player.get_current_player()
        except ImportError:
            return None

    def setCurrentPlayer(self, player: Any) -> None:
        """Set the current player (service method)."""
        name = None
        if player and hasattr(player, "get_name"):
            try:
                name = player.get_name()
            except Exception:
                pass
        log.info("selected %s", name)

        try:
            from jive.slim.player import Player

            Player.set_current_player(player)
        except ImportError:
            pass

    def discoverPlayers(self) -> None:
        """Trigger player discovery (service method)."""
        self._set_state("probing_player")

    def discoverServers(self) -> None:
        """Trigger server discovery (service method)."""
        self._set_state("probing_server")

    def connectPlayer(self) -> None:
        """
        Connect to the current player (service method).

        If the current player is already connected, transitions to
        ``connected`` state; otherwise starts ``searching``.
        """
        try:
            from jive.slim.player import Player

            current = Player.get_current_player()
            if current is not None and current.is_connected():
                self._set_state("connected")
            else:
                self._set_state("searching")
        except Exception:
            self._set_state("searching")

    def disconnectPlayer(self) -> None:
        """
        Disconnect the current player (service method).

        Transitions to ``disconnected`` state and tells the player
        to disconnect from its server.
        """
        self._set_state("disconnected")

        try:
            from jive.slim.player import Player

            current = Player.get_current_player()
            if current is not None:
                current.disconnect_from_server()
        except Exception:
            pass

    def iteratePlayers(self) -> Iterator[tuple[Any, Any]]:
        """Iterate over all known players (service method)."""
        try:
            from jive.slim.player import Player

            return Player.iterate()
        except ImportError:
            return iter(())

    def iterateSqueezeCenters(self) -> Iterator[tuple[Any, Any]]:
        """Iterate over all known servers (service method)."""
        try:
            from jive.slim.slim_server import SlimServer

            return SlimServer.iterate()
        except ImportError:
            return iter(())

    def countPlayers(self) -> int:
        """Return the number of known players (service method)."""
        count = 0
        try:
            from jive.slim.player import Player

            for _ in Player.iterate():
                count += 1
        except ImportError:
            pass
        return count

    def getPollList(self) -> List[str]:
        """Return the current poll address list (service method)."""
        return list(self.poll)

    def setPollList(self, poll: List[str]) -> None:
        """
        Set a new poll address list and restart discovery
        (service method).
        """
        self.poll = list(poll)
        self.discoverPlayers()

    # ------------------------------------------------------------------
    # Debug output
    # ------------------------------------------------------------------

    def _debug(self) -> None:
        """Log the current discovery state for debugging."""
        now = _get_ticks()

        try:
            from jive.slim.player import Player
            from jive.slim.slim_server import SlimServer
        except ImportError:
            log.info("---- (Player/SlimServer not available for debug) ----")
            return

        current_player = Player.get_current_player()

        log.info("----")
        log.info("State: %s", self.state)
        log.info("CurrentPlayer: %s", current_player)
        log.info("CurrentServer: %s", SlimServer.get_current_server())
        log.info("Servers:")
        for _id, server in SlimServer.iterate():
            try:
                name = server.get_name() if hasattr(server, "get_name") else "?"
                ip_port = (
                    server.get_ip_port() if hasattr(server, "get_ip_port") else "?"
                )
                connected = (
                    server.is_connected() if hasattr(server, "is_connected") else "?"
                )
                last_seen = (
                    server.get_last_seen() if hasattr(server, "get_last_seen") else now
                )
                timeout = DISCOVERY_TIMEOUT - (now - last_seen)
                version = (
                    server.get_version() if hasattr(server, "get_version") else "?"
                )
                log.info(
                    "\t%s [%s] connected=%s timeout=%s version=%s",
                    name,
                    ip_port,
                    connected,
                    timeout,
                    version,
                )
            except Exception:
                log.info("\t%s (error reading info)", server)

        log.info("Players:")
        for _id, player in Player.iterate():
            try:
                name = player.get_name() if hasattr(player, "get_name") else "?"
                pid = player.get_id() if hasattr(player, "get_id") else "?"
                uuid = player.get_uuid() if hasattr(player, "get_uuid") else "?"
                pserver = (
                    player.get_slim_server()
                    if hasattr(player, "get_slim_server")
                    else "?"
                )
                connected = (
                    player.is_connected() if hasattr(player, "is_connected") else "?"
                )
                available = (
                    player.is_available() if hasattr(player, "is_available") else "?"
                )
                last_seen = (
                    player.get_last_seen() if hasattr(player, "get_last_seen") else now
                )
                timeout = DISCOVERY_TIMEOUT - (now - last_seen)
                log.info(
                    "\t%s [%s] uuid=%s server=%s connected=%s available=%s timeout=%s",
                    name,
                    pid,
                    uuid,
                    pserver,
                    connected,
                    available,
                    timeout,
                )
            except Exception:
                log.info("\t%s (error reading info)", player)

        log.info("----")

    # ------------------------------------------------------------------
    # Settings persistence helpers
    # ------------------------------------------------------------------

    def get_settings(self) -> Dict[str, Any]:
        """
        Return the applet's settings dict.

        Tries the AppletManager first, falls back to a local dict.
        """
        mgr = _get_applet_manager()
        if mgr is not None:
            try:
                entry = mgr.get_applet_db().get(self.applet_name, {})
                settings = entry.get("settings")
                if settings is not None:
                    return settings
            except Exception:
                pass

        # Fallback: use instance attribute (base Applet sets _settings = None)
        if self._settings is None:
            self._settings = {"currentPlayer": False}
        return self._settings

    # Lua alias
    getSettings = get_settings

    def store_settings(self) -> None:
        """Persist settings via the AppletManager."""
        mgr = _get_applet_manager()
        if mgr is not None:
            try:
                mgr._store_settings(self.applet_name)
            except Exception as exc:
                log.debug("store_settings failed: %s", exc)

    # Lua alias
    storeSettings = store_settings

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"SlimDiscoveryApplet(state={self.state!r}, poll={self.poll!r})"
