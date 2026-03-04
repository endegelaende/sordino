"""
jive.ui.label — Label widget for the Jivelite Python3 port.

Ported from ``Label.lua`` and ``jive_label.c`` in the original jivelite project.

A Label widget displays single- or multi-line text.  Any Python value can be
set as the label value — ``str()`` is used to convert it before display.

Features:

* **Multi-line text** — text is split on ``\\n`` / ``\\r`` boundaries and
  each line is rendered independently
* **Per-line formatting** — the ``line`` style array can override ``font``,
  ``lineHeight``, ``fg`` (foreground colour) and ``sh`` (shadow colour) for
  each line index
* **Text scrolling** — when the rendered text is wider than the widget the
  label scrolls horizontally (activated on focus gain, stopped on focus loss)
* **Priority value** — ``set_value(value, priority_duration)`` temporarily
  shows *value* for *priority_duration* ms, then reverts to the persistent
  value
* **Shadow text** — an optional 1-pixel-offset shadow layer behind the
  foreground text
* **Background tile** — optional ``bgImg`` tile rendered behind the text
* **Alignment** — text position within bounds controlled by ``align`` style
* **Preferred bounds** — reports text width/height + padding so layout
  containers can size the widget correctly
* **Style text fallback** — if no value is set, the ``text`` style key is
  used as default content

Copyright 2010 Logitech. All Rights Reserved. (original Lua/C code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import re
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    List,
    Optional,
    Tuple,
)

from jive.ui.constants import (
    ALIGN_LEFT,
    ALIGN_TOP_LEFT,
    FRAME_RATE_DEFAULT,
    LAYER_ALL,
    LAYER_CONTENT,
    WH_NIL,
    XY_NIL,
    Align,
)
from jive.ui.surface import Surface
from jive.ui.widget import Widget
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event
    from jive.ui.surface import Surface
    from jive.ui.tile import JiveTile  # type: ignore[attr-defined]
    from jive.ui.timer import Timer

__all__ = ["Label"]


def _font_metric(font: Any, name: str, default: int = 0) -> int:
    """
    Read a font metric that may be either a method (real Font) or a plain
    attribute (MagicMock in tests).

    Returns *default* when the font is ``None`` or lacks the attribute.
    """
    if font is None:
        return default
    val = getattr(font, name, None)
    if val is None:
        return default
    if callable(val):
        return int(val())
    return int(val)


log = logger("jivelite.ui")

# ---------------------------------------------------------------------------
# Constants matching jive_label.c
# ---------------------------------------------------------------------------

_SCROLL_FPS_DIVISOR = 2  # actual FPS = FRAME_RATE / 2
_SCROLL_OFFSET_STEP_MINIMUM = 5
_FONT_SCROLL_FACTOR = 5

_SCROLL_PAD_RIGHT = 40
_SCROLL_PAD_LEFT = -200
_SCROLL_PAD_START = -100

_MAX_CHARS = 1000  # max characters before splitting a text line

_JIVE_COLOR_BLACK = 0x000000FF
_JIVE_COLOR_WHITE = 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Internal data structures mirroring the C structs
# ---------------------------------------------------------------------------


class _LabelLine:
    """Per-line rendering data (mirrors ``LabelLine`` in C)."""

    __slots__ = (
        "text_sh",
        "text_fg",
        "label_x",
        "label_y",
        "line_height",
        "text_offset",
    )

    def __init__(self) -> None:
        self.text_sh: Optional[Surface] = None
        self.text_fg: Optional[Surface] = None
        self.label_x: int = 0
        self.label_y: int = 0
        self.line_height: int = 0
        self.text_offset: int = 0


class _LabelFormat:
    """Per-line format override (mirrors ``LabelFormat`` in C)."""

    __slots__ = ("font", "is_sh", "is_fg", "fg", "sh", "line_height", "text_offset")

    def __init__(self) -> None:
        self.font: Any = None
        self.is_sh: bool = False
        self.is_fg: bool = False
        self.fg: int = _JIVE_COLOR_BLACK
        self.sh: int = _JIVE_COLOR_BLACK
        self.line_height: int = 0
        self.text_offset: int = 0


# ---------------------------------------------------------------------------
# Label widget
# ---------------------------------------------------------------------------


class Label(Widget):
    """
    A widget that displays text.

    Parameters
    ----------
    style : str
        The style key used to look up skin parameters.
    value : object, optional
        The text (or any object) to display.  ``str()`` is called on it
        before rendering.
    """

    __slots__ = (
        "value",
        "priority_timer",
        "previous_persistent_value",
        "_label_w",
        "_text_align",
        "_bg_tile",
        "_base_font",
        "_base_line_height",
        "_base_text_offset",
        "_base_fg",
        "_base_sh",
        "_base_is_sh",
        "_formats",
        "_scroll_offset",
        "_scroll_offset_step",
        "_lines",
        "_text_w",
        "_text_h",
        "_animation_handle",
        "_text_stop_callback",
    )

    def __init__(self, style: str, value: Any = None) -> None:
        if not isinstance(style, str):
            raise TypeError(f"style must be a string, got {type(style).__name__}")

        super().__init__(style)

        # Lua-side fields
        self.value: Any = value

        # Priority value support
        self.priority_timer: Optional[Timer] = None
        self.previous_persistent_value: Any = None

        # Peer-equivalent state (mirroring LabelWidget in C)
        self._label_w: int = 0  # max render width
        self._text_align: int = int(ALIGN_LEFT)
        self._bg_tile: Optional[JiveTile] = None

        # Base format
        self._base_font: Any = None
        self._base_line_height: int = 0
        self._base_text_offset: int = 0
        self._base_fg: int = _JIVE_COLOR_BLACK
        self._base_sh: int = _JIVE_COLOR_WHITE
        self._base_is_sh: bool = False

        # Per-line format overrides
        self._formats: List[_LabelFormat] = []

        # Scroll
        self._scroll_offset: int = _SCROLL_PAD_START
        self._scroll_offset_step: int = _SCROLL_OFFSET_STEP_MINIMUM

        # Prepared lines
        self._lines: List[_LabelLine] = []
        self._text_w: int = 0  # max text width across lines
        self._text_h: int = 0  # total text height

        # Animation handle (from Widget.add_animation)
        self._animation_handle: Any = None

        # Text-stop callback (optional, called when scroll pauses)
        self._text_stop_callback: Optional[Callable[..., None]] = None

        # Focus listeners for scroll start/stop
        from jive.ui.constants import EVENT_FOCUS_GAINED, EVENT_FOCUS_LOST

        self.add_listener(
            int(EVENT_FOCUS_GAINED),
            lambda _evt: self._animate_scroll(True) or 0,  # type: ignore[func-returns-value]
        )
        self.add_listener(
            int(EVENT_FOCUS_LOST),
            lambda _evt: self._animate_scroll(False) or 0,  # type: ignore[func-returns-value]
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_value(self) -> Any:
        """Return the current display value."""
        return self.value

    # Alias matching Lua ``Label:getValue``
    getValue = get_value

    def set_value(self, value: Any, priority_duration: Optional[int] = None) -> None:
        """
        Set the text displayed in the label.

        Parameters
        ----------
        value : object
            The new value to display.
        priority_duration : int, optional
            If given, *value* is shown for this many milliseconds and then
            the label reverts to the previous persistent value.  During the
            priority window only another ``set_value`` with a
            ``priority_duration`` will replace the text.
        """
        if priority_duration is not None:
            if self.priority_timer is None:
                from jive.ui.timer import Timer as TimerClass

                def _revert() -> None:
                    pv = self.previous_persistent_value
                    if pv is None:
                        pv = ""
                    self._set_value_internal(pv)

                self.priority_timer = TimerClass(0, _revert, once=True)

            self._set_value_internal(value)
            self.priority_timer.restart(priority_duration)
        else:
            if not (
                self.priority_timer is not None and self.priority_timer.is_running()
            ):
                self._set_value_internal(value)
            self.previous_persistent_value = value

    # Alias matching Lua ``Label:setValue``
    setValue = set_value

    def _set_value_internal(self, value: Any) -> None:
        """Update the value and trigger re-layout if changed."""
        if self.value != value:
            self.value = value
            self.re_layout()

    # ------------------------------------------------------------------
    # Text-stop callback
    # ------------------------------------------------------------------

    def set_text_stop_callback(self, cb: Optional[Callable[..., None]]) -> None:
        """Register a callback invoked when text scrolling pauses."""
        self._text_stop_callback = cb

    @property
    def textStopCallback(self) -> Optional[Callable[..., None]]:
        """Lua-compatible property for the text-stop callback.

        Supports both ``label.textStopCallback = cb`` (set) and
        ``label.textStopCallback(label)`` (get + call), matching the
        Lua pattern where this is a plain assignable field.
        """
        return self._text_stop_callback

    @textStopCallback.setter
    def textStopCallback(self, cb: Optional[Callable[..., None]]) -> None:
        self._text_stop_callback = cb

    # ------------------------------------------------------------------
    # Skin (jiveL_label_skin)
    # ------------------------------------------------------------------

    def re_skin(self) -> None:
        """Reset all label-specific cached skin state, then call super."""
        self._bg_tile = None
        self._base_font = None
        self._base_line_height = 0
        self._base_text_offset = 0
        self._base_fg = _JIVE_COLOR_BLACK
        self._base_sh = _JIVE_COLOR_WHITE
        self._base_is_sh = False
        self._formats = []
        self._lines = []
        self._text_w = 0
        self._text_h = 0
        self._label_w = 0
        self._scroll_offset = _SCROLL_PAD_START
        super().re_skin()

    def _skin(self) -> None:
        """
        Apply skin/style parameters.

        Reads: ``font``, ``lineHeight``, ``fg``, ``sh``, per-line ``line``
        array, ``bgImg``, ``align``.
        """
        from jive.ui.style import (
            style_align,
            style_array_color,
            style_array_font,
            style_array_int,
            style_array_size,
            style_color,
            style_font,
            style_int,
            style_tile,
        )

        # jive_widget_pack equivalent
        self._widget_pack()

        # Free old formats
        self._formats.clear()

        # Base font
        self._base_font = style_font(self, "font")

        # scroll_offset_step is font-size dependent
        font_size = getattr(self._base_font, "size", 0) if self._base_font else 0
        if font_size and font_size > _SCROLL_OFFSET_STEP_MINIMUM * _FONT_SCROLL_FACTOR:
            self._scroll_offset_step = font_size // _FONT_SCROLL_FACTOR
        else:
            self._scroll_offset_step = _SCROLL_OFFSET_STEP_MINIMUM

        # Base line height / text offset
        cap_h = _font_metric(self._base_font, "capheight")
        txt_off = _font_metric(self._base_font, "offset")

        self._base_line_height = style_int(self, "lineHeight", cap_h)
        self._base_text_offset = txt_off

        # Foreground / shadow colours
        fg_packed, _fg_set = style_color(self, "fg", _JIVE_COLOR_BLACK)
        self._base_fg = fg_packed
        sh_packed, sh_set = style_color(self, "sh", _JIVE_COLOR_WHITE)
        # Detect if shadow was explicitly set (non-default)
        self._base_sh = sh_packed
        self._base_is_sh = sh_set or self._has_style_key("sh")

        # Per-line formats
        num_format = style_array_size(self, "line")
        for i in range(num_format):
            fmt = _LabelFormat()
            # Python lists are 0-based; the C/Lua original used 1-based
            # indices (i+1) because Lua tables start at 1.  Our
            # style_array_value indexes into a plain Python list, so we
            # must pass the 0-based index directly.
            fmt.font = style_array_font(self, "line", i, "font")
            if fmt.font is not None:
                fmt_cap = _font_metric(fmt.font, "capheight")
                fmt.line_height = style_array_int(self, "line", i, "height", fmt_cap)
                fmt.text_offset = _font_metric(self._base_font, "offset")
                f_size = getattr(fmt.font, "size", 0) if fmt.font else 0
                if f_size > self._scroll_offset_step * _FONT_SCROLL_FACTOR:
                    self._scroll_offset_step = f_size // _FONT_SCROLL_FACTOR

            fmt_fg_packed, _fmt_fg_set = style_array_color(
                self, "line", i, "fg", _JIVE_COLOR_BLACK
            )
            fmt.fg = fmt_fg_packed
            fmt.is_fg = bool(_fmt_fg_set)
            fmt_sh_packed, fmt_sh_set = style_array_color(
                self, "line", i, "sh", _JIVE_COLOR_BLACK
            )
            fmt.sh = fmt_sh_packed
            fmt.is_sh = bool(fmt_sh_set) or fmt.sh != _JIVE_COLOR_BLACK
            self._formats.append(fmt)

        # Background tile
        bg_tile = style_tile(self, "bgImg", None)
        if bg_tile is not self._bg_tile:
            self._bg_tile = bg_tile

        # Alignment
        self._text_align = style_align(self, "align", int(ALIGN_LEFT))

    def _has_style_key(self, key: str) -> bool:
        """Check if the style skin has an explicit value for *key*."""
        from jive.ui.style import skin as style_db
        from jive.ui.style import style_path

        path = style_path(self)
        val = style_db.find_value(style_db.data, path, key)
        # find_value returns _SENTINEL_NIL when the key is absent
        from jive.ui.style import _SENTINEL_NIL

        return val is not _SENTINEL_NIL

    # ------------------------------------------------------------------
    # Prepare text surfaces (static ``prepare()`` in jive_label.c)
    # ------------------------------------------------------------------

    def _prepare(self) -> None:
        """
        Split the label text into lines and render each line's foreground
        and shadow text surfaces.

        This mirrors the ``prepare()`` function in ``jive_label.c``.
        """
        # Free existing lines
        self._gc_lines()

        # Get display string
        raw = self.value
        if raw is None:
            # Fall back to style "text" value
            from jive.ui.style import style_value

            raw = style_value(self, "text", "")

        text = str(raw) if raw is not None else ""
        if not text:
            self._text_w = 0
            self._text_h = 0
            return

        # Split on newlines (matching C behaviour with \n, \r)
        raw_lines = re.split(r"[\n\r]+", text)

        # Further split very long lines (MAX_CHARS)
        split_lines: List[str] = []
        for raw_line in raw_lines:
            while len(raw_line) > _MAX_CHARS:
                split_lines.append(raw_line[:_MAX_CHARS])
                raw_line = raw_line[_MAX_CHARS:]
            split_lines.append(raw_line)

        max_width = 0
        total_height = 0

        for line_idx, line_text in enumerate(split_lines):
            # Determine format for this line
            font = self._base_font
            line_height = self._base_line_height
            text_offset = self._base_text_offset
            fg = self._base_fg
            sh = self._base_sh
            is_sh = self._base_is_sh

            if line_idx < len(self._formats):
                fmt = self._formats[line_idx]
                if fmt.font is not None:
                    font = fmt.font
                    line_height = fmt.line_height
                    text_offset = fmt.text_offset
                if fmt.is_fg:
                    fg = fmt.fg
                if fmt.is_sh:
                    sh = fmt.sh
                    is_sh = True

            ll = _LabelLine()
            ll.line_height = line_height
            ll.text_offset = text_offset

            # Render text surfaces (wrap raw pygame.Surface in Surface)
            if font is not None:
                raw_fg = font.render(line_text, fg)
                if raw_fg is not None:
                    ll.text_fg = Surface(raw_fg)
                else:
                    ll.text_fg = None

                if is_sh:
                    raw_sh = font.render(line_text, sh)
                    ll.text_sh = Surface(raw_sh) if raw_sh is not None else None
                else:
                    ll.text_sh = None

                if ll.text_fg is not None:
                    w, _h = ll.text_fg.get_size()
                    max_width = max(max_width, w)
            else:
                ll.text_fg = None
                ll.text_sh = None

            total_height += line_height
            self._lines.append(ll)

        self._text_w = max_width
        self._text_h = total_height
        self._scroll_offset = _SCROLL_PAD_START

    # ------------------------------------------------------------------
    # Layout (jiveL_label_layout)
    # ------------------------------------------------------------------

    def _layout(self) -> None:
        """
        Prepare text surfaces and compute each line's position within
        the widget bounds.
        """
        self._prepare()

        bx, by, bw, bh = self.get_bounds()
        pl, pt, pr, pb = self.get_padding()

        inner_x = bx + pl
        inner_y = by + pt
        inner_w = bw - pl - pr
        inner_h = bh - pt - pb

        # Vertical alignment of the entire text block
        y = Widget.valign(self._text_align, inner_y, inner_h, self._text_h)

        for ll in self._lines:
            if ll.text_fg is not None:
                w, h = ll.text_fg.get_size()
            else:
                w = 0

            ll.label_x = Widget.halign(self._text_align, inner_x, inner_w, w) - bx
            ll.label_y = y - ll.text_offset - by
            y += ll.line_height

        # Maximum render width (for scroll detection)
        self._label_w = inner_w

    # ------------------------------------------------------------------
    # Animation — text scrolling (jiveL_label_animate / do_animate)
    # ------------------------------------------------------------------

    def _animate_scroll(self, start: bool) -> None:
        """
        Start or stop text scroll animation.

        Mirrors ``jiveL_label_animate`` in ``jive_label.c``.
        """
        scroll_fps = max(1, FRAME_RATE_DEFAULT // _SCROLL_FPS_DIVISOR)

        if start:
            self._scroll_offset = _SCROLL_PAD_START

            if self._animation_handle is not None:
                return  # already running

            self._animation_handle = self.add_animation(self._do_animate, scroll_fps)
        else:
            self._scroll_offset = 0

            if self._animation_handle is None:
                return

            self.remove_animation(self._animation_handle)
            self._animation_handle = None

    def _do_animate(self) -> None:
        """
        Advance the scroll position by one step and request a redraw.

        Mirrors ``jiveL_label_do_animate`` in ``jive_label.c``.
        """
        # No scroll needed if text fits
        if self._text_w <= self._label_w:
            if self._text_stop_callback is not None:
                self._text_stop_callback(self)
            return

        self._scroll_offset += self._scroll_offset_step

        if self._scroll_offset > self._text_w + _SCROLL_PAD_RIGHT:
            # Completed one scroll cycle — reset and pause
            self._scroll_offset = 0
            self.re_draw()
            # Pause
            self._scroll_offset = _SCROLL_PAD_LEFT
            if self._text_stop_callback is not None:
                self._text_stop_callback(self)
            return

        if self._scroll_offset < 0:
            return  # still in pause region, no visual change

        self.re_draw()

    # ------------------------------------------------------------------
    # Draw (jiveL_label_draw)
    # ------------------------------------------------------------------

    def draw(self, surface: Surface, layer: int = LAYER_ALL) -> None:
        """
        Draw the label onto *surface*.

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

        if not (draw_layer and self._lines):
            return

        bx, by, bw, bh = self.get_bounds()

        for ll in self._lines:
            if ll.text_fg is None:
                continue

            w, h = ll.text_fg.get_size()

            # Scroll offset
            o = 0 if self._scroll_offset < 0 else self._scroll_offset
            if w < self._label_w:
                o = 0

            s = self._text_w - o + _SCROLL_PAD_RIGHT
            text_w = self._label_w

            # Shadow text — source.blit_clip(sx, sy, sw, sh, dst, dx, dy)
            if ll.text_sh is not None:
                ll.text_sh.blit_clip(
                    o,
                    0,
                    text_w,
                    h,
                    surface,
                    bx + ll.label_x + 1,
                    by + ll.label_y + 1,
                )
                # Wrap-around portion
                if o and s < text_w:
                    wrap_len = max(0, text_w - s)
                    ll.text_sh.blit_clip(
                        0,
                        0,
                        wrap_len,
                        h,
                        surface,
                        bx + ll.label_x + s + 1,
                        by + ll.label_y + 1,
                    )

            # Foreground text — source.blit_clip(sx, sy, sw, sh, dst, dx, dy)
            ll.text_fg.blit_clip(
                o,
                0,
                text_w,
                h,
                surface,
                bx + ll.label_x,
                by + ll.label_y,
            )
            # Wrap-around portion
            if o and s < text_w:
                wrap_len = max(0, text_w - s)
                ll.text_fg.blit_clip(
                    0,
                    0,
                    wrap_len,
                    h,
                    surface,
                    bx + ll.label_x + s,
                    by + ll.label_y,
                )

    # ------------------------------------------------------------------
    # Preferred bounds (jiveL_label_get_preferred_bounds)
    # ------------------------------------------------------------------

    def get_preferred_bounds(
        self,
    ) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
        """
        Return the preferred ``(x, y, w, h)`` for layout purposes.

        Width and height include text dimensions plus padding.
        """
        self.check_skin()

        # Ensure text is prepared
        if not self._lines and self.value is not None:
            self._prepare()

        pl, pt, pr, pb = self.get_padding()
        w = self._text_w + pl + pr
        h = self._text_h + pt + pb

        pbounds = self.preferred_bounds
        px = pbounds[0] if pbounds[0] is not None and pbounds[0] != XY_NIL else None
        py = pbounds[1] if pbounds[1] is not None and pbounds[1] != XY_NIL else None
        pw = pbounds[2] if pbounds[2] is not None and pbounds[2] != WH_NIL else w
        ph = pbounds[3] if pbounds[3] is not None and pbounds[3] != WH_NIL else h

        return (px, py, pw, ph)

    # ------------------------------------------------------------------
    # GC helpers
    # ------------------------------------------------------------------

    def _gc_lines(self) -> None:
        """Release all prepared line surfaces."""
        self._lines.clear()

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
        val_str = str(self.value) if self.value is not None else ""
        # Replace control characters for readability
        val_str = re.sub(r"[\x00-\x1f]", " ", val_str)
        return f"Label({val_str})"

    def __str__(self) -> str:
        return self.__repr__()
