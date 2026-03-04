"""
jive.net.socket_tcp_server — TCP server socket for accepting client connections.

Ported from ``jive/net/SocketTcpServer.lua`` in the original jivelite project.

SocketTcpServer extends SocketBase to implement a TCP server that
listens for incoming client connections.  When a client connects,
the ``t_accept()`` method returns a new :class:`SocketTcp` instance
representing the client connection.

This is used for local services within jivelite (e.g., a local
HTTP server for serving artwork or status pages).

The Lua original uses LuaSocket's TCP socket with ``bind()`` and
``listen()`` to accept connections, wrapping each accepted socket
in a new SocketTcp instance.  In Python we use the standard library's
``socket`` module with the same pattern.

Convention from the Lua original: methods prefixed with ``t_`` are
conceptually "thread-side" operations.  In this Python port everything
runs cooperatively in the main event loop, but we preserve the naming
convention for traceability back to the Lua source.

Usage::

    from jive.net.socket_tcp_server import SocketTcpServer

    listener = SocketTcpServer(jnt, "localhost", 9006, "listener")

    def on_connect(network_err=None):
        new_sock = listener.t_accept()
        if new_sock:
            # Set up read/write pumps on the new connection
            new_sock.t_add_read(my_pump_func)

    listener.t_add_read(on_connect)

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013 Adrian Smith (SocketTcpServer implementation)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import socket as _socket_mod
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Optional,
    Tuple,
    Union,
)

from jive.net.socket_base import SocketBase
from jive.net.socket_tcp import SocketTcp
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.net.network_thread import NetworkThread

__all__ = ["SocketTcpServer"]

log = logger("net.http")


class SocketTcpServer(SocketBase):
    """
    A TCP server socket for accepting client connections.

    Subclass of :class:`SocketBase`.  Mirrors
    ``jive.net.SocketTcpServer`` from the Lua original.

    Creates a listening TCP socket bound to the given *address* and
    *port*.  Call :meth:`t_accept` to accept an incoming connection,
    which returns a new :class:`SocketTcp` instance for the client.

    Parameters
    ----------
    jnt : NetworkThread or None
        The network thread coordinator.
    address : str
        The address to bind to (e.g., ``"localhost"``, ``"0.0.0.0"``).
    port : int
        The TCP port to listen on.
    name : str
        Human-readable name for debugging.  Defaults to ``""``.

    Raises
    ------
    ValueError
        If *address* or *port* is not provided.
    OSError
        If the socket cannot be bound or set to listen mode.  In this
        case the constructor returns normally but ``t_sock`` will be
        ``None`` — callers should check for this.

    Notes
    -----
    The Lua original returns ``nil`` from ``__init`` on bind/listen
    failure.  In Python we cannot return ``None`` from ``__init__``,
    so instead we set ``t_sock`` to ``None`` and log a warning.
    Callers should check ``server.t_sock is not None`` before using.
    """

    __slots__ = ("_tcp_address", "_tcp_port", "_connection_count")

    def __init__(
        self,
        jnt: Optional[NetworkThread] = None,
        address: str = "",
        port: int = 0,
        name: str = "",
    ) -> None:
        if not address:
            raise ValueError(
                "Cannot create SocketTcpServer without hostname/ip address"
            )
        if port is None:
            raise ValueError("Cannot create SocketTcpServer without port")

        log.debug("SocketTcpServer:__init__(%s, %s, %d)", name, address, port)

        super().__init__(jnt, name)

        self._tcp_address: str = address
        self._tcp_port: int = port
        self._connection_count: int = 0

        # Create, bind, and listen
        try:
            sock = _socket_mod.socket(
                _socket_mod.AF_INET,
                _socket_mod.SOCK_STREAM,
            )

            # Allow address reuse to avoid "Address already in use" on restart
            sock.setsockopt(
                _socket_mod.SOL_SOCKET,
                _socket_mod.SO_REUSEADDR,
                1,
            )

            sock.bind((address, port))
            sock.listen(10)
            sock.settimeout(1)

            self.t_sock = sock

        except OSError as exc:
            log.warn("SocketTcpServer bind/listen error: %s", exc)
            self.t_sock = None

    # ------------------------------------------------------------------
    # Accept
    # ------------------------------------------------------------------

    def t_accept(self) -> Optional[SocketTcp]:
        """
        Accept an incoming client connection.

        Returns a new :class:`SocketTcp` instance representing the
        client connection, or ``None`` if the accept fails (e.g.,
        timeout, no pending connections).

        Each accepted connection is given a unique name derived from
        this server's name and a connection counter.

        Returns
        -------
        SocketTcp or None
            A new TCP socket for the accepted client, or ``None``
            on failure.
        """
        if self.t_sock is None:
            return None

        try:
            new_sock, addr = self.t_sock.accept()
        except _socket_mod.timeout:
            return None
        except OSError as exc:
            log.warn("SocketTcpServer accept error: %s", exc)
            return None

        self._connection_count += 1

        conn_name = f"{self.js_name} [connection #{self._connection_count}]"

        # Create a SocketTcp wrapper for the accepted connection
        # We use "unknown" for address/port since the Lua original does
        # the same — the actual peer address is available from the
        # underlying socket if needed.
        sock_tcp = SocketTcp(
            jnt=self.jnt,
            address="unknown",
            port=0,  # Will be set below
            name=conn_name,
        )

        # Replace the SocketTcp's socket with the accepted one and
        # mark it as connected
        sock_tcp.t_sock = new_sock
        new_sock.setblocking(False)
        sock_tcp.t_set_connected(True)

        # Store the actual peer address if available
        try:
            peer_addr = new_sock.getpeername()
            sock_tcp._tcp_address = peer_addr[0]
            sock_tcp._tcp_port = peer_addr[1]
        except OSError as exc:
            log.debug("_accept: could not get peer address: %s", exc)

        return sock_tcp

    # ------------------------------------------------------------------
    # Read override — no timeout for server sockets
    # ------------------------------------------------------------------

    def t_add_read(
        self,
        pump: Callable[..., Optional[bool]],
        timeout: int = 0,
    ) -> None:
        """
        Override read pump registration to force timeout to 0 (no timeout).

        Server sockets should never time out while listening —
        they wait indefinitely for incoming connections.

        Parameters
        ----------
        pump : callable
            A function ``pump(network_err=None)`` that handles
            incoming connections (typically calls ``t_accept()``).
        timeout : int
            Ignored — always set to 0 (no timeout).
        """
        super().t_add_read(pump, 0)

    # ------------------------------------------------------------------
    # Address / Port accessors
    # ------------------------------------------------------------------

    @property
    def address(self) -> str:
        """The address this server is bound to."""
        return self._tcp_address

    @property
    def port(self) -> int:
        """The port this server is listening on."""
        return self._tcp_port

    @property
    def connection_count(self) -> int:
        """The total number of connections accepted so far."""
        return self._connection_count

    def t_get_address_port(self) -> Tuple[str, int]:
        """
        Return ``(address, port)`` for this server socket.

        Returns
        -------
        tuple of (str, int)
        """
        return self._tcp_address, self._tcp_port

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"SocketTcpServer({self.js_name!r}, "
            f"address={self._tcp_address!r}, "
            f"port={self._tcp_port}, "
            f"connections={self._connection_count})"
        )

    def __str__(self) -> str:
        return f"SocketTcpServer {{{self.js_name}}}"
