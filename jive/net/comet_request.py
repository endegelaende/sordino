"""
jive.net.comet_request — Comet/Bayeux HTTP request over POST.

Ported from ``jive/net/CometRequest.lua`` in the original jivelite project.

CometRequest encapsulates a Comet HTTP request over POST HTTP.  It is
a subclass of :class:`RequestHttp` that automatically:

* Encodes the request body as JSON (the Comet/Bayeux message data)
* Decodes the JSON response body
* Supports both concatenated and chunked response modes (determined
  by the presence of a ``Transfer-Encoding`` response header)

The Lua original uses LTN12 source/sink chains with ``jsonfilters``
for encoding/decoding.  In Python we use the standard ``json`` module
(already wrapped in ``jive.utils.jsonfilters``).

The key difference between CometRequest and RequestJsonRpc is that
CometRequest:

* Does not use the JSON-RPC envelope (method/params/id) — instead it
  sends raw Bayeux protocol messages as a JSON array.
* Supports chunked transfer encoding for long-lived streaming
  connections (Comet long-polling / streaming).
* The response sink mode is determined dynamically based on the
  ``Transfer-Encoding`` response header.

For streaming (chunked) connections, the server may send multiple
JSON arrays concatenated within a single HTTP chunk, or a single
JSON array may span multiple chunks.  This class uses a persistent
decode buffer and ``json.JSONDecoder.raw_decode()`` to correctly
handle both cases.

Convention from the Lua original: methods prefixed with ``t_`` are
conceptually "thread-side" operations.  In this Python port everything
runs cooperatively in the main event loop, but we preserve the naming
convention for traceability back to the Lua source.

Usage::

    from jive.net.comet_request import CometRequest

    def my_sink(data, err=None, request=None):
        if err:
            print(f"error: {err}")
        elif data:
            print(f"received Comet response: {data}")

    # Create a CometRequest with Bayeux message data
    data = [{"channel": "/meta/handshake", "version": "1.0"}]
    req = CometRequest(my_sink, 'http://192.168.1.1:9000/cometd', data)

    # Use a SocketHttp to fetch
    http.fetch(req)

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import json as _json
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Union,
)

from jive.net.request_http import RequestHttp
from jive.utils.jsonfilters import decode as json_decode
from jive.utils.jsonfilters import encode as json_encode
from jive.utils.log import logger

__all__ = ["CometRequest"]

log = logger("net.comet")


def _get_body_source(data: Any) -> Callable[[], Optional[str]]:
    """
    Create a body source callable that returns the JSON-encoded
    request data on first call and ``None`` on subsequent calls.

    Mirrors the Lua ``_getBodySource`` function that chains a
    one-shot source through ``jsonfilters.encode``.

    Parameters
    ----------
    data : Any
        The Bayeux protocol message data (typically a list of dicts)
        to encode as JSON in the request body.

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
        return json_encode(data)

    return _source


# Reusable JSON decoder for raw_decode() — avoids creating one per call
_JSON_DECODER = _json.JSONDecoder()


class CometRequest(RequestHttp):
    """
    A Comet/Bayeux HTTP request over POST.

    Subclass of :class:`RequestHttp`.  Mirrors ``jive.net.CometRequest``
    from the Lua original.

    Automatically encodes the request body as JSON (Bayeux messages)
    and decodes the JSON response body.  Supports both concatenated
    and chunked response modes for Comet streaming.

    For streaming (chunked) connections, the server may deliver:

    * Multiple complete JSON arrays in one HTTP chunk (concatenated),
      e.g. ``[{...}][{...}]``
    * A single JSON array split across multiple HTTP chunks (partial),
      e.g. chunk 1 = ``[{"channel":"/meta/co``, chunk 2 = ``nnect"...}]``

    We handle both cases with a persistent ``_chunk_buffer`` and
    ``json.JSONDecoder.raw_decode()`` which parses one JSON value
    from the start of a string and reports where it ended.

    Parameters
    ----------
    sink : callable or None
        A main-thread sink function that receives the decoded JSON
        response data (a Python list of Bayeux message dicts).
        Called as:

        - ``sink(data, err=None, request=None)`` — decoded JSON data
        - ``sink(None, err, request=None)`` — on error

    uri : str
        The URI of the Comet/Bayeux service on the HTTP server
        (e.g., ``'http://192.168.1.1:9000/cometd'``).

    data : Any
        The Bayeux protocol message data to send.  Typically a list
        of dicts representing Bayeux messages (handshake, connect,
        subscribe, etc.).

    options : dict, optional
        Additional options passed to :class:`RequestHttp`.  If not
        provided, defaults to setting ``Content-Type: text/json``.
        The ``t_body_source`` option is set automatically by this
        class.
    """

    __slots__ = ("_chunk_buffer",)

    def __init__(
        self,
        sink: Optional[Callable[..., Any]] = None,
        uri: str = "/",
        data: Any = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        # Default options with Content-Type header
        if options is None:
            options = {
                "headers": {
                    "Content-Type": "text/json",
                },
            }

        # Set the body source to encode our data as JSON
        options["t_body_source"] = _get_body_source(data)

        # Buffer for accumulating partial JSON across HTTP chunks.
        # Only used in ``jive-by-chunk`` (streaming) mode.
        self._chunk_buffer: str = ""

        # Initialize superclass as a POST request
        super().__init__(
            sink=sink,
            method="POST",
            uri=uri,
            options=options,
        )

    # ------------------------------------------------------------------
    # Response sink mode override
    # ------------------------------------------------------------------

    def t_get_response_sink_mode(self) -> str:
        """
        Return the response sink mode based on the Transfer-Encoding
        response header.

        For Comet streaming connections, the server sends chunked
        transfer encoding, and we want to process each chunk as it
        arrives.  For regular responses (no Transfer-Encoding), we
        concatenate all data before processing.

        Returns
        -------
        str
            ``"jive-by-chunk"`` if the response uses Transfer-Encoding
            (chunked), ``"jive-concat"`` otherwise.
        """
        if self.t_get_response_header("transfer-encoding"):
            return "jive-by-chunk"
        return "jive-concat"

    # ------------------------------------------------------------------
    # Response body override
    # ------------------------------------------------------------------

    def t_set_response_body(self, data: Optional[Union[str, bytes]]) -> None:
        """
        Process the Comet response body.

        Overrides the base class to decode JSON before passing to the
        response sink.  Only sends data back for HTTP 200 responses;
        for other status codes, the error is forwarded to the sink.

        For chunked (streaming) responses, uses ``raw_decode()`` with
        a persistent ``_chunk_buffer`` to handle:

        * Concatenated JSON values in one chunk: ``[{...}][{...}]``
        * Partial JSON split across chunks: ``[{"chann`` + ``el":...}]``

        Parameters
        ----------
        data : str, bytes, or None
            The raw response body data.  For chunked responses, this
            is called once per chunk.  ``None`` signals end-of-stream.
        """
        sink = self.t_get_response_sink()

        # Abort if we have no sink
        if sink is None:
            return

        # Only send data back for 200 OK
        code, err = self.t_get_response_status()

        if code != 200:
            sink(None, err, self)
            return

        if data is None or data == "" or data == b"":
            # End-of-stream or empty chunk — flush any remaining buffer
            if self._chunk_buffer:
                self._flush_buffer(sink)
            return

        # Convert bytes to str
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")

        # Append to the decode buffer
        self._chunk_buffer += data

        # Extract all complete JSON values from the buffer
        self._flush_buffer(sink)

    def _flush_buffer(self, sink: Callable[..., Any]) -> None:
        """
        Extract and dispatch all complete JSON values from
        ``_chunk_buffer`` using ``raw_decode()``.

        After this call, ``_chunk_buffer`` contains only the
        un-parseable remainder (partial JSON or whitespace).
        """
        buf = self._chunk_buffer

        while buf:
            # Skip leading whitespace
            stripped = buf.lstrip()
            if not stripped:
                buf = ""
                break

            # Update buf to the stripped version so raw_decode
            # indices are correct relative to buf
            buf = stripped

            try:
                decoded, end_idx = _JSON_DECODER.raw_decode(buf)
            except _json.JSONDecodeError:
                # Incomplete JSON — keep the remainder for the next
                # chunk to complete it
                break

            # Dispatch the decoded value to the sink
            try:
                sink(decoded, None, self)
            except Exception as exc:
                log.error("Error in Comet sink callback: %s", exc)

            # Advance past the consumed value
            buf = buf[end_idx:]

        self._chunk_buffer = buf

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"CometRequest({self.t_get_request_string()!r})"

    def __str__(self) -> str:
        return f"CometRequest {{{self.t_get_request_string()}}}"
