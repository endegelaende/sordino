"""
jive.ui.surface — Graphic surface for the Jivelite Python3 port.

Ported from ``jive_surface.c`` and ``jive/ui/Surface.lua`` in the original
jivelite project.

A Surface wraps a ``pygame.Surface`` and exposes the drawing, blitting and
image-loading API that the original C code provided to Lua.  Colours are
32-bit RGBA integers (e.g. ``0xFF0000FF`` for opaque red) matching the
original convention.

Copyright 2010 Logitech. All Rights Reserved. (original C implementation)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Sequence, Union

import pygame
import pygame.gfxdraw

from jive.utils.log import logger

__all__ = ["Surface"]

log = logger("jivelite.ui")

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------


def _rgba_to_tuple(color: int) -> tuple[int, int, int, int]:
    """Convert a 32-bit ``0xRRGGBBAA`` integer to an ``(R, G, B, A)`` tuple."""
    return (
        (color >> 24) & 0xFF,
        (color >> 16) & 0xFF,
        (color >> 8) & 0xFF,
        color & 0xFF,
    )


def _rgba_to_rgb(color: int) -> tuple[int, int, int]:
    """Convert a 32-bit ``0xRRGGBBAA`` integer to an ``(R, G, B)`` tuple."""
    return (
        (color >> 24) & 0xFF,
        (color >> 16) & 0xFF,
        (color >> 8) & 0xFF,
    )


# ---------------------------------------------------------------------------
# Search-path helpers (analogous to ``jive_find_file`` in C)
# ---------------------------------------------------------------------------

_search_paths: list[Path] = []


def add_search_path(path: Union[str, Path]) -> None:
    """Append a directory to the image/asset search path."""
    p = Path(path)
    if p not in _search_paths:
        _search_paths.append(p)


def find_file(name: str) -> Optional[Path]:
    """
    Resolve *name* against the search paths.

    Returns the first existing ``Path`` found, or the original *name* as a
    ``Path`` if it is already absolute and exists.  Returns ``None`` when the
    file cannot be located.
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

    return None


# ---------------------------------------------------------------------------
# Surface class
# ---------------------------------------------------------------------------


class Surface:
    """
    A graphic surface backed by a ``pygame.Surface``.

    Mirrors the API exposed by ``jive_surface.c`` to Lua:

    * Static constructors: ``new_rgb``, ``new_rgba``, ``load_image``,
      ``load_image_data``, ``draw_text``
    * Blitting: ``blit``, ``blit_clip``, ``blit_alpha``
    * Clipping: ``set_clip``, ``get_clip``, ``push_clip``, ``pop_clip``
    * Offset: ``set_offset``, ``get_offset``
    * Drawing primitives (from *SDL_gfx*): ``pixel``, ``hline``, ``vline``,
      ``rectangle``, ``filled_rectangle``, ``line``, ``aaline``, ``circle``,
      ``aacircle``, ``filled_circle``, ``ellipse``, ``aaellipse``,
      ``filled_ellipse``, ``pie``, ``filled_pie``, ``trigon``,
      ``aatrigon``, ``filled_trigon``
    * Transforms: ``rotozoom``, ``zoom``, ``shrink``, ``resize``
    * Query: ``get_size``, ``get_bytes``
    * Lifecycle: ``release``
    """

    __slots__ = ("_srf", "_offset_x", "_offset_y", "_clip_stack")

    def __init__(self, pg_surface: pygame.Surface) -> None:
        self._srf: Optional[pygame.Surface] = pg_surface
        self._offset_x: int = 0
        self._offset_y: int = 0
        self._clip_stack: list[pygame.Rect] = []

    # ------------------------------------------------------------------
    # Static constructors
    # ------------------------------------------------------------------

    @staticmethod
    def new_rgb(w: int, h: int) -> Surface:
        """Create a new opaque RGB surface of *w* × *h* pixels."""
        srf = pygame.Surface((w, h), 0)
        srf.fill((0, 0, 0))
        return Surface(srf)

    @staticmethod
    def new_rgba(w: int, h: int) -> Surface:
        """
        Create a new RGBA surface of *w* × *h* pixels, filled with
        full transparency.
        """
        srf = pygame.Surface((w, h), pygame.SRCALPHA)
        srf.fill((0, 0, 0, 0))
        return Surface(srf)

    @staticmethod
    def load_image(path: str) -> Surface:
        """
        Load an image from *path*.

        If *path* is relative the search-path list is consulted (see
        ``add_search_path``).  Raises ``FileNotFoundError`` if the image
        cannot be located.
        """
        resolved = find_file(path)
        if resolved is None:
            raise FileNotFoundError(f"Cannot find image: {path}")

        pg = pygame.image.load(str(resolved))
        # Convert for fast blitting while preserving alpha
        if pg.get_alpha() is not None or pg.get_colorkey() is not None:
            pg = pg.convert_alpha()
        else:
            pg = pg.convert()
        return Surface(pg)

    @staticmethod
    def load_image_data(data: bytes, length: Optional[int] = None) -> Surface:
        """
        Load an image from raw *data* bytes.

        *length* is accepted for API compatibility with the C original but
        is ignored (Python bytes carry their own length).
        """
        import io

        pg = pygame.image.load(io.BytesIO(data))
        if pg.get_alpha() is not None or pg.get_colorkey() is not None:
            pg = pg.convert_alpha()
        else:
            pg = pg.convert()
        return Surface(pg)

    @staticmethod
    def draw_text(font: "Font", color: int, text: str) -> Optional[Surface]:  # noqa: F821
        """
        Render *text* in *font* with *color* (32-bit RGBA).

        Returns a new ``Surface`` containing the rendered text, or ``None``
        if the text is empty.

        The *font* argument is a ``jive.ui.font.Font`` instance.
        """
        if not text:
            return None

        pg_srf = font.render(text, color)
        if pg_srf is None:
            return None
        return Surface(pg_srf)

    # ------------------------------------------------------------------
    # Raw pygame access (for framework internals / renderer)
    # ------------------------------------------------------------------

    @property
    def pg(self) -> pygame.Surface:
        """Return the underlying ``pygame.Surface``.  Raises if released."""
        if self._srf is None:
            raise RuntimeError("Surface has been released")
        return self._srf

    # ------------------------------------------------------------------
    # Offset
    # ------------------------------------------------------------------

    def get_offset(self) -> tuple[int, int]:
        """Return the current drawing offset ``(x, y)``."""
        return self._offset_x, self._offset_y

    def set_offset(self, x: int, y: int) -> None:
        """Set the drawing offset.  All blit/draw operations are shifted."""
        self._offset_x = x
        self._offset_y = y

    # ------------------------------------------------------------------
    # Clipping
    # ------------------------------------------------------------------

    def get_clip(self) -> tuple[int, int, int, int]:
        """Return ``(x, y, w, h)`` of the current clip rectangle."""
        r = self.pg.get_clip()
        return r.x, r.y, r.w, r.h

    def set_clip(self, x: int, y: int, w: int, h: int) -> None:
        """Set the clip rectangle."""
        self.pg.set_clip(pygame.Rect(x, y, w, h))

    def push_clip(self, x: int, y: int, w: int, h: int) -> None:
        """
        Save the current clip and intersect with the given rectangle.
        """
        self._clip_stack.append(self.pg.get_clip())
        old = self.pg.get_clip()
        new = old.clip(pygame.Rect(x, y, w, h))
        self.pg.set_clip(new)

    def pop_clip(self) -> None:
        """Restore the previously pushed clip rectangle."""
        if self._clip_stack:
            self.pg.set_clip(self._clip_stack.pop())

    # ------------------------------------------------------------------
    # Blitting
    # ------------------------------------------------------------------

    def blit(self, dst: Surface, dx: int, dy: int) -> None:
        """Blit this surface onto *dst* at ``(dx, dy)``."""
        dst.pg.blit(self.pg, (dx + dst._offset_x, dy + dst._offset_y))

    def blit_clip(
        self,
        sx: int,
        sy: int,
        sw: int,
        sh: int,
        dst: Surface,
        dx: int,
        dy: int,
    ) -> None:
        """Blit a sub-rectangle of this surface onto *dst*."""
        area = pygame.Rect(sx, sy, sw, sh)
        dst.pg.blit(self.pg, (dx + dst._offset_x, dy + dst._offset_y), area)

    def blit_alpha(self, dst: Surface, dx: int, dy: int, alpha: int) -> None:
        """
        Blit this surface onto *dst* using a per-surface *alpha* value
        (0–255).  Only meaningful for RGB surfaces.
        """
        # Temporarily set alpha, blit, then reset
        old_alpha = self.pg.get_alpha()
        self.pg.set_alpha(alpha)
        dst.pg.blit(self.pg, (dx + dst._offset_x, dy + dst._offset_y))
        self.pg.set_alpha(old_alpha)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_size(self) -> tuple[int, int]:
        """Return ``(width, height)`` of the surface."""
        return self.pg.get_size()

    def get_bytes(self) -> int:
        """Return the size of the surface in bytes."""
        w, h = self.pg.get_size()
        return w * h * self.pg.get_bytesize()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def release(self) -> None:
        """
        Explicitly free the underlying surface.

        This is useful when temporary surfaces are created frequently
        (e.g. rotozoom) — Python's GC doesn't know the size of the pixel
        data and may delay collection.
        """
        self._srf = None

    # ------------------------------------------------------------------
    # Flip (for the screen surface)
    # ------------------------------------------------------------------

    def flip(self) -> None:
        """Flip (update) the display surface.  Only valid for the screen."""
        pygame.display.flip()

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_bmp(self, path: str) -> None:
        """Save the surface as a BMP file."""
        pygame.image.save(self.pg, path)

    # ------------------------------------------------------------------
    # Compare
    # ------------------------------------------------------------------

    def cmp(self, other: Surface) -> bool:
        """
        Pixel-wise comparison.  Returns ``True`` if the surfaces are
        identical in size and content.
        """
        if self.pg.get_size() != other.pg.get_size():
            return False
        # Convert both to the same format and compare raw bytes
        buf_a = pygame.image.tobytes(self.pg, "RGBA")
        buf_b = pygame.image.tobytes(other.pg, "RGBA")
        return buf_a == buf_b

    # ------------------------------------------------------------------
    # Transforms
    # ------------------------------------------------------------------

    def rotozoom(self, angle: float, zoom: float, smooth: int = 1) -> Surface:
        """
        Rotate and zoom the surface.

        *angle* is in degrees (counter-clockwise).  *zoom* is a scale
        factor (1.0 = original size).  *smooth* enables anti-aliasing
        when non-zero.
        """
        pg = pygame.transform.rotozoom(self.pg, angle, zoom)
        return Surface(pg)

    def zoom(self, zoom_x: float, zoom_y: float, smooth: int = 1) -> Surface:
        """Scale the surface by independent X and Y factors."""
        w, h = self.pg.get_size()
        new_w = max(1, int(w * zoom_x))
        new_h = max(1, int(h * zoom_y))
        if smooth:
            pg = pygame.transform.smoothscale(self.pg, (new_w, new_h))
        else:
            pg = pygame.transform.scale(self.pg, (new_w, new_h))
        return Surface(pg)

    def shrink(self, factor_x: int, factor_y: int) -> Surface:
        """
        Shrink the surface by integer factors (e.g. ``shrink(2, 2)``
        halves the size).
        """
        w, h = self.pg.get_size()
        new_w = max(1, w // max(1, factor_x))
        new_h = max(1, h // max(1, factor_y))
        pg = pygame.transform.smoothscale(self.pg, (new_w, new_h))
        return Surface(pg)

    def resize(self, new_w: int, new_h: int, smooth: int = 1) -> Surface:
        """Resize the surface to an exact pixel size."""
        new_w = max(1, new_w)
        new_h = max(1, new_h)
        if smooth:
            pg = pygame.transform.smoothscale(self.pg, (new_w, new_h))
        else:
            pg = pygame.transform.scale(self.pg, (new_w, new_h))
        return Surface(pg)

    # ------------------------------------------------------------------
    # Drawing primitives  (SDL_gfx equivalents via pygame.draw / gfxdraw)
    #
    # All coordinates are offset by (self._offset_x, self._offset_y).
    # ------------------------------------------------------------------

    def _ox(self, x: int) -> int:
        return x + self._offset_x

    def _oy(self, y: int) -> int:
        return y + self._offset_y

    def pixel(self, x: int, y: int, color: int) -> None:
        """Draw a single pixel."""
        try:
            pygame.gfxdraw.pixel(
                self.pg, self._ox(x), self._oy(y), _rgba_to_tuple(color)
            )
        except OverflowError:
            pass  # off-screen

    def hline(self, x1: int, x2: int, y: int, color: int) -> None:
        """Draw a horizontal line from ``(x1, y)`` to ``(x2, y)``."""
        try:
            pygame.gfxdraw.hline(
                self.pg,
                self._ox(x1),
                self._ox(x2),
                self._oy(y),
                _rgba_to_tuple(color),
            )
        except OverflowError:
            pass

    def vline(self, x: int, y1: int, y2: int, color: int) -> None:
        """Draw a vertical line from ``(x, y1)`` to ``(x, y2)``."""
        try:
            pygame.gfxdraw.vline(
                self.pg,
                self._ox(x),
                self._oy(y1),
                self._oy(y2),
                _rgba_to_tuple(color),
            )
        except OverflowError:
            pass

    def rectangle(self, x1: int, y1: int, x2: int, y2: int, color: int) -> None:
        """Draw an unfilled rectangle."""
        try:
            pygame.gfxdraw.rectangle(
                self.pg,
                pygame.Rect(
                    self._ox(x1),
                    self._oy(y1),
                    x2 - x1,
                    y2 - y1,
                ),
                _rgba_to_tuple(color),
            )
        except OverflowError:
            pass

    def filled_rectangle(self, x1: int, y1: int, x2: int, y2: int, color: int) -> None:
        """Draw a filled rectangle."""
        try:
            pygame.gfxdraw.box(
                self.pg,
                pygame.Rect(
                    self._ox(x1),
                    self._oy(y1),
                    x2 - x1,
                    y2 - y1,
                ),
                _rgba_to_tuple(color),
            )
        except OverflowError:
            pass

    def line(self, x1: int, y1: int, x2: int, y2: int, color: int) -> None:
        """Draw a line."""
        pygame.draw.line(
            self.pg,
            _rgba_to_tuple(color),
            (self._ox(x1), self._oy(y1)),
            (self._ox(x2), self._oy(y2)),
        )

    def aaline(self, x1: int, y1: int, x2: int, y2: int, color: int) -> None:
        """Draw an anti-aliased line."""
        pygame.draw.aaline(
            self.pg,
            _rgba_to_tuple(color),
            (self._ox(x1), self._oy(y1)),
            (self._ox(x2), self._oy(y2)),
        )

    def circle(self, x: int, y: int, r: int, color: int) -> None:
        """Draw an unfilled circle."""
        try:
            pygame.gfxdraw.circle(
                self.pg, self._ox(x), self._oy(y), r, _rgba_to_tuple(color)
            )
        except OverflowError:
            pass

    def aacircle(self, x: int, y: int, r: int, color: int) -> None:
        """Draw an anti-aliased circle."""
        try:
            pygame.gfxdraw.aacircle(
                self.pg, self._ox(x), self._oy(y), r, _rgba_to_tuple(color)
            )
        except OverflowError:
            pass

    def filled_circle(self, x: int, y: int, r: int, color: int) -> None:
        """Draw a filled circle."""
        try:
            pygame.gfxdraw.filled_circle(
                self.pg, self._ox(x), self._oy(y), r, _rgba_to_tuple(color)
            )
        except OverflowError:
            pass

    def ellipse(self, x: int, y: int, rx: int, ry: int, color: int) -> None:
        """Draw an unfilled ellipse."""
        try:
            pygame.gfxdraw.ellipse(
                self.pg, self._ox(x), self._oy(y), rx, ry, _rgba_to_tuple(color)
            )
        except OverflowError:
            pass

    def aaellipse(self, x: int, y: int, rx: int, ry: int, color: int) -> None:
        """Draw an anti-aliased ellipse."""
        try:
            pygame.gfxdraw.aaellipse(
                self.pg, self._ox(x), self._oy(y), rx, ry, _rgba_to_tuple(color)
            )
        except OverflowError:
            pass

    def filled_ellipse(self, x: int, y: int, rx: int, ry: int, color: int) -> None:
        """Draw a filled ellipse."""
        try:
            pygame.gfxdraw.filled_ellipse(
                self.pg, self._ox(x), self._oy(y), rx, ry, _rgba_to_tuple(color)
            )
        except OverflowError:
            pass

    def pie(self, x: int, y: int, r: int, start: int, end: int, color: int) -> None:
        """Draw an unfilled pie/arc segment."""
        try:
            pygame.gfxdraw.pie(
                self.pg,
                self._ox(x),
                self._oy(y),
                r,
                start,
                end,
                _rgba_to_tuple(color),
            )
        except OverflowError:
            pass

    def filled_pie(
        self, x: int, y: int, r: int, start: int, end: int, color: int
    ) -> None:
        """Draw a filled pie/arc segment."""
        # pygame.gfxdraw doesn't expose filledPie directly; use pygame.draw.
        # We draw a filled arc approximation via polygon points.
        import math

        cx, cy = self._ox(x), self._oy(y)
        col = _rgba_to_tuple(color)
        points = [(cx, cy)]
        # Step through the arc in 2-degree increments
        s = start % 360
        e = end % 360
        if e <= s:
            e += 360
        for a in range(s, e + 1, 2):
            rad = math.radians(a)
            px = cx + int(r * math.cos(rad))
            py = cy + int(r * math.sin(rad))
            points.append((px, py))
        if len(points) >= 3:
            pygame.draw.polygon(self.pg, col, points)

    def trigon(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        x3: int,
        y3: int,
        color: int,
    ) -> None:
        """Draw an unfilled triangle."""
        try:
            pygame.gfxdraw.trigon(
                self.pg,
                self._ox(x1),
                self._oy(y1),
                self._ox(x2),
                self._oy(y2),
                self._ox(x3),
                self._oy(y3),
                _rgba_to_tuple(color),
            )
        except OverflowError:
            pass

    def aatrigon(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        x3: int,
        y3: int,
        color: int,
    ) -> None:
        """Draw an anti-aliased triangle."""
        try:
            pygame.gfxdraw.aatrigon(
                self.pg,
                self._ox(x1),
                self._oy(y1),
                self._ox(x2),
                self._oy(y2),
                self._ox(x3),
                self._oy(y3),
                _rgba_to_tuple(color),
            )
        except OverflowError:
            pass

    def filled_trigon(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        x3: int,
        y3: int,
        color: int,
    ) -> None:
        """Draw a filled triangle."""
        try:
            pygame.gfxdraw.filled_trigon(
                self.pg,
                self._ox(x1),
                self._oy(y1),
                self._ox(x2),
                self._oy(y2),
                self._ox(x3),
                self._oy(y3),
                _rgba_to_tuple(color),
            )
        except OverflowError:
            pass

    # ------------------------------------------------------------------
    # Fill  (convenience — not in original C API but very common)
    # ------------------------------------------------------------------

    def fill(self, color: int) -> None:
        """Fill the entire surface with *color* (32-bit RGBA)."""
        self.pg.fill(_rgba_to_tuple(color))

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        if self._srf is None:
            return "Surface(<released>)"
        w, h = self._srf.get_size()
        bits = self._srf.get_bitsize()
        return f"Surface({w}x{h}, {bits}bit)"

    def __del__(self) -> None:
        # Let pygame's garbage collection handle it, but clear our ref.
        self._srf = None
