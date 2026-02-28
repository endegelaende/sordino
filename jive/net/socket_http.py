"""
jive.net.socket_http — HTTP client socket with state machine.

Ported from ``jive/net/SocketHttp.lua`` in the original jivelite project.

SocketHttp extends SocketTcp to implement a full HTTP client with a
state-machine-driven send/receive pipeline.  It supports:

* Request queuing and pipelining
* DNS resolution before connect
* Non-blocking connect, send, and receive
* Chunked transfer encoding
* Content-Length-based reads
* Until-close reads
* Keep-alive connection management
* HTTP authentication (Basic)
* HTTP/1.1 protocol

The Lua original uses LuaSocket's ``socket.select()`` with LTN12
source/sink pipelines and custom socket sources/sinks for streaming
data.  In Python we use the standard ``socket`` module with simple
callbacks, preserving the same state machine structure.

State machine (send side):
    t_send_dequeue → t_send_resolve → t_send_connect → t_send_request → t_send_complete → (back to dequeue)

State machine (receive side):
    t_recv_dequeue → t_recv_headers → t_recv_response → t_recv_complete → (back to dequeue)

Convention from the Lua original: methods prefixed with ``t_`` are
conceptually "thread-side" operations.  In this Python port everything
runs cooperatively in the main event loop, but we preserve the naming
convention for traceability.

Usage::

    from jive.net.socket_http import SocketHttp
    from jive.net.request_http import RequestHttp

    http = SocketHttp(jnt, "192.168.1.1", 9000, "slimserver")

    def my_sink(data, err=None, request=None):
        if err:
            print(f"error: {err}")
        elif data:
            print(f"received: {len(data)} bytes")

    req = RequestHttp(my_sink, 'GET', '/xml/status.xml')
    http.fetch(req)

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import base64
import socket as _socket_mod
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

from jive.net.dns import DNS
from jive.net.request_http import RequestHttp
from jive.net.socket_tcp import SocketTcp
from jive.ui.task import Task
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.net.network_thread import NetworkThread

__all__ = ["SocketHttp"]

log = logger("net.http")

# Block size for socket reads
BLOCKSIZE = 4096

# Timeout for socket operations (in seconds)
SOCKET_CONNECT_TIMEOUT = 10  # connect in 10 seconds
SOCKET_BODY_TIMEOUT = 70  # response body in 70 seconds

# HTTP authentication credentials registry
# Key: "ip:port" → credential dict
_credentials: Dict[str, Dict[str, str]] = {}

# User-Agent version string placeholder
_JIVE_VERSION = "jivelite-py/0.1.0"
_MACHINE = "jivelite"
_ARCH = "python"


class SocketHttp(SocketTcp):
    """
    An HTTP socket implementing a state-machine-driven client.

    Subclass of :class:`SocketTcp`.  Mirrors ``jive.net.SocketHttp``
    from the Lua original.

    Manages two state machines:
    - **Send**: dequeue → resolve → connect → send request → complete
    - **Receive**: dequeue → receive headers → receive response → complete

    Requests are queued and processed in order (HTTP pipelining).

    Parameters
    ----------
    jnt : NetworkThread or None
        The network thread coordinator.
    host : str
        The hostname or IP address of the HTTP server.
    port : int
        The TCP port of the HTTP server.
    name : str
        Human-readable name for debugging.  Defaults to ``""``.
    """

    __slots__ = (
        "host",
        "_http_send_state",
        "_http_recv_state",
        "_http_send_requests",
        "_http_send_request",
        "_http_recv_requests",
        "_http_recv_request",
        "_http_protocol",
        "_recv_body_buffer",
        "cached_ip",
    )

    def __init__(
        self,
        jnt: Optional[NetworkThread] = None,
        host: str = "",
        port: int = 80,
        name: str = "",
    ) -> None:
        log.debug("SocketHttp:__init__(%s, %s, %d)", name, host, port)

        super().__init__(jnt=jnt, address=host, port=port, name=name)

        # The original hostname (before DNS resolution)
        self.host: str = host

        # Send state machine
        self._http_send_state: str = "t_send_dequeue"
        self._http_send_requests: List[RequestHttp] = []
        self._http_send_request: Optional[RequestHttp] = None

        # Receive state machine
        self._http_recv_state: str = "t_recv_dequeue"
        self._http_recv_requests: List[RequestHttp] = []
        self._http_recv_request: Optional[RequestHttp] = None

        # HTTP protocol version
        self._http_protocol: str = "1.1"

        # Buffer for leftover data between header and body parsing
        self._recv_body_buffer: bytes = b""

        # Cached IP address (for DNS bypass)
        self.cached_ip: Optional[str] = None

    # ------------------------------------------------------------------
    # Class methods for HTTP authentication
    # ------------------------------------------------------------------

    @classmethod
    def set_credentials(
        cls,
        ipport: Tuple[str, int],
        realm: str,
        username: str,
        password: str,
    ) -> None:
        """
        Set HTTP authentication credentials for a server.

        Parameters
        ----------
        ipport : tuple of (str, int)
            The IP address and port as a tuple.
        realm : str
            The authentication realm.
        username : str
            The username.
        password : str
            The password.
        """
        key = f"{ipport[0]}:{ipport[1]}"
        _credentials[key] = {
            "ipport": key,
            "realm": realm,
            "username": username,
            "password": password,
        }

    # ------------------------------------------------------------------
    # Fetch — queue a request
    # ------------------------------------------------------------------

    def fetch(self, request: RequestHttp) -> None:
        """
        Queue an HTTP request for processing.

        The request is added to the send queue and the state machine
        is kicked if idle.

        Parameters
        ----------
        request : RequestHttp
            The HTTP request to fetch.
        """
        self._http_send_requests.append(request)

        log.debug(
            "%s queuing %s - %d requests in queue",
            self,
            request,
            len(self._http_send_requests),
        )

        # Start the state machine if idle
        self.t_send_dequeue_if_idle()

    # ------------------------------------------------------------------
    # Send state machine
    # ------------------------------------------------------------------

    def _t_next_send_state(
        self,
        go: bool,
        new_state: Optional[str] = None,
    ) -> None:
        """
        Advance the send state machine.

        Parameters
        ----------
        go : bool
            If True, immediately call the new state function.
        new_state : str, optional
            The new state to transition to.
        """
        log.debug(
            "%s:_t_next_send_state(%s, %s)",
            self,
            go,
            new_state,
        )

        if new_state is not None:
            method = getattr(self, new_state, None)
            if method is None or not callable(method):
                log.error("Unknown send state: %s", new_state)
                return
            self._http_send_state = new_state

        if go:
            method = getattr(self, self._http_send_state, None)
            if method is not None:
                method()

    def _dequeue_request(self) -> Optional[RequestHttp]:
        """
        Remove and return the next request from the send queue.

        Can be overridden by subclasses (e.g., SocketHttpQueue).

        Returns
        -------
        RequestHttp or None
            The next request, or None if the queue is empty.
        """
        if self._http_send_requests:
            return self._http_send_requests.pop(0)
        return None

    def t_send_dequeue(self) -> None:
        """
        Dequeue the next request from the send queue.

        If a request is available, transitions to either
        ``t_send_resolve`` (if not connected) or ``t_send_request``
        (if already connected).
        """
        log.debug("%s:t_send_dequeue()", self)

        self._http_send_request = self._dequeue_request()

        if self._http_send_request is not None:
            log.debug(
                "%s send processing %s",
                self,
                self._http_send_request,
            )
            if self.connected():
                self._t_next_send_state(True, "t_send_request")
            else:
                self._t_next_send_state(True, "t_send_resolve")

    def t_send_dequeue_if_idle(self) -> None:
        """
        Cause a dequeue and processing on the send queue if the
        state machine is idle (in dequeue state).
        """
        log.debug(
            "%s:t_send_dequeue_if_idle state=%s",
            self,
            self._http_send_state,
        )

        if self._http_send_state == "t_send_dequeue":
            self._t_next_send_state(True)

    def t_send_resolve(self) -> None:
        """
        Resolve the hostname to an IP address before connecting.

        If the address is already an IP, skips DNS and goes directly
        to connect.  If a cached IP is available, uses that.
        """
        log.debug("%s:t_send_resolve()", self)

        dns = DNS()

        if self.cached_ip:
            log.debug(
                "Using cached ip address: %s for: %s",
                self.cached_ip,
                self.host,
            )
            self.address = self.cached_ip
            self._t_next_send_state(True, "t_send_connect")
            return

        if dns.is_ip(self.host):
            # Don't look up an IP address
            self.address = self.host
            self._t_next_send_state(True, "t_send_connect")
            return

        # Perform DNS resolution
        log.debug("%s DNS lookup for %s", self, self.host)
        ip, err = dns.toip(self.host)

        # Check the socket hasn't been closed during resolution
        if self._http_send_state != "t_send_resolve":
            log.debug("%s socket closed during DNS request", self)
            return

        log.debug("%s IP=%s", self, ip)
        if ip is None:
            err_msg = (
                f"{self.host} {err}" if err else f"{self.host} DNS resolution failed"
            )
            self.close(err_msg)
            return

        self.address = ip
        self._t_next_send_state(True, "t_send_connect")

    def t_send_connect(self) -> None:
        """
        Open (connect) the TCP socket.

        On failure, closes the socket with the error.
        """
        log.debug("%s:t_send_connect()", self)

        result, err = self.t_connect()

        if err is not None and result is None:
            log.error("%s:t_send_connect: %s", self, err)
            self.close(err)
            return

        self._t_next_send_state(True, "t_send_request")

    def _t_get_send_headers(self) -> Dict[str, str]:
        """
        Calculate the headers to send from the socket's perspective.

        Combines socket-level headers (User-Agent, Host, Content-Length,
        Accept-Language, Authorization) with request-specific headers.

        Returns
        -------
        dict
            Header name → value mapping.
        """
        log.debug("%s:_t_get_send_headers()", self)

        headers: Dict[str, str] = {
            "User-Agent": f"SqueezePlay-{_MACHINE}/{_JIVE_VERSION} ({_ARCH})",
        }

        ip, port = self.t_get_address_port()

        req_headers = self._http_send_request.t_get_request_headers()

        # Set Host header if not already provided
        if "Host" not in req_headers:
            if port == 80:
                headers["Host"] = self.host
            else:
                headers["Host"] = f"{self.host}:{port}"

        # Set Content-Length for POST requests
        if self._http_send_request.t_has_body():
            body = self._http_send_request.t_body()
            if body is not None:
                if isinstance(body, str):
                    headers["Content-Length"] = str(len(body.encode("utf-8")))
                else:
                    headers["Content-Length"] = str(len(body))

        # Accept-Language
        req_headers["Accept-Language"] = "en"

        # HTTP authentication
        cred_key = f"{ip}:{port}"
        cred = _credentials.get(cred_key)
        if cred:
            auth_str = f"{cred['username']}:{cred['password']}"
            b64 = base64.b64encode(auth_str.encode("utf-8")).decode("ascii")
            req_headers["Authorization"] = f"Basic {b64}"

        return headers

    def t_send_request(self) -> None:
        """
        Send the HTTP request (headers and body) to the server.

        Builds the full HTTP request string and writes it to the
        socket using a write pump.
        """
        log.debug("%s:t_send_request()", self)

        if self._http_send_request is None:
            return

        if self.t_sock is None:
            log.error("%s:t_send_request: no socket", self)
            self.close("no socket")
            return

        # Build the request data
        request_line = (
            f"{self._http_send_request.t_get_request_string()} "
            f"HTTP/{self._http_protocol}"
        )

        lines: List[str] = [request_line]

        # Add socket-level headers
        for k, v in self._t_get_send_headers().items():
            lines.append(f"{k}: {v}")

        # Add request-level headers
        for k, v in self._http_send_request.t_get_request_headers().items():
            lines.append(f"{k}: {v}")

        lines.append("")  # Empty line separating headers from body

        if self._http_send_request.t_has_body():
            body = self._http_send_request.t_body()
            if body is not None:
                if isinstance(body, bytes):
                    body = body.decode("utf-8", errors="replace")
                lines.append(body)
        else:
            lines.append("")

        request_data = "\r\n".join(lines)
        request_bytes = request_data.encode("utf-8")

        # State for the non-blocking send
        send_offset = [0]
        sock_self = self

        def _send_pump(network_err: Optional[str] = None) -> Optional[bool]:
            """Pump function that sends request data."""
            log.debug("%s:t_send_request._send_pump()", sock_self)

            if network_err:
                log.error(
                    "%s:t_send_request._send_pump: %s",
                    sock_self,
                    network_err,
                )
                sock_self.close(network_err)
                return None

            if sock_self.t_sock is None:
                return None

            try:
                sent = sock_self.t_sock.send(request_bytes[send_offset[0] :])
                send_offset[0] += sent

                if send_offset[0] >= len(request_bytes):
                    # All data sent
                    sock_self.t_remove_write()
                    sock_self._t_next_send_state(True, "t_send_complete")
                    return None
                else:
                    # More data to send — timeout will keep us going
                    return None

            except BlockingIOError:
                # Would block — try again on next select cycle
                return None
            except OSError as exc:
                if "timeout" in str(exc).lower():
                    return None
                log.error(
                    "%s:t_send_request._send_pump: %s",
                    sock_self,
                    exc,
                )
                sock_self.close(str(exc))
                return None

        self.socket_active()
        self.t_add_write(_send_pump, SOCKET_CONNECT_TIMEOUT)

    def t_send_complete(self) -> None:
        """
        Called when the request has been fully sent.

        Moves the request to the receive queue and dequeues the next
        send request.
        """
        if self._http_send_request is not None:
            self._http_recv_requests.append(self._http_send_request)
            self._http_send_request = None

        self._t_next_send_state(True, "t_send_dequeue")

        if self._http_recv_state == "t_recv_dequeue":
            self._t_next_recv_state(True)

    # ------------------------------------------------------------------
    # Receive state machine
    # ------------------------------------------------------------------

    def _t_next_recv_state(
        self,
        go: bool,
        new_state: Optional[str] = None,
    ) -> None:
        """
        Advance the receive state machine.

        Parameters
        ----------
        go : bool
            If True, immediately call the new state function.
        new_state : str, optional
            The new state to transition to.
        """
        log.debug(
            "%s:_t_next_recv_state(%s, %s)",
            self,
            go,
            new_state,
        )

        if new_state is not None:
            method = getattr(self, new_state, None)
            if method is None or not callable(method):
                log.error("Unknown recv state: %s", new_state)
                return
            self._http_recv_state = new_state

        if go:
            method = getattr(self, self._http_recv_state, None)
            if method is not None:
                method()

    def t_recv_dequeue(self) -> None:
        """
        Dequeue the next request from the receive queue.

        If a request is waiting, transitions to ``t_recv_headers``
        to read the response.  If no requests are pending and we
        are connected, sets up an idle close handler.
        """
        log.debug(
            "%s:t_recv_dequeue() queueLength=%d",
            self,
            len(self._http_recv_requests),
        )

        if self._http_recv_request is not None:
            log.warn("Already dequeued in t_recv_dequeue")

        if self._http_recv_requests:
            self._http_recv_request = self._http_recv_requests.pop(0)
            log.debug(
                "%s recv processing %s",
                self,
                self._http_recv_request,
            )
            self._t_next_recv_state(True, "t_recv_headers")
            return

        # No requests — back to idle
        log.debug("%s: no request recv in queue", self)

        if self.connected():
            # Set up a pump that closes the socket on idle data
            sock_self = self

            def _idle_pump(network_err: Optional[str] = None) -> Optional[bool]:
                sock_self.close("idle close")
                return None

            self.t_add_read(_idle_pump)

    def t_recv_headers(self) -> None:
        """
        Read HTTP response headers from the socket.

        Sets up a read pump that reads lines until an empty line
        is encountered (end of headers), then parses the status
        line and headers.
        """
        log.debug("%s:t_recv_headers()", self)

        sock_self = self
        recv_buffer = [b""]
        status_code = [None]
        status_line = [None]
        headers: Dict[str, str] = {}

        def _headers_pump(network_err: Optional[str] = None) -> Optional[bool]:
            log.debug("%s:t_recv_headers._headers_pump()", sock_self)

            if network_err:
                log.error(
                    "%s:t_recv_headers._headers_pump: %s",
                    sock_self,
                    network_err,
                )
                sock_self.close(network_err)
                return None

            if sock_self.t_sock is None:
                return None

            # Read available data
            try:
                chunk = sock_self.t_sock.recv(BLOCKSIZE)
                if not chunk:
                    # Connection closed
                    sock_self.close("connection closed during headers")
                    return None
                recv_buffer[0] += chunk
            except BlockingIOError:
                # No data available yet
                return None
            except OSError as exc:
                if "timeout" in str(exc).lower():
                    return None
                log.error(
                    "%s:t_recv_headers._headers_pump: %s",
                    sock_self,
                    exc,
                )
                sock_self.close(str(exc))
                return None

            # Try to parse complete lines from buffer
            while True:
                idx = recv_buffer[0].find(b"\r\n")
                if idx == -1:
                    # No complete line yet
                    return None

                line_bytes = recv_buffer[0][:idx]
                recv_buffer[0] = recv_buffer[0][idx + 2 :]

                try:
                    line = line_bytes.decode("utf-8", errors="replace")
                except Exception:
                    line = line_bytes.decode("latin-1")

                # Parse status line
                if status_code[0] is None:
                    # e.g., "HTTP/1.1 200 OK"
                    parts = line.split(" ", 2)
                    if len(parts) >= 2 and parts[0].startswith("HTTP/"):
                        try:
                            status_code[0] = int(parts[1])
                            status_line[0] = line
                        except ValueError:
                            sock_self.close("malformed status line")
                            return None
                    else:
                        sock_self.close("malformed status line")
                        return None
                    continue

                # Parse header line or detect end of headers
                if line != "":
                    colon_idx = line.find(":")
                    if colon_idx == -1:
                        log.warn("malformed response header: %s", line)
                        sock_self.close("malformed response headers")
                        return None

                    name = line[:colon_idx].strip()
                    value = line[colon_idx + 1 :].strip()
                    headers[name] = value
                else:
                    # Empty line — end of headers
                    sock_self._http_recv_request.t_set_response_headers(
                        status_code[0],
                        status_line[0],
                        headers,
                    )

                    # Store any leftover data in buffer for body reading
                    sock_self._recv_body_buffer = recv_buffer[0]

                    # Move on to response body
                    sock_self._t_next_recv_state(True, "t_recv_response")
                    return None

            return None

        self.t_add_read(_headers_pump, SOCKET_BODY_TIMEOUT)

    def t_recv_response(self) -> None:
        """
        Read the HTTP response body.

        Determines the transfer mode (chunked, content-length, or
        until-close) and sets up the appropriate read pump.
        """
        if self._http_recv_request is None:
            return

        transfer_encoding = self._http_recv_request.t_get_response_header(
            "transfer-encoding"
        )
        content_length_str = self._http_recv_request.t_get_response_header(
            "content-length"
        )
        connection_close = (
            self._http_recv_request.t_get_response_header("connection") == "close"
        )

        if transfer_encoding == "chunked":
            mode = "chunked"
            # Don't count chunked connections as active (long-lived)
            self.socket_inactive()
        elif content_length_str is not None:
            mode = "by-length"
        else:
            mode = "until-closed"

        sink_mode = self._http_recv_request.t_get_response_sink_mode()

        # Build the appropriate read pump
        sock_self = self
        body_buffer = getattr(self, "_recv_body_buffer", b"")
        self._recv_body_buffer = b""

        if mode == "chunked":
            self._recv_chunked(sink_mode, connection_close, body_buffer)
        elif mode == "by-length":
            content_length = int(content_length_str)
            self._recv_by_length(
                sink_mode, connection_close, content_length, body_buffer
            )
        else:
            self._recv_until_closed(sink_mode, connection_close, body_buffer)

    def _deliver_to_sink(
        self,
        sink_mode: str,
        data_chunks: List[bytes],
        final_data: Optional[bytes],
    ) -> None:
        """
        Deliver response data to the request's sink.

        Parameters
        ----------
        sink_mode : str
            ``"jive-concat"`` or ``"jive-by-chunk"``.
        data_chunks : list of bytes
            Accumulated data chunks (for concat mode).
        final_data : bytes or None
            Final chunk of data (for by-chunk mode), or None on completion.
        """
        if self._http_recv_request is None:
            return

        if sink_mode == "jive-concat":
            blob = b"".join(data_chunks)
            try:
                text = blob.decode("utf-8", errors="replace")
            except Exception:
                text = blob.decode("latin-1")
            self._http_recv_request.t_set_response_body(text)
        elif sink_mode == "jive-by-chunk":
            if final_data is not None:
                try:
                    text = final_data.decode("utf-8", errors="replace")
                except Exception:
                    text = final_data.decode("latin-1")
                self._http_recv_request.t_set_response_body(text)
            else:
                self._http_recv_request.t_set_response_body(None)

    def _recv_complete(self, connection_close: bool) -> None:
        """
        Called when response body reading is complete.

        Removes the read handler, optionally closes the connection,
        and transitions to ``t_recv_complete``.
        """
        self.t_remove_read()

        if connection_close:
            # Close the TCP socket but don't reset HTTP state
            SocketTcp.close(self)

        self._t_next_recv_state(True, "t_recv_complete")

    def _recv_by_length(
        self,
        sink_mode: str,
        connection_close: bool,
        content_length: int,
        initial_data: bytes,
    ) -> None:
        """
        Read response body with known Content-Length.
        """
        sock_self = self
        remaining = [content_length]
        data_chunks: List[bytes] = []

        # Process any data we already have from header reading
        if initial_data:
            data_chunks.append(initial_data)
            remaining[0] -= len(initial_data)

            if remaining[0] <= 0:
                # Already have all data
                self._deliver_to_sink(sink_mode, data_chunks, None)
                self._recv_complete(connection_close)
                return

        def _body_pump(network_err: Optional[str] = None) -> Optional[bool]:
            if network_err:
                log.error(
                    "%s:_recv_by_length._body_pump: %s",
                    sock_self,
                    network_err,
                )
                sock_self.close(network_err)
                return None

            if sock_self.t_sock is None:
                return None

            try:
                size = min(BLOCKSIZE, remaining[0])
                chunk = sock_self.t_sock.recv(size)

                if not chunk:
                    # Connection closed prematurely
                    sock_self._deliver_to_sink(sink_mode, data_chunks, None)
                    sock_self._recv_complete(connection_close)
                    return None

                if sink_mode == "jive-by-chunk":
                    sock_self._deliver_to_sink(sink_mode, [], chunk)

                data_chunks.append(chunk)
                remaining[0] -= len(chunk)

                if remaining[0] <= 0:
                    # Done reading
                    if sink_mode == "jive-concat":
                        sock_self._deliver_to_sink(sink_mode, data_chunks, None)
                    else:
                        # Signal completion for by-chunk mode
                        sock_self._deliver_to_sink(sink_mode, [], None)
                    sock_self._recv_complete(connection_close)
                    return None

            except BlockingIOError:
                return None
            except OSError as exc:
                if "timeout" in str(exc).lower():
                    return None
                log.error(
                    "%s:_recv_by_length._body_pump: %s",
                    sock_self,
                    exc,
                )
                sock_self.close(str(exc))

            return None

        self.t_add_read(_body_pump, SOCKET_BODY_TIMEOUT)

    def _recv_until_closed(
        self,
        sink_mode: str,
        connection_close: bool,
        initial_data: bytes,
    ) -> None:
        """
        Read response body until the connection is closed.
        """
        sock_self = self
        data_chunks: List[bytes] = []

        if initial_data:
            data_chunks.append(initial_data)

        def _body_pump(network_err: Optional[str] = None) -> Optional[bool]:
            if network_err:
                log.error(
                    "%s:_recv_until_closed._body_pump: %s",
                    sock_self,
                    network_err,
                )
                sock_self.close(network_err)
                return None

            if sock_self.t_sock is None:
                return None

            try:
                chunk = sock_self.t_sock.recv(BLOCKSIZE)

                if not chunk:
                    # Connection closed — done
                    if sink_mode == "jive-concat":
                        sock_self._deliver_to_sink(sink_mode, data_chunks, None)
                    else:
                        sock_self._deliver_to_sink(sink_mode, [], None)

                    # Close the TCP socket
                    SocketTcp.close(sock_self)
                    sock_self._recv_complete(False)
                    return None

                if sink_mode == "jive-by-chunk":
                    sock_self._deliver_to_sink(sink_mode, [], chunk)

                data_chunks.append(chunk)

            except BlockingIOError:
                return None
            except OSError as exc:
                if "timeout" in str(exc).lower():
                    return None

                # Treat connection reset as normal close
                if sink_mode == "jive-concat":
                    sock_self._deliver_to_sink(sink_mode, data_chunks, None)
                else:
                    sock_self._deliver_to_sink(sink_mode, [], None)

                SocketTcp.close(sock_self)
                sock_self._recv_complete(False)

            return None

        self.t_add_read(_body_pump, SOCKET_BODY_TIMEOUT)

    def _recv_chunked(
        self,
        sink_mode: str,
        connection_close: bool,
        initial_data: bytes,
    ) -> None:
        """
        Read chunked transfer-encoded response body.

        Parses chunk sizes and data according to HTTP/1.1 chunked
        transfer encoding specification.
        """
        sock_self = self
        buf = [initial_data]
        data_chunks: List[bytes] = []

        # Chunked parsing state:
        # 1 = reading chunk size line
        # 2 = reading chunk data
        # 3 = reading chunk terminator (CRLF after data)
        chunk_state = [1]
        chunk_remaining = [0]

        def _body_pump(network_err: Optional[str] = None) -> Optional[bool]:
            if network_err:
                log.error(
                    "%s:_recv_chunked._body_pump: %s",
                    sock_self,
                    network_err,
                )
                sock_self.close(network_err)
                return None

            if sock_self.t_sock is None:
                return None

            # Read more data from socket
            try:
                new_data = sock_self.t_sock.recv(BLOCKSIZE)
                if not new_data:
                    # Connection closed unexpectedly during chunked read
                    if sink_mode == "jive-concat":
                        sock_self._deliver_to_sink(sink_mode, data_chunks, None)
                    else:
                        sock_self._deliver_to_sink(sink_mode, [], None)
                    sock_self._recv_complete(connection_close)
                    return None
                buf[0] += new_data
            except BlockingIOError:
                pass
            except OSError as exc:
                if "timeout" in str(exc).lower():
                    pass
                else:
                    log.error(
                        "%s:_recv_chunked._body_pump: %s",
                        sock_self,
                        exc,
                    )
                    sock_self.close(str(exc))
                    return None

            # Process buffered data
            while True:
                if chunk_state[0] == 1:
                    # Reading chunk size line
                    idx = buf[0].find(b"\r\n")
                    if idx == -1:
                        return None  # Need more data

                    size_line = buf[0][:idx].decode("ascii", errors="replace")
                    buf[0] = buf[0][idx + 2 :]

                    # Strip chunk extensions (after ';')
                    size_str = size_line.split(";")[0].strip()
                    try:
                        chunk_size = int(size_str, 16)
                    except ValueError:
                        log.error("invalid chunk size: %s", size_str)
                        sock_self.close("invalid chunk size")
                        return None

                    if chunk_size == 0:
                        # Last chunk — done
                        if sink_mode == "jive-concat":
                            sock_self._deliver_to_sink(sink_mode, data_chunks, None)
                        else:
                            sock_self._deliver_to_sink(sink_mode, [], None)
                        sock_self._recv_complete(connection_close)
                        return None

                    chunk_remaining[0] = chunk_size
                    chunk_state[0] = 2

                elif chunk_state[0] == 2:
                    # Reading chunk data
                    available = len(buf[0])
                    if available == 0:
                        return None  # Need more data

                    to_read = min(available, chunk_remaining[0])
                    chunk_data = buf[0][:to_read]
                    buf[0] = buf[0][to_read:]
                    chunk_remaining[0] -= to_read

                    if sink_mode == "jive-by-chunk":
                        sock_self._deliver_to_sink(sink_mode, [], chunk_data)
                    data_chunks.append(chunk_data)

                    if chunk_remaining[0] == 0:
                        chunk_state[0] = 3

                elif chunk_state[0] == 3:
                    # Reading chunk terminator CRLF
                    if len(buf[0]) < 2:
                        return None  # Need more data

                    # Skip the CRLF
                    buf[0] = buf[0][2:]
                    chunk_state[0] = 1

            return None

        self.t_add_read(_body_pump, SOCKET_BODY_TIMEOUT)

    def t_recv_complete(self) -> None:
        """
        Called when response reception is complete.

        Marks the socket as inactive and dequeues the next receive
        request.
        """
        self.socket_inactive()
        self._http_recv_request = None
        self._t_next_recv_state(True, "t_recv_dequeue")

    # ------------------------------------------------------------------
    # Lifecycle overrides
    # ------------------------------------------------------------------

    def free(self) -> None:
        """
        Free the socket and dump all request queues.
        """
        log.debug("%s:free()", self)

        self._http_send_requests = []
        self._http_send_request = None
        self._http_recv_requests = []
        self._http_recv_request = None

        super().free()

    def close(self, err: Optional[str] = None) -> None:
        """
        Close the socket and cancel all pending/in-flight requests.

        Error sinks are called for requests that were in progress.

        Parameters
        ----------
        err : str, optional
            The error reason for logging and sink notification.
        """
        log.debug("%s closing with err: %s", self, err)

        # Close the underlying TCP socket
        SocketTcp.close(self, err)

        # Capture and clear in-flight requests
        error_send_request = self._http_send_request
        error_recv_requests = list(self._http_recv_requests)

        if self._http_recv_request is not None:
            error_recv_requests.insert(0, self._http_recv_request)

        self._http_send_request = None
        self._http_recv_request = None
        self._http_recv_requests = []

        # Restart state machines
        self._t_next_send_state(True, "t_send_dequeue")
        self._t_next_recv_state(True, "t_recv_dequeue")

        # Notify error sinks — state must be updated before here,
        # as the error sinks may re-enter with new requests
        if error_send_request is not None:
            error_sink = error_send_request.t_get_response_sink()
            if error_sink is not None:
                try:
                    error_sink(None, err)
                except Exception as exc:
                    log.error("Error in error sink: %s", exc)

        for request in error_recv_requests:
            error_sink = request.t_get_response_sink()
            if error_sink is not None:
                try:
                    error_sink(None, err)
                except Exception as exc:
                    log.error("Error in error sink: %s", exc)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"SocketHttp({self.js_name!r}, "
            f"host={self.host!r}, "
            f"port={self.port}, "
            f"send_state={self._http_send_state!r})"
        )

    def __str__(self) -> str:
        return f"SocketHttp {{{self.js_name}}}"
