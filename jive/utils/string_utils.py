"""
jive.utils.string_utils — String utility functions.

Ported from share/jive/jive/utils/string.lua

Provides string manipulation utilities that extend Python's built-in
string operations, matching the API of the original Lua module.

Usage:
    from jive.utils.string_utils import (
        str2hex,
        trim_null,
        split,
        match_literal,
        url_encode,
        url_decode,
    )

    # Convert string to hex representation
    hex_str = str2hex("ABC")  # "41 42 43 "

    # Trim string at first null byte
    trimmed = trim_null("hello\x00world")  # "hello"

    # Split a string by pattern
    parts = split(",", "a,b,c")  # ["a", "b", "c"]

    # Match a literal string (no regex special chars)
    result = match_literal("file (1).txt", "(1)")  # "(1)"

    # URL encode/decode
    encoded = url_encode("hello world")  # "hello+world"
    decoded = url_decode("hello+world")  # "hello world"

Copyright 2010 Logitech. All Rights Reserved.
This file is licensed under BSD. Please see the LICENSE file for details.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote_plus, unquote_plus


def str2hex(s: str | bytes) -> str:
    """
    Convert a string to its hexadecimal representation.

    Each byte is represented as a two-character uppercase hex value
    followed by a space.

    Equivalent to Lua's ``str2hex(s)`` which replaces each character
    with its ASCII hex value using ``string.format("%02X ")``.

    Args:
        s: The input string or bytes to convert.

    Returns:
        A string of space-separated hex values.

    Examples:
        >>> str2hex("ABC")
        '41 42 43 '
        >>> str2hex("")
        ''
        >>> str2hex(b"\\x00\\xff")
        '00 FF '
    """
    if isinstance(s, str):
        s = s.encode("latin-1", errors="replace")
    return "".join(f"{b:02X} " for b in s)


def trim_null(s: str) -> str:
    """
    Trim a string at the first null byte (``\\x00``).

    Equivalent to Lua's ``trim(s)`` which finds the first ``%z``
    (null byte) and returns the substring before it.

    Args:
        s: The input string.

    Returns:
        The portion of *s* before the first null byte, or the
        entire string if no null byte is found.

    Examples:
        >>> trim_null("hello\\x00world")
        'hello'
        >>> trim_null("no nulls here")
        'no nulls here'
        >>> trim_null("\\x00leading null")
        ''
        >>> trim_null("")
        ''
    """
    idx = s.find("\x00")
    if idx >= 0:
        return s[:idx]
    return s


def split(
    pattern: str,
    s: str,
    result: Optional[list[str]] = None,
) -> list[str]:
    """
    Split a string on a pattern.

    Equivalent to Lua's ``split(inSplitPattern, myString, returnTable)``.

    Note the argument order matches the original Lua function:
    pattern comes first, then the string to split. This differs from
    Python's ``str.split()`` convention but preserves API compatibility.

    When *pattern* is an empty string, the string is split into
    individual characters (matching the Lua behavior).

    When *pattern* is non-empty, it is treated as a plain string
    delimiter (not a regex pattern), matching the most common usage
    in the jivelite codebase. For regex splitting, use :func:`re.split`
    directly.

    Args:
        pattern: The delimiter string. If empty, splits into individual
                 characters.
        s: The string to split.
        result: Optional existing list to append results to. If ``None``,
                a new list is created and returned.

    Returns:
        A list of substrings. If *result* was provided, the substrings
        are appended to it and the same list is returned.

    Examples:
        >>> split(",", "a,b,c")
        ['a', 'b', 'c']
        >>> split("", "abc")
        ['a', 'b', 'c']
        >>> split(",", "no-commas")
        ['no-commas']
        >>> split(",", "a,,b")
        ['a', '', 'b']
        >>> existing = ["x"]
        >>> split(",", "a,b", existing)
        ['x', 'a', 'b']
    """
    if result is None:
        result = []

    if pattern == "":
        # Split into individual characters (matching Lua behavior)
        result.extend(list(s))
    else:
        # Split on literal delimiter
        # We use str.split(-1) to match Lua's behavior of not
        # collapsing consecutive delimiters
        parts = s.split(pattern)
        result.extend(parts)

    return result


def match_literal(
    s: str,
    pattern: str,
    init: Optional[int] = None,
) -> Optional[str]:
    """
    Find the first occurrence of a literal substring.

    Equivalent to Lua's ``matchLiteral(s, pattern, init)``, which
    escapes all regex special characters in *pattern* before calling
    ``string.match``. In Python, we simply use :meth:`str.find` since
    we're looking for a literal match.

    Args:
        s: The string to search in.
        pattern: The literal substring to find. Regex special characters
                 are treated as literal characters (matching the Lua
                 function's behavior of escaping them).
        init: Optional starting position (0-based). If negative, counts
              from the end of the string, matching Lua's convention
              (though Lua uses 1-based indexing).

    Returns:
        The matched substring if found, or ``None`` if not found.
        Since this is a literal match, the returned string always
        equals *pattern* — but returning it (vs. a bool) matches
        the Lua ``string.match`` return convention.

    Examples:
        >>> match_literal("hello world", "world")
        'world'
        >>> match_literal("hello world", "xyz") is None
        True
        >>> match_literal("file (1).txt", "(1)")
        '(1)'
        >>> match_literal("hello world", "world", 6)
        'world'
        >>> match_literal("hello world", "world", 99) is None
        True
    """
    if init is not None:
        if init < 0:
            # Lua allows negative init to count from end
            init = max(0, len(s) + init)
        idx = s.find(pattern, init)
    else:
        idx = s.find(pattern)

    if idx >= 0:
        return pattern
    return None


def url_decode(s: str) -> str:
    """
    Decode a URL-encoded string.

    Equivalent to Lua's ``urlDecode(str)``:
    - ``+`` is replaced with spaces
    - ``%XX`` hex sequences are decoded to characters
    - ``\\r\\n`` is normalized to ``\\n``

    Uses Python's :func:`urllib.parse.unquote_plus` which handles
    the ``+`` → space and ``%XX`` decoding in one step, then
    normalizes line endings.

    Args:
        s: A URL-encoded string.

    Returns:
        The decoded string.

    Examples:
        >>> url_decode("hello+world")
        'hello world'
        >>> url_decode("hello%20world")
        'hello world'
        >>> url_decode("%48%65%6C%6C%6F")
        'Hello'
        >>> url_decode("line1%0D%0Aline2")
        'line1\\nline2'
        >>> url_decode("already decoded")
        'already decoded'
    """
    decoded = unquote_plus(s)
    decoded = decoded.replace("\r\n", "\n")
    return decoded


def url_encode(s: str) -> str:
    """
    Encode a string for use in a URL.

    Equivalent to Lua's ``urlEncode(str)``:
    - ``\\n`` is converted to ``\\r\\n`` before encoding
    - Non-alphanumeric characters (except space) become ``%XX``
    - Spaces become ``+``

    Uses Python's :func:`urllib.parse.quote_plus` which handles
    the space → ``+`` and character → ``%XX`` encoding.

    Args:
        s: The string to URL-encode.

    Returns:
        The URL-encoded string.

    Examples:
        >>> url_encode("hello world")
        'hello+world'
        >>> url_encode("a=1&b=2")
        'a%3D1%26b%3D2'
        >>> url_encode("")
        ''
        >>> url_encode("already_safe_123")
        'already_safe_123'
    """
    # Normalize line endings: \n → \r\n (matching Lua behavior)
    s = s.replace("\n", "\r\n")
    # quote_plus: space → +, unsafe chars → %XX
    # safe="" means only alphanumerics and _ are left unencoded
    return quote_plus(s, safe="")
