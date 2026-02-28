"""
jive.ui.font — TrueType font loading and text rendering for the Jivelite
Python3 port.

Ported from ``jive_font.c`` and ``jive/ui/Font.lua`` in the original
jivelite project.

A Font wraps a ``pygame.freetype.Font`` and exposes the metrics and
rendering API that the C code provided to Lua: ``load``, ``width``,
``height``, ``ascend``, ``capheight``, ``offset``, and ``render``.

Fonts are cached by ``(name, size)`` — loading the same font twice returns
the same instance (with an increased reference count), matching the
behaviour of ``jive_font_load`` in the C original.

Colours are 32-bit RGBA integers (e.g. ``0xFF0000FF`` for opaque red),
consistent with the Surface API.

Copyright 2010 Logitech. All Rights Reserved. (original C implementation)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import pygame
import pygame.freetype

from jive.utils.log import logger

__all__ = ["Font"]

log = logger("jivelite.ui")

# ---------------------------------------------------------------------------
# Module-level font cache  (mirrors the C linked-list ``fonts``)
# ---------------------------------------------------------------------------

_font_cache: Dict[Tuple[str, int], Font] = {}

# ---------------------------------------------------------------------------
# Search-path helpers — shared with surface.py
# ---------------------------------------------------------------------------

_search_paths: list[Path] = []


def add_font_search_path(path: Union[str, Path]) -> None:
    """Append a directory to the font search path."""
    p = Path(path)
    if p not in _search_paths:
        _search_paths.append(p)


def _find_font_file(name: str) -> Optional[Path]:
    """
    Resolve *name* against the font search paths.

    Returns the first existing ``Path`` found, or ``None`` when the file
    cannot be located.
    """
    p = Path(name)
    if p.is_absolute() and p.exists():
        return p

    for base in _search_paths:
        candidate = base / name
        if candidate.exists():
            return candidate

    # Fall-back: maybe it's relative to CWD
    if p.exists():
        return p

    # Last resort: let pygame/SDL_ttf try its own lookup
    return None


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------


def _rgba_to_tuple(color: int) -> Tuple[int, int, int, int]:
    """Convert a 32-bit ``0xRRGGBBAA`` integer to an ``(R, G, B, A)`` tuple."""
    return (
        (color >> 24) & 0xFF,
        (color >> 16) & 0xFF,
        (color >> 8) & 0xFF,
        color & 0xFF,
    )


# ---------------------------------------------------------------------------
# Font class
# ---------------------------------------------------------------------------


class Font:
    """
    A TrueType font, backed by ``pygame.freetype.Font``.

    **Do not instantiate directly** — use the ``Font.load(name, size)``
    class method which caches fonts by ``(name, size)``.

    Mirrors the C API:

    * ``Font.load(name, size)`` — load / retrieve from cache
    * ``font.width(text)``      — pixel width of *text*
    * ``font.height()``         — line height (capheight − descent + 1)
    * ``font.ascend()``         — font ascent in pixels
    * ``font.capheight()``      — height of the capital letter *H*
    * ``font.offset()``         — ascend − capheight
    * ``font.render(text, color)`` — render text → ``pygame.Surface``
    """

    __slots__ = (
        "_pg_font",
        "_name",
        "_size",
        "_height",
        "_ascend",
        "_capheight",
        "_refcount",
    )

    def __init__(
        self,
        pg_font: pygame.freetype.Font,
        name: str,
        size: int,
        height: int,
        ascend: int,
        capheight: int,
    ) -> None:
        self._pg_font: pygame.freetype.Font = pg_font
        self._name: str = name
        self._size: int = size
        self._height: int = height
        self._ascend: int = ascend
        self._capheight: int = capheight
        self._refcount: int = 1

    # ------------------------------------------------------------------
    # Factory / cache
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, name: str, size: int) -> Font:
        """
        Load a font by *name* and *size* (in points).

        If the same ``(name, size)`` has been loaded before the cached
        instance is returned (with its reference count bumped).

        Raises ``FileNotFoundError`` if the font file cannot be located and
        ``RuntimeError`` if pygame.freetype fails to open it.
        """
        key = (name, size)
        if key in _font_cache:
            cached = _font_cache[key]
            cached._refcount += 1
            return cached

        # Ensure the freetype module is initialised
        if not pygame.freetype.get_init():
            pygame.freetype.init()

        resolved = _find_font_file(name)
        font_path: Union[str, Path]
        if resolved is not None:
            font_path = str(resolved)
        else:
            # Let pygame try — it may find system fonts
            font_path = name

        try:
            pg_font = pygame.freetype.Font(str(font_path), size)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load font '{name}' at size {size}: {exc}"
            ) from exc

        # --- Compute metrics (matches load_ttf_font in jive_font.c) ---

        # Ascent
        ascend = int(pg_font.get_sized_ascender(size))

        # Cap-height: max-y of the glyph 'H'
        try:
            metrics_h = pg_font.get_metrics("H", size)
            if metrics_h and metrics_h[0] is not None:
                # get_metrics returns list of (min_x, max_x, min_y, max_y,
                # horizontal_advance_x, horizontal_advance_y)
                capheight = int(metrics_h[0][3])  # max_y
            else:
                capheight = ascend
        except Exception:
            capheight = ascend

        # Descent: min-y of the glyph 'g'
        try:
            metrics_g = pg_font.get_metrics("g", size)
            if metrics_g and metrics_g[0] is not None:
                descent = int(metrics_g[0][2])  # min_y (negative)
            else:
                descent = int(pg_font.get_sized_descender(size))
        except Exception:
            descent = int(pg_font.get_sized_descender(size))

        # Height: capheight - descent + 1  (C original formula)
        height = capheight - descent + 1

        font = cls(pg_font, name, size, height, ascend, capheight)
        _font_cache[key] = font
        return font

    # ------------------------------------------------------------------
    # Reference counting (for parity with C; Python GC handles lifetime)
    # ------------------------------------------------------------------

    def ref(self) -> Font:
        """Increment the reference count and return self."""
        self._refcount += 1
        return self

    def free(self) -> None:
        """
        Decrement the reference count.  When it reaches zero the font is
        removed from the cache.
        """
        self._refcount -= 1
        if self._refcount <= 0:
            key = (self._name, self._size)
            _font_cache.pop(key, None)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def width(self, text: str) -> int:
        """
        Return the number of pixels needed to render *text*.

        Returns ``0`` for ``None`` or empty strings.
        """
        if not text:
            return 0
        rect = self._pg_font.get_rect(text, size=self._size)
        return int(rect.width)

    def nwidth(self, text: str, n: int) -> int:
        """
        Return the pixel width of the first *n* characters of *text*.
        """
        if n <= 0 or not text:
            return 0
        return self.width(text[:n])

    def height(self) -> int:
        """
        Return the font height in pixels.

        This is ``capheight - descent + 1``, matching the C original.
        """
        return self._height

    def ascend(self) -> int:
        """Return the font ascent in pixels."""
        return self._ascend

    def capheight(self) -> int:
        """
        Return the cap-height (max-y of the glyph 'H') in pixels.
        """
        return self._capheight

    def offset(self) -> int:
        """
        Return ``ascend - capheight``.

        This is the gap between the top of the em-square and the top of
        capital letters, used for vertical alignment.
        """
        return self._ascend - self._capheight

    # ------------------------------------------------------------------
    # Glyph metrics (for individual characters)
    # ------------------------------------------------------------------

    def miny_char(self, ch: str) -> int:
        """Return the min-y metric for character *ch*."""
        metrics = self._pg_font.get_metrics(ch, size=self._size)
        if metrics and metrics[0] is not None:
            return int(metrics[0][2])  # min_y
        return 0

    def maxy_char(self, ch: str) -> int:
        """Return the max-y metric for character *ch*."""
        metrics = self._pg_font.get_metrics(ch, size=self._size)
        if metrics and metrics[0] is not None:
            return int(metrics[0][3])  # max_y
        return 0

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, text: str, color: int) -> Optional[pygame.Surface]:
        """
        Render *text* with the given *color* (32-bit RGBA) and return a
        ``pygame.Surface`` containing the rendered text.

        Returns ``None`` for empty strings (matching the C behaviour which
        avoids calling ``TTF_RenderUTF8_Blended`` on empty input).
        """
        if not text:
            return None

        col = _rgba_to_tuple(color)
        # pygame.freetype renders with alpha-blending by default
        try:
            surface, rect = self._pg_font.render(
                text,
                fgcolor=col,
                size=self._size,
            )
            return surface
        except Exception as exc:
            log.error(f"render returned error: {exc}")
            return None

    def render_to(
        self,
        dest: pygame.Surface,
        dest_pos: Tuple[int, int],
        text: str,
        color: int,
    ) -> Optional[pygame.Rect]:
        """
        Render *text* directly onto *dest* at *dest_pos*.

        Returns the bounding ``pygame.Rect`` of the rendered text, or
        ``None`` on failure.
        """
        if not text:
            return None

        col = _rgba_to_tuple(color)
        try:
            rect = self._pg_font.render_to(
                dest,
                dest_pos,
                text,
                fgcolor=col,
                size=self._size,
            )
            return rect
        except Exception as exc:
            log.error(f"render_to returned error: {exc}")
            return None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """The font file name (as passed to ``load``)."""
        return self._name

    @property
    def size(self) -> int:
        """The font size in points."""
        return self._size

    @property
    def pg_font(self) -> pygame.freetype.Font:
        """The underlying ``pygame.freetype.Font`` object."""
        return self._pg_font

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    @classmethod
    def clear_cache(cls) -> None:
        """
        Clear the font cache.  Useful for testing and when changing
        search paths.
        """
        _font_cache.clear()

    @classmethod
    def cache_size(cls) -> int:
        """Return the number of fonts currently cached."""
        return len(_font_cache)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Font(name={self._name!r}, size={self._size}, "
            f"height={self._height}, ascend={self._ascend}, "
            f"capheight={self._capheight}, refs={self._refcount})"
        )
