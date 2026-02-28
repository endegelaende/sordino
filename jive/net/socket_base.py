"""
jive.net.socket_base — Abstract base socket for network I/O.

Ported from ``jive/net/Socket.lua`` in the original jivelite project.

The base Socket class provides:

* A name for debugging/logging
* A reference to the NetworkThread (``jnt``) coordinator
* Read/write pump registration via Task-based generators
* Socket lifecycle management (open/close/free)
* Priority control for scheduling
* Network activity tracking (active/inactive notifications)

In the Lua original, Socket uses LuaSocket's ``socket.select()`` for
multiplexing and LOOP OOP for class hierarchy.  In Python we use the
standard ``socket`` module and plain class inheritance, with the
cooperative Task scheduler from ``jive.ui.task`` for pump functions.

Convention from the Lua original: methods prefixed with ``t_`` are
conceptually "thread-side" operations (executed in the network thread
context).  In this Python port there is no separate thread — everything
runs cooperatively in the main event loop — but we preserve the naming
convention for traceability back to the Lua source.

Usage::

    from jive.net.socket_base import SocketBase

    class MySocket(SocketBase):
        def __init__(self, jnt, name=""):
            super().__init__(jnt, name)

        def t_connect(self):
            ...

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
    Optional,
    Union,
)

from jive.ui.task import PRIORITY_LOW, Task
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.net.network_thread import NetworkThread

__all__ = ["SocketBase"]

log = logger("net.socket")


class SocketBase:
    """
    Abstract base class for all network sockets.

    Mirrors ``jive.net.Socket`` from the Lua original.

    Parameters
    ----------
    jnt : NetworkThread or None
        The network thread coordinator that manages select-based I/O.
        May be ``None`` for testing or when not yet connected.
    name : str
        Human-readable name for debugging/logging.  Defaults to ``""``.
    """

    __slots__ = (
        "jnt",
        "js_name",
        "t_sock",
        "priority",
        "active",
        "read_pump",
        "write_pump",
    )

    def __init__(self, jnt: Optional[NetworkThread] = None, name: str = "") -> None:
        self.jnt: Optional[NetworkThread] = jnt
        self.js_name: str = name or ""
        self.t_sock: Optional[_socket_mod.socket] = None
        self.priority: Optional[int] = None
        self.active: bool = False
        self.read_pump: Optional[Callable[..., Any]] = None
        self.write_pump: Optional[Callable[..., Any]] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def free(self) -> None:
        """Free (and close) the socket, releasing all resources."""
        log.debug("free: %s", self)
        self.close()

    def close(self) -> None:
        """
        Close the underlying OS socket and unregister read/write pumps.

        After close, ``t_sock`` is set to ``None``.
        """
        log.debug("close: %s", self)

        if self.t_sock is not None:
            self.t_remove_read()
            self.t_remove_write()
            try:
                self.t_sock.close()
            except OSError:
                pass
            self.t_sock = None

            self.socket_inactive()

    # ------------------------------------------------------------------
    # Priority
    # ------------------------------------------------------------------

    def set_priority(self, priority: int) -> None:
        """
        Set the socket priority for scheduling.

        Parameters
        ----------
        priority : int
            One of the ``PRIORITY_*`` constants from ``jive.ui.task``.
        """
        self.priority = priority

    # ------------------------------------------------------------------
    # Network activity tracking
    # ------------------------------------------------------------------

    def socket_active(self) -> None:
        """
        Notify the network thread that this socket is actively
        performing I/O.  Used for power management / UI indicators.
        """
        if not self.active:
            self.active = True
            if self.jnt is not None:
                self.jnt.network_active(self)

    def socket_inactive(self) -> None:
        """
        Notify the network thread that this socket is no longer
        actively performing I/O.
        """
        if self.active:
            self.active = False
            if self.jnt is not None:
                self.jnt.network_inactive(self)

    # ------------------------------------------------------------------
    # Read / Write pump management
    # ------------------------------------------------------------------

    def _make_task_error_handler(self) -> Callable[[Any], None]:
        """Return an error callback that closes this socket on task failure."""

        def _task_error(obj: Any) -> None:
            self.close()

        return _task_error

    def t_add_read(
        self,
        pump: Callable[..., Optional[bool]],
        timeout: int = 60,
    ) -> None:
        """
        Register a read pump function and add the socket to the
        network thread's read-select list.

        The pump is wrapped in a Task that iterates over all read
        operations.  The Task yields when the pump returns ``False``
        (nothing to do right now) and continues when the pump returns
        a truthy value.

        Parameters
        ----------
        pump : callable
            A function ``pump(network_err=None)`` that performs one
            step of reading.  Returns ``True``/truthy to keep reading
            in this tick, or ``False``/falsy to yield.
        timeout : int
            Timeout in seconds for the read operation (0 = no timeout).
        """
        # Build a generator-based task that loops over the pump
        sock_self = self  # capture for the closure

        def _read_task_func(obj: Any, *args: Any) -> Any:
            """Generator that drives the read pump."""
            network_err = args[0] if args else None
            while sock_self.read_pump is not None:
                result = sock_self.read_pump(network_err)
                if not result:
                    # Yield False → suspend, will be resumed by select
                    val = yield False
                    # On resume, val may carry a network error
                    network_err = val
                else:
                    network_err = None

        task = Task(
            f"{self}(R)",
            self,
            _read_task_func,
            self._make_task_error_handler(),
            self.priority if self.priority is not None else PRIORITY_LOW,
        )

        self.read_pump = pump

        if self.jnt is not None:
            self.jnt.t_add_read(self.t_sock, task, timeout)

    def t_remove_read(self) -> None:
        """Unregister the read pump and remove from the read-select list."""
        if self.read_pump is not None:
            self.read_pump = None
            if self.jnt is not None and self.t_sock is not None:
                self.jnt.t_remove_read(self.t_sock)

    def t_add_write(
        self,
        pump: Callable[..., Optional[bool]],
        timeout: int = 60,
    ) -> None:
        """
        Register a write pump function and add the socket to the
        network thread's write-select list.

        Parameters
        ----------
        pump : callable
            A function ``pump(network_err=None)`` that performs one
            step of writing.
        timeout : int
            Timeout in seconds for the write operation (0 = no timeout).
        """
        sock_self = self

        def _write_task_func(obj: Any, *args: Any) -> Any:
            """Generator that drives the write pump."""
            network_err = args[0] if args else None
            while sock_self.write_pump is not None:
                result = sock_self.write_pump(network_err)
                if not result:
                    val = yield False
                    network_err = val
                else:
                    network_err = None

        task = Task(
            f"{self}(W)",
            self,
            _write_task_func,
            self._make_task_error_handler(),
            self.priority if self.priority is not None else PRIORITY_LOW,
        )

        self.write_pump = pump

        if self.jnt is not None:
            self.jnt.t_add_write(self.t_sock, task, timeout)

    def t_remove_write(self) -> None:
        """Unregister the write pump and remove from the write-select list."""
        if self.write_pump is not None:
            self.write_pump = None
            if self.jnt is not None and self.t_sock is not None:
                self.jnt.t_remove_write(self.t_sock)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"SocketBase({self.js_name!r})"

    def __str__(self) -> str:
        return f"Socket {{{self.js_name}}}"
