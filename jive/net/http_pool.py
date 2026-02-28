"""
jive.net.http_pool — HTTP connection pool managing multiple sockets.

Ported from ``jive/net/HttpPool.lua`` in the original jivelite project.

HttpPool manages a set of HTTP sockets (:class:`SocketHttpQueue`) and
two queues of requests.  Sockets are opened dynamically as the queue
size grows (controlled by a threshold parameter) and are closed after
a keep-alive timeout when all requests have been serviced.

The pool implements the ``t_dequeue()`` interface expected by
:class:`SocketHttpQueue`, which calls back into the pool to obtain the
next request to process.

Key features:

* **Connection pooling** — up to *quantity* simultaneous HTTP sockets
  to the same server, opened on demand.
* **Request queuing** — incoming requests are queued and dispatched to
  idle sockets.
* **Keep-alive timeout** — idle connections are closed after 60 seconds
  of inactivity to conserve resources.
* **Priority support** — sockets can be assigned a priority level that
  affects their scheduling in the network thread.

Convention from the Lua original: methods prefixed with ``t_`` are
conceptually "thread-side" operations.  In this Python port everything
runs cooperatively in the main event loop, but we preserve the naming
convention for traceability back to the Lua source.

Usage::

    from jive.net.http_pool import HttpPool

    # Create a pool for http://192.168.1.1:9000
    # with max 4 connections, threshold of 2 requests per connection
    pool = HttpPool(jnt, "slimserver", "192.168.1.1", 9000, quantity=4, threshold=2)

    # Queue a request
    pool.queue(my_request)

    # Free all connections
    pool.free()

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    List,
    Optional,
    Tuple,
    Union,
)

from jive.net.request_http import RequestHttp
from jive.net.socket_http_queue import SocketHttpQueue
from jive.ui.timer import Timer
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.net.network_thread import NetworkThread

__all__ = ["HttpPool"]

log = logger("net.http")

# Timeout for idle keep-alive connections (in milliseconds)
KEEPALIVE_TIMEOUT = 60000  # 60 seconds


class HttpPool:
    """
    A connection pool managing multiple HTTP sockets to a single server.

    Mirrors ``jive.net.HttpPool`` from the Lua original.

    The pool maintains an array of :class:`SocketHttpQueue` instances
    (up to *quantity*), a shared request queue, and dispatches requests
    to idle sockets.  When all requests have been serviced, idle
    connections are closed after a keep-alive timeout.

    The pool implements the ``t_dequeue(socket)`` method required by
    :class:`SocketHttpQueue` — each socket calls back into the pool
    to obtain the next request to process.

    Parameters
    ----------
    jnt : NetworkThread or None
        The network thread coordinator.
    name : str
        Human-readable pool name for debugging.  Defaults to ``""``.
    ip : str
        The IP address or hostname of the HTTP server.
    port : int
        The TCP port of the HTTP server.
    quantity : int
        Maximum number of simultaneous connections.  Defaults to 1.
    threshold : int
        The ratio of requests to connections.  When the number of
        pending requests exceeds ``threshold * active_connections``,
        an additional connection is opened (up to *quantity*).
        Defaults to 10.
    priority : int or None
        Optional priority level for the sockets' scheduling in the
        network thread.  One of the ``PRIORITY_*`` constants from
        ``jive.ui.task``, or ``None`` for default.
    """

    __slots__ = (
        "jnt",
        "_pool_name",
        "_pool_sockets",
        "_pool_active",
        "_pool_threshold",
        "_req_queue",
        "_req_queue_count",
        "_timeout_timer",
    )

    def __init__(
        self,
        jnt: Optional[NetworkThread] = None,
        name: str = "",
        ip: str = "",
        port: int = 80,
        quantity: int = 1,
        threshold: int = 10,
        priority: Optional[int] = None,
    ) -> None:
        self.jnt: Optional[NetworkThread] = jnt
        self._pool_name: str = name or ""
        self._pool_active: int = 1
        self._pool_threshold: int = threshold
        self._req_queue: List[Union[RequestHttp, Callable[[], RequestHttp]]] = []
        self._req_queue_count: int = 0
        self._timeout_timer: Optional[Timer] = None

        # Initialize the pool of SocketHttpQueue instances
        q = max(1, quantity)
        self._pool_sockets: List[SocketHttpQueue] = []

        for i in range(q):
            sock = SocketHttpQueue(
                jnt=jnt,
                address=ip,
                port=port,
                queue_obj=self,
                name=f"{self._pool_name}{i + 1}",
            )
            if priority is not None:
                sock.set_priority(priority)
            self._pool_sockets.append(sock)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def free(self) -> None:
        """
        Free the pool — close and free all connections.

        After calling ``free()``, the pool should not be reused.
        """
        for sock in self._pool_sockets:
            sock.free()
        self._pool_sockets.clear()

        if self._timeout_timer is not None:
            self._timeout_timer.stop()
            self._timeout_timer = None

    def close(self) -> None:
        """
        Close all connections to the server.

        Unlike ``free()``, the pool can still be reused after
        ``close()`` — new connections will be opened on demand.
        """
        for sock in self._pool_sockets:
            sock.close()

        if self._timeout_timer is not None:
            self._timeout_timer.stop()
            self._timeout_timer = None

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def queue(self, request: Union[RequestHttp, Callable[[], RequestHttp]]) -> None:
        """
        Queue a request for processing.

        The request is added to the pool's shared queue and dispatched
        to the first available socket.  If the queue grows beyond the
        threshold, additional connections are activated.

        Parameters
        ----------
        request : RequestHttp or callable
            The HTTP request to queue.  Can also be a callable (factory
            function) that returns a :class:`RequestHttp` when called —
            this allows lazy request construction.
        """
        self._req_queue.append(request)
        self._req_queue_count += 1

        # Calculate how many connections should be active.
        # In the Lua original, the active count is simply set to the
        # total number of sockets in the pool (the threshold-based
        # calculation is commented out).  We replicate that behavior.
        self._pool_active = len(self._pool_sockets)

        log.debug(
            "%s: %d requests, %d connections",
            self,
            self._req_queue_count,
            self._pool_active,
        )

        # Kick all active sockets to start processing
        for i in range(self._pool_active):
            if i < len(self._pool_sockets):
                self._pool_sockets[i].t_send_dequeue_if_idle()

    # ------------------------------------------------------------------
    # Dequeue interface (called by SocketHttpQueue)
    # ------------------------------------------------------------------

    def t_dequeue(self, socket: Any) -> Tuple[Optional[RequestHttp], bool]:
        """
        Dequeue the next request from the pool's shared queue.

        This method is called by :class:`SocketHttpQueue` instances
        when they need a new request to process.

        Parameters
        ----------
        socket : SocketHttpQueue
            The socket requesting a new task.

        Returns
        -------
        tuple of (RequestHttp or None, bool)
            A 2-tuple where:

            - The first element is the next request to process, or
              ``None`` if the queue is empty.
            - The second element is ``False`` (the Lua original always
              returns ``False`` for the close flag from ``t_dequeue``).
              Idle connections are managed via the keep-alive timer
              instead of immediate close signals.
        """
        log.debug("%s:t_dequeue()", self)

        if self._req_queue:
            request = self._req_queue.pop(0)

            # If the request is a factory function, call it
            if callable(request) and not isinstance(request, RequestHttp):
                request = request()

            self._req_queue_count -= 1

            log.debug("%s dequeues %s", self, request)

            # Cancel the keep-alive timeout timer since we have work
            if self._timeout_timer is not None:
                self._timeout_timer.stop()
                self._timeout_timer = None

            return request, False

        # Queue is empty — reset the count
        self._req_queue_count = 0

        # Start a keep-alive timeout to close idle connections
        if self._timeout_timer is None:
            pool_self = self

            def _on_timeout() -> None:
                log.debug("%s: closing idle connection", pool_self)
                for i in range(pool_self._pool_active):
                    if i < len(pool_self._pool_sockets):
                        pool_self._pool_sockets[i].close("keep-alive timeout")

            self._timeout_timer = Timer(
                KEEPALIVE_TIMEOUT,
                _on_timeout,
                once=True,
            )
            self._timeout_timer.start()

        # Return None, False — no request available, don't close socket
        # (the socket will go idle until the timeout fires or new
        # requests arrive)
        return None, False

    # ------------------------------------------------------------------
    # Accessors (for testing / inspection)
    # ------------------------------------------------------------------

    @property
    def pool_name(self) -> str:
        """The pool name (for debugging)."""
        return self._pool_name

    @property
    def pool_size(self) -> int:
        """The total number of sockets in the pool."""
        return len(self._pool_sockets)

    @property
    def active_count(self) -> int:
        """The number of currently active socket connections."""
        return self._pool_active

    @property
    def queue_count(self) -> int:
        """The number of requests currently in the queue."""
        return self._req_queue_count

    @property
    def sockets(self) -> List[SocketHttpQueue]:
        """The list of pool sockets (read-only copy)."""
        return list(self._pool_sockets)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"HttpPool({self._pool_name!r}, "
            f"sockets={len(self._pool_sockets)}, "
            f"queue={self._req_queue_count})"
        )

    def __str__(self) -> str:
        return f"HttpPool {{{self._pool_name}}}"
