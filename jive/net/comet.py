"""
jive.net.comet — Cometd/Bayeux protocol client for LMS communication.

Ported from ``jive/net/Comet.lua`` in the original jivelite project.

The Comet class implements the Bayeux protocol over HTTP for
bidirectional communication with a Lyrion Music Server (LMS,
formerly Logitech Media Server / SlimServer).  It uses two HTTP
connections:

* **Chunked connection** (``chttp``) — a long-lived streaming
  connection that receives server-pushed events via chunked
  transfer encoding.
* **Request connection** (``rhttp``) — a short-lived connection
  for sending requests and subscriptions to the server.

Protocol flow:
    1. **Handshake** — ``/meta/handshake`` to obtain a ``clientId``
    2. **Connect** — ``/meta/connect`` + ``/meta/subscribe`` to
       establish the streaming connection and subscribe to events
    3. **Subscribe/Request** — ``/slim/subscribe``, ``/slim/request``
       for LMS-specific operations
    4. **Reconnect** — ``/meta/reconnect`` to restore a dropped
       connection using the existing ``clientId``
    5. **Disconnect** — ``/meta/disconnect`` to cleanly close

Reconnection is managed according to server advice (retry interval,
reconnect strategy, backoff).

Convention from the Lua original: methods prefixed with ``t_`` are
conceptually "thread-side" operations.  In this Python port everything
runs cooperatively in the main event loop, but we preserve the naming
convention for traceability back to the Lua source.

Usage::

    from jive.net.comet import Comet

    comet = Comet(jnt, "slimserver")
    comet.set_endpoint("192.168.1.1", 9000, "/cometd")
    comet.connect()

    # Subscribe to an event
    comet.subscribe('/slim/serverstatus', my_callback,
                    player_id, ['serverstatus', 0, 50, 'subscribe:60'])

    # Send a one-shot request
    comet.request(my_callback, player_id, ['status', '-', 1])

    # Disconnect
    comet.disconnect()

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
import random
import re
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from jive.net.comet_request import CometRequest
from jive.net.dns import DNS
from jive.net.socket_http import SocketHttp
from jive.ui.task import PRIORITY_HIGH
from jive.ui.timer import Timer
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.net.network_thread import NetworkThread

__all__ = ["Comet"]

log = logger("net.comet")

# Times are in milliseconds
RETRY_DEFAULT = 5000  # default delay time to retry connection (5s)
MAX_BACKOFF = 60000  # don't wait longer than this before retrying (60s)

# Connection states
UNCONNECTED = "UNCONNECTED"  # not connected
CONNECTING = "CONNECTING"  # handshake request sent
CONNECTED = "CONNECTED"  # handshake completed
UNCONNECTING = "UNCONNECTING"  # disconnect request sent

# Version string for handshake
_JIVE_VERSION = "jivelite-py/0.1.0"


class _Subscription:
    """Internal record for a Comet subscription."""

    __slots__ = (
        "reqid",
        "subscription",
        "playerid",
        "request",
        "func",
        "priority",
        "pending",
    )

    def __init__(
        self,
        reqid: int,
        subscription: str,
        playerid: Optional[str],
        request: Any,
        func: Callable[..., Any],
        priority: Optional[Any] = None,
        pending: bool = True,
    ) -> None:
        self.reqid: int = reqid
        self.subscription: str = subscription
        self.playerid: Optional[str] = playerid
        self.request: Any = request
        self.func: Callable[..., Any] = func
        self.priority: Optional[Any] = priority
        self.pending: bool = pending


class _PendingUnsub:
    """Internal record for a pending unsubscribe request."""

    __slots__ = ("reqid", "subscription")

    def __init__(self, reqid: int, subscription: str) -> None:
        self.reqid: int = reqid
        self.subscription: str = subscription


class _PendingRequest:
    """Internal record for a pending one-shot request."""

    __slots__ = ("reqid", "func", "playerid", "request", "priority")

    def __init__(
        self,
        reqid: int,
        func: Optional[Callable[..., Any]],
        playerid: Optional[str],
        request: Any,
        priority: Optional[Any] = None,
    ) -> None:
        self.reqid: int = reqid
        self.func: Optional[Callable[..., Any]] = func
        self.playerid: Optional[str] = playerid
        self.request: Any = request
        self.priority: Optional[Any] = priority


class Comet:
    """
    Cometd/Bayeux protocol client for LMS communication.

    Mirrors ``jive.net.Comet`` from the Lua original.

    This class manages a persistent connection to a Lyrion Music Server
    using the Bayeux/Cometd protocol over HTTP.  It supports
    subscriptions (for server-push events), one-shot requests, and
    automatic reconnection with configurable advice.

    Notifications emitted via ``jnt.notify()``:

    * ``cometConnected(self)`` — when the Comet connection is established
    * ``cometDisconnected(self, idle_timeout_triggered)`` — when disconnected

    Parameters
    ----------
    jnt : NetworkThread or None
        The network thread coordinator.
    name : str
        Human-readable name for debugging.  Defaults to ``""``.
    """

    __slots__ = (
        "jnt",
        "name",
        "uri",
        "chttp",
        "rhttp",
        "aggressive",
        "isactive",
        "state",
        "client_id",
        "reqid",
        "advice",
        "failures",
        "batch",
        "subs",
        "pending_unsubs",
        "pending_reqs",
        "sent_reqs",
        "notify_callbacks",
        "reconnect_timer",
        "idle_timeout",
        "idle_timer",
        "idle_timeout_triggered",
        "_uuid",
        "_mac",
    )

    def __init__(
        self,
        jnt: Optional[NetworkThread] = None,
        name: str = "",
    ) -> None:
        log.debug("Comet: __init__(%s)", name)

        self.jnt: Optional[NetworkThread] = jnt
        self.name: str = name

        self.uri: Optional[str] = None
        self.chttp: Optional[SocketHttp] = None
        self.rhttp: Optional[SocketHttp] = None

        self.aggressive: bool = False  # aggressive reconnects
        self.isactive: bool = False  # is the connection active
        self.state: str = UNCONNECTED  # connection state

        self.client_id: Optional[str] = None  # clientId from server
        self.reqid: int = 1  # used to identify non-subscription requests
        self.advice: Dict[str, Any] = {}  # advice from server
        self.failures: int = 0  # count of connection failures
        self.batch: int = 0  # are we batching queries?

        self.subs: List[_Subscription] = []  # all subscriptions
        self.pending_unsubs: List[_PendingUnsub] = []  # pending unsubscribes
        self.pending_reqs: List[_PendingRequest] = []  # pending requests
        self.sent_reqs: List[Dict[str, Any]] = []  # sent requests, awaiting response
        self.notify_callbacks: Dict[str, Dict[int, Callable[..., Any]]] = {}

        # Reconnection timer
        self.reconnect_timer: Timer = Timer(0, lambda: self._handle_timer(), once=True)

        # Idle disconnect
        self.idle_timeout: Optional[int] = None  # seconds
        self.idle_timer: Optional[Timer] = None
        self.idle_timeout_triggered: Optional[bool] = None

        # UUID/MAC for handshake — can be set externally
        self._uuid: Optional[str] = None
        self._mac: Optional[str] = None

        # Subscribe to networkConnected events
        if jnt is not None:
            jnt.subscribe(self)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_uuid(self, uuid: Optional[str] = None, mac: Optional[str] = None) -> None:
        """Set the UUID and MAC address for handshake identification."""
        self._uuid = uuid
        self._mac = mac

    def aggressive_reconnect(self, aggressive: bool) -> None:
        """Enable or disable aggressive reconnection behavior."""
        self.aggressive = aggressive

    def set_endpoint(self, ip: str, port: int, path: str = "/cometd") -> None:
        """
        Set the server endpoint for the Comet connection.

        Parameters
        ----------
        ip : str
            The IP address or hostname of the server.
        port : int
            The TCP port of the server.
        path : str
            The absolute path to the Cometd handler.  Defaults to
            ``'/cometd'``.
        """
        log.debug(
            "%s: set_endpoint state=%s, %s, %d, %s",
            self,
            self.state,
            ip,
            port,
            path,
        )

        old_state = self.state

        # Force disconnection
        self._set_state(UNCONNECTED)

        self.uri = f"http://{ip}:{port}{path}"

        # Create two HTTP sockets: one for chunked and one for requests
        self.chttp = SocketHttp(
            jnt=self.jnt, host=ip, port=port, name=f"{self.name}_Chunked"
        )
        self.rhttp = SocketHttp(
            jnt=self.jnt, host=ip, port=port, name=f"{self.name}_Request"
        )

        self.chttp.set_priority(PRIORITY_HIGH)
        self.rhttp.set_priority(PRIORITY_HIGH)

        if old_state in (CONNECTING, CONNECTED):
            # Reconnect
            self._handshake()

    # ------------------------------------------------------------------
    # Connect / Disconnect
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        Initiate a Comet connection.

        If already connected or connecting, this is a no-op.  If
        disconnecting, forces a new connection.
        """
        log.debug("%s: connect state=%s", self, self.state)

        if self.uri is None:
            raise RuntimeError("Cannot connect without setting an endpoint first")

        self.isactive = True

        if self.state in (CONNECTING, CONNECTED):
            return

        if self.state == UNCONNECTING:
            self._set_state(UNCONNECTED)

        self._handshake()

    def disconnect(self) -> None:
        """
        Disconnect from the server.

        If already disconnected or disconnecting, this is a no-op.
        If connecting (handshake in progress), forces immediate
        disconnection.
        """
        log.debug("%s: disconnect state=%s", self, self.state)

        self.isactive = False

        if self.state in (UNCONNECTED, UNCONNECTING):
            return

        if self.state == CONNECTING:
            self._set_state(UNCONNECTED)
            return

        self._disconnect()

    # ------------------------------------------------------------------
    # Network event handler
    # ------------------------------------------------------------------

    def notify_networkConnected(self, *args: Any) -> None:
        """Called when a network connection event occurs."""
        if self.state in (CONNECTING, CONNECTED):
            log.info("%s: Got networkConnected event, will try to reconnect", self)
            self._set_state(UNCONNECTED)
            self.connect()
        else:
            log.debug(
                "%s: Got networkConnected event, but not currently connected",
                self,
            )

    # ------------------------------------------------------------------
    # Subscription API
    # ------------------------------------------------------------------

    def subscribe(
        self,
        subscription: str,
        func: Callable[..., Any],
        playerid: Optional[str] = None,
        request: Optional[Any] = None,
        priority: Optional[Any] = None,
    ) -> None:
        """
        Subscribe to a server event channel.

        The *func* callback will be called whenever the server sends
        data on the subscribed channel.

        Parameters
        ----------
        subscription : str
            The subscription channel (e.g., ``'/slim/serverstatus'``).
        func : callable
            The callback function ``func(event)`` called for each
            server event.
        playerid : str, optional
            The player ID to scope the subscription to, or ``None``
            for server-global subscriptions.
        request : list, optional
            The SlimServer request parameters (e.g.,
            ``['serverstatus', 0, 50, 'subscribe:60']``).
        priority : Any, optional
            Priority level for the subscription.
        """
        req_id = self.reqid

        log.debug(
            "%s: subscribe(%s, %s, reqid:%d, %s, %s, priority:%s)",
            self,
            subscription,
            func,
            req_id,
            playerid,
            request,
            priority,
        )

        # Remember the subscription for re-subscribing on reconnect
        self.subs.append(
            _Subscription(
                reqid=req_id,
                subscription=subscription,
                playerid=playerid,
                request=request if request is not None else [],
                func=func,
                priority=priority,
                pending=True,
            )
        )

        self.reqid = req_id + 1

        # Send immediately unless batching or not connected
        if self.state != CONNECTED or self.batch != 0:
            return

        self._send_pending_requests()

    def unsubscribe(
        self,
        subscription: str,
        func: Optional[Callable[..., Any]] = None,
    ) -> None:
        """
        Unsubscribe from a server event channel.

        Parameters
        ----------
        subscription : str
            The subscription channel.
        func : callable, optional
            If provided, only remove this specific callback.  If
            ``None``, remove all callbacks for the channel.
        """
        req_id = self.reqid

        log.debug(
            "%s: unsubscribe(%s, %s, reqid:%d)",
            self,
            subscription,
            func,
            req_id,
        )

        # Remove from notify list
        if func is not None:
            callbacks = self.notify_callbacks.get(subscription)
            if callbacks is not None:
                callbacks.pop(id(func), None)
        else:
            self.notify_callbacks.pop(subscription, None)

        # If we still have callbacks for this subscription, don't unsubscribe
        callbacks = self.notify_callbacks.get(subscription)
        if callbacks:
            return

        log.debug(
            "No more callbacks for %s, unsubscribing at server",
            subscription,
        )

        # Remove from subs list
        self.subs = [s for s in self.subs if s.subscription != subscription]

        # Add to pending unsubs
        self.pending_unsubs.append(
            _PendingUnsub(reqid=req_id, subscription=subscription)
        )

        self.reqid = req_id + 1

        if self.state != CONNECTED or self.batch != 0:
            return

        self._send_pending_requests()

    def request(
        self,
        func: Optional[Callable[..., Any]],
        playerid: Optional[str] = None,
        request: Optional[Any] = None,
        priority: Optional[Any] = None,
    ) -> int:
        """
        Send a one-shot request to the server.

        Unlike subscriptions, one-shot requests are automatically
        cleaned up after the response is received.

        Parameters
        ----------
        func : callable or None
            The callback function ``func(event)`` called when the
            response is received.  Can be ``None`` for fire-and-forget.
        playerid : str, optional
            The player ID to scope the request to.
        request : list, optional
            The SlimServer request parameters (e.g.,
            ``['status', '-', 1]``).
        priority : Any, optional
            Priority level for the request.

        Returns
        -------
        int
            The request ID assigned to this request, which can be
            used to cancel it via ``remove_request()``.
        """
        req_id = self.reqid

        log.debug(
            "%s: request(%s, reqid:%d, %s, %s, priority:%s)",
            self,
            func,
            req_id,
            playerid,
            request,
            priority,
        )

        self.pending_reqs.append(
            _PendingRequest(
                reqid=req_id,
                func=func,
                playerid=playerid,
                request=request if request is not None else [],
                priority=priority,
            )
        )

        self.reqid = req_id + 1

        # If we're disconnected, try to reconnect
        if self.state in (UNCONNECTED, UNCONNECTING):
            self._reconnect()

        if self.state != CONNECTED or self.batch != 0:
            if self.state != CONNECTED and self.jnt is not None:
                self.jnt.notify("cometDisconnected", self, self.idle_timeout_triggered)
                self.idle_timeout_triggered = None

            return req_id

        self._send_pending_requests()
        return req_id

    def remove_request(self, request_id: int) -> bool:
        """
        Remove a pending or sent request by its ID.

        Parameters
        ----------
        request_id : int
            The request ID to remove.

        Returns
        -------
        bool
            ``True`` if the request was found and removed,
            ``False`` otherwise.
        """
        if self.state == CONNECTED:
            log.warn(
                "Can't remove sent request while connection is active. %d",
                request_id,
            )
            return False

        # Try sent requests
        for i, req in enumerate(self.sent_reqs):
            if req.get("id") == request_id:
                self.sent_reqs.pop(i)
                return True

        # Try pending requests
        for i, req in enumerate(self.pending_reqs):
            if req.reqid == request_id:
                self.pending_reqs.pop(i)
                return True

        log.warn("request not found to remove, unexpected. %d", request_id)
        return False

    # ------------------------------------------------------------------
    # Callback management
    # ------------------------------------------------------------------

    def add_callback(
        self,
        subscription: str,
        func: Callable[..., Any],
    ) -> None:
        """
        Add a callback function for an already-subscribed event.

        Parameters
        ----------
        subscription : str
            The subscription channel.
        func : callable
            The callback function to add.
        """
        log.debug("%s: add_callback(%s, %s)", self, subscription, func)

        if subscription not in self.notify_callbacks:
            self.notify_callbacks[subscription] = {}

        self.notify_callbacks[subscription][id(func)] = func

    def remove_callback(
        self,
        subscription: str,
        func: Callable[..., Any],
    ) -> None:
        """
        Remove a callback function from a subscription.

        Parameters
        ----------
        subscription : str
            The subscription channel.
        func : callable
            The callback function to remove.
        """
        log.debug("%s: remove_callback(%s, %s)", self, subscription, func)

        callbacks = self.notify_callbacks.get(subscription)
        if callbacks is not None:
            callbacks.pop(id(func), None)

    # ------------------------------------------------------------------
    # Batch mode
    # ------------------------------------------------------------------

    def start_batch(self) -> None:
        """Begin batching queries — subscriptions and requests are queued."""
        log.debug("%s: start_batch %d", self, self.batch)
        self.batch += 1

    def end_batch(self) -> None:
        """End batch mode and send all batched queries together."""
        log.debug("%s: end_batch %d", self, self.batch)

        self.batch -= 1
        if self.batch != 0:
            return

        if self.state != CONNECTED:
            return

        self._send_pending_requests()

    # ------------------------------------------------------------------
    # Idle timeout
    # ------------------------------------------------------------------

    def set_idle_timeout(self, idle_timeout: Optional[int]) -> None:
        """
        Set idle timeout: disconnect after *idle_timeout* seconds
        of inactivity since the most recent request.

        Parameters
        ----------
        idle_timeout : int or None
            Seconds of idle time before disconnecting.  ``0`` or
            ``None`` disables the idle timeout.
        """
        self.idle_timeout = idle_timeout

        if not idle_timeout or idle_timeout == 0:
            if self.idle_timer is not None:
                self.idle_timer.stop()
        else:
            self._reset_idle_timer()

    def _reset_idle_timer(self) -> None:
        """Reset the idle disconnect timer."""
        if not self.idle_timeout or self.idle_timeout == 0:
            return

        if self.idle_timer is None:
            comet_self = self

            def _on_idle() -> None:
                if comet_self.state == CONNECTED:
                    log.debug(
                        "%s disconnect after idle_timeout: %s",
                        comet_self,
                        comet_self.idle_timeout,
                    )
                    comet_self.idle_timeout_triggered = True
                    comet_self._disconnect()

            self.idle_timer = Timer(0, _on_idle, once=True)

        self.idle_timer.stop()
        self.idle_timer = Timer(
            self.idle_timeout * 1000,
            lambda: (
                self.idle_timeout_triggered is None
                and self.state == CONNECTED
                and setattr(self, "idle_timeout_triggered", True)  # type: ignore[func-returns-value]
                or self._disconnect()
                if self.state == CONNECTED
                else None
            ),
            once=True,
        )
        self.idle_timer.start()

    # ------------------------------------------------------------------
    # Internal — State management
    # ------------------------------------------------------------------

    def _set_state(self, state: str) -> None:
        """
        Transition to a new connection state and emit notifications.

        Parameters
        ----------
        state : str
            The new state: ``UNCONNECTED``, ``CONNECTING``,
            ``CONNECTED``, or ``UNCONNECTING``.
        """
        if self.state == state:
            return

        # Stop reconnect timer
        self.reconnect_timer.stop()

        # Set state before notifications (re-entrant safety)
        self.state = state
        log.debug("%s: state is %s", self, state)

        if state == CONNECTED:
            self.failures = 0
            if self.jnt is not None:
                self.jnt.notify("cometConnected", self)

        elif state == UNCONNECTED:
            # Force connections closed
            if self.chttp is not None:
                self.chttp.close()
            if self.rhttp is not None:
                self.rhttp.close()

            if self.jnt is not None:
                self.jnt.notify("cometDisconnected", self, self.idle_timeout_triggered)
            self.idle_timeout_triggered = None

    # ------------------------------------------------------------------
    # Internal — Handshake
    # ------------------------------------------------------------------

    def _handshake(self) -> None:
        """Initiate the Bayeux handshake."""
        log.debug("%s: _handshake(), calling: %s", self, self.uri)

        if self.state != UNCONNECTED:
            # Ensure we're in the right state
            if self.state != CONNECTING:
                return

        if not self.isactive:
            log.info("%s: _handshake() connection not active", self)
            return

        # Reset all subscriptions to pending for re-subscription
        for sub in self.subs:
            log.debug(
                "Will re-subscribe to %s id=%d",
                sub.subscription,
                sub.reqid,
            )
            sub.pending = True

            # Remove from sent_reqs to avoid duplicates
            self.sent_reqs = [r for r in self.sent_reqs if r.get("id") != sub.reqid]

        # Reset clientId
        self.client_id = None

        # Build handshake message
        ext: Dict[str, Any] = {"rev": _JIVE_VERSION}
        if self._uuid is not None:
            ext["uuid"] = self._uuid
        if self._mac is not None:
            ext["mac"] = self._mac

        data = [
            {
                "channel": "/meta/handshake",
                "version": "1.0",
                "supportedConnectionTypes": ["streaming"],
                "ext": ext,
            }
        ]

        self._set_state(CONNECTING)

        req = CometRequest(
            sink=self._get_handshake_sink(),
            uri=self.uri,
            data=data,
        )

        if self.chttp is not None:
            self.chttp.fetch(req)

    def _get_handshake_sink(self) -> Callable[..., Any]:
        """Return the sink callback for the handshake response."""
        comet_self = self

        def _sink(
            chunk: Any = None,
            err: Optional[str] = None,
            request: Any = None,
        ) -> None:
            if comet_self.state != CONNECTING:
                return

            if err:
                log.info("%s: _handshake error: %s", comet_self, err)
                comet_self._handle_advice(request)
                return

            if not chunk:
                return

            # chunk should be a list of Bayeux messages
            if isinstance(chunk, list) and len(chunk) > 0:
                data = chunk[0]
            elif isinstance(chunk, dict):
                data = chunk
            else:
                log.warn(
                    "%s: unexpected handshake response: %s", comet_self, type(chunk)
                )
                return

            # Update advice if any
            if data.get("advice"):
                comet_self.advice = data["advice"]
                log.debug("%s: _handshake, advice updated from server", comet_self)

            if data.get("successful"):
                comet_self.client_id = data.get("clientId")
                if data.get("advice"):
                    comet_self.advice = data["advice"]

                log.debug(
                    "%s: _handshake OK, clientId: %s",
                    comet_self,
                    comet_self.client_id,
                )

                # Rewrite clientId in requests to be resent
                if comet_self.client_id:
                    for req in comet_self.sent_reqs:
                        resp = req.get("data", {}).get("response", "")
                        if resp and isinstance(resp, str):
                            # Replace old clientId with new one
                            new_resp = re.sub(
                                r"/([0-9a-zA-Z]+)/",
                                f"/{comet_self.client_id}/",
                                resp,
                                count=1,
                            )
                            if "data" in req:
                                req["data"]["response"] = new_resp

                # Continue with connect phase
                comet_self._connect()
            else:
                log.warn(
                    "%s: _handshake error: %s",
                    comet_self,
                    data.get("error"),
                )
                comet_self._handle_advice()

        return _sink

    # ------------------------------------------------------------------
    # Internal — Connect / Reconnect
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        """Establish the streaming connection after handshake."""
        log.debug("%s: _connect()", self)

        if self.client_id is None:
            log.warn("%s: _connect without clientId", self)
            return

        data = [
            {
                "channel": "/meta/connect",
                "clientId": self.client_id,
                "connectionType": "streaming",
            },
            {
                "channel": "/meta/subscribe",
                "clientId": self.client_id,
                "subscription": f"/{self.client_id}/**",
            },
        ]

        req = CometRequest(
            sink=self._get_event_sink(),
            uri=self.uri,
            data=data,
        )

        if self.chttp is not None:
            self.chttp.fetch(req)

    def _reconnect(self) -> None:
        """Reconnect to the server, trying to maintain the existing clientId."""
        log.debug("%s: _reconnect(), calling: %s", self, self.uri)

        if self.state != UNCONNECTED:
            return

        if not self.isactive:
            log.info("%s: _reconnect() connection not active", self)
            return

        if not self.client_id:
            log.debug(
                "%s: _reconnect error: cannot reconnect without clientId, "
                "handshaking instead",
                self,
            )
            self._handshake()
            return

        data = [
            {
                "channel": "/meta/reconnect",
                "clientId": self.client_id,
                "connectionType": "streaming",
            },
            {
                "channel": "/meta/subscribe",
                "clientId": self.client_id,
                "subscription": f"/{self.client_id}/**",
            },
        ]

        self._set_state(CONNECTING)

        req = CometRequest(
            sink=self._get_event_sink(),
            uri=self.uri,
            data=data,
        )

        if self.chttp is not None:
            self.chttp.fetch(req)

    def _connected(self) -> None:
        """Called when the connect/reconnect phase completes successfully."""
        data: List[Dict[str, Any]] = []

        # Add any un-acknowledged requests to the outgoing data
        for v in self.sent_reqs:
            data.append(v)

        self._send_pending_requests(data)
        self._set_state(CONNECTED)

    def _disconnect(self) -> None:
        """Send a disconnect message to the server."""
        if self.state != CONNECTED:
            return

        log.debug("%s: disconnect()", self)

        # Mark all subs as pending for re-subscription later
        for sub in self.subs:
            log.debug("Will re-subscribe to %s on next connect", sub.subscription)
            sub.pending = True

        # We no longer care about sent request replies
        self.sent_reqs = []

        data = [
            {
                "channel": "/meta/disconnect",
                "clientId": self.client_id,
            }
        ]

        self._set_state(UNCONNECTING)

        req = CometRequest(
            sink=self._get_request_sink(),
            uri=self.uri,
            data=data,
        )

        if self.rhttp is not None:
            self.rhttp.fetch(req)

    # ------------------------------------------------------------------
    # Internal — Pending requests
    # ------------------------------------------------------------------

    def _add_pending_requests(self, data: List[Dict[str, Any]]) -> None:
        """Add all pending unsubs, subscriptions, and requests to *data*."""
        if self.client_id is None:
            return

        # Add pending unsubscribe requests first
        for unsub in self.pending_unsubs:
            msg = {
                "channel": "/slim/unsubscribe",
                "id": unsub.reqid,
                "data": {
                    "unsubscribe": f"/{self.client_id}{unsub.subscription}",
                },
            }
            data.append(msg)
            self.sent_reqs.append(msg)

        self.pending_unsubs = []

        # Add pending subscription requests
        for sub in self.subs:
            if sub.pending:
                cmd = [sub.playerid or "", sub.request]
                subscription_path = f"/{self.client_id}{sub.subscription}"

                msg: Dict[str, Any] = {
                    "channel": "/slim/subscribe",
                    "id": sub.reqid,
                    "data": {
                        "request": cmd,
                        "response": subscription_path,
                    },
                }

                if sub.priority is not None:
                    msg["data"]["priority"] = sub.priority

                # Add callback
                if sub.subscription not in self.notify_callbacks:
                    self.notify_callbacks[sub.subscription] = {}
                self.notify_callbacks[sub.subscription][id(sub.func)] = sub.func

                # Mark as sent
                sub.pending = False

                data.append(msg)
                self.sent_reqs.append(msg)

        # Add pending one-shot requests
        for pending in self.pending_reqs:
            cmd = [pending.playerid or "", pending.request]

            msg = {
                "channel": "/slim/request",
                "data": {
                    "request": cmd,
                    "response": f"/{self.client_id}/slim/request",
                },
            }

            if pending.priority is not None:
                msg["data"]["priority"] = pending.priority

            # Only ask for a response if we have a callback
            if pending.func is not None:
                msg["id"] = pending.reqid

                sub_key = f"/slim/request|{pending.reqid}"
                if sub_key not in self.notify_callbacks:
                    self.notify_callbacks[sub_key] = {}
                self.notify_callbacks[sub_key][id(pending.func)] = pending.func

                self.sent_reqs.append(msg)

            data.append(msg)

        self.pending_reqs = []

    def _send_pending_requests(
        self,
        data: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Send any pending subscriptions and requests."""
        if data is None:
            data = []

        self._add_pending_requests(data)

        if not data:
            return

        log.debug("Sending %d pending request(s)", len(data))

        req = CometRequest(
            sink=self._get_request_sink(),
            uri=self.uri,
            data=data,
        )

        # Cache the IP from chunked connection for the request connection
        if self.chttp is not None and self.rhttp is not None:
            dns = DNS()
            chttp_addr = getattr(self.chttp, "_tcp_address", None)
            if chttp_addr and dns.is_ip(chttp_addr):
                log.debug(
                    "caching chttp ip address: %s for: %s",
                    chttp_addr,
                    self.uri,
                )
                self.rhttp.cached_ip = chttp_addr

        if self.rhttp is not None:
            self.rhttp.fetch(req)

    # ------------------------------------------------------------------
    # Internal — Event / Request sinks
    # ------------------------------------------------------------------

    def _get_event_sink(self) -> Callable[..., Any]:
        """Return the sink callback for the chunked event connection."""
        comet_self = self

        def _sink(
            chunk: Any = None,
            err: Optional[str] = None,
            request: Any = None,
        ) -> None:
            if err:
                log.info("%s: _get_event_sink error: %s", comet_self, err)
                comet_self._handle_advice(request)
                return

            if chunk is not None:
                comet_self._response(chunk)

        return _sink

    def _get_request_sink(self) -> Callable[..., Any]:
        """Return the sink callback for the request connection."""
        comet_self = self

        def _sink(
            chunk: Any = None,
            err: Optional[str] = None,
            request: Any = None,
        ) -> None:
            if err:
                log.info("%s: _get_request_sink error: %s", comet_self, err)
                comet_self._handle_advice(request)
                return

            if chunk is not None:
                comet_self._response(chunk)

        return _sink

    # ------------------------------------------------------------------
    # Internal — Response handling
    # ------------------------------------------------------------------

    def _response(self, chunk: Any) -> None:
        """Handle responses for both request and chunked connections."""
        if not chunk:
            return

        # chunk should be a list of Bayeux event dicts
        events: List[Dict[str, Any]]
        if isinstance(chunk, list):
            events = chunk
        elif isinstance(chunk, dict):
            events = [chunk]
        else:
            log.warn("%s: unexpected response type: %s", self, type(chunk))
            return

        for event in events:
            # Update advice if present
            if event.get("advice"):
                self.advice = event["advice"]
                log.debug("%s: _response, advice updated from server", self)

            # Log response
            channel = event.get("channel", "")
            event_id = event.get("id")

            if event.get("error"):
                log.warn(
                    "%s: _response, %s id=%s failed: %s",
                    self,
                    channel,
                    event_id,
                    event.get("error"),
                )
                if event.get("advice"):
                    self._handle_advice()
                    return
            else:
                log.debug(
                    "%s: _response, %s id=%s OK",
                    self,
                    channel,
                    event_id,
                )

            # Remove request from sent queue
            if event_id is not None:
                try:
                    event_id_int = int(event_id)
                    self.sent_reqs = [
                        r for r in self.sent_reqs if r.get("id") != event_id_int
                    ]
                except (ValueError, TypeError):
                    pass

            # Handle response by channel
            if channel == "/meta/connect":
                if event.get("successful"):
                    self._connected()
                else:
                    self._handle_advice()
                    return

            elif channel == "/meta/disconnect":
                if event.get("successful"):
                    if self.state == UNCONNECTING:
                        self.client_id = None
                        self._set_state(UNCONNECTED)
                else:
                    self._handle_advice()
                    return

            elif channel == "/meta/reconnect":
                if event.get("successful"):
                    self._connected()
                else:
                    self._handle_advice()
                    return

            elif channel in (
                "/meta/subscribe",
                "/meta/unsubscribe",
                "/slim/subscribe",
                "/slim/unsubscribe",
            ):
                # No action needed
                pass

            elif channel == "/slim/request" and event.get("successful"):
                # No action needed
                pass

            elif channel:
                # Data event — dispatch to subscribed callbacks
                subscription = channel

                # Strip clientId from channel
                subscription = re.sub(r"^/[0-9A-Za-z]+", "", subscription)

                onetime_request = False
                if "/slim/request" in subscription:
                    if not event_id:
                        log.error("No id. event")
                        return
                    subscription = f"{subscription}|{event_id}"
                    onetime_request = True

                callbacks = self.notify_callbacks.get(subscription)
                if callbacks:
                    log.debug(
                        "%s: _response, notifying callbacks for %s",
                        self,
                        subscription,
                    )

                    for func in list(callbacks.values()):
                        log.debug("  callback to: %s", func)
                        try:
                            func(event)
                        except Exception as exc:
                            log.error(
                                "Error in callback for %s: %s",
                                subscription,
                                exc,
                            )

                    if onetime_request:
                        self.notify_callbacks.pop(subscription, None)
                else:
                    log.debug(
                        "%s: _response, got data for unsubscribed event, "
                        "ignoring -> %s",
                        self,
                        subscription,
                    )

            else:
                log.warn(
                    "%s: _response, unknown error: %s",
                    self,
                    event.get("error"),
                )
                self._handle_advice()
                return

    # ------------------------------------------------------------------
    # Internal — Advice handling / Reconnection
    # ------------------------------------------------------------------

    def _handle_advice(
        self,
        comet_request: Optional[Any] = None,
    ) -> None:
        """
        Decide what to do after a disconnection or error.

        Uses the server's advice (retry interval, reconnect strategy)
        to schedule a reconnection attempt.
        """
        log.info("%s: _handle_advice state=%s", self, self.state)

        if self.state == UNCONNECTED:
            return

        # Check for HTTP 401 authorization failure
        if comet_request is not None:
            try:
                status_code, _ = comet_request.t_get_response_status()
                if status_code == 401 and self.jnt is not None:
                    self.jnt.notify("cometHttpError", self, comet_request)
            except (AttributeError, TypeError):
                pass

        # Force connection closed
        self._set_state(UNCONNECTED)

        self.failures += 1
        reconnect_type = self.advice.get("reconnect", "retry")
        retry_interval = RETRY_DEFAULT

        try:
            retry_interval = int(self.advice.get("interval", RETRY_DEFAULT))
        except (ValueError, TypeError):
            pass

        if retry_interval == 0:
            # Retry immediately
            pass
        elif self.aggressive:
            # Random interval between 1s and advice.interval
            retry_interval = random.randint(1000, max(1001, retry_interval))
        else:
            # Backoff: multiply by failure count
            retry_interval = retry_interval * self.failures
            if retry_interval > MAX_BACKOFF:
                retry_interval = MAX_BACKOFF

        if reconnect_type == "none":
            self.client_id = None
            log.info(
                "%s: advice is %s, server told us not to reconnect",
                self,
                reconnect_type,
            )
        else:
            log.info(
                "%s: advice is %s, connect in %.1f seconds",
                self,
                reconnect_type,
                retry_interval / 1000.0,
            )

            # Schedule reconnection
            self.reconnect_timer.stop()
            self.reconnect_timer = Timer(
                retry_interval,
                lambda: self._handle_timer(),
                once=True,
            )
            self.reconnect_timer.start()

    def _handle_timer(self) -> None:
        """Called by the reconnect timer to initiate a reconnection."""
        log.debug(
            "%s: _handle_timer state=%s advice=%s",
            self,
            self.state,
            self.advice,
        )

        if self.state != UNCONNECTED:
            log.debug("%s: ignoring timer while %s", self, self.state)
            return

        reconnect_type = self.advice.get("reconnect", "retry")

        if reconnect_type == "handshake":
            self._handshake()
        elif reconnect_type == "retry":
            self._reconnect()

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Comet({self.name!r}, state={self.state!r})"

    def __str__(self) -> str:
        return f"Comet {{{self.name}}}"
