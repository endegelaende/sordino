"""
jive.ui.icon — Icon widget for the Jivelite Python3 port.

Ported from ``Icon.lua`` and ``jive_icon.c`` in the original jivelite project.

An Icon widget displays an image (a :class:`~jive.ui.surface.Surface`).
The image can be set programmatically or supplied by the active skin/style.

Features:

* **Static image display** — set via constructor or ``set_value()``
* **Style default image** — falls back to ``img`` (or custom ``img_style_name``)
  from the active skin when no explicit image is set
* **Frame animation** — sprite-sheet animation driven by ``frameRate`` /
  ``frameWidth`` style parameters
* **Background tile** — optional ``bgImg`` tile rendered behind the icon
* **Alignment** — icon position within bounds controlled by ``align`` style
* **Network sink** — ``sink()`` returns an LTN12-style callback for loading
  images from the network layer
* **Preferred bounds** — reports image size + padding so layout containers
  can size the widget correctly

Copyright 2010 Logitech. All Rights Reserved. (original Lua/C code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Optional,
    Tuple,
)

from jive.ui.constants import (
    ALIGN_TOP_LEFT,
    LAYER_ALL,
    LAYER_CONTENT,
    WH_NIL,
    XY_NIL,
    Align,
)
from jive.ui.widget import Widget
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.surface import Surface
    from jive.ui.tile import JiveTile  # type: ignore[attr-defined]

__all__ = ["Icon"]

log = logger("jivelite.ui")

# ---------------------------------------------------------------------------
# Scroll / animation constants matching jive_icon.c
# ---------------------------------------------------------------------------

_FRAME_RATE_DEFAULT = 0  # 0 = no animation


# ---------------------------------------------------------------------------
# Icon widget
# ---------------------------------------------------------------------------


class Icon(Widget):
    """
    A widget that displays an image.

    Parameters
    ----------
    style : str
        The style key used to look up skin parameters.
    image : Surface, optional
        An explicit image surface.  When *None* the style's ``img``
        value is used as the default image.
    """

    __slots__ = (
        "image",
        "img_style_name",
        "_img",
        "_default_img",
        "_bg_tile",
        "_frame_width",
        "_frame_rate",
        "_anim_frame",
        "_anim_total",
        "_image_width",
        "_image_height",
        "_icon_align",
        "_offset_x",
        "_offset_y",
        "_animation_handle",
    )

    def __init__(self, style: str, image: Optional[Surface] = None) -> None:
        if not isinstance(style, str):
            raise TypeError(f"style must be a string, got {type(style).__name__}")

        super().__init__(style)

        # Lua-side fields
        self.image: Optional[Surface] = image
        self.img_style_name: Optional[str] = None

        # Peer-equivalent state (mirroring IconWidget in C)
        self._img: Optional[Surface] = None  # currently active image (ref)
        self._default_img: Optional[Surface] = None  # from style
        self._bg_tile: Optional[JiveTile] = None

        # Animation
        self._frame_width: int = -1
        self._frame_rate: int = 0
        self._anim_frame: int = 0
        self._anim_total: int = 1

        # Computed image metrics
        self._image_width: int = 0
        self._image_height: int = 0

        # Alignment
        self._icon_align: int = int(ALIGN_TOP_LEFT)

        # Drawing offsets
        self._offset_x: int = 0
        self._offset_y: int = 0

        # Animation handle (from Widget.add_animation)
        self._animation_handle: Any = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_image(self) -> Optional[Surface]:
        """Return the explicit image set on this icon, or *None*."""
        return self.image

    def set_value(self, image: Optional[Surface]) -> None:
        """
        Set the image displayed by this icon.

        If the image size changes, a re-layout is triggered; otherwise
        only a re-draw.
        """
        old_w = self._image_width
        old_h = self._image_height

        self.image = image
        self._prepare()

        if self._image_width != old_w or self._image_height != old_h:
            self.re_layout()
        else:
            self.re_draw()

    # Alias matching Lua ``Icon:setValue``
    setValue = set_value

    def sink(self) -> Callable[[Optional[bytes], Optional[str]], bool]:
        """
        Return an LTN12-style sink function for loading images from the
        network.

        Usage with the jive.net classes::

            icon = Icon("icon")
            req = RequestHttp(icon.sink())
            http.fetch(req)
        """

        def _sink(
            chunk: Optional[bytes] = None,
            err: Optional[str] = None,
        ) -> bool:
            if err:
                # FIXME — error handling
                pass
            elif chunk:
                from jive.ui.surface import Surface as SurfaceClass

                surf = SurfaceClass.load_image_data(chunk, len(chunk))
                self.set_value(surf)
            return True

        return _sink

    # ------------------------------------------------------------------
    # Skin (jiveL_icon_skin)
    # ------------------------------------------------------------------

    def re_skin(self) -> None:
        """Reset all icon-specific cached skin state, then call super.

        Sets ``_img = None`` so that ``_prepare()`` will re-process the
        active image (recalculating width/height/animation) instead of
        taking the early-return ``img is self._img`` path.

        Does NOT touch ``self.image`` — that is the programmatically
        set image owned by the caller, not a cached skin value.
        """
        self._bg_tile = None
        self._default_img = None
        self._img = None  # force _prepare() to re-process
        self._frame_width = -1
        self._frame_rate = 0
        self._anim_frame = 0
        self._anim_total = 1
        self._offset_x = 0
        self._offset_y = 0
        self._icon_align = int(ALIGN_TOP_LEFT)
        super().re_skin()

    def _skin(self) -> None:
        """
        Apply skin/style parameters.

        Reads: ``img`` (or custom ``imgStyleName``), ``frameRate``,
        ``frameWidth``, ``bgImg``, ``align``.
        """
        from jive.ui.style import (
            style_align,
            style_image,
            style_insets,
            style_int,
            style_tile,
        )

        # jive_widget_pack equivalent — read preferred bounds, padding,
        # border, layer, z-order, hidden from style.
        self._widget_pack()

        # Default image from style
        img_key = self.img_style_name or "img"
        img = style_image(self, img_key, None)

        # Title-bar button icons (and similar) are stored as Tiles in the
        # skin, not as Surfaces.  When style_image() finds nothing, fall
        # back to style_tile() and extract the underlying pygame.Surface.
        tile = None
        if img is None:
            tile = style_tile(self, img_key, None)
            if tile is not None:
                pg_surf = tile.get_image_surface()
                if pg_surf is not None:
                    from jive.ui.surface import Surface as SurfaceClass

                    img = SurfaceClass(pg_surf)

        # Diagnostic: log title-bar button icon resolution
        parent = self.parent
        parent_style = getattr(parent, "style", "") if parent else ""
        if parent_style.startswith("button_") and parent_style != "button_none":
            from jive.ui.style import style_path as _style_path

            path = _style_path(self)
            if img is not None:
                log.info(
                    "Icon._skin: button icon OK — path=%r hidden=%s img=%r",
                    path,
                    self._hidden,
                    type(img).__name__,
                )
            else:
                log.warn(
                    "Icon._skin: button icon MISSING — path=%r hidden=%s "
                    "style_image=None tile=%r parent_style=%r",
                    path,
                    self._hidden,
                    tile,
                    parent_style,
                )

        if self._default_img is not img:
            self._default_img = img

        # Animation parameters
        self._frame_rate = style_int(self, "frameRate", 0)
        if self._frame_rate:
            self._frame_width = style_int(self, "frameWidth", -1)

        # Background tile
        bg_tile = style_tile(self, "bgImg", None)
        if bg_tile is not self._bg_tile:
            self._bg_tile = bg_tile

        # Alignment
        self._icon_align = style_align(self, "align", int(ALIGN_TOP_LEFT))

    # ------------------------------------------------------------------
    # Prepare (selects active image, sets up animation)
    # ------------------------------------------------------------------

    def _prepare(self) -> None:
        """
        Select the active image (explicit > style default) and set up
        frame animation if required.

        Mirrors the ``prepare()`` function in ``jive_icon.c``.
        """
        # Choose image: widget image takes priority over style default
        img = self.image if self.image is not None else self._default_img

        # Several skins use ``"img": False`` to mean "no image for this
        # state".  Guard against any non-Surface value that slipped
        # through style lookup so we never call .get_size() on a bool.
        if img is not None and not hasattr(img, "get_size"):
            img = None

        if img is self._img:
            return  # no change

        # Release old ref (Python GC handles actual memory)
        self._img = img
        self._anim_frame = 0

        # Remove existing animation handler
        if self._animation_handle is not None:
            self.remove_animation(self._animation_handle)
            self._animation_handle = None

        if self._img is not None:
            w, h = self._img.get_size()
            self._image_width = w
            self._image_height = h

            # Animated icon (sprite sheet)
            if self._frame_rate and self._frame_width > 0:
                self._anim_total = max(1, self._image_width // self._frame_width)
                self._image_width = self._frame_width

                # Register animation
                self._animation_handle = self.add_animation(self._do_animate, self._frame_rate)
            else:
                self._anim_total = 1
        else:
            self._image_width = 0
            self._image_height = 0
            self._anim_total = 1

    # ------------------------------------------------------------------
    # Layout (jiveL_icon_layout)
    # ------------------------------------------------------------------

    def _layout(self) -> None:
        """
        Compute the icon's draw offset inside its bounds using the
        configured alignment.
        """
        self._prepare()

        if self._img is not None:
            bx, by, bw, bh = self.get_bounds()
            pl, pt, pr, pb = self.get_padding()

            inner_x = bx + pl
            inner_y = by + pt
            inner_w = bw - pl - pr
            inner_h = bh - pt - pb

            self._offset_x = (
                Widget.halign(self._icon_align, inner_x, inner_w, self._image_width) - bx
            )
            self._offset_y = (
                Widget.valign(self._icon_align, inner_y, inner_h, self._image_height) - by
            )

    # ------------------------------------------------------------------
    # Animation (jiveL_icon_animate)
    # ------------------------------------------------------------------

    def _do_animate(self) -> None:
        """Advance the animation frame and request a redraw."""
        if self._anim_total > 0:
            self._anim_frame += 1
            if self._anim_frame >= self._anim_total:
                self._anim_frame = 0
            self.re_draw()

    # ------------------------------------------------------------------
    # Draw (jiveL_icon_draw)
    # ------------------------------------------------------------------

    def draw(self, surface: Surface, layer: int = LAYER_ALL) -> None:
        """
        Draw the icon onto *surface*.

        Parameters
        ----------
        surface : Surface
            The target surface to paint on.
        layer : int
            Bitmask of layers to draw (default ``LAYER_ALL``).
        """
        draw_layer = layer & self._layer

        # Background tile
        if draw_layer and self._bg_tile is not None:
            bx, by, bw, bh = self.get_bounds()
            self._bg_tile.blit(surface, bx, by, bw, bh)

        if not draw_layer or self._img is None:
            return

        bx, by, bw, bh = self.get_bounds()

        # Clip to widget bounds
        surface.push_clip(bx, by, bw, bh)
        try:
            # Source rect for the current animation frame
            src_x = self._image_width * self._anim_frame
            src_y = 0
            src_w = self._image_width
            src_h = self._image_height

            dst_x = bx + self._offset_x
            dst_y = by + self._offset_y

            self._img.blit_clip(src_x, src_y, src_w, src_h, surface, dst_x, dst_y)
        finally:
            surface.pop_clip()

    # ------------------------------------------------------------------
    # Preferred bounds (jiveL_icon_get_preferred_bounds)
    # ------------------------------------------------------------------

    def get_preferred_bounds(
        self,
    ) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
        """
        Return the preferred ``(x, y, w, h)`` for layout purposes.

        Width and height include padding around the image.
        """
        self.check_skin()
        self._prepare()

        w: int = 0
        h: int = 0

        if self._img is not None:
            img_w, img_h = self._img.get_size()

            if self._anim_total > 1:
                img_w //= self._anim_total

            pl, pt, pr, pb = self.get_padding()
            w = img_w + pl + pr
            h = img_h + pt + pb

        pb = self.preferred_bounds  # type: ignore[assignment]
        px = pb[0] if pb[0] is not None and pb[0] != XY_NIL else None  # type: ignore[index]
        py = pb[1] if pb[1] is not None and pb[1] != XY_NIL else None  # type: ignore[index]
        pw = pb[2] if pb[2] is not None and pb[2] != WH_NIL else w  # type: ignore[index]
        ph = pb[3] if pb[3] is not None and pb[3] != WH_NIL else h  # type: ignore[index]

        return (px, py, pw, ph)

    # ------------------------------------------------------------------
    # jive_widget_pack — read common style properties
    # ------------------------------------------------------------------

    def _widget_pack(self) -> None:
        """
        Read the common widget style properties: preferred bounds,
        padding, border, layer, z-order, hidden.

        This mirrors ``jive_widget_pack()`` in ``jive_widget.c``.
        """
        from jive.ui.style import style_insets, style_int

        # Preferred bounds
        sx = style_int(self, "x", XY_NIL)
        sy = style_int(self, "y", XY_NIL)
        sw = style_int(self, "w", WH_NIL)
        sh = style_int(self, "h", WH_NIL)

        self.preferred_bounds[0] = None if sx == XY_NIL else sx
        self.preferred_bounds[1] = None if sy == XY_NIL else sy
        self.preferred_bounds[2] = None if sw == WH_NIL else sw
        self.preferred_bounds[3] = None if sh == WH_NIL else sh

        # Padding & border
        pad = style_insets(self, "padding", [0, 0, 0, 0])
        self.padding[:] = pad[:4] if len(pad) >= 4 else pad + [0] * (4 - len(pad))

        bdr = style_insets(self, "border", [0, 0, 0, 0])
        self.border[:] = bdr[:4] if len(bdr) >= 4 else bdr + [0] * (4 - len(bdr))

        # Layer / z-order / hidden
        self._layer = style_int(self, "layer", int(LAYER_CONTENT))
        self._z_order = style_int(self, "zOrder", 0)
        self._hidden = bool(style_int(self, "hidden", 0))

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        label = self.image or self.style
        return f"Icon({label!r})"

    def __str__(self) -> str:
        return self.__repr__()
