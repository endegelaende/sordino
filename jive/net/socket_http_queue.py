"""
jive.net.socket_http_queue — HTTP socket with external request queue.

Ported from ``jive/net/SocketHttpQueue.lua`` in the original jivelite project.

SocketHttpQueue is a subclass of :class:`SocketHttp` designed to use an
external request queue (such as the one provided by :class:`HttpPool`)
instead of its own internal queue.

When the internal send queue is empty, ``_dequeue_request()`` delegates
to the external queue object's ``t_dequeue()`` method, which returns
the next request to process (or ``None`` if the queue is empty).

Convention from the Lua original: methods prefixed with ``t_`` are
conceptually "thread-side" operations.  In this Python port everything
runs cooperatively in the main event loop, but we preserve the naming
convention for traceability back to the Lua source.

Usage::

    from jive.net.socket_http_queue import SocketHttpQueue

    # pool is an HttpPool instance that implements t_dequeue()
    sock = SocketHttpQueue(jnt, "192.168.1.1", 9000, pool, "slimserver1")

    # The pool will call sock.t_send_dequeue_if_idle() when it has
    # new requests to process.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Optional,
    Protocol,
    Tuple,
    Union,
)

from jive.net.request_http import RequestHttp
from jive.net.socket_http import SocketHttp
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.net.network_thread import NetworkThread

__all__ = ["SocketHttpQueue"]

log = logger("net.http")


class QueueProvider(Protocol):
    """
    Protocol for external queue providers (e.g., HttpPool).

    Any object passed as ``queue_obj`` to :class:`SocketHttpQueue` must
    implement this interface.
    """

    def t_dequeue(self, socket: Any) -> Tuple[Optional[RequestHttp], bool]:
        """
        Dequeue the next HTTP request from the external queue.

        Parameters
        ----------
        socket : Any
            The SocketHttpQueue instance requesting a new task.

        Returns
        -------
        tuple of (RequestHttp or None, bool)
            A 2-tuple where the first element is the next request to
            process (or ``None`` if the queue is empty), and the second
            element is a boolean indicating whether the connection
            should be closed (``True``) or kept alive (``False``).
        """
        ...


class SocketHttpQueue(SocketHttp):
    """
    A SocketHttp that uses an external request queue.

    Subclass of :class:`SocketHttp`.  Mirrors
    ``jive.net.SocketHttpQueue`` from the Lua original.

    Instead of maintaining its own request queue, this socket delegates
    dequeuing to an external ``queue_obj`` (typically an
    :class:`HttpPool`).  This allows a pool of sockets to share a
    single request queue with intelligent load balancing.

    Parameters
    ----------
    jnt : NetworkThread or None
        The network thread coordinator.
    address : str
        The hostname or IP address of the HTTP server.
    port : int
        The TCP port of the HTTP server.
    queue_obj : QueueProvider
        An object implementing ``t_dequeue(socket)`` that returns
        ``(request, close)`` where *request* is a
        :class:`RequestHttp` or ``None``, and *close* is a bool
        indicating whether to close the connection.
    name : str
        Human-readable name for debugging.  Defaults to ``""``.
    """

    __slots__ = ("_http_queue",)

    def __init__(
        self,
        jnt: Optional[NetworkThread] = None,
        address: str = "",
        port: int = 80,
        queue_obj: Optional[Any] = None,
        name: str = "",
    ) -> None:
        log.debug(
            "SocketHttpQueue:__init__(%s, %s, %d)",
            name,
            address,
            port,
        )

        super().__init__(jnt=jnt, host=address, port=port, name=name)

        self._http_queue: Optional[Any] = queue_obj

    # ------------------------------------------------------------------
    # Dequeue override
    # ------------------------------------------------------------------

    def _dequeue_request(self) -> Optional[RequestHttp]:
        """
        Dequeue a request from the external queue.

        Overrides :meth:`SocketHttp._dequeue_request` to delegate to
        the external queue provider.

        If the queue provider returns ``None`` for the request and
        ``True`` for close, the socket is closed.

        Returns
        -------
        RequestHttp or None
            The next request to process, or ``None`` if the external
            queue is empty.
        """
        log.debug("%s:_dequeue_request()", self)

        if self._http_queue is None:
            # Fall back to internal queue if no external queue
            return super()._dequeue_request()

        request, close = self._http_queue.t_dequeue(self)

        if request is not None:
            return request  # type: ignore[no-any-return]

        if close:
            self.close("queue close")

        return None

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"SocketHttpQueue({self.js_name!r}, host={self.host!r}, port={self.port})"
        )

    def __str__(self) -> str:
        return f"SocketHttpQueue {{{self.js_name}}}"
