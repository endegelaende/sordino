"""
jive.slim.local_player — Local player instance for local playback.

Ported from ``jive/slim/LocalPlayer.lua`` in the original jivelite project.

LocalPlayer is a subclass of :class:`Player` that represents the device
running jivelite itself.  Key differences from a remote Player:

* ``is_local_player()`` returns ``True``
* Maintains a sequence number for synchronising locally-maintained
  state (volume, power) with the server
* Tracks the "last SqueezeCenter" the local player was connected to
* Can refresh locally-maintained parameters back to the server when
  the sequence number is out of sync

The device type defaults to ``squeezeplay`` (device ID 12) but can be
overridden via ``set_device_type()`` for hardware-specific builds
(e.g., ``controller``, ``boom``).

Usage::

    from jive.slim.local_player import LocalPlayer

    lp = LocalPlayer(jnt, "00:04:20:aa:bb:cc")
    print(lp.is_local_player())  # True
    print(lp.get_device_type())  # (12, "squeezeplay", "SqueezePlay")

    # Override device identity:
    LocalPlayer.set_device_type("controller", "Squeezebox Controller")

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Optional,
    Tuple,
)

from jive.slim.player import Player
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.net.network_thread import NetworkThread
    from jive.slim.slim_server import SlimServer

__all__ = ["LocalPlayer"]

log = logger("jivelite.player")

# ---------------------------------------------------------------------------
# Default device identity — can be overridden by hardware-specific classes
# ---------------------------------------------------------------------------

_DEVICE_ID: int = 12
_DEVICE_MODEL: str = "squeezeplay"
_DEVICE_NAME: str = "SqueezePlay"


class LocalPlayer(Player):
    """
    Player instance for local playback.

    Inherits from :class:`Player` and adds:

    * Device-type identity (``DEVICE_ID``, ``DEVICE_MODEL``,
      ``DEVICE_NAME``).
    * Sequence-number tracking for locally-maintained parameters.
    * ``last_squeeze_center`` — remembers the last server this local
      player was connected to.
    * ``is_local_player()`` returns ``True``.
    * ``refresh_locally_maintained_parameters()`` re-sends volume and
      power state to the server.

    Parameters
    ----------
    jnt : NetworkThread or None
        The network-thread coordinator (notification bus).
    player_id : str
        The player identifier (typically a MAC address).
    uuid : str or None
        Optional player UUID (currently unused, kept for API parity).
    """

    # ------------------------------------------------------------------
    # Class-level device type management
    # ------------------------------------------------------------------

    @classmethod
    def set_device_type(cls, model: str, name: Optional[str] = None) -> None:
        """
        Override the device type for this class.

        Parameters
        ----------
        model : str
            Device model identifier (e.g., ``"controller"``).
        name : str or None
            Human-readable device name.  Defaults to *model* if not
            given.

        Notes
        -----
        In the Lua original, this also sets DEVICE_ID to 9 (controller).
        We replicate that behaviour here.
        """
        global _DEVICE_ID, _DEVICE_MODEL, _DEVICE_NAME
        _DEVICE_ID = 9
        _DEVICE_MODEL = model
        _DEVICE_NAME = name or model

    @classmethod
    def get_device_type(cls) -> Tuple[int, str, str]:
        """
        Return the current device type as ``(device_id, model, name)``.
        """
        return _DEVICE_ID, _DEVICE_MODEL, _DEVICE_NAME

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        jnt: Optional[NetworkThread] = None,
        player_id: str = "",
        uuid: Optional[str] = None,
    ) -> None:
        # Let the parent Player.__init__ handle singleton logic
        if hasattr(self, "_local_initialised") and self._local_initialised:
            return

        super().__init__(jnt=jnt, player_id=player_id)

        self._local_initialised: bool = True

        # Initialise with default device-type values
        self.update_init(
            None,
            {
                "name": _DEVICE_NAME,
                "model": _DEVICE_MODEL,
            },
        )

        # Sequence number for synchronising local state with the server
        self.sequence_number: int = 1

        # Last server this local player was connected to
        self.last_squeeze_center: Optional[Any] = None

        # Capture play mode flag (not used in standard builds)
        self._capture_play_mode: bool = False

    # ------------------------------------------------------------------
    # Last SqueezeCenter
    # ------------------------------------------------------------------

    def get_last_squeeze_center(self) -> Optional[Any]:
        """Return the last server this local player was connected to."""
        return self.last_squeeze_center

    def set_last_squeeze_center(self, server: Optional[Any]) -> None:
        """Record the last server this local player was connected to."""
        log.debug("lastSqueezeCenter set: %s", server)
        self.last_squeeze_center = server

    # ------------------------------------------------------------------
    # Sequence number management
    # ------------------------------------------------------------------

    def increment_sequence_number(self) -> int:
        """
        Increment the local sequence number and return the new value.
        """
        self.sequence_number += 1
        return self.get_current_sequence_number()

    def get_current_sequence_number(self) -> int:
        """Return the current local sequence number."""
        return self.sequence_number

    def is_sequence_number_in_sync(self, server_sequence_number: int) -> bool:
        """
        Check if the server's sequence number matches ours.

        The Lua original has commented-out logic for a more
        sophisticated sequence-controller check.  The simplified
        version always returns ``True`` (matching the active Lua code).

        Parameters
        ----------
        server_sequence_number : int
            The sequence number reported by the server.

        Returns
        -------
        bool
            ``True`` if in sync, ``False`` otherwise.
        """
        # The original Lua code has the detailed check commented out
        # and simply returns true.  We replicate that behaviour.
        return True

    # ------------------------------------------------------------------
    # Refresh locally-maintained parameters
    # ------------------------------------------------------------------

    def refresh_locally_maintained_parameters(self) -> None:
        """
        Re-send local values (volume, power) to the server.

        Called when the sequence number is out of sync.  Only the last
        call increments the sequence number so that the next player
        status comes back with a single increase.
        """
        log.debug("refresh_locally_maintained_parameters()")

        # Refresh volume (without incrementing sequence number)
        vol = self.get_volume()
        if vol is not None:
            self._volume_no_increment(vol, send=True)

        # Refresh power state
        # In the Lua original this checks jiveMain:getSoftPowerState().
        # Since we don't have JiveMain yet, we use the current power info.
        power_on = self.info.get("power", False)
        self.set_power(power_on)

    # ------------------------------------------------------------------
    # Identity overrides
    # ------------------------------------------------------------------

    def is_local_player(self) -> bool:
        """Return ``True`` — this is a local player."""
        return True

    @classmethod
    def is_local(cls) -> bool:
        """Class-level check — LocalPlayer is always local."""
        return True

    # ------------------------------------------------------------------
    # Capture play mode
    # ------------------------------------------------------------------

    def get_capture_play_mode(self) -> bool:
        """Return ``False`` for standard local player."""
        return self._capture_play_mode

    def set_capture_play_mode(self, capture_play_mode: bool) -> None:
        """Set the capture play mode flag."""
        self._capture_play_mode = capture_play_mode

    # ------------------------------------------------------------------
    # Volume (no-increment variant)
    # ------------------------------------------------------------------

    def _volume_no_increment(self, vol: int, send: bool = False) -> Optional[int]:
        """
        Set volume without incrementing the sequence number.

        Delegates to ``Player.volume()`` which handles the actual
        server communication and rate-limiting.

        Parameters
        ----------
        vol : int
            The volume value to set.
        send : bool
            If ``True``, bypass the rate-limit check.

        Returns
        -------
        int or None
            The volume value, or ``None`` if rate-limited.
        """
        return Player.volume(self, vol, send)

    # ------------------------------------------------------------------
    # Disconnect / reconnect helpers
    # ------------------------------------------------------------------

    @classmethod
    def disconnect_server_and_preserve_local_player(cls, player: Player) -> None:
        """
        Disconnect from player and server, then re-set a "clean"
        LocalPlayer as current player (if one exists).

        If there is no local player, the current player is set to
        ``None``.

        Parameters
        ----------
        player : Player
            The player instance initiating the disconnect.
        """
        # Disconnect from player and server
        Player.set_current_player(None)

        # Find the local player and re-set it as current
        local_player = Player.get_local_player()
        if local_player is not None:
            if (
                local_player.get_slim_server()
                and local_player.get_slim_server() is not False
            ):
                local_player.stop()
            Player.set_current_player(local_player)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"LocalPlayer({self.id!r})"

    def __str__(self) -> str:
        return f"LocalPlayer {{{self.get_name()}}}"
