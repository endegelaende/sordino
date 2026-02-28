"""
jive.utils.debug — Debug utilities.

Ported from share/jive/jive/utils/debug.lua

Provides utilities for debugging: table/object dumping and
function call tracing. In the original Lua code, this module
extends Lua's built-in ``debug`` module. In Python, we provide
equivalent functionality using the standard library's ``pprint``
and ``sys.settrace``.

Usage::

    from jive.utils.debug import dump, trace_on, trace_off

    # Dump a nested structure
    data = {"a": "bla", "c": {"nested": True}}
    dump(data)

    # Output:
    # { # dict
    #   'a': 'bla',
    #   'c': { # dict
    #     'nested': True,
    #   },
    # }

    # Turn on line-by-line tracing (very verbose!)
    trace_on()

    # ... your code here ...

    # Turn off tracing
    trace_off()

    # Get a traceback string
    tb = traceback()
    print(tb)

Copyright 2010 Logitech. All Rights Reserved.
This file is licensed under BSD. Please see the LICENSE file for details.
"""

from __future__ import annotations

import sys
import traceback as _traceback_mod
from io import StringIO
from typing import Any, Optional, TextIO

# ─── Dump ─────────────────────────────────────────────────────────────────────


def dump(
    obj: Any,
    depth: int = 2,
    stream: Optional[TextIO] = None,
) -> None:
    """
    Pretty-print a nested object (dict, list, etc.) to a stream.

    Equivalent to Lua's ``debug.dump(table, depth)``, which uses
    ``loop.debug.Viewer`` to print tables with configurable depth.

    In Python we provide our own recursive formatter that produces
    output similar to the Lua version, with indentation and type
    annotations for containers.

    Args:
        obj: The object to dump. Works best with dicts, lists, tuples,
             sets, and primitive types.
        depth: Maximum nesting depth. Sub-structures deeper than this
               are shown as ``{...}`` / ``[...]``. Default is 2,
               matching the Lua default.
        stream: Output stream. Defaults to ``sys.stdout``.

    Examples:
        >>> dump({"a": 1, "b": [2, 3]})
        { # dict
          'a': 1,
          'b': [ # list
            2,
            3,
          ],
        }

        >>> dump({"deep": {"nested": {"value": 42}}}, depth=1)
        { # dict
          'deep': {...},
        }
    """
    if stream is None:
        stream = sys.stdout
    output = _format_value(obj, depth=depth, current_depth=0, indent=0)
    stream.write(output)
    stream.write("\n")


def dump_to_string(obj: Any, depth: int = 2) -> str:
    """
    Dump an object to a string instead of a stream.

    Convenience wrapper around :func:`dump` that captures the output
    in a :class:`StringIO` buffer and returns it as a string.

    Args:
        obj: The object to dump.
        depth: Maximum nesting depth.

    Returns:
        The formatted string representation.

    Examples:
        >>> s = dump_to_string({"key": "value"})
        >>> "key" in s
        True
    """
    buf = StringIO()
    dump(obj, depth=depth, stream=buf)
    return buf.getvalue()


def _format_value(
    obj: Any,
    depth: int,
    current_depth: int,
    indent: int,
) -> str:
    """Recursively format a value for dump output."""
    prefix = "  " * indent

    if isinstance(obj, dict):
        if current_depth >= depth:
            return "{...}"
        if len(obj) == 0:
            return "{}"
        lines = ["{ # dict"]
        for key, value in obj.items():
            formatted_val = _format_value(
                value,
                depth=depth,
                current_depth=current_depth + 1,
                indent=indent + 1,
            )
            lines.append(f"{'  ' * (indent + 1)}{key!r}: {formatted_val},")
        lines.append(f"{prefix}}}")
        return "\n".join(lines)

    if isinstance(obj, (list, tuple)):
        bracket_open = "[" if isinstance(obj, list) else "("
        bracket_close = "]" if isinstance(obj, list) else ")"
        type_name = "list" if isinstance(obj, list) else "tuple"

        if current_depth >= depth:
            return f"{bracket_open}...{bracket_close}"
        if len(obj) == 0:
            return f"{bracket_open}{bracket_close}"
        lines = [f"{bracket_open} # {type_name}"]
        for item in obj:
            formatted_item = _format_value(
                item,
                depth=depth,
                current_depth=current_depth + 1,
                indent=indent + 1,
            )
            lines.append(f"{'  ' * (indent + 1)}{formatted_item},")
        lines.append(f"{prefix}{bracket_close}")
        return "\n".join(lines)

    if isinstance(obj, set):
        if current_depth >= depth:
            return "{...}"
        if len(obj) == 0:
            return "set()"
        lines = ["{ # set"]
        for item in sorted(obj, key=repr):
            formatted_item = _format_value(
                item,
                depth=depth,
                current_depth=current_depth + 1,
                indent=indent + 1,
            )
            lines.append(f"{'  ' * (indent + 1)}{formatted_item},")
        lines.append(f"{prefix}}}")
        return "\n".join(lines)

    # Primitive types
    return repr(obj)


# ─── Trace ────────────────────────────────────────────────────────────────────

_trace_active: bool = False


def _trace_callback(
    frame: Any,
    event: str,
    arg: Any,
) -> Any:
    """
    Trace function set via ``sys.settrace`` to print each executed line.

    Produces output similar to Lua's trace hook:
        filename:line TRACE (in function_name)
    """
    if event == "line":
        filename = frame.f_code.co_filename
        lineno = frame.f_lineno
        funcname = frame.f_code.co_name
        print(f"{filename}:{lineno} TRACE (in {funcname})")
    return _trace_callback


def trace_on() -> None:
    """
    Enable line-by-line tracing of Python execution.

    Equivalent to Lua's ``debug.traceon()``.

    **Warning:** This is extremely verbose and will significantly slow
    down execution. Use only for debugging specific issues.

    Use :func:`trace_off` to disable tracing.
    """
    global _trace_active
    _trace_active = True
    sys.settrace(_trace_callback)


def trace_off() -> None:
    """
    Disable line-by-line tracing.

    Equivalent to Lua's ``debug.traceoff()``.
    """
    global _trace_active
    _trace_active = False
    sys.settrace(None)


def is_tracing() -> bool:
    """
    Return whether tracing is currently active.

    Returns:
        ``True`` if :func:`trace_on` has been called and
        :func:`trace_off` has not yet been called.
    """
    return _trace_active


# ─── Traceback ────────────────────────────────────────────────────────────────


def traceback(skip: int = 1) -> str:
    """
    Return a formatted traceback string for the current call stack.

    Equivalent to Lua's ``debug.traceback()``.

    Args:
        skip: Number of stack frames to skip from the top.
              Default is 1, which skips this function itself so
              the traceback starts at the caller.

    Returns:
        A multi-line string showing the call stack.

    Examples:
        >>> tb = traceback()
        >>> "traceback" not in tb  # this function is skipped
        True
    """
    buf = StringIO()
    _traceback_mod.print_stack(limit=None, file=buf)
    lines = buf.getvalue().splitlines()
    # Each frame is 2 lines (location + code), skip the requested frames
    # from the end (most recent) plus our own frame
    if skip > 0 and len(lines) >= skip * 2:
        lines = lines[: -(skip * 2)]
    return "\n".join(lines)


# ─── Convenience re-exports from stdlib debug ────────────────────────────────

# These mirror the Lua pattern of extending the debug module
# with custom functions while keeping access to the built-in ones.


def getinfo(depth: int = 1) -> dict[str, Any]:
    """
    Get information about a stack frame.

    Simplified equivalent of Lua's ``debug.getinfo(level)``.

    Args:
        depth: Stack depth to inspect. 0 is this function, 1 is
               the caller, 2 is the caller's caller, etc.

    Returns:
        A dict with keys:
        - ``name``: Function name (or ``"?"`` if unknown)
        - ``filename``: Source file path
        - ``lineno``: Current line number
        - ``locals``: Dict of local variable names and values
    """
    # Add 1 to skip this function itself
    frame = sys._getframe(depth + 1)
    return {
        "name": frame.f_code.co_name,
        "filename": frame.f_code.co_filename,
        "lineno": frame.f_lineno,
        "locals": dict(frame.f_locals),
    }
