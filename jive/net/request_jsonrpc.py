"""
jive.net.request_jsonrpc — JSON-RPC request over HTTP POST.

Ported from ``jive/net/RequestJsonRpc.lua`` in the original jivelite project.

RequestJsonRpc implements the JSON-RPC protocol over POST HTTP.  It is
a subclass of :class:`RequestHttp` that automatically:

* Encodes the request body as JSON (method, params, id)
* Decodes the JSON response body
* Generates a unique request ID for correlation

The Lua original uses LTN12 source/sink chains with ``jsonfilters``
for encoding/decoding.  In Python we use the standard ``json`` module
(already wrapped in ``jive.utils.jsonfilters``).

Convention from the Lua original: methods prefixed with ``t_`` are
conceptually "thread-side" operations.  In this Python port everything
runs cooperatively in the main event loop, but we preserve the naming
convention for traceability back to the Lua source.

Usage::

    from jive.net.request_jsonrpc import RequestJsonRpc

    def my_sink(data, err=None, request=None):
        if err:
            print(f"error: {err}")
        elif data:
            print(f"received JSON-RPC response: {data}")

    # Create a JSON-RPC request
    req = RequestJsonRpc(my_sink, '/jsonrpc', 'slim.request', ['', ['serverstatus', 0, 50]])

    # Use a SocketHttp to fetch
    http.fetch(req)

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Union,
)

from jive.net.request_http import RequestHttp
from jive.utils.jsonfilters import decode as json_decode
from jive.utils.jsonfilters import encode as json_encode
from jive.utils.log import logger

__all__ = ["RequestJsonRpc"]

log = logger("net.http")

# Module-level counter for generating unique-ish JSON-RPC IDs when
# the Lua-style id(obj) trick is not applicable.
_next_id: int = 0


def _generate_id(obj: Any) -> str:
    """
    Generate a JSON-RPC request ID.

    The Lua original uses ``string.sub(tostring(json), 9)`` which
    yields a hex memory address.  In Python we use ``id(obj)`` to
    get a similarly unique identifier, formatted as hex for parity.

    Parameters
    ----------
    obj : Any
        The object whose identity contributes to the ID.

    Returns
    -------
    str
        A unique-ish string ID for the request.
    """
    global _next_id
    _next_id += 1
    return f"{id(obj):x}-{_next_id}"


def _get_body_source(json_data: Dict[str, Any]) -> Callable[[], Optional[str]]:
    """
    Create a body source callable that returns the JSON-encoded
    request body on first call and ``None`` on subsequent calls.

    Mirrors the Lua ``_getBodySource`` function that chains a
    one-shot source through ``jsonfilters.encode``.

    Parameters
    ----------
    json_data : dict
        The JSON-RPC request data with keys ``method``, ``params``,
        and ``id``.

    Returns
    -------
    callable
        A source function ``source() -> str | None``.
    """
    sent = False

    def _source() -> Optional[str]:
        nonlocal sent
        if sent:
            return None
        sent = True
        payload = {
            "method": json_data["method"],
            "params": json_data["params"],
            "id": json_data["id"],
        }
        encoded = json_encode(payload)
        return encoded

    return _source


class RequestJsonRpc(RequestHttp):
    """
    A JSON-RPC request over HTTP POST.

    Subclass of :class:`RequestHttp`.  Mirrors ``jive.net.RequestJsonRpc``
    from the Lua original.

    Automatically encodes the request body as JSON and decodes the
    JSON response body.

    Parameters
    ----------
    sink : callable or None
        A main-thread sink function that receives the decoded JSON
        response data (a Python dict/list).  Called as:

        - ``sink(data, err=None, request=None)`` — decoded JSON data
        - ``sink(None, err, request=None)`` — on error

    uri : str
        The URI of the JSON-RPC service on the HTTP server
        (e.g., ``'/jsonrpc'``).

    method : str
        The JSON-RPC method name (e.g., ``'slim.request'``).

    params : list or None
        The JSON-RPC params (a list that will be encoded to JSON).
        Defaults to an empty list.

    options : dict, optional
        Additional options passed to :class:`RequestHttp`.  The
        ``t_body_source`` option is set automatically by this class.
    """

    __slots__ = ("_json",)

    def __init__(
        self,
        sink: Optional[Callable[..., Any]] = None,
        uri: str = "/",
        method: str = "",
        params: Optional[Union[List[Any], Sequence[Any]]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        if params is None:
            params = []

        # Build the JSON-RPC request data
        json_data: Dict[str, Any] = {
            "method": method,
            "params": list(params),
        }

        # Generate a unique ID
        req_id = _generate_id(json_data)
        json_data["id"] = req_id

        # Store for later access
        self._json: Dict[str, Any] = json_data

        # Build options with our body source
        if options is None:
            options = {}
        options["t_body_source"] = _get_body_source(json_data)

        # Initialize superclass as a POST request
        super().__init__(
            sink=sink,
            method="POST",
            uri=uri,
            options=options,
        )

    # ------------------------------------------------------------------
    # Response body override
    # ------------------------------------------------------------------

    def t_set_response_body(self, data: Optional[Union[str, bytes]]) -> None:
        """
        Process the JSON-RPC response body.

        Overrides the base class to decode JSON before passing to the
        response sink.  Only sends data back for HTTP 200 responses;
        for other status codes, the error is forwarded to the sink.

        Parameters
        ----------
        data : str, bytes, or None
            The raw response body data.
        """
        sink = self.t_get_response_sink()

        # Abort if we have no sink
        if sink is None:
            return

        # Only send data back for 200 OK
        code, err = self.t_get_response_status()

        if code == 200:
            if data is not None and data != "" and data != b"":
                try:
                    decoded = json_decode(data)
                except Exception as exc:
                    log.error("JSON decode error: %s", exc)
                    sink(None, str(exc), self)
                    return

                sink(decoded, None, self)
            # Note: unlike the base class, we don't send sink(None) on
            # successful completion here — the Lua original also omits
            # the end-of-stream signal for JSON-RPC responses.
        else:
            sink(None, err, self)

    # ------------------------------------------------------------------
    # JSON-RPC ID
    # ------------------------------------------------------------------

    def get_json_id(self) -> str:
        """
        Return the JSON-RPC ID assigned to this request.

        This ID is included in the JSON-RPC request body and can be
        used to correlate responses with requests.

        Returns
        -------
        str
            The request ID.
        """
        return self._json["id"]

    # ------------------------------------------------------------------
    # Accessors for method and params (convenience)
    # ------------------------------------------------------------------

    @property
    def json_method(self) -> str:
        """The JSON-RPC method name."""
        return self._json["method"]

    @property
    def json_params(self) -> List[Any]:
        """The JSON-RPC params list."""
        return self._json["params"]

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"RequestJsonRpc({self._json['id']!r}, method={self._json['method']!r})"

    def __str__(self) -> str:
        return f"RequestJsonRpc {{{self._json['id']}}}"
