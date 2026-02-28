"""
jive.ui.style — Style/skin lookup system for the Jivelite Python3 port.

Ported from ``src/jive_style.c`` and the Lua-side style tables in the
original jivelite project.

The style system provides hierarchical lookup of visual properties
(fonts, colours, images, tiles, padding, alignment, integers, etc.) for
widgets.  It works as follows:

1. Every widget has a **style path** — a dotted string built from the
   widget's ``style`` attribute and the styles of its ancestors.
   Example: ``"text_list.menu.item"``

2. The global **skin** (``jive.ui.style``) is a nested dict that maps
   style paths to property dicts.

3. When a widget asks for ``style_int("padding")``, the lookup walks
   from the most-specific path to the least-specific, checking the skin
   dict at each level.

4. Lookups are **cached** per ``(path, key)`` for the lifetime of the
   current skin.  Calling ``style_changed()`` invalidates the cache.

5. A per-window skin override is also supported — the ``window.skin``
   attribute can hold a local style dict that takes precedence.

6. Style values may be **callables** — if a looked-up value is callable,
   it is invoked with ``(widget, *args)`` and the return value is used.

Type-specific helpers
---------------------

* ``style_int``     — integer (or bool treated as 0/1)
* ``style_color``   — 32-bit ``0xRRGGBBAA`` packed colour
* ``style_font``    — ``Font`` object
* ``style_image``   — ``Surface`` object
* ``style_tile``    — ``Tile`` object
* ``style_align``   — ``Align`` enum value
* ``style_insets``  — 4-element ``[left, top, right, bottom]``
* ``style_array_size`` — size of an array-typed value
* ``style_array_int``  — integer from a sub-array
* ``style_array_color``— colour from a sub-array
* ``style_array_font`` — font from a sub-array
* ``style_value``   — generic value (resolves callables)
* ``style_rawvalue``— generic value (does NOT resolve callables)

Copyright 2010 Logitech. All Rights Reserved. (original C code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

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

from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.font import Font
    from jive.ui.surface import Surface
    from jive.ui.tile import Tile
    from jive.ui.widget import Widget

__all__ = [
    "StyleDB",
    "style_path",
    "style_rawvalue",
    "style_value",
    "style_int",
    "style_color",
    "style_font",
    "style_image",
    "style_tile",
    "style_align",
    "style_insets",
    "style_array_size",
    "style_array_int",
    "style_array_color",
    "style_array_font",
    "style_array_value",
]

log = logger("jivelite.ui.style")

# Sentinel used to mark a cached "not found" lookup so that we
# distinguish between "never looked up" and "looked up but absent".
_SENTINEL_NIL = object()


# ---------------------------------------------------------------------------
# Global skin storage
# ---------------------------------------------------------------------------


class StyleDB:
    """
    Holds the global skin (a nested dict) and the lookup cache.

    There is normally a single module-level instance, ``skin``, that all
    widgets share.  Per-window skins are handled by passing the window's
    local dict to the lookup functions.

    Skin structure example::

        {
            "text_list": {
                "menu": {
                    "item": {
                        "font": Font("FreeSans", 14),
                        "fg":   [0xFF, 0xFF, 0xFF, 0xFF],
                        "padding": [4, 4, 4, 4],
                    },
                    "bgImg": Tile.fill_color(0x000000FF),
                },
                "title": {
                    "text": {"font": Font("FreeSansBold", 18)},
                },
            },
            "window": {
                "bgImg": Tile.fill_color(0x000000FF),
            },
        }

    The lookup for path ``"text_list.menu.item"`` and key ``"font"``
    first checks ``skin["text_list"]["menu"]["item"]["font"]``, then
    ``skin["menu"]["item"]["font"]``, then ``skin["item"]["font"]``.
    """

    __slots__ = ("_skin", "_cache")

    def __init__(self) -> None:
        self._skin: Dict[str, Any] = {}
        self._cache: Dict[str, Dict[str, Any]] = {}

    # ---- Skin get/set ----

    @property
    def data(self) -> Dict[str, Any]:
        """Direct access to the skin dict (for programmatic setup)."""
        return self._skin

    @data.setter
    def data(self, value: Dict[str, Any]) -> None:
        self._skin = value
        self.invalidate()

    def update(self, d: Dict[str, Any]) -> None:
        """Merge *d* into the skin (shallow update of top-level keys)."""
        self._skin.update(d)
        self.invalidate()

    def invalidate(self) -> None:
        """Clear the lookup cache (called on skin change)."""
        self._cache.clear()

    # ---- Path-based search ----

    def _search_path(
        self,
        root: Dict[str, Any],
        path_str: str,
        key: str,
    ) -> Any:
        """
        Walk *path_str* (e.g. ``"text_list.menu.item"``) inside *root*
        and return ``root[tok1][tok2]...[tokN][key]`` if found, else
        ``_SENTINEL_NIL``.
        """
        tokens = path_str.split(".")
        node: Any = root
        for tok in tokens:
            if not isinstance(node, dict):
                return _SENTINEL_NIL
            node = node.get(tok)
            if node is None:
                return _SENTINEL_NIL

        if not isinstance(node, dict):
            return _SENTINEL_NIL

        val = node.get(key)
        if val is None:
            return _SENTINEL_NIL
        return val

    def find_value(
        self,
        skin_dict: Dict[str, Any],
        path: str,
        key: str,
    ) -> Any:
        """
        Search the *skin_dict* for *key* starting from the most-specific
        *path*, then progressively stripping the first component.

        This mirrors the C ``jiveL_style_find_value``.

        Returns ``_SENTINEL_NIL`` if not found.
        """
        ptr: Optional[str] = path
        while ptr is not None:
            val = self._search_path(skin_dict, ptr, key)
            if val is not _SENTINEL_NIL:
                return val

            dot = ptr.find(".")
            if dot < 0:
                break
            ptr = ptr[dot + 1 :]

        return _SENTINEL_NIL

    # ---- Cached lookup (global skin) ----

    def rawvalue(
        self,
        widget: Widget,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Look up *key* for *widget* in the global skin (with caching).

        Returns the raw value (does NOT resolve callables).
        Falls back to the per-window skin, then to *default*.

        This mirrors the C ``jiveL_style_rawvalue``.
        """
        path = style_path(widget)

        # ---- Check cache ----
        path_cache = self._cache.get(path)
        if path_cache is None:
            path_cache = {}
            self._cache[path] = path_cache

        cached = path_cache.get(key)
        if cached is not None:
            if cached is _SENTINEL_NIL:
                # Fall through to per-window skin below
                pass
            else:
                return cached
        else:
            # Not yet cached — look up in global skin
            val = self.find_value(self._skin, path, key)
            # Store in cache (including sentinel for "not found")
            path_cache[key] = val

            if val is not _SENTINEL_NIL:
                return val

        # ---- Per-window skin ----
        window = widget.get_window()
        if window is not None:
            win_skin = getattr(window, "skin", None)
            if win_skin is not None and isinstance(win_skin, dict):
                val = self.find_value(win_skin, path, key)
                if val is not _SENTINEL_NIL:
                    return val

        return default

    def value(
        self,
        widget: Widget,
        key: str,
        default: Any = None,
        *args: Any,
    ) -> Any:
        """
        Like ``rawvalue`` but resolves callables.

        If the looked-up value is a callable, it is called with
        ``(widget, *args)`` and the result is returned.

        This mirrors the C ``jiveL_style_value``.
        """
        val = self.rawvalue(widget, key, default)
        if callable(val):
            try:
                return val(widget, *args)
            except Exception as exc:
                log.warn(f"error in style function for key={key!r}: {exc}")
                return default
        return val

    def __repr__(self) -> str:
        n_keys = len(self._skin)
        n_cached = sum(len(v) for v in self._cache.values())
        return f"StyleDB(keys={n_keys}, cached={n_cached})"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

skin: StyleDB = StyleDB()
"""Module-level global skin instance."""


# ---------------------------------------------------------------------------
# Style path construction
# ---------------------------------------------------------------------------


def style_path(widget: Widget) -> str:
    """
    Build the dotted style path for *widget* by walking up the parent
    chain and collecting ``style`` and ``style_modifier`` attributes.

    E.g. a Label with ``style="text"`` inside a Group with
    ``style="item"`` inside a Window with ``style="text_list"`` produces
    ``"text_list.item.text"``.

    The result is cached on the widget as ``_style_path`` and
    invalidated whenever ``re_skin()`` is called.

    This mirrors the C ``jiveL_style_path``.
    """
    cached = getattr(widget, "_style_path", None)
    if cached is not None:
        return cached

    parts: List[str] = []
    w: Any = widget
    while w is not None:
        st = getattr(w, "style", None)
        if st:
            parts.append(st)

        sm = getattr(w, "style_modifier", None)
        if sm:
            parts.append(sm)

        w = getattr(w, "parent", None)

    # The path reads root → leaf, but we walked leaf → root
    parts.reverse()
    path = ".".join(parts)

    # Cache on widget
    try:
        widget._style_path = path  # type: ignore[attr-defined]
    except AttributeError:
        pass

    return path


# ---------------------------------------------------------------------------
# Free-function lookup helpers (convenience API)
# ---------------------------------------------------------------------------


def style_rawvalue(
    widget: Widget,
    key: str,
    default: Any = None,
) -> Any:
    """Module-level shortcut to ``skin.rawvalue(widget, key, default)``."""
    return skin.rawvalue(widget, key, default)


def style_value(
    widget: Widget,
    key: str,
    default: Any = None,
    *args: Any,
) -> Any:
    """Module-level shortcut to ``skin.value(widget, key, default, *args)``."""
    return skin.value(widget, key, default, *args)


def style_int(widget: Widget, key: str, default: int = 0) -> int:
    """
    Look up an integer style value.

    Booleans are converted to 0/1 (matching the C behaviour).
    """
    val = skin.value(widget, key, default)
    if isinstance(val, bool):
        return int(val)
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def style_color(
    widget: Widget,
    key: str,
    default: int = 0x000000FF,
) -> Tuple[int, Optional[bool]]:
    """
    Look up a colour style value.

    Colours in the skin are stored as ``[r, g, b]`` or ``[r, g, b, a]``
    lists, matching the Lua tables.  They are packed into a 32-bit
    ``0xRRGGBBAA`` integer.

    Returns ``(color_int, is_set)`` where *is_set* is ``True`` if the
    value was found in the skin.
    """
    val = skin.value(widget, key, None)
    if val is None:
        return (default, False)

    return (_pack_color(val), True)


def _pack_color(val: Any) -> int:
    """
    Pack a colour value into ``0xRRGGBBAA``.

    Accepts:
    * ``int`` — returned as-is (assumed already packed)
    * ``list`` / ``tuple`` of 3 or 4 ints
    * Empty list/tuple → returns 0 (transparent)
    """
    if isinstance(val, int):
        return val
    if isinstance(val, (list, tuple)):
        if len(val) == 0:
            return 0
        r = int(val[0]) & 0xFF
        g = int(val[1]) & 0xFF if len(val) > 1 else 0
        b = int(val[2]) & 0xFF if len(val) > 2 else 0
        a = int(val[3]) & 0xFF if len(val) > 3 else 0xFF
        return (r << 24) | (g << 16) | (b << 8) | a
    return 0


def style_font(widget: Widget, key: str = "font") -> Any:
    """
    Look up a ``Font`` style value.

    If not found, returns a default FreeSans 15pt font.
    """
    val = skin.value(widget, key, None)
    if val is not None:
        return val

    # Default font — lazy import to avoid circular dependency
    try:
        from jive.ui.font import Font

        return Font.load("fonts/FreeSans.ttf", 15)
    except Exception:
        return None


def style_image(
    widget: Widget,
    key: str,
    default: Optional[Surface] = None,
) -> Optional[Surface]:
    """Look up a ``Surface`` style value."""
    val = skin.value(widget, key, default)
    return val


def style_tile(
    widget: Widget,
    key: str,
    default: Optional[Tile] = None,
) -> Optional[Tile]:
    """Look up a ``Tile`` style value."""
    val = skin.value(widget, key, default)
    return val


def style_align(widget: Widget, key: str = "align", default: int = 0) -> int:
    """
    Look up an alignment style value.

    The value in the skin may be a string (``"center"``, ``"left"``, etc.)
    or an ``Align`` enum integer.
    """
    from jive.ui.constants import Align

    val = skin.value(widget, key, None)
    if val is None:
        return default

    if isinstance(val, int):
        return val

    if isinstance(val, str):
        _ALIGN_MAP = {
            "center": int(Align.CENTER),
            "left": int(Align.LEFT),
            "right": int(Align.RIGHT),
            "top": int(Align.TOP),
            "bottom": int(Align.BOTTOM),
            "top-left": int(Align.TOP_LEFT),
            "top_left": int(Align.TOP_LEFT),
            "top-right": int(Align.TOP_RIGHT),
            "top_right": int(Align.TOP_RIGHT),
            "bottom-left": int(Align.BOTTOM_LEFT),
            "bottom_left": int(Align.BOTTOM_LEFT),
            "bottom-right": int(Align.BOTTOM_RIGHT),
            "bottom_right": int(Align.BOTTOM_RIGHT),
        }
        return _ALIGN_MAP.get(val.lower(), default)

    return default


def style_insets(
    widget: Widget,
    key: str = "padding",
    default: Optional[List[int]] = None,
) -> List[int]:
    """
    Look up an insets / padding / border style value.

    The value in the skin may be:
    * a single ``int`` — applied to all four sides
    * a ``list``/``tuple`` of 4 ints — ``[left, top, right, bottom]``

    Returns ``[left, top, right, bottom]``.

    Mirrors the C ``jive_style_insets``.
    """
    val = skin.value(widget, key, None)
    if val is None:
        return list(default) if default else [0, 0, 0, 0]

    if isinstance(val, (int, float)):
        v = int(val)
        return [v, v, v, v]

    if isinstance(val, (list, tuple)):
        left = int(val[0]) if len(val) > 0 else 0
        top = int(val[1]) if len(val) > 1 else 0
        right = int(val[2]) if len(val) > 2 else 0
        bottom = int(val[3]) if len(val) > 3 else 0
        return [left, top, right, bottom]

    return list(default) if default else [0, 0, 0, 0]


# ---------------------------------------------------------------------------
# Array-typed style helpers (matching C jive_style_array_* functions)
# ---------------------------------------------------------------------------


def style_array_value(
    widget: Widget,
    array_key: str,
    index: int,
    value_key: str,
    default: Any = None,
) -> Any:
    """
    Look up ``skin[path][array_key][index][value_key]``.

    This mirrors the C ``jiveL_style_array_value``.
    """
    arr = skin.rawvalue(widget, array_key, None)
    if arr is None or not isinstance(arr, (list, tuple, dict)):
        return default

    if isinstance(arr, dict):
        elem = arr.get(index)
    else:
        try:
            elem = arr[index]
        except (IndexError, TypeError):
            return default

    if elem is None:
        return default

    if isinstance(elem, dict):
        val = elem.get(value_key)
        if val is not None:
            return val

    return default


def style_array_size(widget: Widget, key: str) -> int:
    """
    Return the number of elements in an array-typed style value.

    Handles both ``list`` and ``dict`` (with integer keys — returns
    the maximum key, matching the C sparse-array iteration).
    """
    arr = skin.value(widget, key, None)
    if arr is None:
        return 0
    if isinstance(arr, (list, tuple)):
        return len(arr)
    if isinstance(arr, dict):
        if not arr:
            return 0
        max_key = 0
        for k in arr:
            try:
                max_key = max(max_key, int(k))
            except (TypeError, ValueError):
                pass
        return max_key
    return 0


def style_array_int(
    widget: Widget,
    array_key: str,
    index: int,
    value_key: str,
    default: int = 0,
) -> int:
    """Look up an integer from an array-typed style value."""
    val = style_array_value(widget, array_key, index, value_key, default)
    if isinstance(val, bool):
        return int(val)
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def style_array_color(
    widget: Widget,
    array_key: str,
    index: int,
    value_key: str,
    default: int = 0x000000FF,
) -> Tuple[int, Optional[bool]]:
    """Look up a colour from an array-typed style value."""
    val = style_array_value(widget, array_key, index, value_key, None)
    if val is None:
        return (default, False)
    return (_pack_color(val), True)


def style_array_font(
    widget: Widget,
    array_key: str,
    index: int,
    value_key: str = "font",
) -> Any:
    """Look up a font from an array-typed style value."""
    val = style_array_value(widget, array_key, index, value_key, None)
    if val is not None:
        return val

    # Default font fallback
    try:
        from jive.ui.font import Font

        return Font.load("fonts/FreeSans.ttf", 15)
    except Exception:
        return None
