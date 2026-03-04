"""
jive.slim.player — Squeezebox / Transporter player representation.

Ported from ``jive/slim/Player.lua`` in the original jivelite project.

The Player class represents a Squeezebox-compatible player (hardware or
software) connected to a Lyrion Music Server (LMS).  It maintains:

* **Identity** — MAC-based player ID, name, model, UUID
* **Connection state** — which SlimServer the player is attached to,
  connected/disconnected status
* **Playback state** — mode (play/pause/stop), track elapsed/duration,
  playlist position, volume, shuffle, repeat
* **Notifications** — fires events through the ``jnt`` (NetworkThread)
  notification bus whenever state changes (playerNew, playerConnected,
  playerModeChange, playerTrackChange, etc.)
* **Commands** — send playback commands to the server via Comet
  (play, pause, stop, volume, seek, playlist navigation, etc.)

Player objects are unique per player-ID (MAC address).  Calling
``Player(jnt, player_id)`` twice with the same *player_id* returns
the **same** object — this is enforced via the module-level
``_player_ids`` weak-value dictionary.

Class-level state:

* ``_player_ids``   — weak dict of all Player instances by ID
* ``_player_list``  — dict of currently active players
* ``_current_player`` — the currently selected player (if any)

Notifications emitted (via ``jnt.notify(...)``):

    playerCurrent, playerNew, playerDelete,
    playerConnected, playerDisconnected,
    playerNewName, playerDigitalVolumeControl,
    playerPower, playerNeedsUpgrade,
    playerModeChange, playerTrackChange,
    playerPlaylistChange, playerShuffleModeChange,
    playerRepeatModeChange, playerPlaylistSize,
    playerTitleStatus, playerAlarmState,
    playerSleepChange, playerLoaded

Usage::

    from jive.slim.player import Player

    player = Player(jnt, "00:04:20:aa:bb:cc")
    player.update_init(server, {"name": "Living Room", "model": "squeezeplay"})

    # After server status arrives:
    player.update_player_info(server, info_dict)

    # Send commands:
    player.toggle_pause()
    player.volume(75)
    player.fwd()

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
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

from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.net.network_thread import NetworkThread
    from jive.slim.slim_server import SlimServer

__all__ = ["Player"]

log = logger("jivelite.player")

# ---------------------------------------------------------------------------
# Device ID / model tables (from Player.lua)
# ---------------------------------------------------------------------------

DEVICE_IDS: Dict[int, str] = {
    2: "squeezebox",
    3: "softsqueeze",
    4: "squeezebox2",
    5: "transporter",
    6: "softsqueeze3",
    7: "receiver",
    8: "squeezeslave",
    9: "controller",
    10: "boom",
    11: "softboom",
    12: "squeezeplay",
}

DEVICE_TYPE: Dict[str, str] = {
    "squeezebox": "ip2k",
    "softsqueeze": "softsqueeze",
    "squeezebox2": "ip3k",
    "squeezebox3": "ip3k",
    "transporter": "ip3k",
    "softsqueeze3": "softsqueeze",
    "receiver": "ip3k",
    "squeezeslave": "squeezeslave",
    "controller": "squeezeplay",
    "boom": "ip3k",
    "softboom": "softsqueeze",
    "squeezeplay": "squeezeplay",
}

# Minimum interval between repeated key/button commands (ms)
MIN_KEY_INT: int = 150


# ---------------------------------------------------------------------------
# Module-level player registries
# ---------------------------------------------------------------------------

# Weak-value dict: enforces one Player instance per player-ID.
# When no strong references remain, the entry is automatically removed.
_player_ids: Dict[str, "Player"] = {}
# Ensure _player_ids uses weak values (approximation — see __init__)
# Python's weakref.WeakValueDictionary can't hold arbitrary objects,
# but our Player objects are normal classes, so this works fine.
_player_ids_weak: weakref.WeakValueDictionary[str, "Player"] = (
    weakref.WeakValueDictionary()
)

# Active players (strong references, removed explicitly via free())
_player_list: Dict[str, "Player"] = {}

# Currently selected player
_current_player: Optional["Player"] = None


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


# ---------------------------------------------------------------------------
# Helper: _whats_playing
# ---------------------------------------------------------------------------


def _whats_playing(
    data: Dict[str, Any],
) -> Tuple[Optional[str], Optional[Any]]:
    """
    Extract the current-track identifier and artwork from a player
    status structure.

    Returns
    -------
    (whats_playing, artwork)
        *whats_playing* is a string track-id (or descriptive text),
        *artwork* is an icon-id or icon URL, or ``None``.
    """
    whats_playing: Optional[str] = None
    artwork: Optional[Any] = None

    item_loop = data.get("item_loop")
    if item_loop and len(item_loop) > 0:
        item = item_loop[0]
        params = item.get("params") if isinstance(item, dict) else None

        if params and isinstance(params, dict):
            track_id = params.get("track_id")
            if track_id is not None and not data.get("remote"):
                whats_playing = str(track_id)
            elif (
                item.get("text")
                and data.get("remote")
                and isinstance(data.get("current_title"), str)
            ):
                whats_playing = str(item["text"]) + "\n" + str(data["current_title"])
            elif item.get("text"):
                whats_playing = str(item["text"])
        elif isinstance(item, dict) and item.get("text"):
            whats_playing = str(item["text"])

        if isinstance(item, dict):
            artwork = item.get("icon-id") or item.get("icon")

    return whats_playing, artwork


def _format_show_briefly_text(msg: Any) -> str:
    """
    Format a showBriefly text message.

    Handles both ``\\n`` instructions within a string and adding
    newlines between list elements.
    """
    if isinstance(msg, str):
        parts = msg.split("\\n")
        return "\n".join(parts)

    if isinstance(msg, (list, tuple)):
        # Keep only str/int elements
        filtered = [str(v) for v in msg if isinstance(v, (str, int, float))]
        text = "\n".join(filtered)
        # Split on literal backslash-n sequences
        parts = text.split("\\n")
        return "\n".join(parts)

    return str(msg) if msg is not None else ""


# ===================================================================
# Player class
# ===================================================================


class Player:
    """
    Represents a Squeezebox / Transporter player.

    Parameters
    ----------
    jnt : NetworkThread or None
        The network-thread coordinator (notification bus).
    player_id : str
        The player identifier (typically a MAC address).

    Notes
    -----
    Calling ``Player(jnt, id)`` with the same *player_id* returns the
    existing instance — only one Player object per ID is ever created.
    """

    # ------------------------------------------------------------------
    # Construction (singleton-per-ID)
    # ------------------------------------------------------------------

    def __new__(
        cls, jnt: Optional[NetworkThread] = None, player_id: str = ""
    ) -> Player:
        """Enforce one instance per player_id."""
        pid = player_id.lower()
        existing = _player_ids_weak.get(pid)
        if existing is not None and type(existing) is cls:
            return existing
        instance = super().__new__(cls)
        return instance

    def __init__(
        self,
        jnt: Optional[NetworkThread] = None,
        player_id: str = "",
    ) -> None:
        pid = player_id.lower()

        # Guard against re-initialising an existing instance
        if hasattr(self, "_initialised") and self._initialised:
            return

        self._initialised: bool = True

        self.jnt: Optional[NetworkThread] = jnt
        self.id: str = pid

        # Server this player is connected to (False = none)
        self.slim_server: Any = False  # SlimServer | False
        self.config: Any = False
        self.last_seen: int = 0

        # Info dict from server (name, model, connected, power, …)
        self.info: Dict[str, Any] = {}

        # Player state from server (full status blob)
        self.state: Dict[str, Any] = {}
        self.mode: str = "off"

        self.is_on_stage: bool = False

        # Popup state holders (stubs — full UI wiring happens later)
        self.mixed_popup: Dict[str, Any] = {}
        self.popup_info: Dict[str, Any] = {}
        self.popup_icon: Dict[str, Any] = {}

        # Browse history
        self.browse_history: Dict[str, Any] = {}

        # Track timing
        self.rate: Optional[float] = None
        self.track_seen: Optional[float] = None
        self.track_correction: float = 0.0
        self.track_time: Optional[float] = None
        self.track_duration: Optional[float] = None

        # Playlist
        self.playlist_size: Optional[int] = None
        self.playlist_current_index: Optional[int] = None
        self.playlist_timestamp: Optional[Any] = None

        # Now-playing tracking
        self.now_playing: Optional[str] = None
        self.now_playing_artwork: Optional[Any] = None

        # Presets
        self.defined_presets: Optional[Any] = None

        # Alarm state
        self.alarm_state: Optional[str] = None
        self.alarm_next: Optional[float] = None
        self.alarm_snooze_seconds: Optional[int] = None
        self.alarm_timeout_seconds: Optional[int] = None
        self.alarm_version: Optional[int] = None
        self.alarm_next2: Optional[float] = None
        self.alarm_repeat: Optional[int] = None
        self.alarm_days: Optional[str] = None

        # Volume rate-limiting
        self.mixer_to: Optional[int] = None

        # Button rate-limiting
        self.button_to: Optional[int] = None

        # Waiting-to-play flag (Bug 15814)
        self.waiting_to_play: bool = False

        # Server-refresh flag
        self.server_refresh_in_progress: bool = False

        # Register in the weak dict
        _player_ids_weak[self.id] = self

    # ------------------------------------------------------------------
    # Class-level iteration / current-player
    # ------------------------------------------------------------------

    @classmethod
    def iterate(cls) -> Iterator[Tuple[str, "Player"]]:
        """Iterate over all active players as ``(id, player)`` pairs."""
        yield from _player_list.items()

    @classmethod
    def get_current_player(cls) -> Optional["Player"]:
        """Return the currently selected player (or ``None``)."""
        return _current_player

    @classmethod
    def set_current_player(cls, player: Optional["Player"]) -> None:
        """
        Set the currently selected player and update the current server.

        Fires ``playerCurrent`` notification.
        """
        global _current_player

        last_current = _current_player
        _current_player = player

        # Lazy import to avoid circular deps
        from jive.slim.slim_server import SlimServer

        SlimServer.set_current_server(
            player.slim_server if player and player.slim_server else None
        )

        # If the old current player is no longer active, free it
        if last_current is not None and last_current.last_seen == 0:
            last_current.free()

        # Notify (even if unchanged — matches Lua behaviour)
        if last_current is not None and last_current.jnt is not None:
            last_current.jnt.notify("playerCurrent", _current_player)
        elif player is not None and player.jnt is not None:
            player.jnt.notify("playerCurrent", _current_player)

    @classmethod
    def is_local(cls) -> bool:
        """Class-level check — base Player is never local."""
        return False

    @classmethod
    def get_rate_limit_time(cls) -> int:
        """Return the minimum interval (ms) between repeated commands."""
        return MIN_KEY_INT

    @classmethod
    def get_local_player(cls) -> Optional["Player"]:
        """Return the first local player found, or ``None``."""
        for player in _player_list.values():
            if player.is_local_player():
                return player
        return None

    # ------------------------------------------------------------------
    # Instance identity helpers
    # ------------------------------------------------------------------

    def is_local_player(self) -> bool:
        """Return ``True`` if this is a LocalPlayer."""
        return False

    def get_last_squeeze_center(self) -> Optional[Any]:
        """Not used for remote players."""
        return None

    # ------------------------------------------------------------------
    # Browse history
    # ------------------------------------------------------------------

    def set_last_browse_index(self, key: str, index: int) -> None:
        browse = self.get_last_browse(key)
        if browse is None:
            browse = {}
            self.browse_history[key] = browse
        browse["index"] = index

    def get_last_browse_index(self, key: str) -> Optional[int]:
        browse = self.get_last_browse(key)
        return browse.get("index") if browse else None

    def get_last_browse(self, key: str) -> Optional[Dict[str, Any]]:
        return self.browse_history.get(key)

    def set_last_browse(self, key: str, last_browse: Optional[Dict[str, Any]]) -> None:
        if self.browse_history is None:
            return
        if last_browse is None:
            self.browse_history.pop(key, None)
        else:
            self.browse_history[key] = last_browse

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def update_init(
        self,
        slim_server: Optional[Any],
        init: Dict[str, Any],
    ) -> None:
        """
        Initialise player on start-up with a name, model, and
        optionally attach to a server.
        """
        self.info["name"] = init.get("name")
        self.info["model"] = init.get("model")
        self.info["connected"] = False

        self.last_seen = 0  # don't timeout
        _player_list[self.id] = self

        if slim_server:
            log.debug("%s new for %s", self, slim_server)
            self.slim_server = slim_server
            self.slim_server._add_player(self)

    def get_init(self) -> Dict[str, Any]:
        """Return the state needed for ``update_init``."""
        return {
            "name": self.info.get("name"),
            "model": self.info.get("model"),
        }

    def set_server_refresh_in_progress(self, value: bool) -> None:
        self.server_refresh_in_progress = value

    # ------------------------------------------------------------------
    # updatePlayerInfo  (from serverstatus)
    # ------------------------------------------------------------------

    def update_player_info(
        self,
        slim_server: Any,
        player_info: Dict[str, Any],
        use_sequence_number: bool = False,
        is_sequence_number_in_sync: bool = True,
    ) -> None:
        """
        Update the player with fresh data from the server.

        Called when ``serverstatus`` data arrives.  Fires appropriate
        notifications for state changes.
        """
        # Ignore updates from a different server if the player is
        # not connected to it
        if (
            self.slim_server is not False
            and self.slim_server is not slim_server
            and not _to_bool(player_info.get("connected"))
        ):
            return

        # Save old info
        old_info = dict(self.info)
        self.info = {}

        # UUID
        uuid_val = player_info.get("uuid")
        if isinstance(uuid_val, str):
            self.info["uuid"] = uuid_val
        elif isinstance(uuid_val, (int, float)):
            self.info["uuid"] = str(int(uuid_val))
        else:
            self.info["uuid"] = None

        # Basic info
        self.config = True
        self.info["name"] = str(player_info.get("name", ""))
        self.info["model"] = str(player_info.get("model", ""))
        self.info["connected"] = _to_bool(player_info.get("connected"))
        self.info["power"] = _to_bool(player_info.get("power"))
        self.info["needs_upgrade"] = _to_bool(player_info.get("player_needs_upgrade"))
        self.info["is_upgrading"] = _to_bool(player_info.get("player_is_upgrading"))
        self.info["pin"] = (
            str(player_info["pin"]) if player_info.get("pin") is not None else None
        )
        self.info["digital_volume_control"] = _to_int_or_none(
            player_info.get("digital_volume_control")
        )
        self.info["use_volume_control"] = _to_int_or_none(
            player_info.get("use_volume_control")
        )

        self.last_seen = _get_ticks()

        # PIN is removed after linking
        if old_info.get("pin") and not player_info.get("pin"):
            self.info["pin"] = None

        # Check: have we changed server?
        if self.server_refresh_in_progress or self.slim_server is not slim_server:
            if self.slim_server is slim_server and self.server_refresh_in_progress:
                log.info("Same server but serverRefreshInProgress: %s", slim_server)

            self.set_server_refresh_in_progress(False)

            # Delete from old server
            if self.slim_server and self.slim_server is not False:
                self.free(self.slim_server)
                # Refresh connected state after free()
                self.info["connected"] = _to_bool(player_info.get("connected"))

            # The player was NOT connected to the new server before
            old_info["connected"] = False

            # Add to new server
            log.debug("%s new for %s", self, slim_server)
            self.slim_server = slim_server
            self.slim_server._add_player(self)

            # Update current server
            if _current_player is self:
                from jive.slim.slim_server import SlimServer

                SlimServer.set_current_server(slim_server)

            # Player is now available
            _player_list[self.id] = self
            if self.jnt:
                self.jnt.notify("playerNew", self)

        # Firmware upgrades
        if old_info.get("needs_upgrade") != self.info.get(
            "needs_upgrade"
        ) or old_info.get("is_upgrading") != self.info.get("is_upgrading"):
            if self.jnt:
                self.jnt.notify(
                    "playerNeedsUpgrade",
                    self,
                    self.is_needs_upgrade(),
                    self.is_upgrading(),
                )

        # Name change
        if self.info.get("name") and old_info.get("name") != self.info.get("name"):
            if self.jnt:
                self.jnt.notify("playerNewName", self, self.info["name"])

        # Digital volume control change
        if old_info.get("digital_volume_control") != self.info.get(
            "digital_volume_control"
        ):
            log.debug(
                "notify_playerDigitalVolumeControl: %s",
                self.info.get("digital_volume_control"),
            )
            if self.jnt:
                self.jnt.notify(
                    "playerDigitalVolumeControl",
                    self,
                    self.info.get("digital_volume_control"),
                )

        # Power change
        if (not use_sequence_number or is_sequence_number_in_sync) and old_info.get(
            "power"
        ) != self.info.get("power"):
            if self.jnt:
                self.jnt.notify("playerPower", self, self.info.get("power"))
        elif use_sequence_number and not is_sequence_number_in_sync:
            log.debug(
                "power value ignored (out of sync), revert to old: %s",
                old_info.get("power"),
            )
            self.info["power"] = old_info.get("power")

        # Connected status change
        log.debug(
            "oldInfo.connected=%s self.info.connected=%s",
            old_info.get("connected"),
            self.info.get("connected"),
        )
        if old_info.get("connected") != self.info.get("connected"):
            if self.info.get("connected"):
                if self.jnt:
                    self.jnt.notify("playerConnected", self)
            else:
                if self.jnt:
                    self.jnt.notify("playerDisconnected", self)

    # ------------------------------------------------------------------
    # MAC-to-model guessing
    # ------------------------------------------------------------------

    @staticmethod
    def mac_to_model(mac: Optional[str]) -> Optional[str]:
        """
        Parse a MAC address and try to guess the player model based
        on known Slim Devices OUI ranges.
        """
        if not mac:
            return None

        m = re.match(
            r"([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}):"
            r"([0-9a-fA-F]{2}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2})",
            mac,
        )
        if not m:
            return "squeezeplay"

        prefix = m.group(1).lower()
        a = m.group(2).lower()
        b = m.group(3).lower()

        if prefix != "00:04:20":
            return "squeezeplay"

        if a == "04":
            return "slimp3"
        elif a == "05":
            d = b[0]
            if d.isalpha():
                return "squeezebox2"
            else:
                return "squeezebox"
        elif a in ("06", "07"):
            return "squeezebox3"
        elif a == "08":
            if b == "01":
                return "boom"
        elif a in ("10", "11"):
            return "transporter"
        elif a in ("12", "13", "14", "15"):
            return "squeezebox3"
        elif a in ("16", "17", "18", "19"):
            return "receiver"
        elif a in ("1a", "1b", "1c", "1d"):
            return "controller"
        elif a in ("1e", "1f", "20", "21"):
            return "boom"

        return "receiver"

    @staticmethod
    def ssid_is_squeezebox(ssid: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Check if an SSID belongs to a Squeezebox in setup mode.

        Returns ``(mac, has_ethernet)`` or ``(None, None)``.
        """
        m = re.match(r"logitech([+\-])squeezebox[+\-]([0-9a-fA-F]+)", ssid)
        if not m:
            return None, None

        has_ethernet = m.group(1)
        raw_hex = m.group(2)

        # Insert colons every 2 hex chars
        pairs = [raw_hex[i : i + 2] for i in range(0, len(raw_hex), 2)]
        mac = ":".join(pairs).lower() if len(pairs) == 6 else None
        return mac, has_ethernet

    # ------------------------------------------------------------------
    # Update from SSID (setup mode)
    # ------------------------------------------------------------------

    def update_ssid(self, ssid: str, last_scan: int) -> None:
        """Update player state from a WLAN SSID (ad-hoc setup mode)."""
        mac, _ = self.ssid_is_squeezebox(ssid)
        assert self.id == mac

        if last_scan < self.last_seen:
            return

        self.config = "needsNetwork"
        self.config_ssid = ssid
        self.info["connected"] = False
        self.last_seen = last_scan

        _player_list[self.id] = self
        if self.jnt:
            self.jnt.notify("playerNew", self)

    # ------------------------------------------------------------------
    # free / teardown
    # ------------------------------------------------------------------

    def free(
        self, slim_server: Optional[Any] = None, server_delete_only: bool = False
    ) -> None:
        """
        Delete the player, if connected to the given server.

        Parameters
        ----------
        slim_server : SlimServer or None
            Only free if the player is attached to this server.
            If ``None``, free unconditionally.
        server_delete_only : bool
            If ``True``, only clean up the server association without
            removing from the player list.
        """
        if slim_server is not None and self.slim_server is not slim_server:
            return

        log.debug("%s delete for %s", self, self.slim_server)

        if not server_delete_only:
            self.last_seen = 0
            if self.jnt:
                self.jnt.notify("playerDelete", self)

        if self is _current_player:
            if self.jnt:
                self.jnt.notify("playerDisconnected", self)
            self.info["connected"] = False
            return

        if not self.is_local_player() and not server_delete_only:
            _player_list.pop(self.id, None)

        if self.slim_server and self.slim_server is not False:
            if self.is_on_stage:
                self.off_stage()
            self.slim_server._delete_player(self)
            self.slim_server = False

    # ------------------------------------------------------------------
    # Subscriptions (delegate to server's Comet)
    # ------------------------------------------------------------------

    def subscribe(self, *args: Any, **kwargs: Any) -> None:
        """Subscribe to Comet events for this player."""
        if not self.slim_server or self.slim_server is False:
            return
        self.slim_server.comet.subscribe(*args, **kwargs)

    def unsubscribe(self, *args: Any, **kwargs: Any) -> None:
        """Unsubscribe from Comet events for this player."""
        if not self.slim_server or self.slim_server is False:
            return
        self.slim_server.comet.unsubscribe(*args, **kwargs)

    # ------------------------------------------------------------------
    # Track elapsed / duration
    # ------------------------------------------------------------------

    def get_track_elapsed(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Return ``(elapsed, duration)`` for the current track.

        *elapsed* is the playback position in seconds.
        *duration* is the track length in seconds (or ``None``).
        """
        if self.track_time is None:
            return None, None

        if self.mode == "play" and self.track_seen is not None:
            now = _get_ticks() / 1000.0
            rate = self.rate if self.rate is not None else 1.0
            self.track_correction = rate * (now - self.track_seen)

        if self.track_correction <= 0:
            return self.track_time, self.track_duration
        else:
            elapsed = self.track_time + self.track_correction
            return elapsed, self.track_duration

    # ------------------------------------------------------------------
    # Property accessors
    # ------------------------------------------------------------------

    def get_model(self) -> Optional[str]:
        """Return the player model string."""
        return self.info.get("model")

    def get_playlist_timestamp(self) -> Optional[Any]:
        """Return the playlist timestamp (change indicator)."""
        return self.playlist_timestamp

    def get_playlist_size(self) -> Optional[int]:
        """Return the playlist size."""
        return self.playlist_size

    def get_playlist_current_index(self) -> Optional[int]:
        """Return the 1-based index of the current track."""
        return self.playlist_current_index

    def get_player_mode(self) -> Optional[str]:
        """Return the player mode (play/pause/stop/off)."""
        return self.mode

    def get_player_status(self) -> Dict[str, Any]:
        """Return the full player status dict."""
        return self.state

    def get_name(self) -> str:
        """Return the player name."""
        name = self.info.get("name")
        if name:
            return name  # type: ignore[no-any-return]
        # Fallback: last 3 octets of MAC with colons removed
        suffix = self.id[9:] if len(self.id) > 9 else self.id
        return "Squeezebox " + suffix.replace(":", "")

    def is_power_on(self) -> Optional[bool]:
        """Return ``True`` if the player is powered on."""
        return self.info.get("power")

    def get_id(self) -> str:
        """Return the player ID (MAC address)."""
        return self.id

    def get_ssid(self) -> Optional[str]:
        """Return the player SSID if in setup mode."""
        if self.config == "needsNetwork":
            return getattr(self, "config_ssid", None)
        return None

    def get_uuid(self) -> Optional[str]:
        """Return the player UUID."""
        return self.info.get("uuid")

    def get_mac_address(self) -> Optional[str]:
        """
        Return the player MAC address (hex only, no separators),
        or ``None`` for HTTP players.
        """
        model = self.info.get("model")
        dtype = DEVICE_TYPE.get(model or "")
        if dtype in ("ip3k", "squeezeplay"):
            return re.sub(r"[^0-9a-fA-F]", "", self.id)
        return None

    def get_pin(self) -> Optional[str]:
        """Return the SN PIN for this player (if any)."""
        return self.info.get("pin")

    def clear_pin(self) -> None:
        """Clear the SN pin (after linking)."""
        self.info["pin"] = None

    def get_slim_server(self) -> Any:
        """Return the associated SlimServer (or ``False``)."""
        return self.slim_server

    # ------------------------------------------------------------------
    # Commands  (call / send)
    # ------------------------------------------------------------------

    def call(
        self,
        cmd: Sequence[Any],
        use_background_request: bool = False,
    ) -> Optional[Any]:
        """
        Send a command and listen for a response.

        Parameters
        ----------
        cmd : list
            The command tokens, e.g. ``['status', '-', 10, ...]``.
        use_background_request : bool
            If ``True``, use a background (non-user) request.

        Returns
        -------
        The request-ID, or ``None``.
        """
        log.debug("Player:call(): %s", cmd)

        if not self.slim_server or self.slim_server is False:
            log.warning("Player:call() — no server attached")
            return None

        sink = self._get_sink(cmd)

        if use_background_request:
            self.slim_server.request(sink, self.id, cmd)
            return None

        return self.slim_server.user_request(sink, self.id, cmd)

    def send(
        self,
        cmd: Sequence[Any],
        use_background_request: bool = False,
    ) -> None:
        """
        Send a command without expecting a response.
        """
        log.debug("Player:send(): %s", cmd)

        if not self.slim_server or self.slim_server is False:
            log.warning("Player:send() — no server attached")
            return

        if use_background_request:
            self.slim_server.request(None, self.id, cmd)
        else:
            self.slim_server.user_request(None, self.id, cmd)

    def _get_sink(self, cmd: Sequence[Any]) -> Callable[..., None]:
        """
        Build a sink callback for the given command.

        The sink dispatches to ``self._process_<cmd[0]>()`` when
        a response chunk arrives.
        """
        first = str(cmd[0]) if cmd else "unknown"

        def sink(chunk: Any = None, err: Any = None) -> None:
            if err:
                log.warning("err in player sink: %s", err)
            elif chunk is not None:
                proc_name = f"_process_{first}"
                proc = getattr(self, proc_name, None)
                if proc is not None:
                    proc(chunk)

        return sink

    # ------------------------------------------------------------------
    # onStage / offStage  (subscribe to player events)
    # ------------------------------------------------------------------

    def on_stage(self) -> None:
        """
        Called when this player is being browsed — subscribe to
        status and display events.
        """
        log.debug("Player:on_stage()")
        self.is_on_stage = True

        if not self.slim_server or self.slim_server is False:
            return

        comet = self.slim_server.comet

        comet.start_batch()

        # Subscribe to player status
        cmd: List[Any] = [
            "status",
            "-",
            10,
            "menu:menu",
            "useContextMenu:1",
            "subscribe:600",
        ]
        comet.subscribe(
            f"/slim/playerstatus/{self.id}",
            self._get_sink(cmd),
            self.id,
            cmd,
        )

        # Subscribe to display status
        cmd_display: List[Any] = ["displaystatus", "subscribe:showbriefly"]
        comet.subscribe(
            f"/slim/displaystatus/{self.id}",
            self._get_sink(cmd_display),
            self.id,
            cmd_display,
        )

        comet.end_batch()

        # Initialise popup holders (stubs — full UI wiring later)
        self.mixed_popup = {"window": None}
        self.popup_info = {"window": None}
        self.popup_icon = {"window": None}

    def off_stage(self) -> None:
        """Go back to the shadows — unsubscribe from events."""
        log.debug("Player:off_stage()")
        self.is_on_stage = False
        self.browse_history = {}

        if not self.slim_server or self.slim_server is False:
            return

        comet = self.slim_server.comet

        comet.start_batch()
        comet.unsubscribe(f"/slim/playerstatus/{self.id}")
        comet.unsubscribe(f"/slim/displaystatus/{self.id}")
        comet.end_batch()

        self.mixed_popup = {}

    # ------------------------------------------------------------------
    # updateIconbar (stub — wired when Iconbar is ported)
    # ------------------------------------------------------------------

    def update_iconbar(self) -> None:
        """Update the iconbar with current player state (stub)."""
        log.debug("Player:update_iconbar()")
        # Full implementation requires the Iconbar widget.
        # For now we just log — the iconbar will be wired in M11.

    # ------------------------------------------------------------------
    # _process_status  — handle player status notifications
    # ------------------------------------------------------------------

    def _process_status(self, event: Any) -> None:
        """Process the playerstatus data and fire notifications."""
        log.debug("Player:_process_status()")

        data = event if isinstance(event, dict) else getattr(event, "data", event)
        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        if not isinstance(data, dict):
            log.warning("_process_status: no data dict")
            return

        if data.get("error"):
            return

        old_state = self.state
        self.state = data

        # Track timing
        self.rate = _to_float(data.get("rate"))
        self.track_seen = _get_ticks() / 1000.0
        self.track_correction = 0.0
        self.track_time = _to_float(data.get("time"))
        self.track_duration = _to_float(data.get("duration"))
        self.playlist_size = _to_int_or_none(data.get("playlist_tracks"))

        cur_idx = data.get("playlist_cur_index")
        self.playlist_current_index = int(cur_idx) + 1 if cur_idx is not None else None
        self.defined_presets = data.get("preset_loop")
        self.alarm_snooze_seconds = _to_int_or_none(data.get("alarm_snooze_seconds"))
        self.alarm_timeout_seconds = _to_int_or_none(data.get("alarm_timeout_seconds"))
        self.waiting_to_play = bool(data.get("waitingToPlay"))

        # Update player info from status
        player_info: Dict[str, Any] = {
            "uuid": self.info.get("uuid"),
            "name": data.get("player_name"),
            "digital_volume_control": data.get("digital_volume_control"),
            "use_volume_control": data.get("use_volume_control"),
            "model": self.info.get("model"),
            "connected": data.get("player_connected"),
            "power": data.get("power"),
            "player_needs_upgrade": data.get("player_needs_upgrade"),
            "player_is_upgrading": data.get("player_is_upgrading"),
            "pin": self.info.get("pin"),
            "seq_no": data.get("seq_no"),
        }

        use_seq = False
        in_sync = True
        if self.is_local_player() and player_info.get("seq_no") is not None:
            use_seq = True
            if not self.is_sequence_number_in_sync(int(player_info["seq_no"])):
                in_sync = False

        self.update_player_info(self.slim_server, player_info, use_seq, in_sync)

        # Track change detection
        now_playing, artwork = _whats_playing(data)

        if self.state.get("mode") != old_state.get("mode"):
            log.debug("notify_playerModeChange")
            self.mode = self.state.get("mode", self.mode)
            if self.jnt:
                self.jnt.notify("playerModeChange", self, self.state.get("mode"))

        # Alarm state
        if (
            self.state.get("alarm_state") != old_state.get("alarm_state")
            or self.state.get("alarm_next") != old_state.get("alarm_next")
            or self.state.get("alarm_version") != old_state.get("alarm_version")
            or self.state.get("alarm_next2") != old_state.get("alarm_next2")
            or self.state.get("alarm_repeat") != old_state.get("alarm_repeat")
            or self.state.get("alarm_days") != old_state.get("alarm_days")
        ):
            log.debug("notify_playerAlarmState")
            if self.state.get("alarm_state") == "none":
                self.alarm_state = None
                self.alarm_next = None
            else:
                self.alarm_state = self.state.get("alarm_state")
                self.alarm_next = _to_float(self.state.get("alarm_next"))

            self.alarm_version = _to_int_or_none(self.state.get("alarm_version"))
            self.alarm_next2 = _to_float(self.state.get("alarm_next2"))
            self.alarm_repeat = _to_int_or_none(self.state.get("alarm_repeat"))
            self.alarm_days = self.state.get("alarm_days")

            if self.jnt:
                self.jnt.notify(
                    "playerAlarmState",
                    self,
                    self.state.get("alarm_state"),
                    self.alarm_next,
                    self.alarm_version,
                    self.alarm_next2,
                    self.alarm_repeat,
                    self.alarm_days,
                )

        # Shuffle
        if self.state.get("playlist shuffle") != old_state.get("playlist shuffle"):
            log.debug("notify_playerShuffleModeChange")
            if self.jnt:
                self.jnt.notify(
                    "playerShuffleModeChange",
                    self,
                    self.state.get("playlist shuffle"),
                )

        # Sleep
        if self.state.get("sleep") != old_state.get("sleep"):
            log.debug("notify_playerSleepChange")
            if self.jnt:
                self.jnt.notify("playerSleepChange", self, self.state.get("sleep"))

        # Repeat
        if self.state.get("playlist repeat") != old_state.get("playlist repeat"):
            log.debug("notify_playerRepeatModeChange")
            if self.jnt:
                self.jnt.notify(
                    "playerRepeatModeChange",
                    self,
                    self.state.get("playlist repeat"),
                )

        # Track change
        if self.now_playing != now_playing or self.now_playing_artwork != artwork:
            log.debug("notify_playerTrackChange")
            self.now_playing = now_playing
            self.now_playing_artwork = artwork
            if self.jnt:
                self.jnt.notify("playerTrackChange", self, now_playing, artwork)

        # Playlist change
        if self.state.get("playlist_timestamp") != old_state.get("playlist_timestamp"):
            log.debug("notify_playerPlaylistChange")
            self.playlist_timestamp = self.state.get("playlist_timestamp")
            if self.jnt:
                self.jnt.notify("playerPlaylistChange", self)

        # Volume
        mixer_vol = self.state.get("mixer volume")
        if mixer_vol is not None:
            self.state["mixer volume"] = int(float(mixer_vol))

        if use_seq:
            if in_sync:
                server_vol = self.state.get("mixer volume")
                current_vol = self.get_volume()
                if server_vol is not None and server_vol != current_vol:
                    if server_vol == 0 and current_vol is not None and current_vol < 0:
                        # Muted — server sends 0, ignore
                        self.state["mixer volume"] = old_state.get("mixer volume")
                    else:
                        self.volume_local(server_vol, False, True)
            else:
                log.debug(
                    "volume value ignored (out of sync), revert to old: %s",
                    old_state.get("mixer volume"),
                )
                self.state["mixer volume"] = old_state.get("mixer volume")

                # Refresh locally maintained parameters
                if not in_sync:
                    self.refresh_locally_maintained_parameters()

        # Iconbar
        self.update_iconbar()

    # ------------------------------------------------------------------
    # _process_displaystatus  (stub — full popup UI later)
    # ------------------------------------------------------------------

    def _process_displaystatus(self, event: Any) -> None:
        """Process display-status data (showBriefly popups)."""
        log.debug("Player:_process_displaystatus()")

        data = event if isinstance(event, dict) else getattr(event, "data", event)
        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        if not isinstance(data, dict):
            return

        display = data.get("display")
        if not display:
            return

        dtype = display.get("type", "text")
        text_val = display.get("text", "")
        if isinstance(text_val, (list, tuple)):
            text_val = _format_show_briefly_text(text_val)
        duration = int(display.get("duration", 3000))

        # For now just log — full popup rendering comes with Skin/Applet porting
        log.debug(
            "showBriefly: type=%s duration=%d text=%s",
            dtype,
            duration,
            text_val[:80] if isinstance(text_val, str) else text_val,
        )

    # ------------------------------------------------------------------
    # _process_button
    # ------------------------------------------------------------------

    def _process_button(self, event: Any) -> None:
        """Process button response — clears rate-limit timer."""
        log.debug("_process_button()")
        self.button_to = None

    # ------------------------------------------------------------------
    # Playback commands
    # ------------------------------------------------------------------

    def toggle_pause(self) -> None:
        """Toggle between play and pause."""
        if not self.state:
            return

        paused = self.mode
        log.debug("Player:toggle_pause(%s)", paused)

        if paused in ("stop", "pause"):
            self.unpause()
        elif paused == "play":
            self.pause()

    def stop_preview(self) -> None:
        if not self.state:
            return
        self.call(["playlist", "preview", "cmd:stop"])
        self.update_iconbar()

    def pause(self, use_background_request: bool = False) -> None:
        """Pause playback."""
        if not self.state:
            return
        self.call(["pause", "1"], use_background_request)
        self.mode = "pause"
        self.update_iconbar()

    def unpause(self) -> None:
        """Resume playback from pause or stop."""
        if not self.state:
            return

        if self.mode in ("stop", "pause"):
            self.track_seen = _get_ticks() / 1000.0
            self.call(["pause", "0"])
            self.mode = "play"

        self.update_iconbar()

    def stop_alarm(self, continue_audio: bool = False) -> None:
        """Stop the alarm.  Optionally continue audio."""
        if not self.state:
            return
        if not continue_audio:
            self.pause()
        self.alarm_state = "none"
        self.call(["jivealarm", "stop:1"])
        self.update_iconbar()

    def snooze(self) -> None:
        """Snooze the alarm."""
        if not self.state:
            return
        if self.alarm_state == "active":
            self.alarm_state = "snooze"
            self.call(["jivealarm", "snooze:1"])
        self.update_iconbar()

    def is_paused(self) -> bool:
        """Return ``True`` if the player is paused."""
        return bool(self.state) and self.mode == "pause"

    def is_preset_defined(self, preset: int) -> bool:
        """Return ``True`` if the given preset is defined."""
        if self.defined_presets and isinstance(self.defined_presets, (list, dict)):
            val = (
                self.defined_presets.get(preset)
                if isinstance(self.defined_presets, dict)
                else (
                    self.defined_presets[preset]
                    if preset < len(self.defined_presets)
                    else None
                )
            )
            if val is not None and int(val) == 0:
                return False
        return True

    def is_waiting_to_play(self) -> bool:
        return self.waiting_to_play

    def set_waiting_to_play(self, value: bool) -> None:
        self.waiting_to_play = value

    def get_alarm_state(self) -> Optional[str]:
        return self.alarm_state

    def set_alarm_state(self, state: Optional[str]) -> None:
        self.alarm_state = state

    def get_play_mode(self) -> Optional[str]:
        """Return nil|stop|play|pause."""
        if self.state:
            return self.mode
        return None

    def get_effective_play_mode(self) -> Optional[str]:
        """Identical for non-local player."""
        return self.get_play_mode()

    def is_current(self, index: int) -> bool:
        """Return ``True`` if *index* (1-based) is the current track."""
        if self.state:
            return self.state.get("playlist_cur_index") == index - 1
        return False

    def is_needs_upgrade(self) -> bool:
        return bool(self.info.get("needs_upgrade"))

    def is_upgrading(self) -> bool:
        return bool(self.info.get("is_upgrading"))

    def play(self) -> None:
        """Start playback."""
        log.debug("Player:play()")
        if self.mode != "play":
            self.track_seen = _get_ticks() / 1000.0
        self.call(["mode", "play"])
        self.mode = "play"
        self.update_iconbar()

    def stop(self) -> None:
        """Stop playback."""
        log.debug("Player:stop()")
        self.call(["mode", "stop"])
        self.mode = "stop"
        self.update_iconbar()

    def playlist_jump_index(self, index: int) -> None:
        """Jump to a 1-based playlist index."""
        log.debug("Player:playlist_jump_index(%d)", index)
        if index < 1:
            return
        self.call(["playlist", "index", index - 1])

    def playlist_delete_index(self, index: int) -> None:
        """Delete a track from the playlist (1-based index)."""
        log.debug("Player:playlist_delete_index(%d)", index)
        if index < 1:
            return
        self.call(["playlist", "delete", index - 1])

    def playlist_zap_index(self, index: int) -> None:
        """Zap a track from the playlist (1-based index)."""
        log.debug("Player:playlist_zap_index(%d)", index)
        if index < 1:
            return
        self.call(["playlist", "zap", index - 1])

    # ------------------------------------------------------------------
    # Button commands
    # ------------------------------------------------------------------

    def button(self, button_name: str) -> None:
        """Send a button press to the server (rate-limited)."""
        now = _get_ticks()
        if self.button_to is None or self.button_to < now:
            log.debug("Sending button: %s", button_name)
            self.call(["button", button_name])
            self.button_to = now + MIN_KEY_INT
        else:
            log.debug("Suppressing button: %s", button_name)

    def repeat_toggle(self) -> None:
        self.button("repeat")

    def sleep_toggle(self) -> None:
        self.button("sleep")

    def shuffle_toggle(self) -> None:
        self.button("shuffle")

    def power_toggle(self) -> None:
        self.button("power")

    def number_hold(self, number: int) -> None:
        self.button(f"{number}.hold")

    def preset_press(self, number: int) -> None:
        self.button(f"preset_{number}.single")

    def scan_rew(self) -> None:
        self.button("scan_rew")

    def scan_fwd(self) -> None:
        self.button("scan_fwd")

    def rew(self) -> None:
        log.debug("Player:rew()")
        self.button("jump_rew")

    def fwd(self) -> None:
        log.debug("Player:fwd()")
        self.button("jump_fwd")

    # ------------------------------------------------------------------
    # Power
    # ------------------------------------------------------------------

    def set_power(
        self,
        on: bool,
        sequence_number: Optional[int] = None,
        is_server_request: bool = False,
    ) -> None:
        """Set the player power state."""
        if is_server_request:
            return
        if not self.state:
            return

        log.debug("Player:set_power(%s)", on)
        val = "1" if on else "0"
        cmd: List[Any] = ["power", val]
        if sequence_number is not None:
            cmd.append(f"seq_no:{sequence_number}")
        self.call(cmd, use_background_request=True)

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------

    def volume(
        self,
        vol: int,
        send: bool = False,
        sequence_number: Optional[int] = None,
    ) -> Optional[int]:
        """
        Send a new volume value to the server.

        Returns the volume value, or ``None`` if rate-limited.
        """
        now = _get_ticks()
        if self.mixer_to is None or self.mixer_to < now or send:
            log.debug("Sending player:volume(%d)", vol)
            cmd: List[Any] = ["mixer", "volume", vol]
            if sequence_number is not None:
                cmd.append(f"seq_no:{sequence_number}")
            self.send(cmd)
            self.mixer_to = now + MIN_KEY_INT
            self.state["mixer volume"] = vol
            return vol
        else:
            log.debug("Suppressing player:volume(%d)", vol)
            return None

    def volume_local(
        self,
        vol: int,
        _unused: bool = False,
        state_only: bool = False,
    ) -> None:
        """
        Update local volume state (no server command).

        This is a stub that LocalPlayer overrides for actual audio
        playback.  The base Player just stores the state.
        """
        self.state["mixer volume"] = vol

    def goto_time(self, t: float) -> None:
        """Jump to a new time position in the current track."""
        self.track_seen = _get_ticks() / 1000.0
        self.track_time = t
        log.debug("Sending player:time(%s)", t)
        self.send(["time", t])
        self.set_waiting_to_play(True)

    def is_track_seekable(self) -> bool:
        """Return ``True`` if the current track supports seeking."""
        return bool(self.track_duration and self.state.get("can_seek"))

    def is_remote(self) -> bool:
        """Return ``True`` if the current track is a remote stream."""
        return bool(self.state.get("remote"))

    def mute(
        self,
        do_mute: bool,
        sequence_number: Optional[int] = None,
    ) -> Optional[int]:
        """Mute or unmute the player.  Returns the new volume value."""
        vol = self.state.get("mixer volume", 0)

        if do_mute and vol >= 0:
            cmd: List[Any] = ["mixer", "muting", "toggle"]
            if sequence_number is not None:
                cmd.append(f"seq_no:{sequence_number}")
            self.send(cmd)
            vol = -abs(vol)
        elif not do_mute and vol < 0:
            cmd = ["mixer", "muting", "toggle"]
            if sequence_number is not None:
                cmd.append(f"seq_no:{sequence_number}")
            self.send(cmd)
            vol = abs(vol)

        self.state["mixer volume"] = vol
        return vol  # type: ignore[no-any-return]

    def get_volume(self) -> Optional[int]:
        """Return the current volume (from last status update)."""
        if self.state:
            return self.state.get("mixer volume", 0)  # type: ignore[no-any-return]
        return None

    # ------------------------------------------------------------------
    # Server connectivity helpers
    # ------------------------------------------------------------------

    def can_connect_to_server(self) -> bool:
        """Return ``True`` if this player can connect to another server."""
        model = self.info.get("model")
        return DEVICE_TYPE.get(model or "") in ("ip3k", "squeezeplay")

    def connect_to_server(self, server: Any) -> Optional[bool]:
        """Tell the player to connect to another server."""
        server.wake_on_lan()

        if self.config == "needsServer":
            from jive.slim.slim_server import SlimServer

            SlimServer.add_locally_requested_server(server)
            return None

        if self.slim_server and self.slim_server is not False:
            ip, port = server.get_ip_port()

            server.disconnect()

            from jive.slim.slim_server import SlimServer

            SlimServer.add_locally_requested_server(server)
            self.send(["connect", ip], use_background_request=True)
            return True

        log.warning("No method to connect %s to %s", self, server)
        return False

    def disconnect_from_server(self) -> None:
        """Disconnect from the server (no-op for remote players)."""
        pass

    # ------------------------------------------------------------------
    # Misc accessors
    # ------------------------------------------------------------------

    def get_last_seen(self) -> int:
        return self.last_seen

    def get_alarm_snooze_seconds(self) -> int:
        return self.alarm_snooze_seconds or 540

    def get_digital_volume_control(self) -> int:
        """0 = fixed volume, 1 = variable (default)."""
        return self.info.get("digital_volume_control") or 1

    def use_volume_control(self) -> int:
        """0 = don't use volume, 1 = use volume (default)."""
        return (
            self.info.get("use_volume_control")
            or self.info.get("digital_volume_control")
            or 1
        )

    def get_alarm_timeout_seconds(self) -> int:
        return self.alarm_timeout_seconds or 3600

    def is_connected(self) -> bool:
        """Return ``True`` if connected to server and server is connected."""
        return bool(
            self.slim_server
            and self.slim_server is not False
            and self.slim_server.is_connected()
            and self.info.get("connected")
        )

    def has_connection_failed(self) -> bool:
        """Stub — subclasses may override."""
        return False

    def is_available(self) -> bool:
        """
        Return ``True`` if the player is available (connected or
        in configuration mode).
        """
        return self.config is not False

    def needs_network_config(self) -> bool:
        return self.config == "needsNetwork"  # type: ignore[no-any-return]

    def needs_music_source(self) -> bool:
        return self.config == "needsServer"  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Sequence numbers (stub — LocalPlayer overrides)
    # ------------------------------------------------------------------

    def is_sequence_number_in_sync(self, server_seq: int) -> bool:
        """Check if the server sequence number matches ours."""
        return True

    def refresh_locally_maintained_parameters(self) -> None:
        """Refresh volume/power/etc. back to the server."""
        pass

    # ------------------------------------------------------------------
    # Capture play mode (stub)
    # ------------------------------------------------------------------

    def get_capture_play_mode(self) -> bool:
        return False

    def set_capture_play_mode(self, mode: bool) -> None:
        pass

    # ------------------------------------------------------------------
    # Tie window (stub — wired when Window system is complete)
    # ------------------------------------------------------------------

    def tie_window(self, window: Any) -> None:
        """Tie a window to this player (stub)."""
        pass

    # ------------------------------------------------------------------
    # Lua-compatible camelCase aliases
    # ------------------------------------------------------------------
    # Ported applets (SlimBrowser, NowPlaying, SelectPlayer, etc.) call
    # Player methods using the original Lua camelCase names.  These
    # aliases ensure ``hasattr(player, "getPlaylistSize")`` etc. succeed
    # and route to the canonical snake_case implementation.

    # --- Accessors ---
    getId = get_id
    getName = get_name
    getModel = get_model
    getUuid = get_uuid
    getSSID = get_ssid
    getPin = get_pin
    clearPin = clear_pin
    getMacAddress = get_mac_address
    getSlimServer = get_slim_server
    getVolume = get_volume
    getPlayMode = get_play_mode
    getEffectivePlayMode = get_effective_play_mode
    getPlayerMode = get_player_mode
    getPlayerStatus = get_player_status
    getPlaylistSize = get_playlist_size
    getPlaylistCurrentIndex = get_playlist_current_index
    getPlaylistTimestamp = get_playlist_timestamp
    getTrackElapsed = get_track_elapsed
    getLastSeen = get_last_seen
    getAlarmSnoozeSeconds = get_alarm_snooze_seconds
    getAlarmTimeoutSeconds = get_alarm_timeout_seconds
    getAlarmState = get_alarm_state
    setAlarmState = set_alarm_state
    getDigitalVolumeControl = get_digital_volume_control
    useVolumeControl = use_volume_control
    getRateLimitTime = get_rate_limit_time
    getCapturePlayMode = get_capture_play_mode
    setCapturePlayMode = set_capture_play_mode
    getLastSqueezeCenter = get_last_squeeze_center
    getLastBrowseIndex = get_last_browse_index
    setLastBrowseIndex = set_last_browse_index
    getLastBrowse = get_last_browse
    setLastBrowse = set_last_browse
    getInit = get_init
    getLocalPlayer = get_local_player
    getCurrentPlayer = get_current_player
    setCurrentPlayer = set_current_player

    # --- Predicates ---
    isLocal = is_local
    isLocalPlayer = is_local_player
    isRemote = is_remote
    isPowerOn = is_power_on
    isPaused = is_paused
    isCurrent = is_current
    isConnected = is_connected
    isAvailable = is_available
    isNeedsUpgrade = is_needs_upgrade
    isUpgrading = is_upgrading
    isPresetDefined = is_preset_defined
    isWaitingToPlay = is_waiting_to_play
    setWaitingToPlay = set_waiting_to_play
    isTrackSeekable = is_track_seekable
    isSequenceNumberInSync = is_sequence_number_in_sync
    hasConnectionFailed = has_connection_failed
    needsNetworkConfig = needs_network_config
    needsMusicSource = needs_music_source
    canConnectToServer = can_connect_to_server

    # --- Commands / mutations ---
    togglePause = toggle_pause
    stopPreview = stop_preview
    stopAlarm = stop_alarm
    setPower = set_power
    powerToggle = power_toggle
    repeatToggle = repeat_toggle
    shuffleToggle = shuffle_toggle
    sleepToggle = sleep_toggle
    scanRew = scan_rew
    scanFwd = scan_fwd
    gotoTime = goto_time
    volumeLocal = volume_local
    numberHold = number_hold
    presetPress = preset_press
    playlistJumpIndex = playlist_jump_index
    playlistDeleteIndex = playlist_delete_index
    playlistZapIndex = playlist_zap_index
    connectToServer = connect_to_server
    disconnectFromServer = disconnect_from_server
    updateIconbar = update_iconbar
    updateInit = update_init
    updatePlayerInfo = update_player_info
    updateSsid = update_ssid
    onStage = on_stage
    offStage = off_stage
    tieWindow = tie_window
    setServerRefreshInProgress = set_server_refresh_in_progress
    refreshLocallyMaintainedParameters = refresh_locally_maintained_parameters

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Player({self.id!r})"

    def __str__(self) -> str:
        return f"Player {{{self.get_name()}}}"


# ===================================================================
# Module-level helpers
# ===================================================================


def _to_bool(value: Any) -> bool:
    """Convert a Lua-style value to Python bool.

    Handles numeric strings, ints, bools, and None.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    try:
        return int(value) == 1
    except (ValueError, TypeError):
        return bool(value)


def _to_int_or_none(value: Any) -> Optional[int]:
    """Convert to int or return None."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _to_float(value: Any) -> Optional[float]:
    """Convert to float or return None."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def reset_player_globals() -> None:
    """
    Reset all module-level player state.

    **For testing only** — clears all player registries.
    """
    global _current_player
    _player_ids_weak.clear()
    _player_list.clear()
    _current_player = None
