"""
jive.net.request_http — HTTP request object for network I/O.

Ported from ``jive/net/RequestHttp.lua`` in the original jivelite project.

RequestHttp encapsulates an HTTP request to be processed by a
SocketHttp.  It stores the request method, URI, headers, body source,
and response handling (status, headers, body sink).

The Lua original uses LTN12 source/sink pipelines for body data flow
and LOOP OOP for class hierarchy.  In Python we use simple callables
for sources and sinks, and standard class inheritance.

Key concepts:

* **Request side**: method (GET/POST), parsed URI, headers, body source
* **Response side**: status code/line, headers, body sink, stream mode
* **Redirect handling**: automatic redirect following (up to 5 hops)

Convention from the Lua original: methods prefixed with ``t_`` are
conceptually "thread-side" operations.  In this Python port everything
runs cooperatively in the main event loop, but we preserve the naming
convention for traceability.

Usage::

    from jive.net.request_http import RequestHttp

    def my_sink(data, err=None, request=None):
        if err:
            print(f"error: {err}")
        elif data:
            print(f"received {len(data)} bytes")
        else:
            print("response complete")

    # GET request
    req = RequestHttp(my_sink, 'GET', 'http://192.168.1.1:9000/xml/status.xml')

    # POST request with body
    def body_source():
        return b"key=value"

    req = RequestHttp(my_sink, 'POST', '/api/endpoint', options={
        't_body_source': body_source,
        'headers': {'Content-Type': 'application/x-www-form-urlencoded'},
    })

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import traceback
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)
from urllib.parse import ParseResult, urlparse

from jive.utils.log import logger

__all__ = ["RequestHttp"]

log = logger("net.http")


def _parse_uri(uri: str) -> Dict[str, Any]:
    """
    Parse a URI string into a dict with components matching the Lua
    ``socket.url.parse()`` output.

    Returns a dict with keys: scheme, host, port, path, query, fragment, params.

    Parameters
    ----------
    uri : str
        The URI to parse.

    Returns
    -------
    dict
        Parsed URI components.
    """
    parsed: ParseResult = urlparse(uri)

    host = parsed.hostname or ""
    port = parsed.port or 80
    path = parsed.path or "/"
    scheme = parsed.scheme or "http"
    query = parsed.query or None
    fragment = parsed.fragment or None

    # Lua's url.parse uses 'params' for path parameters (after ';')
    params = None
    if ";" in (parsed.path or ""):
        path_parts = parsed.path.split(";", 1)
        path = path_parts[0]
        params = path_parts[1] if len(path_parts) > 1 else None

    if not path:
        path = "/"

    return {
        "scheme": scheme,
        "host": host,
        "port": port,
        "path": path,
        "query": query,
        "fragment": fragment,
        "params": params,
    }


def _make_safe(
    source_or_sink: Optional[Callable[..., Any]],
    errstr: str,
) -> Optional[Callable[..., Any]]:
    """
    Wrap a source or sink callable to catch exceptions.

    Mirrors the Lua ``_makeSafe`` function that wraps callbacks with
    ``Task:pcall`` for error protection.

    Parameters
    ----------
    source_or_sink : callable or None
        The function to wrap.
    errstr : str
        A prefix string for error messages.

    Returns
    -------
    callable or None
        The wrapped function, or None if input was None.
    """
    if source_or_sink is None:
        return None

    def _safe_wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return source_or_sink(*args, **kwargs)
        except Exception as exc:
            log.error("%s %s", errstr, exc)
            return None, str(exc)

    return _safe_wrapper


class RequestHttp:
    """
    An HTTP request to be processed by a SocketHttp.

    Mirrors ``jive.net.RequestHttp`` from the Lua original.

    Parameters
    ----------
    sink : callable or None
        A main-thread sink function that receives response data.
        Called as ``sink(data, err=None, request=None)``:

        - ``sink(data)`` — a chunk of response data (str or bytes)
        - ``sink(None)`` — response complete (end-of-data)
        - ``sink(None, err)`` — error occurred

    method : str
        The HTTP method: ``'GET'`` or ``'POST'``.

    uri : str
        The URI to request.  Can be a full URL
        (``http://host:port/path``) or just a path (``/path``).

    options : dict, optional
        Optional parameters:

        - ``t_body_source`` : callable — a source function for POST
          body data.  Returns the body content (str or bytes).
        - ``headers`` : dict — additional request headers to send.
        - ``headers_sink`` : callable — a function to receive response
          headers.
        - ``stream`` : bool — if True, deliver response data chunk by
          chunk instead of concatenating.
    """

    __slots__ = (
        "_method",
        "_uri",
        "_body_source",
        "_body_cache",
        "_request_headers",
        "_response_status_code",
        "_response_status_line",
        "_response_headers",
        "_response_headers_sink",
        "_response_body",
        "_response_done",
        "_response_sink",
        "_response_stream",
        "_options",
        "redirect",
    )

    def __init__(
        self,
        sink: Optional[Callable[..., Any]] = None,
        method: str = "GET",
        uri: str = "/",
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        # Parse the URI
        self._uri: Dict[str, Any] = _parse_uri(uri)

        # Request method
        self._method: str = method

        # Default request headers
        self._request_headers: Dict[str, str] = {}

        # Body source for POST
        self._body_source: Optional[Callable[..., Any]] = None
        self._body_cache: Optional[Union[str, bytes]] = None

        # Response state
        self._response_status_code: Optional[int] = None
        self._response_status_line: Optional[str] = None
        self._response_headers: Optional[Dict[str, str]] = None
        self._response_headers_sink: Optional[Callable[..., Any]] = None
        self._response_body: str = ""
        self._response_done: bool = False
        self._response_sink: Optional[Callable[..., Any]] = sink
        self._response_stream: bool = False

        # Stash options for redirect handling
        self._options: Optional[Dict[str, Any]] = options

        # Redirect counter
        self.redirect: int = 0

        # Process options
        if options is not None:
            # Body source
            self._body_source = options.get("t_body_source")
            if self._body_source is not None and method == "GET":
                log.warn(
                    "Body source provided in HTTP request won't be used by GET request"
                )

            # Additional headers
            extra_headers = options.get("headers")
            if extra_headers:
                for k, v in extra_headers.items():
                    self._request_headers[k] = v

            # Headers sink
            self._response_headers_sink = options.get("headers_sink")

            # Stream mode
            if options.get("stream"):
                self._response_stream = True

        # Set Host header from parsed URI
        if self._uri["host"]:
            host_header = self._uri["host"]
            if self._uri["port"] != 80:
                host_header = f"{host_header}:{self._uri['port']}"
            if "Host" not in self._request_headers:
                self._request_headers["Host"] = host_header

    # ------------------------------------------------------------------
    # URI
    # ------------------------------------------------------------------

    def get_uri(self) -> Dict[str, Any]:
        """
        Return the parsed URI dict.

        Returns
        -------
        dict
            The parsed URI with keys: scheme, host, port, path, query,
            fragment, params.
        """
        return self._uri

    # ------------------------------------------------------------------
    # Request — method, headers, body
    # ------------------------------------------------------------------

    def t_has_body(self) -> bool:
        """
        Return whether the request has a body to send (i.e., is POST).

        Returns
        -------
        bool
        """
        return self._method == "POST"

    def t_body(self) -> Optional[Union[str, bytes]]:
        """
        Return the request body content.

        For POST requests, calls the body source to get the content
        (caching the result for subsequent calls).

        Returns
        -------
        str or bytes or None
            The request body, or None if no body.
        """
        if self._body_cache is None and self.t_has_body():
            source = self.t_get_body_source()
            if source is not None:
                result = source()
                if result is not None:
                    self._body_cache = result
        return self._body_cache

    def t_get_request_string(self) -> str:
        """
        Return the HTTP request line string (e.g., ``"GET /path"``).

        For GET requests, includes query string, params, and fragment.

        Returns
        -------
        str
            The request string (without HTTP version).
        """
        parts: List[str] = [self._method, " ", self._uri["path"]]

        if self._method == "GET":
            if self._uri.get("params"):
                parts.append(";")
                parts.append(self._uri["params"])
            if self._uri.get("query"):
                parts.append("?")
                parts.append(self._uri["query"])
            if self._uri.get("fragment"):
                parts.append("#")
                parts.append(self._uri["fragment"])

        return "".join(parts)

    def t_get_request_headers(self) -> Dict[str, str]:
        """
        Return the request headers dict.

        Returns
        -------
        dict
            Header name → value mapping.
        """
        return self._request_headers

    def t_get_request_header(self, key: str) -> Optional[str]:
        """
        Return a specific request header value.

        Parameters
        ----------
        key : str
            The header name.

        Returns
        -------
        str or None
            The header value, or None if not set.
        """
        return self._request_headers.get(key)

    def t_get_body_source(self) -> Optional[Callable[..., Any]]:
        """
        Return the body source function, wrapped for error safety.

        Returns
        -------
        callable or None
            The safe-wrapped body source, or None.
        """
        return _make_safe(self._body_source, "Body source:")

    # ------------------------------------------------------------------
    # Response — status, headers, body
    # ------------------------------------------------------------------

    def t_set_response_headers(
        self,
        status_code: int,
        status_line: str,
        headers: Dict[str, str],
    ) -> None:
        """
        Set the response status and headers (called by the HTTP socket
        when headers have been fully received).

        Header keys are normalized to lowercase for consistent lookup.

        Parameters
        ----------
        status_code : int
            The HTTP status code (e.g., 200, 404).
        status_line : str
            The full HTTP status line (e.g., ``"HTTP/1.1 200 OK"``).
        headers : dict
            The response headers (original case).
        """
        # Normalize header keys to lowercase
        mapped: Dict[str, str] = {}
        for k, v in headers.items():
            mapped[k.lower()] = v

        self._response_status_code = status_code
        self._response_status_line = status_line
        self._response_headers = mapped

        # Notify headers sink if provided
        if self._response_headers_sink is not None:
            try:
                self._response_headers_sink(headers)
            except Exception as exc:
                log.error("Error in headers sink: %s", exc)

    def t_get_response_header(self, key: str) -> Optional[str]:
        """
        Return a response header value.

        Parameters
        ----------
        key : str
            The header name (case-insensitive).

        Returns
        -------
        str or None
            The header value, or None if not present.
        """
        if self._response_headers is not None:
            return self._response_headers.get(key.lower())
        return None

    def t_get_response_status(self) -> Tuple[Optional[int], Optional[str]]:
        """
        Return the response status code and status line.

        Returns
        -------
        tuple of (int or None, str or None)
            ``(status_code, status_line)``
        """
        return self._response_status_code, self._response_status_line

    def t_get_response_sink_mode(self) -> str:
        """
        Return the response sink mode.

        Returns
        -------
        str
            ``"jive-by-chunk"`` if streaming, ``"jive-concat"`` otherwise.
        """
        if self._response_stream:
            return "jive-by-chunk"
        return "jive-concat"

    def t_get_response_sink(self) -> Optional[Callable[..., Any]]:
        """
        Return the response sink function, wrapped for error safety.

        Returns
        -------
        callable or None
            The safe-wrapped response sink, or None.
        """
        return _make_safe(self._response_sink, "Response sink:")

    def t_set_response_body(self, data: Optional[Union[str, bytes]]) -> None:
        """
        Process response body data (called by the HTTP socket when
        body data has been received).

        Handles:
        - 200 OK: delivers data to sink
        - 301/302/307 redirects: follows the redirect (up to 5 hops)
        - Other errors: delivers error to sink

        Parameters
        ----------
        data : str, bytes, or None
            The response body data.  ``None`` means the response is
            complete (for chunked/streaming) or we're reading headers
            after a redirect.
        """
        sink = self.t_get_response_sink()

        # Abort if we have no sink
        if sink is None:
            return

        code, err = self.t_get_response_status()

        # Handle 200 OK
        if code == 200:
            if self._response_stream:
                sink(data, None, self)
            else:
                if data and data != "" and data != b"":
                    sink(data, None, self)
                    sink(None, None, self)

        # Handle redirects (GET only, up to 5 hops)
        elif code in (301, 302, 307) and self._method == "GET" and self.redirect < 5:
            # Only process redirect when data is None (headers fully read)
            if data is None:
                redirect_url = self.t_get_response_header("location")
                if redirect_url:
                    log.info("%d redirect: %s", code, redirect_url)

                    # Re-parse the redirect URL
                    new_uri = _parse_uri(redirect_url)

                    # Rebuild headers
                    new_headers: Dict[str, str] = {}
                    if self._options and self._options.get("headers"):
                        for k, v in self._options["headers"].items():
                            new_headers[k] = v

                    if new_uri["host"]:
                        host_header = new_uri["host"]
                        if new_uri["port"] != 80:
                            host_header = f"{host_header}:{new_uri['port']}"
                        new_headers["Host"] = host_header

                    self.redirect += 1
                    self._request_headers = new_headers
                    self._uri = new_uri

                    # Reset response state
                    self._response_status_code = None
                    self._response_status_line = None
                    self._response_headers = None
                    self._response_body = ""
                    self._response_done = False

                    # Note: in the Lua original, a new SocketHttp is created
                    # to follow the redirect.  In this port, the caller
                    # (SocketHttp) is responsible for detecting the redirect
                    # and re-fetching.  We set a flag that can be checked.
                    log.debug(
                        "Redirect prepared to %s:%d%s",
                        new_uri["host"],
                        new_uri["port"],
                        new_uri["path"],
                    )

        # Handle errors
        else:
            if not err:
                err = f"HTTP request failed with code {code}"
            sink(None, err, self)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"RequestHttp({self.t_get_request_string()!r})"

    def __str__(self) -> str:
        return f"RequestHttp {{{self.t_get_request_string()}}}"
