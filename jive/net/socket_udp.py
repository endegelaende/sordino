"""
jive.net.socket_udp — UDP socket for network I/O.

Ported from ``jive/net/SocketUdp.lua`` in the original jivelite project.

SocketUdp extends SocketBase to provide UDP datagram communication.
It is primarily used for discovering SlimServers / Lyrion Music Servers
on the local network via broadcast packets.

The Lua original uses LuaSocket's UDP implementation with LTN12
source/sink pipelines for data flow.  In Python we use the standard
``socket`` module with simple callback functions replacing the
source/sink pattern.

Convention from the Lua original: methods prefixed with ``t_`` are
conceptually "thread-side" operations.  In this Python port everything
runs cooperatively in the main event loop, but we preserve the naming
convention for traceability.

Usage::

    from jive.net.socket_udp import SocketUdp

    # Create a sink to receive data
    def my_sink(chunk, err=None):
        if err:
            print(f"error: {err}")
        elif chunk:
            print(f"received: {chunk['data']} from {chunk['ip']}")

    # Create a SocketUdp
    sock = SocketUdp(jnt, my_sink, "discovery")

    # Send data to an address
    sock.send(lambda: "Hello", "10.0.0.1", 3333)

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import socket as _socket_mod
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Union,
)

from jive.net.socket_base import SocketBase
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.net.network_thread import NetworkThread

__all__ = ["SocketUdp"]

log = logger("net.socket")


# Type alias for a received UDP chunk (matches Lua table structure)
# Contains: {'data': str|bytes, 'ip': str, 'port': int}
UdpChunk = Dict[str, Any]

# Type for a sink function: called with (chunk, err) where chunk is
# a UdpChunk dict or None, and err is an error string or None.
UdpSink = Callable[..., Any]

# Type for a source function: returns data string or None
UdpSource = Callable[[], Optional[Union[str, bytes]]]


def _create_udp_socket(
    localport: Optional[int] = None,
) -> _socket_mod.socket:
    """
    Create a configured UDP socket.

    Mirrors the Lua ``_createUdpSocket`` local function.

    Parameters
    ----------
    localport : int, optional
        If provided, the socket will be bound to ``('', localport)``
        for receiving on a specific port.

    Returns
    -------
    socket.socket
        A configured, non-blocking UDP socket with broadcast enabled.

    Raises
    ------
    OSError
        If the socket cannot be created or configured.
    """
    sock = _socket_mod.socket(
        _socket_mod.AF_INET,
        _socket_mod.SOCK_DGRAM,
    )

    try:
        sock.setsockopt(
            _socket_mod.SOL_SOCKET,
            _socket_mod.SO_BROADCAST,
            1,
        )
        sock.setblocking(False)

        if localport is not None:
            sock.setsockopt(
                _socket_mod.SOL_SOCKET,
                _socket_mod.SO_REUSEADDR,
                1,
            )
            sock.bind(("", localport))

    except OSError:
        sock.close()
        raise

    return sock


class SocketUdp(SocketBase):
    """
    A socket for UDP datagram communication.

    Subclass of :class:`SocketBase`.  Mirrors ``jive.net.SocketUdp``
    from the Lua original.

    The sink receives chunks that are dicts with the following keys:

    - ``data`` : the received datagram data (bytes)
    - ``ip``   : the source IP address (str)
    - ``port`` : the source port (int)

    ``None`` is never sent to the sink as end-of-stream because the
    UDP source cannot determine when the "stream" ends.

    Parameters
    ----------
    jnt : NetworkThread or None
        The network thread coordinator.
    sink : callable
        A main-thread sink function ``sink(chunk, err=None)`` that
        receives incoming UDP datagrams.  ``chunk`` is a dict with
        ``data``, ``ip``, ``port`` keys.
    name : str
        Human-readable name for debugging.  Defaults to ``""``.
    localport : int, optional
        If provided, bind to this local UDP port for receiving.
    """

    __slots__ = ("_queue",)

    def __init__(
        self,
        jnt: Optional[NetworkThread] = None,
        sink: Optional[UdpSink] = None,
        name: str = "",
        localport: Optional[int] = None,
    ) -> None:
        super().__init__(jnt, name)

        self._queue: List[UdpSink] = []

        try:
            sock = _create_udp_socket(localport)
        except OSError as exc:
            log.error("SocketUdp: failed to create socket: %s", exc)
            return

        self.t_sock = sock

        # Register the read pump if we have a sink
        if sink is not None:
            read_pump = self._t_get_read_pump(sink)
            self.t_add_read(read_pump, 0)  # 0 = no timeout

    # ------------------------------------------------------------------
    # Read pump
    # ------------------------------------------------------------------

    def _t_get_read_pump(self, sink: UdpSink) -> Callable[..., Optional[bool]]:
        """
        Build and return a pump function for reading UDP data.

        The pump reads one datagram per call from the socket and
        forwards it to the sink as a ``UdpChunk`` dict.

        Parameters
        ----------
        sink : callable
            The sink to forward received data to.

        Returns
        -------
        callable
            A pump function suitable for ``t_add_read()``.
        """
        sock_self = self

        def _read_pump(network_err: Optional[str] = None) -> Optional[bool]:
            if network_err:
                log.error("SocketUdp:readPump() error: %s", network_err)
                return None

            if sock_self.t_sock is None:
                return None

            try:
                data, addr = sock_self.t_sock.recvfrom(65536)
                if data is not None:
                    chunk: UdpChunk = {
                        "data": data,
                        "ip": addr[0],
                        "port": addr[1],
                    }
                    try:
                        sink(chunk)
                    except Exception as exc:
                        log.error("SocketUdp: sink error: %s", exc)
            except BlockingIOError:
                # No data available right now (EWOULDBLOCK / EAGAIN)
                pass
            except OSError as exc:
                log.error("SocketUdp:readPump: %s", exc)

            return None  # Always yield back — select will wake us

        return _read_pump

    # ------------------------------------------------------------------
    # Write support
    # ------------------------------------------------------------------

    def _t_get_sink(
        self,
        address: str,
        port: int,
    ) -> UdpSink:
        """
        Build a sink function that sends UDP datagrams to the
        given address and port.

        Parameters
        ----------
        address : str
            The destination IP address or broadcast address.
        port : int
            The destination UDP port.

        Returns
        -------
        callable
            A sink function ``sink(chunk, err=None)``.
        """
        sock_self = self

        def _send_sink(
            chunk: Optional[Union[str, bytes]] = None,
            err: Optional[str] = None,
        ) -> Optional[int]:
            if chunk and chunk != "" and chunk != b"":
                if sock_self.t_sock is not None:
                    if isinstance(chunk, str):
                        chunk = chunk.encode("utf-8")
                    try:
                        return sock_self.t_sock.sendto(chunk, (address, port))
                    except OSError as exc:
                        log.error("SocketUdp: sendto error: %s", exc)
                        return None
            return 1

        return _send_sink

    def _t_get_write_pump(
        self,
        source: UdpSource,
    ) -> Callable[..., Optional[bool]]:
        """
        Build a pump function for writing UDP data.

        The pump pulls one sink from the internal queue per call,
        gets data from the source, and sends it.  When the queue is
        empty the write pump removes itself.

        Parameters
        ----------
        source : callable
            A source function that returns data to send, or ``None``
            when exhausted.

        Returns
        -------
        callable
            A pump function suitable for ``t_add_write()``.
        """
        sock_self = self

        def _write_pump(network_err: Optional[str] = None) -> Optional[bool]:
            if network_err:
                log.error("SocketUdp:writePump() error: %s", network_err)
                # Fall through to dequeue logic

            if not sock_self._queue:
                sock_self.t_remove_write()
                return None

            send_sink = sock_self._queue.pop(0)

            # Get data from the source and pipe to the sink
            try:
                data = source()
                if data is not None:
                    send_sink(data)
            except Exception as exc:
                log.warn("SocketUdp:writePump: %s", exc)

            return None

        return _write_pump

    def send(
        self,
        source: UdpSource,
        address: str,
        port: int,
    ) -> None:
        """
        Send data obtained through *source* to the given *address*
        and *port*.

        The source is a callable that returns the data to send (a
        string or bytes), or ``None`` when there is no more data.

        Multiple sends can be queued; they will be processed in
        order.

        Parameters
        ----------
        source : callable
            A source function ``source()`` that returns data to send.
        address : str
            Destination IP address or broadcast address.
        port : int
            Destination UDP port.
        """
        if self.t_sock is None:
            log.warn("SocketUdp:send() called on closed socket")
            return

        if len(self._queue) == 0:
            # Start writing — register the write pump
            self.t_add_write(self._t_get_write_pump(source), 60)

        self._queue.append(self._t_get_sink(address, port))

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"SocketUdp({self.js_name!r})"

    def __str__(self) -> str:
        return f"SocketUdp {{{self.js_name}}}"
