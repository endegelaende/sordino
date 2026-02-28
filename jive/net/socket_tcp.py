"""
jive.net.socket_tcp — TCP client socket for network I/O.

Ported from ``jive/net/SocketTcp.lua`` in the original jivelite project.

SocketTcp extends SocketBase to provide TCP connection management.
It stores the remote address and port, tracks connection state, and
overrides the read/write pump registration to automatically detect
when the connection has been established (first successful data
pump means we are connected).

This class is mainly designed as a superclass for SocketHttp and
therefore is not fully useful on its own.

Convention from the Lua original: methods prefixed with ``t_`` are
conceptually "thread-side" operations.  In this Python port everything
runs cooperatively in the main event loop, but we preserve the naming
convention for traceability.

Usage::

    from jive.net.socket_tcp import SocketTcp

    # Create a TCP socket
    sock = SocketTcp(jnt, "192.168.1.1", 9090, "cli")

    # Check connected state
    if sock.connected():
        print(f"{sock} is connected")

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import errno
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
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.net.network_thread import NetworkThread

__all__ = ["SocketTcp"]

log = logger("net.http")


class SocketTcp(SocketBase):
    """
    A TCP socket to send/receive data using the NetworkThread.

    Subclass of :class:`SocketBase`.  Mirrors ``jive.net.SocketTcp``
    from the Lua original.

    Parameters
    ----------
    jnt : NetworkThread or None
        The network thread coordinator.
    address : str
        The hostname or IP address to connect to.
    port : int
        The TCP port number.
    name : str
        Human-readable name for debugging.  Defaults to ``""``.

    Raises
    ------
    ValueError
        If *address* or *port* is not provided.
    """

    __slots__ = ("_tcp_address", "_tcp_port", "_tcp_connected")

    def __init__(
        self,
        jnt: Optional[NetworkThread] = None,
        address: str = "",
        port: int = 0,
        name: str = "",
    ) -> None:
        if not address:
            raise ValueError("Cannot create SocketTcp without hostname/ip address")
        if port is None:
            raise ValueError("Cannot create SocketTcp without port")

        super().__init__(jnt, name)

        self._tcp_address: str = address
        self._tcp_port: int = port
        self._tcp_connected: bool = False

    # ------------------------------------------------------------------
    # Address / Port accessors
    # ------------------------------------------------------------------

    @property
    def address(self) -> str:
        """The remote address (hostname or IP) this socket connects to."""
        return self._tcp_address

    @address.setter
    def address(self, value: str) -> None:
        self._tcp_address = value

    @property
    def port(self) -> int:
        """The remote port this socket connects to."""
        return self._tcp_port

    @port.setter
    def port(self, value: int) -> None:
        self._tcp_port = value

    def t_get_address_port(self) -> Tuple[str, int]:
        """
        Return ``(address, port)`` for this socket.

        Maps to Lua ``t_getAddressPort()``.
        """
        return self._tcp_address, self._tcp_port

    # ------------------------------------------------------------------
    # Connection state
    # ------------------------------------------------------------------

    def connected(self) -> bool:
        """
        Return the connected state of the socket.

        In the Lua original this was mutex-protected for thread safety.
        In our single-threaded Python port no mutex is needed.
        """
        return self._tcp_connected

    def t_set_connected(self, state: bool) -> None:
        """
        Update the connected state.

        Parameters
        ----------
        state : bool
            ``True`` if connected, ``False`` otherwise.
        """
        if state != self._tcp_connected:
            self._tcp_connected = state

    def t_get_connected(self) -> bool:
        """Return the connected state (network-thread side)."""
        return self._tcp_connected

    # ------------------------------------------------------------------
    # Connect
    # ------------------------------------------------------------------

    def t_connect(self) -> Tuple[Optional[int], Optional[str]]:
        """
        Create and initiate a non-blocking TCP connection.

        Returns ``(1, None)`` on success or if connection is in
        progress (non-blocking), or ``(None, error_string)`` on
        failure.

        Maps to Lua ``t_connect()``.
        """
        log.debug("%s: t_connect()", self)

        try:
            # Create a TCP socket (IPv4)
            sock = _socket_mod.socket(
                _socket_mod.AF_INET,
                _socket_mod.SOCK_STREAM,
            )
            sock.setblocking(False)
            self.t_sock = sock

            # Initiate non-blocking connect
            err_code = sock.connect_ex((self._tcp_address, self._tcp_port))

            if err_code == 0:
                # Connected immediately
                return 1, None
            elif err_code in (
                errno.EINPROGRESS,
                errno.EWOULDBLOCK,
                errno.WSAEWOULDBLOCK if hasattr(errno, "WSAEWOULDBLOCK") else -1,
            ):
                # Connection in progress (normal for non-blocking)
                return 1, None
            else:
                err_msg = (
                    _socket_mod.errorTab.get(err_code, f"connect error {err_code}")
                    if hasattr(_socket_mod, "errorTab")
                    else f"connect error {err_code}"
                )
                log.error("SocketTcp:t_connect: %s", err_msg)
                return None, err_msg

        except OSError as exc:
            err_msg = str(exc)
            # On Windows, WSAEWOULDBLOCK (10035) is normal for
            # non-blocking connect
            if (
                getattr(exc, "errno", None)
                in (
                    errno.EINPROGRESS,
                    errno.EWOULDBLOCK,
                )
                or exc.errno == 10035
            ):
                return 1, None
            log.error("SocketTcp:t_connect: %s", err_msg)
            return None, err_msg

    # ------------------------------------------------------------------
    # Lifecycle overrides
    # ------------------------------------------------------------------

    def free(self) -> None:
        """Free the socket.  Calls superclass free."""
        log.debug("free: %s", self)
        super().free()

    def close(self, reason: Optional[str] = None) -> None:
        """
        Close the socket and reset connection state.

        Parameters
        ----------
        reason : str, optional
            A reason string for logging (not used functionally).
        """
        log.debug("close: %s (reason=%s)", self, reason)
        self.t_set_connected(False)
        super().close()

    # ------------------------------------------------------------------
    # Read / Write pump overrides
    # ------------------------------------------------------------------

    def t_add_read(
        self,
        pump: Callable[..., Optional[bool]],
        timeout: int = 60,
    ) -> None:
        """
        Override read pump registration to auto-detect connection.

        Wraps the pump so that on first successful call, the socket
        is marked as connected.
        """
        original_pump = pump
        tcp_self = self

        def _connected_pump(*args: Any, **kwargs: Any) -> Optional[bool]:
            if not tcp_self._tcp_connected:
                tcp_self.t_set_connected(True)
            return original_pump(*args, **kwargs)

        super().t_add_read(_connected_pump, timeout)

    def t_add_write(
        self,
        pump: Callable[..., Optional[bool]],
        timeout: int = 60,
    ) -> None:
        """
        Override write pump registration to auto-detect connection.

        Wraps the pump so that on first successful call, the socket
        is marked as connected.
        """
        original_pump = pump
        tcp_self = self

        def _connected_pump(*args: Any, **kwargs: Any) -> Optional[bool]:
            if not tcp_self._tcp_connected:
                tcp_self.t_set_connected(True)
            return original_pump(*args, **kwargs)

        super().t_add_write(_connected_pump, timeout)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"SocketTcp({self.js_name!r}, "
            f"address={self._tcp_address!r}, "
            f"port={self._tcp_port}, "
            f"connected={self._tcp_connected})"
        )

    def __str__(self) -> str:
        return f"SocketTcp {{{self.js_name}}}"
