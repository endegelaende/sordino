"""
jive.ui.style — Style / skin lookup for the Jivelite Python3 port.

Includes lazy resolution of skin style references: dicts with a
``__type__`` key (e.g. ``{"__type__": "font", "path": "...", "size": 14}``)
are automatically resolved into real Font / Surface / Tile objects on
first access via :meth:`StyleDB.value`.

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
# Lazy reference resolution
# ---------------------------------------------------------------------------


def _is_lazy_ref(val: Any) -> bool:
    """Return ``True`` if *val* is a lazy-loadable style reference dict."""
    return isinstance(val, dict) and "__type__" in val


def _resolve_lazy(val: Dict[str, Any]) -> Any:
    """Resolve a lazy style reference dict into a real object.

    Supported ``__type__`` values:

    * ``"font"`` → :class:`Font` via ``Font.load(path, size)``
    * ``"image"`` → :class:`Surface` via ``Surface.load_image(path)``
    * ``"tile_image"`` → :class:`Tile` via ``Tile.load_image(path)``
    * ``"tile_fill"`` → :class:`Tile` via ``Tile.fill_color(color)``
    * ``"tile_htiles"`` → :class:`Tile` via ``Tile.load_h_tiles(paths)``
    * ``"tile_vtiles"`` → :class:`Tile` via ``Tile.load_v_tiles(paths)``
    * ``"tile_9patch"`` → :class:`Tile` via ``Tile.load_tiles(paths)``

    Returns the resolved object, or the original dict if resolution fails.
    """
    ref_type = val.get("__type__")

    try:
        if ref_type == "font":
            from jive.ui.font import Font

            path = val.get("path", "")
            size = int(val.get("size", 14))
            return Font.load(path, size)

        elif ref_type == "image":
            from jive.ui.surface import Surface

            path = val.get("path", "")
            return Surface.load_image(path)

        elif ref_type == "tile_image":
            from jive.ui.tile import Tile

            path = val.get("path", "")
            return Tile.load_image(path)

        elif ref_type == "tile_fill":
            from jive.ui.tile import Tile

            color = val.get("color", 0x000000FF)
            return Tile.fill_color(color)

        elif ref_type == "tile_htiles":
            from jive.ui.tile import Tile

            paths = val.get("paths", [])
            return Tile.load_htiles(paths)

        elif ref_type == "tile_vtiles":
            from jive.ui.tile import Tile

            paths = val.get("paths", [])
            return Tile.load_vtiles(paths)

        elif ref_type == "tile_9patch":
            from jive.ui.tile import Tile

            paths = val.get("paths", [])
            return Tile.load_tiles(paths)

        else:
            log.debug("Unknown lazy ref type: %s", ref_type)
            return val

    except Exception as exc:
        log.debug(
            "Failed to resolve lazy %s ref (%s): %s",
            ref_type,
            val.get("path") or val.get("paths", "?"),
            exc,
        )
        return None


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
        Like ``rawvalue`` but resolves callables and lazy references.

        If the looked-up value is a callable, it is called with
        ``(widget, *args)`` and the result is returned.

        If the looked-up value is a lazy reference dict (contains a
        ``__type__`` key), it is resolved into a real Font / Surface /
        Tile object.  The resolved value replaces the lazy dict in the
        underlying skin data so that subsequent lookups are instant.

        This mirrors the C ``jiveL_style_value``.
        """
        val = self.rawvalue(widget, key, default)

        # Resolve lazy reference dicts
        if _is_lazy_ref(val):
            resolved = _resolve_lazy(val)
            if resolved is not None and resolved is not val:
                # Store back into the skin dict so we don't re-resolve
                self._store_resolved(widget, key, resolved)
                return resolved
            # Resolution failed — return default
            return default

        if callable(val):
            try:
                return val(widget, *args)
            except Exception as exc:
                log.warn("error in style function for key=%r: %s", key, exc)
                return default
        return val

    def _store_resolved(self, widget: Widget, key: str, resolved: Any) -> None:
        """Write *resolved* back into the skin dict and invalidate the cache entry.

        This replaces the lazy reference dict in the skin so that
        subsequent lookups (including via ``rawvalue``) return the
        resolved object directly.
        """
        path_str = style_path(widget)
        tokens = path_str.split(".")

        # Walk the skin dict to find the leaf node that holds *key*
        # Try progressively shorter sub-paths (matching find_value logic)
        for start in range(len(tokens)):
            node: Any = self._skin
            ok = True
            for tok in tokens[start:]:
                if not isinstance(node, dict):
                    ok = False
                    break
                child = node.get(tok)
                if child is None:
                    ok = False
                    break
                node = child

            if ok and isinstance(node, dict) and key in node:
                node[key] = resolved
                # Invalidate the cache for this path
                path_cache = self._cache.get(path_str)
                if path_cache is not None:
                    path_cache.pop(key, None)
                return

        # Could not locate the exact node — just invalidate the cache
        path_cache = self._cache.get(path_str)
        if path_cache is not None:
            path_cache.pop(key, None)

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
        return str(cached)

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
    widget._style_path = path

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


# Map skin-applet string constants to their enum int values.
# Skin applets (HDSkin, JogglerSkin, etc.) define layout/layer constants
# as plain strings like "LAYOUT_NORTH" instead of importing the enums
# from jive.ui.constants.  This lookup table bridges the gap.
_STR_TO_INT: Dict[str, int] = {
    "LAYOUT_NORTH": 0,
    "LAYOUT_EAST": 1,
    "LAYOUT_SOUTH": 2,
    "LAYOUT_WEST": 3,
    "LAYOUT_CENTER": 4,
    "LAYOUT_NONE": 5,
    "LAYER_FRAME": 0x01,
    "LAYER_CONTENT": 0x02,
    "LAYER_CONTENT_OFF_STAGE": 0x04,
    "LAYER_CONTENT_ON_STAGE": 0x08,
    "LAYER_LOWER": 0x10,
    "LAYER_TITLE": 0x20,
    "LAYER_ALL": 0xFF,
}


def style_int(widget: Widget, key: str, default: int = 0) -> int:
    """
    Look up an integer style value.

    Booleans are converted to 0/1 (matching the C behaviour).
    String constants like ``"LAYOUT_NORTH"`` are resolved via a
    lookup table (skin applets use strings instead of enum imports).
    """
    val = skin.value(widget, key, default)
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, str):
        mapped = _STR_TO_INT.get(val)
        if mapped is not None:
            return mapped
        # Fall through to int() attempt for numeric strings
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
    if val is not None and val is not False:
        # Guard against unresolved lazy refs leaking through
        if _is_lazy_ref(val):
            resolved = _resolve_lazy(val)
            if resolved is not None and resolved is not val:
                return resolved
            val = None
        else:
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
    """Look up a ``Surface`` style value.

    If the skin stores a non-Surface sentinel (e.g. ``False``) to indicate
    "no image", this function returns *default* instead so that callers
    always receive either a real :class:`Surface` or ``None``.
    """
    val = skin.value(widget, key, default)
    # Several skins use ``"img": False`` to mean "no image for this state".
    # Guard against any non-Surface value leaking through.
    if val is not None and not hasattr(val, "get_size"):
        return default
    return val  # type: ignore[no-any-return]  # duck-type checked above


def style_tile(
    widget: Widget,
    key: str,
    default: Optional[Tile] = None,
) -> Optional[Tile]:
    """Look up a ``Tile`` style value.

    In the Lua/C original, ``jive_style_tile`` checks ``lua_isuserdata``
    and falls back to the default when the value is not a Tile (e.g.
    ``bgImg = false``).  We replicate that here: any non-Tile, non-None
    value (such as ``False``, ``0``, or a plain ``int``) is treated as
    "no tile" and the *default* is returned instead.
    """
    val = skin.value(widget, key, default)
    # Guard against unresolved lazy refs
    if _is_lazy_ref(val):
        resolved = _resolve_lazy(val)
        return resolved if resolved is not None and resolved is not val else default
    # Reject non-Tile values (e.g. bgImg = False means "no background")
    if val is not None and not hasattr(val, "blit"):
        return default
    return val  # type: ignore[no-any-return]  # runtime type matches Tile | None


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
            except (TypeError, ValueError) as exc:
                log.debug("style array key parse: %s", exc)
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
    """Look up a font from an array-typed style value.

    Resolves lazy font references (``{"__type__": "font", ...}``) that
    are stored in skin style arrays.  Without this resolution the caller
    would receive the raw dict instead of a ``Font`` object, causing
    rendering to silently fall back to defaults.
    """
    val = style_array_value(widget, array_key, index, value_key, None)
    if val is not None:
        # Resolve lazy font reference dicts
        if _is_lazy_ref(val):
            resolved = _resolve_lazy(val)
            if resolved is not None and resolved is not val:
                # Store back so we don't re-resolve next time
                arr = skin.rawvalue(widget, array_key, None)
                if isinstance(arr, (list, tuple)) and index < len(arr):
                    elem = arr[index]
                    if isinstance(elem, dict):
                        elem[value_key] = resolved
                return resolved
            # Resolution failed — fall through to default
        else:
            return val

    # No per-line font defined — return None so the caller uses the
    # base font instead.  (Returning a hardcoded fallback here would
    # override the widget's own base font which is incorrect.)
    return None
