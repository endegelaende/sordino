"""
jive.utils.dumper — Recursive data serializer.

Ported from share/jive/jive/utils/dumper.lua (DataDumper by Olivetti-Engineering)

The original Lua ``DataDumper`` serializes arbitrary Lua values (tables,
functions, closures, metatables, etc.) into a string that can be
``loadstring``-ed back into Lua. It handles circular references,
closures with upvalues, C functions, metatables, and mixed
integer/string keys.

In Python the use-case is different — we don't need ``loadstring``
equivalence. Instead we provide a recursive serializer that:

1. Produces **human-readable** output for debugging / logging.
2. Handles **circular references** gracefully (prints ``<circular ref>``).
3. Supports dicts, lists, tuples, sets, frozensets, primitives, and
   arbitrary objects (via ``repr``).
4. Optionally assigns to a variable name (matching the Lua API).
5. Can operate in **fast mode** (compact, single-line) or **pretty mode**
   (indented, multi-line with line-length heuristic).

The API mirrors the Lua original's ``dump(value, varname, fastmode, ident)``
signature as closely as practical.

Usage::

    from jive.utils.dumper import dump, dumps

    # Pretty-print a nested structure
    data = {"players": [{"name": "Kitchen", "volume": 50}], "count": 1}
    print(dump(data))
    # return { count = 1, players = { { name = "Kitchen", volume = 50 } } }

    # Fast mode (compact, single-line)
    print(dump(data, fastmode=True))
    # return {count=1,players={{name="Kitchen",volume=50}}}

    # With variable name
    print(dump(data, varname="config"))
    # config = { count = 1, ... }

    # dumps() is an alias that always returns a string (no varname prefix)
    s = dumps(data)

Copyright (c) 2007 Olivetti-Engineering SA (original Lua version)
Python port: BSD license, see LICENSE file for details.
"""

from __future__ import annotations

from typing import Any, Optional

# Lua reserved keywords — used to decide whether a dict key can be
# written as a bare identifier (``key =``) or needs bracket notation
# (``["and"] =``).  We keep this list for Lua-style output fidelity.
_LUA_RESERVED = frozenset(
    {
        "and",
        "break",
        "do",
        "else",
        "elseif",
        "end",
        "false",
        "for",
        "function",
        "if",
        "in",
        "local",
        "nil",
        "not",
        "or",
        "repeat",
        "return",
        "then",
        "true",
        "until",
        "while",
    }
)

# Python keywords that also shouldn't be bare identifiers
_PY_RESERVED = frozenset(
    {
        "False",
        "None",
        "True",
        "and",
        "as",
        "assert",
        "async",
        "await",
        "break",
        "class",
        "continue",
        "def",
        "del",
        "elif",
        "else",
        "except",
        "finally",
        "for",
        "from",
        "global",
        "if",
        "import",
        "in",
        "is",
        "lambda",
        "nonlocal",
        "not",
        "or",
        "pass",
        "raise",
        "return",
        "try",
        "while",
        "with",
        "yield",
    }
)

_ALL_RESERVED = _LUA_RESERVED | _PY_RESERVED

# Maximum line length before switching from single-line to multi-line
# table representation (matching the Lua original's threshold of 80).
_LINE_WIDTH = 80


def dump(
    value: Any,
    varname: Optional[str] = None,
    fastmode: bool = False,
    ident: int = 0,
) -> str:
    """
    Serialize a Python object into a human-readable string.

    The output format is inspired by Lua table literals but uses
    Python conventions where appropriate (e.g. ``True``/``False``
    instead of ``true``/``false``, ``None`` instead of ``nil``).

    Args:
        value: The object to serialize. Supports ``dict``, ``list``,
               ``tuple``, ``set``, ``frozenset``, ``str``, ``int``,
               ``float``, ``bool``, ``None``, ``bytes``, and arbitrary
               objects (via ``repr``).
        varname: Optional variable name. If given, the output is
                 ``varname = <serialized>``; if the name looks like
                 a simple identifier, `` = `` is appended, otherwise
                 it's used verbatim as a prefix.  If ``None``,
                 ``"return "`` is used as prefix (matching Lua API).
        fastmode: If ``True``, produce compact single-line output
                  with no extra whitespace. If ``False`` (default),
                  produce pretty-printed output with indentation
                  and automatic line-breaking for wide tables.
        ident: Initial indentation level (number of 2-space indents).
               Only meaningful when ``fastmode`` is ``False``.

    Returns:
        The serialized string representation.

    Examples:
        >>> dump(42)
        'return 42'
        >>> dump("hello")
        'return "hello"'
        >>> dump({"a": 1}, varname="cfg")
        'cfg = {a = 1}'
        >>> dump([1, 2, 3], fastmode=True)
        'return {1,2,3}'
        >>> dump(None)
        'return None'
    """
    seen: set[int] = set()

    if fastmode:
        serialized = _dump_fast(value, seen)
    else:
        serialized = _dump_pretty(value, ident, seen)

    prefix = _make_prefix(varname)
    return f"{prefix}{serialized}"


def dumps(value: Any, fastmode: bool = False, ident: int = 0) -> str:
    """
    Serialize a Python object to string without any variable prefix.

    Convenience wrapper around :func:`dump` that strips the default
    ``"return "`` prefix, returning just the serialized value.

    Args:
        value: The object to serialize.
        fastmode: Compact mode flag.
        ident: Initial indentation level.

    Returns:
        The serialized string (no ``return`` or variable prefix).

    Examples:
        >>> dumps(42)
        '42'
        >>> dumps({"a": 1})
        '{a = 1}'
        >>> dumps([1, 2], fastmode=True)
        '{1,2}'
    """
    seen: set[int] = set()
    if fastmode:
        return _dump_fast(value, seen)
    return _dump_pretty(value, ident, seen)


# ─── Fast Mode (compact, single-line) ────────────────────────────────────────


def _dump_fast(value: Any, seen: set[int]) -> str:
    """Serialize *value* in compact single-line format."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _quote_string(value)
    if isinstance(value, bytes):
        return repr(value)

    obj_id = id(value)
    if obj_id in seen:
        return '"<circular ref>"'
    seen.add(obj_id)

    try:
        if isinstance(value, dict):
            return _dump_dict_fast(value, seen)
        if isinstance(value, (list, tuple)):
            return _dump_seq_fast(value, seen)
        if isinstance(value, (set, frozenset)):
            return _dump_seq_fast(sorted(value, key=repr), seen)
    finally:
        seen.discard(obj_id)

    # Fallback for unknown types
    return repr(value)


def _dump_dict_fast(d: dict[Any, Any], seen: set[int]) -> str:
    """Serialize a dict in fast mode."""
    if not d:
        return "{}"
    parts: list[str] = []
    # Check if this looks like a sequential integer-keyed table
    # (all keys are ints 0..n-1 or 1..n)
    if _is_sequence_dict(d):
        for i in range(len(d)):
            key = i if i in d else i + 1  # 0-based or 1-based
            parts.append(_dump_fast(d[key], seen))
    else:
        for key in _sorted_keys(d):
            key_str = _format_key_fast(key)
            val_str = _dump_fast(d[key], seen)
            parts.append(f"{key_str}{val_str}")
    return "{" + ",".join(parts) + "}"


def _dump_seq_fast(seq: list[Any] | tuple[Any, ...], seen: set[int]) -> str:
    """Serialize a list/tuple in fast mode."""
    if not seq:
        return "{}"
    parts = [_dump_fast(item, seen) for item in seq]
    return "{" + ",".join(parts) + "}"


# ─── Pretty Mode (indented, multi-line) ──────────────────────────────────────


def _dump_pretty(value: Any, ident: int, seen: set[int]) -> str:
    """Serialize *value* in pretty-printed format."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _quote_string(value)
    if isinstance(value, bytes):
        return repr(value)

    obj_id = id(value)
    if obj_id in seen:
        return '"<circular ref>"'
    seen.add(obj_id)

    try:
        if isinstance(value, dict):
            return _dump_dict_pretty(value, ident, seen)
        if isinstance(value, (list, tuple)):
            return _dump_seq_pretty(value, ident, seen)
        if isinstance(value, (set, frozenset)):
            return _dump_seq_pretty(sorted(value, key=repr), ident, seen)
    finally:
        seen.discard(obj_id)

    return repr(value)


def _dump_dict_pretty(d: dict[Any, Any], ident: int, seen: set[int]) -> str:
    """Serialize a dict in pretty mode."""
    if not d:
        return "{}"

    entries: list[str] = []

    if _is_sequence_dict(d):
        for i in range(len(d)):
            key = i if i in d else i + 1
            entries.append(_dump_pretty(d[key], ident + 1, seen))
    else:
        for key in _sorted_keys(d):
            key_str = _format_key_pretty(key)
            val_str = _dump_pretty(d[key], ident + 1, seen)
            entries.append(f"{key_str}{val_str}")

    # Decide single-line vs multi-line based on total length
    total_len = sum(len(e) for e in entries) + 2 * len(entries) + 4
    if total_len <= _LINE_WIDTH:
        return "{ " + ", ".join(entries) + " }"
    else:
        indent = "  " * (ident + 1)
        outer = "  " * ident
        lines = [f"{indent}{e}" for e in entries]
        return "{\n" + ",\n".join(lines) + "\n" + outer + "}"


def _dump_seq_pretty(
    seq: list[Any] | tuple[Any, ...], ident: int, seen: set[int]
) -> str:
    """Serialize a list/tuple in pretty mode."""
    if not seq:
        return "{}"

    entries = [_dump_pretty(item, ident + 1, seen) for item in seq]

    total_len = sum(len(e) for e in entries) + 2 * len(entries) + 4
    if total_len <= _LINE_WIDTH:
        return "{ " + ", ".join(entries) + " }"
    else:
        indent = "  " * (ident + 1)
        outer = "  " * ident
        lines = [f"{indent}{e}" for e in entries]
        return "{\n" + ",\n".join(lines) + "\n" + outer + "}"


# ─── Key Formatting ──────────────────────────────────────────────────────────


def _format_key_fast(key: Any) -> str:
    """Format a dict key for fast mode output."""
    if isinstance(key, str) and _is_identifier(key):
        return f"{key}="
    return f"[{_dump_fast(key, set())}]="


def _format_key_pretty(key: Any) -> str:
    """Format a dict key for pretty mode output."""
    if isinstance(key, str) and _is_identifier(key):
        return f"{key} = "
    return f"[{_dump_pretty(key, 0, set())}] = "


def _is_identifier(s: str) -> bool:
    """
    Check if a string can be used as a bare key (like a Lua identifier).

    Must match ``^[_%a][_%w]*$`` and not be a reserved keyword.
    """
    if not s:
        return False
    first = s[0]
    if not (first.isalpha() or first == "_"):
        return False
    if not all(c.isalnum() or c == "_" for c in s):
        return False
    if s in _ALL_RESERVED:
        return False
    return True


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _quote_string(s: str) -> str:
    """
    Quote a string value, escaping special characters.

    Uses double quotes to match the Lua convention. Escapes backslashes,
    double quotes, newlines, carriage returns, tabs, and null bytes.
    """
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\r")
    s = s.replace("\t", "\\t")
    s = s.replace("\x00", "\\0")
    return f'"{s}"'


def _is_sequence_dict(d: dict[Any, Any]) -> bool:
    """
    Check if a dict represents a sequential integer-indexed table.

    Returns ``True`` if all keys are contiguous integers starting
    from 0 or 1 (Python vs Lua convention).
    """
    if not d:
        return False
    keys = set(d.keys())
    n = len(d)
    # 0-based: {0, 1, 2, ...}
    if keys == set(range(n)):
        return True
    # 1-based (Lua convention): {1, 2, 3, ...}
    if keys == set(range(1, n + 1)):
        return True
    return False


def _sorted_keys(d: dict[Any, Any]) -> list[Any]:
    """
    Return dict keys in a deterministic, human-friendly order.

    Sorts keys by type first (strings before numbers before others),
    then by value within each type group. This matches the Lua
    DataDumper's key ordering behavior.
    """

    def sort_key(k: Any) -> tuple[int, str]:
        if isinstance(k, str):
            return (0, k)
        if isinstance(k, (int, float)):
            return (1, f"{k:020.6f}" if isinstance(k, float) else f"{k:020d}")
        return (2, repr(k))

    return sorted(d.keys(), key=sort_key)


def _make_prefix(varname: Optional[str]) -> str:
    """Build the output prefix from *varname*."""
    if varname is None:
        return "return "
    if varname == "":
        return ""
    # If it looks like a simple identifier, add " = "
    if _is_identifier(varname):
        return f"{varname} = "
    # Otherwise use verbatim (could be "return " or a complex expression)
    return varname
