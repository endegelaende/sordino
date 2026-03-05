"""
jive.ui.tile — Tiled image system for the Jivelite Python3 port.

Ported from the C tile functions in ``src/jive_surface.c`` and the Lua
wrapper ``share/jive/jive/ui/Tile.lua`` in the original jivelite project.

In the original C code, ``JiveTile`` is actually a typedef alias for
``JiveSurface`` (``typedef JiveSurface JiveTile;``).  The two share the
same struct, but Tile adds 9-patch blitting semantics: a tile can be
composed of up to 9 sub-images that are tiled/stretched to fill an
arbitrary rectangle.

Tile types
----------

* **fill_color** — solid colour fill (no image, just ``boxColor``)
* **load_image** — single image, tiled to fill the area
* **load_tiles** — 9-patch: 4 corners + 4 edges + 1 center
* **load_htiles** — horizontal 3-patch: left / center / right
* **load_vtiles** — vertical 3-patch: top / center / bottom

9-patch layout (matching C ``tile->image[0..8]``):

    ┌──────┬──────┬──────┐
    │  [1] │  [2] │  [3] │   top-left, top, top-right
    ├──────┼──────┼──────┤
    │  [8] │  [0] │  [4] │   left, center, right
    ├──────┼──────┼──────┤
    │  [7] │  [6] │  [5] │   bottom-left, bottom, bottom-right
    └──────┴──────┴──────┘

Copyright 2010 Logitech. All Rights Reserved. (original C code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple, Union

import pygame

from jive.ui.surface import Surface, find_file

if TYPE_CHECKING:
    pass

__all__ = ["Tile"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rgba_to_tuple(color: int) -> Tuple[int, int, int, int]:
    """Convert a 32-bit ``0xRRGGBBAA`` integer to ``(r, g, b, a)``."""
    return (
        (color >> 24) & 0xFF,
        (color >> 16) & 0xFF,
        (color >> 8) & 0xFF,
        color & 0xFF,
    )


def _blit_area(
    src: pygame.Surface,
    dst: pygame.Surface,
    dx: int,
    dy: int,
    dw: int,
    dh: int,
) -> None:
    """
    Tile-blit *src* into the rectangle ``(dx, dy, dw, dh)`` on *dst*.

    The source image is repeated (tiled) to fill the target area,
    exactly matching the C ``blit_area`` helper in ``jive_surface.c``.
    """
    if dw <= 0 or dh <= 0:
        return

    tw = src.get_width()
    th = src.get_height()
    if tw <= 0 or th <= 0:
        return

    y = dy
    remaining_h = dh
    while remaining_h > 0:
        bh = min(th, remaining_h)
        x = dx
        remaining_w = dw
        while remaining_w > 0:
            bw = min(tw, remaining_w)
            dst.blit(src, (x, y), (0, 0, bw, bh))
            x += tw
            remaining_w -= tw
        y += th
        remaining_h -= th


# ---------------------------------------------------------------------------
# Tile flags (matching C defines in jive_surface.c)
# ---------------------------------------------------------------------------

_FLAG_INIT: int = 1 << 0
_FLAG_BG: int = 1 << 1
_FLAG_ALPHA: int = 1 << 2
_FLAG_IMAGE: int = 1 << 4
_FLAG_TILE: int = 1 << 5


# ---------------------------------------------------------------------------
# Tile class
# ---------------------------------------------------------------------------


class Tile:
    """
    A tiled image used to fill an area.

    Mirrors the ``JiveTile`` C API:

    * **Static constructors:** ``fill_color``, ``load_image``,
      ``load_tiles``, ``load_htiles``, ``load_vtiles``
    * **Blitting:** ``blit``, ``blit_centered``
    * **Query:** ``get_min_size``
    * **Lifecycle:** ``free``

    Unlike the C implementation which shares the struct with Surface, the
    Python port keeps Tile as its own class with a clear separation from
    ``Surface``.  It holds either a solid colour, a single ``pygame.Surface``,
    or up to 9 ``pygame.Surface`` patches.
    """

    __slots__ = (
        "_flags",
        "_bg_color",
        "_sdl",
        "_images",
        "_w",
        "_h",
        "_alpha_flags",
        "_refcount",
    )

    def __init__(self) -> None:
        self._flags: int = 0
        self._bg_color: int = 0x000000FF  # default black
        self._sdl: Optional[pygame.Surface] = None
        self._images: List[Optional[pygame.Surface]] = [None] * 9
        # Corner dimensions: w[0] = left-col width, w[1] = right-col width
        #                    h[0] = top-row height, h[1] = bottom-row height
        self._w: List[int] = [0, 0]
        self._h: List[int] = [0, 0]
        self._alpha_flags: int = 0
        self._refcount: int = 1

    # ==================================================================
    # Static constructors
    # ==================================================================

    @staticmethod
    def fill_color(color: int) -> Tile:
        """
        Create a tile that fills with a solid colour.

        *color* is a 32-bit ``0xRRGGBBAA`` value (matching the C API).
        """
        tile = Tile()
        tile._flags = _FLAG_INIT | _FLAG_BG
        tile._bg_color = color
        return tile

    @staticmethod
    def load_image(path: str) -> Optional[Tile]:
        """
        Create a tile from a single image file.

        The image is tiled (repeated) to fill the blit area.  Uses the
        global search-path mechanism from ``jive.ui.surface``.

        Returns ``None`` if the file cannot be found.
        """
        if not path:
            return None

        full = find_file(path)
        if full is None:
            return None

        try:
            raw = pygame.image.load(full)
            srf = raw.convert_alpha()
        except pygame.error:
            return None

        tile = Tile()
        tile._flags = _FLAG_INIT | _FLAG_IMAGE
        tile._sdl = srf
        tile._w[0] = srf.get_width()
        tile._h[0] = srf.get_height()
        return tile

    @staticmethod
    def load_image_data(data: bytes) -> Optional[Tile]:
        """
        Create a tile from raw image bytes (e.g. PNG/JPEG in memory).

        Returns ``None`` on failure.
        """
        import io

        try:
            raw = pygame.image.load(io.BytesIO(data))
            srf = raw.convert_alpha()
        except (pygame.error, Exception):
            return None

        tile = Tile()
        tile._flags = _FLAG_INIT | _FLAG_IMAGE
        tile._sdl = srf
        tile._w[0] = srf.get_width()
        tile._h[0] = srf.get_height()
        return tile

    @staticmethod
    def load_tiles(paths: Sequence[Optional[str]]) -> Optional[Tile]:
        """
        Create a 9-patch tile from up to 9 image paths.

        The *paths* sequence must have exactly 9 elements (some may be
        ``None``).  The layout matches the C code::

            [0] = center
            [1] = top-left      [2] = top       [3] = top-right
            [4] = right          [5] = bottom-right
            [6] = bottom         [7] = bottom-left
            [8] = left
        """
        if len(paths) < 9:
            padded: List[Optional[str]] = list(paths) + [None] * (9 - len(paths))
        else:
            padded = list(paths[:9])

        tile = Tile()
        tile._flags = _FLAG_TILE

        found = 0
        for i, p in enumerate(padded):
            if p is None:
                continue
            full = find_file(p)
            if full is None:
                continue
            try:
                raw = pygame.image.load(full)
                srf = raw.convert_alpha()
                tile._images[i] = srf
                found += 1
            except pygame.error:
                pass

        if found == 0:
            return None

        tile._init_sizes()
        return tile

    @staticmethod
    def load_vtiles(paths: Sequence[str]) -> Optional[Tile]:
        """
        Create a vertical 3-patch tile from ``[top, center, bottom]``.

        Maps to 9-patch positions ``[1, 8, 7]`` (matching the C
        ``jive_tile_load_vtiles`` which uses positions top-left → left →
        bottom-left for the vertical strip).

        Actually, looking at C code:
            path2[1] = path[0]  (top)
            path2[8] = path[1]  (middle / left)
            path2[7] = path[2]  (bottom)
        """
        if len(paths) < 3:
            return None
        nine: List[Optional[str]] = [None] * 9
        nine[1] = paths[0]
        nine[8] = paths[1]
        nine[7] = paths[2]
        return Tile.load_tiles(nine)

    @staticmethod
    def load_htiles(paths: Sequence[str]) -> Optional[Tile]:
        """
        Create a horizontal 3-patch tile from ``[left, center, right]``.

        Maps to 9-patch positions ``[1, 2, 3]`` (matching the C
        ``jive_tile_load_htiles``).
        """
        if len(paths) < 3:
            return None
        nine: List[Optional[str]] = [None] * 9
        nine[1] = paths[0]
        nine[2] = paths[1]
        nine[3] = paths[2]
        return Tile.load_tiles(nine)

    @staticmethod
    def from_surface(surface: Surface) -> Tile:
        """
        Create a tile that wraps an existing ``Surface``.

        This is used when a Surface needs to be blitted as if it were a
        Tile (e.g. as a background image).
        """
        tile = Tile()
        tile._flags = _FLAG_INIT | _FLAG_IMAGE
        tile._sdl = surface.pg
        w, h = surface.get_size()
        tile._w[0] = w
        tile._h[0] = h
        return tile

    # ==================================================================
    # Size computation (matching C ``_init_tile_sizes``)
    # ==================================================================

    def _init_sizes(self) -> None:
        """
        Compute corner dimensions from the loaded patch images.

        Matches the C ``_init_tile_sizes`` function.
        """
        if self._flags & _FLAG_INIT:
            return

        self._w[0] = 0
        self._w[1] = 0
        self._h[0] = 0
        self._h[1] = 0

        imgs = self._images

        # top-left [1]
        if imgs[1]:
            self._w[0] = max(imgs[1].get_width(), self._w[0])
            self._h[0] = max(imgs[1].get_height(), self._h[0])

        # top-right [3]
        if imgs[3]:
            self._w[1] = max(imgs[3].get_width(), self._w[1])
            self._h[0] = max(imgs[3].get_height(), self._h[0])

        # bottom-right [5]
        if imgs[5]:
            self._w[1] = max(imgs[5].get_width(), self._w[1])
            self._h[1] = max(imgs[5].get_height(), self._h[1])

        # bottom-left [7]
        if imgs[7]:
            self._w[0] = max(imgs[7].get_width(), self._w[0])
            self._h[1] = max(imgs[7].get_height(), self._h[1])

        # top [2]
        if imgs[2]:
            self._h[0] = max(imgs[2].get_height(), self._h[0])

        # right [4]
        if imgs[4]:
            self._w[1] = max(imgs[4].get_width(), self._w[1])

        # bottom [6]
        if imgs[6]:
            self._h[1] = max(imgs[6].get_height(), self._h[1])

        # left [8]
        if imgs[8]:
            self._w[0] = max(imgs[8].get_width(), self._w[0])

        # Special case: single center image only
        if imgs[0] and not imgs[1] and self._w[0] == 0:
            self._w[0] = imgs[0].get_width()
            self._h[0] = imgs[0].get_height()

        self._flags |= _FLAG_INIT

    # ==================================================================
    # Query
    # ==================================================================

    def get_min_size(self) -> Tuple[int, int]:
        """
        Return the minimum ``(width, height)`` the tile can be painted.

        For a solid-color tile this is ``(0, 0)``.
        For a single-image tile this is the image size.
        For a 9-patch tile this is the sum of corner dimensions.
        """
        if self._sdl is not None:
            return (self._sdl.get_width(), self._sdl.get_height())

        self._init_sizes()
        return (self._w[0] + self._w[1], self._h[0] + self._h[1])

    def get_image_surface(self) -> Optional[pygame.Surface]:
        """
        Return the underlying ``pygame.Surface`` if this tile is backed
        by a single image, otherwise ``None``.
        """
        if self._sdl is not None:
            return self._sdl
        if self._images[0] is not None:
            return self._images[0]
        return None

    # ==================================================================
    # Alpha
    # ==================================================================

    def set_alpha(self, flags: int) -> None:
        """
        Set per-surface alpha flags on all sub-surfaces.

        *flags* is passed to ``pygame.Surface.set_alpha()``.  A value of
        0 disables per-surface alpha.
        """
        self._alpha_flags = flags
        self._flags |= _FLAG_ALPHA

        if self._sdl is not None:
            self._sdl.set_alpha(flags if flags else None)
            return

        for img in self._images:
            if img is not None:
                img.set_alpha(flags if flags else None)

    # ==================================================================
    # Blitting
    # ==================================================================

    def blit(
        self,
        dst: Surface,
        dx: int,
        dy: int,
        dw: int = 0,
        dh: int = 0,
    ) -> None:
        """
        Blit this tile onto *dst* at ``(dx, dy)`` filling the area
        ``(dw, dh)``.

        If *dw* or *dh* is 0, the tile's minimum size is used for that
        dimension (matching the C ``jive_tile_blit``).
        """
        if dw <= 0 or dh <= 0:
            mw, mh = self.get_min_size()
            if dw <= 0:
                dw = mw
            if dh <= 0:
                dh = mh

        if dw <= 0 or dh <= 0:
            return

        self._blit_impl(dst, dx, dy, dw, dh)

    def blit_centered(
        self,
        dst: Surface,
        dx: int,
        dy: int,
        dw: int = 0,
        dh: int = 0,
    ) -> None:
        """
        Blit this tile centered at ``(dx, dy)`` filling at least
        ``(dw, dh)``.

        Matches the C ``jive_tile_blit_centered``.
        """
        mw, mh = self.get_min_size()
        if dw < mw:
            dw = mw
        if dh < mh:
            dh = mh

        self._blit_impl(dst, dx - dw // 2, dy - dh // 2, dw, dh)

    def _blit_impl(
        self,
        dst: Surface,
        dx: int,
        dy: int,
        dw: int,
        dh: int,
    ) -> None:
        """
        Internal blit implementation matching the C ``_blit_tile``.
        """
        # --- Solid colour fill ---
        if self._flags & _FLAG_BG:
            r, g, b, a = _rgba_to_tuple(self._bg_color)
            # Use Surface's filled_rectangle which respects offsets
            dst.filled_rectangle(dx, dy, dx + dw - 1, dy + dh - 1, self._bg_color)
            return

        # Resolve the destination pygame.Surface (with offset applied)
        dst_srf = dst.pg
        dst_ox = dst._offset_x
        dst_oy = dst._offset_y
        actual_dx = dx + dst_ox
        actual_dy = dy + dst_oy

        # --- Single image (simple or data-loaded) ---
        if self._sdl is not None:
            _blit_area(self._sdl, dst_srf, actual_dx, actual_dy, dw, dh)
            return

        # --- 9-patch ---
        imgs = self._images
        self._init_sizes()

        # Dynamically-loaded single image (position 0 only, no corners)
        if (self._flags & _FLAG_IMAGE) and imgs[0] is not None:
            _blit_area(imgs[0], dst_srf, actual_dx, actual_dy, dw, dh)
            return

        ox = 0
        oy = 0
        ow = 0
        oh = 0

        # top-left [1]
        if imgs[1] is not None:
            ox = min(self._w[0], dw)
            oy = min(self._h[0], dh)
            _blit_area(imgs[1], dst_srf, actual_dx, actual_dy, ox, oy)

        # top-right [3]
        if imgs[3] is not None:
            ow = min(self._w[1], dw)
            oy = min(self._h[0], dh)
            _blit_area(imgs[3], dst_srf, actual_dx + dw - ow, actual_dy, ow, oy)

        # bottom-right [5]
        if imgs[5] is not None:
            ow = min(self._w[1], dw)
            oh = min(self._h[1], dh)
            _blit_area(
                imgs[5],
                dst_srf,
                actual_dx + dw - ow,
                actual_dy + dh - oh,
                ow,
                oh,
            )

        # bottom-left [7]
        if imgs[7] is not None:
            ox = min(self._w[0], dw)
            oh = min(self._h[1], dh)
            _blit_area(imgs[7], dst_srf, actual_dx, actual_dy + dh - oh, ox, oh)

        # top [2]
        if imgs[2] is not None:
            oy_top = min(self._h[0], dh)
            _blit_area(
                imgs[2],
                dst_srf,
                actual_dx + ox,
                actual_dy,
                dw - ox - ow,
                oy_top,
            )

        # right [4]
        if imgs[4] is not None:
            ow_right = min(self._w[1], dw)
            _blit_area(
                imgs[4],
                dst_srf,
                actual_dx + dw - ow_right,
                actual_dy + oy,
                ow_right,
                dh - oy - oh,
            )

        # bottom [6]
        if imgs[6] is not None:
            oh_bottom = min(self._h[1], dh)
            _blit_area(
                imgs[6],
                dst_srf,
                actual_dx + ox,
                actual_dy + dh - oh_bottom,
                dw - ox - ow,
                oh_bottom,
            )

        # left [8]
        if imgs[8] is not None:
            ox_left = min(self._w[0], dw)
            _blit_area(
                imgs[8],
                dst_srf,
                actual_dx,
                actual_dy + oy,
                ox_left,
                dh - oy - oh,
            )

        # center [0]
        if imgs[0] is not None:
            _blit_area(
                imgs[0],
                dst_srf,
                actual_dx + ox,
                actual_dy + oy,
                dw - ox - ow,
                dh - oy - oh,
            )

    # ==================================================================
    # Lifecycle
    # ==================================================================

    def ref(self) -> Tile:
        """Increment reference count and return self (matching C API)."""
        self._refcount += 1
        return self

    def free(self) -> None:
        """
        Decrement reference count.  When it reaches zero, release all
        image data.
        """
        self._refcount -= 1
        if self._refcount > 0:
            return

        self._sdl = None
        for i in range(9):
            self._images[i] = None

    # ==================================================================
    # Dunder
    # ==================================================================

    def __repr__(self) -> str:
        parts = ["Tile("]
        if self._flags & _FLAG_BG:
            parts.append(f"fill=0x{self._bg_color:08X}")
        elif self._sdl is not None:
            w, h = self._sdl.get_width(), self._sdl.get_height()
            parts.append(f"image={w}x{h}")
        elif self._flags & _FLAG_TILE:
            n = sum(1 for img in self._images if img is not None)
            parts.append(f"patches={n}/9")
        parts.append(")")
        return "".join(parts)
