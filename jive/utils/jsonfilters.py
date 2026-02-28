"""
jive.utils.jsonfilters — JSON encode/decode filters.

Ported from share/jive/jive/utils/jsonfilters.lua

Provides simple JSON encoding and decoding functions that act as
"filters" in the LTN12 (Lua Technical Note 12) streaming sense.
In the original Lua code these are used with ``ltn12.source.chain``
and ``ltn12.sink.chain`` to transform data flowing through a
source/sink pipeline.

In Python, the streaming-filter pattern is less common (we typically
just call ``json.loads`` / ``json.dumps`` directly), but we preserve
the same API shape so that code ported from Lua can call
``jsonfilters.decode(chunk)`` and ``jsonfilters.encode(chunk)``
with identical semantics — including the ``None`` and empty-string
pass-through behavior.

Usage::

    from jive.utils.jsonfilters import encode, decode

    # Decode a JSON string into a Python object
    data = decode('{"name": "Squeezebox", "volume": 50}')
    # → {"name": "Squeezebox", "volume": 50}

    # Encode a Python object into a JSON string
    text = encode({"name": "Squeezebox", "volume": 50})
    # → '{"name": "Squeezebox", "volume": 50}'

    # None and empty-string pass through unchanged (LTN12 convention)
    assert decode(None) is None
    assert decode("") == ""
    assert encode(None) is None
    assert encode("") == ""

Copyright 2010 Logitech. All Rights Reserved.
This file is licensed under BSD. Please see the LICENSE file for details.
"""

from __future__ import annotations

import json
from typing import Any, Optional, Union


def decode(chunk: Optional[Union[str, bytes]]) -> Any:
    """
    Decode a JSON chunk (string) into a Python object.

    Replicates the LTN12 filter convention from the Lua original:

    - ``None`` → ``None`` (end-of-stream signal)
    - ``""`` → ``""`` (empty chunk, no data to decode)
    - otherwise → ``json.loads(chunk)``

    Args:
        chunk: A JSON-encoded string, an empty string, or ``None``.

    Returns:
        The decoded Python object (dict, list, str, int, float, bool,
        or ``None``), or the pass-through value for ``None`` / ``""``.

    Raises:
        json.JSONDecodeError: If *chunk* is a non-empty string that
            is not valid JSON.

    Examples:
        >>> decode('{"a": 1}')
        {'a': 1}
        >>> decode('[1, 2, 3]')
        [1, 2, 3]
        >>> decode('"hello"')
        'hello'
        >>> decode('42')
        42
        >>> decode(None) is None
        True
        >>> decode("")
        ''
    """
    if chunk is None:
        return None
    if chunk == "" or chunk == b"":
        return ""
    return json.loads(chunk)


def encode(chunk: Any) -> Optional[str]:
    """
    Encode a Python object into a JSON string.

    Replicates the LTN12 filter convention from the Lua original:

    - ``None`` → ``None`` (end-of-stream signal)
    - ``""`` → ``""`` (empty chunk, no data to encode)
    - otherwise → ``json.dumps(chunk)``

    Note: The Lua original uses ``cjson.encode`` which produces
    compact JSON (no extra whitespace). We match this by using
    ``json.dumps`` with ``separators=(",", ":")`` for compact output.

    Args:
        chunk: A Python object to encode, an empty string, or ``None``.

    Returns:
        A compact JSON string, or the pass-through value for
        ``None`` / ``""``.

    Raises:
        TypeError: If *chunk* is not JSON-serializable.

    Examples:
        >>> encode({"a": 1})
        '{"a":1}'
        >>> encode([1, 2, 3])
        '[1,2,3]'
        >>> encode("hello")
        '"hello"'
        >>> encode(42)
        '42'
        >>> encode(None) is None
        True
        >>> encode("")
        ''
    """
    if chunk is None:
        return None
    if chunk == "":
        return ""
    return json.dumps(chunk, separators=(",", ":"), ensure_ascii=False)
