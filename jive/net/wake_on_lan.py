"""
jive.net.wake_on_lan — Wake-on-LAN magic packet sender.

Ported from ``jive/net/WakeOnLan.lua`` in the original jivelite project.

WakeOnLan sends a "magic packet" to wake a sleeping network device.
The magic packet consists of 6 bytes of ``0xFF`` followed by the
target MAC address repeated 16 times, sent as a UDP broadcast on
port 7.

The Lua original subclasses SocketUdp and uses its ``send()`` method
to broadcast the packet.  In Python we follow the same pattern:
WakeOnLan extends SocketUdp, creates a no-op sink (since we only
send, never receive), and provides a ``wake_on_lan(hwaddr)`` method
that constructs and sends the magic packet.

Usage::

    from jive.net.wake_on_lan import WakeOnLan

    wol = WakeOnLan(jnt)
    wol.wake_on_lan("00:1a:2b:3c:4d:5e")

    # Also accepts dash-separated format:
    wol.wake_on_lan("00-1a-2b-3c-4d-5e")

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import re
from typing import (
    TYPE_CHECKING,
    Any,
    Optional,
)

from jive.net.socket_udp import SocketUdp
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.net.network_thread import NetworkThread

__all__ = ["WakeOnLan"]

log = logger("net.http")

# Broadcast address and port for Wake-on-LAN
_WOL_BROADCAST_ADDR = "255.255.255.255"
_WOL_PORT = 7

# Regex to extract hex pairs from a MAC address string
_HEX_PAIR_RE = re.compile(r"([0-9a-fA-F]{2})")


class WakeOnLan(SocketUdp):
    """
    Wake-on-LAN magic packet sender.

    Subclass of :class:`SocketUdp`.  Mirrors ``jive.net.WakeOnLan``
    from the Lua original.

    Creates a UDP socket with a no-op sink (no data is received —
    this socket is send-only) and provides ``wake_on_lan()`` to
    broadcast magic packets.

    Parameters
    ----------
    jnt : NetworkThread or None
        The network thread coordinator.
    """

    def __init__(self, jnt: Optional[NetworkThread] = None) -> None:
        # Initialize with a no-op sink — we only send, never receive
        super().__init__(jnt=jnt, sink=lambda *args, **kwargs: None, name="WakeOnLan")

    def wake_on_lan(self, hwaddr: str) -> None:
        """
        Send a Wake-on-LAN magic packet to the given hardware address.

        The magic packet consists of:
        - 6 bytes of ``0xFF`` (the synchronization stream)
        - The target MAC address (6 bytes) repeated 16 times

        This is sent as a UDP broadcast to ``255.255.255.255:7``.

        Parameters
        ----------
        hwaddr : str
            The target MAC address as a string of hex pairs separated
            by colons or dashes (e.g., ``"00:1a:2b:3c:4d:5e"`` or
            ``"00-1a-2b-3c-4d-5e"``).

        Raises
        ------
        ValueError
            If *hwaddr* does not contain exactly 6 hex pairs.
        """
        # Extract hex pairs from the MAC address string
        hex_pairs = _HEX_PAIR_RE.findall(hwaddr)

        if len(hex_pairs) != 6:
            raise ValueError(
                f"Invalid MAC address '{hwaddr}': expected 6 hex pairs, "
                f"got {len(hex_pairs)}"
            )

        # Build the 6-byte MAC address
        mac_bytes = bytes(int(h, 16) for h in hex_pairs)

        # Build the magic packet:
        # 6 × 0xFF + 16 × MAC address
        packet = b"\xff" * 6 + mac_bytes * 16

        log.debug("WakeOnLan: sending magic packet for %s", hwaddr)

        # Send the packet as a UDP broadcast
        # The source is a one-shot callable that returns the packet bytes
        self.send(lambda: packet, _WOL_BROADCAST_ADDR, _WOL_PORT)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return "WakeOnLan()"

    def __str__(self) -> str:
        return "WakeOnLan"
