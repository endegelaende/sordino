"""
jive.ui.slider — Slider and Scrollbar widgets for the Jivelite Python3 port.

Ported from ``Slider.lua``, ``Scrollbar.lua`` and ``jive_slider.c`` in the
original jivelite project.

A Slider widget displays a draggable bar within a range. It supports:

* **Range / value** — configurable min/max with current position
* **Scrollbar mode** — ``set_scrollbar(min, max, pos, size)`` for use as a
  scrollbar in menus and text areas
* **Slider mode** — ``set_range(min, max, value)`` for use as a volume/progress
  slider
* **Background tile** — optional ``bgImg`` behind the slider track
* **Bar tile** — ``img`` tile for the filled portion of the slider
* **Pill image** — optional ``pillImg`` draggable indicator
* **Alignment** — vertical/horizontal alignment within bounds
* **Drag support** — mouse drag to change slider value
* **Keyboard / IR** — arrow key and IR remote support for value changes
* **Closure callback** — notified on value changes

The Scrollbar subclass overrides ``__init__`` and ``_set_slider`` to provide
scrollbar-specific behaviour (paging, boundary clamping).

Copyright 2010 Logitech. All Rights Reserved. (original Lua/C code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Optional,
    Tuple,
)

from jive.ui.constants import (
    ALIGN_CENTER,
    ALIGN_TOP_LEFT,
    EVENT_CONSUME,
    EVENT_IR_ALL,
    EVENT_IR_DOWN,
    EVENT_IR_REPEAT,
    EVENT_KEY_PRESS,
    EVENT_MOUSE_ALL,
    EVENT_MOUSE_DOWN,
    EVENT_MOUSE_DRAG,
    EVENT_MOUSE_HOLD,
    EVENT_MOUSE_PRESS,
    EVENT_MOUSE_UP,
    EVENT_SCROLL,
    EVENT_UNUSED,
    KEY_DOWN,
    KEY_FWD,
    KEY_UP,
    LAYER_ALL,
    LAYER_CONTENT,
    WH_FILL,
    WH_NIL,
    XY_NIL,
)
from jive.ui.widget import Widget
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event
    from jive.ui.surface import Surface
    from jive.ui.tile import JiveTile  # type: ignore[attr-defined]

__all__ = ["Slider", "Scrollbar"]

log = logger("jivelite.ui")

# ---------------------------------------------------------------------------
# Mouse operation states
# ---------------------------------------------------------------------------

MOUSE_COMPLETE = 0
MOUSE_DOWN = 1
MOUSE_DRAG = 2

# Paging boundary buffer fraction (for scrollbar page up/down)
PAGING_BOUNDARY_BUFFER_FRACTION = 0.25

# Buffer zone around pill bounds for sloppy touch
BUFFER_ZONE = 15


# ---------------------------------------------------------------------------
# Slider widget
# ---------------------------------------------------------------------------


class Slider(Widget):
    """
    A slider widget that represents a value within a range.

    Can be used as a simple slider (e.g. volume) or as the base for a
    scrollbar.

    Parameters
    ----------
    style : str
        The style key used to look up skin parameters.
    min_val : int, optional
        Minimum value (default 1).
    max_val : int, optional
        Maximum / range value (default 1).
    value : int, optional
        Initial value (defaults to *min_val*).
    closure : callable, optional
        Called as ``closure(slider, value, is_action)`` on value change.
    drag_done_closure : callable, optional
        Called when a drag gesture completes.
    """

    __slots__ = (
        "min",
        "range",
        "value",
        "size",
        "closure",
        "drag_done_closure",
        "slider_enabled",
        "jump_on_down",
        "drag_threshold",
        "mouse_state",
        "mouse_down_x",
        "mouse_down_y",
        "distance_from_mouse_down_max",
        "pill_offset",
        "pill_drag_only",
        "use_drag_done_closure",
        "touchpad_bottom_correction",
        "_align",
        "_bg_tile",
        "_tile",
        "_pill_img",
        "_pill_x",
        "_pill_y",
        "_pill_w",
        "_pill_h",
        "_horizontal",
        "_slider_x",
        "_slider_y",
    )

    def __init__(
        self,
        style: str,
        min_val: int = 1,
        max_val: int = 1,
        value: Optional[int] = None,
        closure: Optional[Callable[..., Any]] = None,
        drag_done_closure: Optional[Callable[..., Any]] = None,
    ) -> None:
        if not isinstance(style, str):
            raise TypeError(f"style must be a string, got {type(style).__name__}")

        super().__init__(style)

        self.min: int = min_val
        self.range: int = max_val
        self.value: int = 1
        self.size: int = 0
        self.closure: Optional[Callable[..., Any]] = closure
        self.drag_done_closure: Optional[Callable[..., Any]] = drag_done_closure
        self.slider_enabled: bool = True
        self.jump_on_down: bool = True

        # Drag state
        self.drag_threshold: int = 12
        self.mouse_state: int = MOUSE_COMPLETE
        self.mouse_down_x: Optional[int] = None
        self.mouse_down_y: Optional[int] = None
        self.distance_from_mouse_down_max: int = 0
        self.pill_offset: Optional[int] = None
        self.pill_drag_only: bool = False
        self.use_drag_done_closure: bool = False

        # Touchpad correction (0 by default for desktop)
        self.touchpad_bottom_correction: int = 0

        # Peer-equivalent state (mirroring SliderWidget in C)
        self._align: int = int(ALIGN_CENTER)
        self._bg_tile: Optional[JiveTile] = None
        self._tile: Optional[JiveTile] = None
        self._pill_img: Optional[Surface] = None
        self._pill_x: int = 0
        self._pill_y: int = 0
        self._pill_w: int = 0
        self._pill_h: int = 0
        self._horizontal: bool = True
        self._slider_x: int = 0
        self._slider_y: int = 0

        # Set initial value
        self.set_value(value if value is not None else self.min)

        # Register listeners
        self.add_action_listener("go", self, Slider._call_closure_action)
        self.add_action_listener("play", self, Slider._call_closure_action)

        self.add_listener(
            EVENT_SCROLL
            | EVENT_KEY_PRESS
            | EVENT_MOUSE_ALL
            | EVENT_IR_DOWN
            | EVENT_IR_REPEAT,
            lambda event: self._event_handler(event),
        )

    # ------------------------------------------------------------------
    # camelCase property aliases (Lua compatibility)
    # ------------------------------------------------------------------
    # In Lua these are plain fields set directly (e.g.
    # ``slider.jumpOnDown = true``).  With ``__slots__`` we need
    # explicit properties so that camelCase assignment works.

    @property
    def jumpOnDown(self) -> bool:
        return self.jump_on_down

    @jumpOnDown.setter
    def jumpOnDown(self, value: bool) -> None:
        self.jump_on_down = value

    @property
    def pillDragOnly(self) -> bool:
        return self.pill_drag_only

    @pillDragOnly.setter
    def pillDragOnly(self, value: bool) -> None:
        self.pill_drag_only = value

    @property
    def dragThreshold(self) -> int:
        return self.drag_threshold

    @dragThreshold.setter
    def dragThreshold(self, value: int) -> None:
        self.drag_threshold = value

    # ------------------------------------------------------------------
    # Public API — Scrollbar mode
    # ------------------------------------------------------------------

    def set_scrollbar(self, min_val: int, max_val: int, pos: int, size: int) -> None:
        """
        Set the slider in scrollbar mode.

        Parameters
        ----------
        min_val : int
            Minimum value of the range.
        max_val : int
            Maximum value of the range.
        pos : int
            Current bar position.
        size : int
            Size of the visible portion.
        """
        self.range = max_val - min_val
        self.value = pos - min_val
        self.size = size
        self.re_draw()

    setScrollbar = set_scrollbar

    # ------------------------------------------------------------------
    # Public API — Slider mode
    # ------------------------------------------------------------------

    def set_range(self, min_val: int, max_val: int, value: int) -> None:
        """
        Set the slider range and value.

        Parameters
        ----------
        min_val : int
            Minimum value.
        max_val : int
            Maximum (range).
        value : int
            Current value.
        """
        self.range = max_val
        self.min = min_val
        self.value = 1
        self.set_value(value)

    setRange = set_range

    def set_value(self, value: Any) -> None:
        """
        Set the slider value, clamped to [min, range].

        Parameters
        ----------
        value : int or str
            The new value.
        """
        try:
            numeric = int(value) if value is not None else 0
        except (TypeError, ValueError):
            numeric = 0

        if self.size == numeric:
            return

        self.size = numeric

        if self.size < self.min:
            self.size = self.min
        elif self.size > self.range:
            self.size = self.range

        self.re_draw()

    setValue = set_value

    def get_value(self) -> int:
        """Return the current slider value."""
        return self.size

    getValue = get_value

    def set_enabled(self, enable: bool) -> None:
        """Enable or disable the slider for interaction."""
        self.slider_enabled = bool(enable)

    setEnabled = set_enabled

    # ------------------------------------------------------------------
    # Internal — move / set slider
    # ------------------------------------------------------------------

    def _move_slider(self, amount: int) -> None:
        """Move the slider value by *amount* and call closure if changed."""
        old_size = self.size
        self.set_value(self.size + amount)
        if self.size != old_size:
            if self.closure is not None:
                self.closure(self, self.size, False)

    def _set_slider(self, percent: float) -> None:
        """Set the slider to a percentage of range and call closure."""
        old_size = self.size
        self.set_value(math.ceil(percent * self.range))
        if self.size != old_size:
            if self.closure is not None:
                self.closure(self, self.size, False)

    def _call_closure_action(self) -> int:
        """Action handler — call the closure with ``is_action=True``."""
        if self.closure is not None:
            self.closure(self, self.size, True)
            return EVENT_CONSUME
        return EVENT_UNUSED

    # ------------------------------------------------------------------
    # Pill bounds
    # ------------------------------------------------------------------

    def get_pill_bounds(
        self, horizontal: Optional[bool] = None
    ) -> Tuple[int, int, int, int]:
        """
        Return ``(x, y, w, h)`` of the pill indicator.

        Parameters
        ----------
        horizontal : bool, optional
            If provided, used as the orientation hint. Otherwise uses
            the widget's configured orientation.
        """
        self.check_skin()
        if self._pill_img is not None:
            return (self._pill_x, self._pill_y, self._pill_w, self._pill_h)
        return (0, 0, 0, 0)

    getPillBounds = get_pill_bounds

    # ------------------------------------------------------------------
    # Mouse helpers
    # ------------------------------------------------------------------

    def _finish_mouse_sequence(self) -> int:
        self.mouse_state = MOUSE_COMPLETE
        self.mouse_down_x = None
        self.mouse_down_y = None
        self.distance_from_mouse_down_max = 0
        self.pill_offset = None
        return EVENT_CONSUME

    def _update_mouse_origin_offset(self, event: Event) -> None:
        x, y = event.get_mouse()[:2]

        if self.mouse_down_x is None:
            self.mouse_down_x = x
            self.mouse_down_y = y
        else:
            dx = x - self.mouse_down_x
            dy = y - (self.mouse_down_y or 0)
            distance = math.sqrt(dx * dx + dy * dy)
            if distance > self.distance_from_mouse_down_max:
                self.distance_from_mouse_down_max = distance  # type: ignore[assignment]

    def _mouse_exceeded_buffer_distance(self, value: int) -> bool:
        return self.distance_from_mouse_down_max >= value

    def mouse_bounds(self, event: Event) -> Tuple[int, int, int, int]:
        """
        Return relative mouse position within slider bounds:
        ``(x_relative, y_relative, width, height)``.
        """
        mouse_x, mouse_y = event.get_mouse()[:2]
        bx, by, bw, bh = self.get_bounds()
        pl, pt, pr, pb = self.get_padding()

        rel_x = mouse_x - (bx + pl)
        rel_y = mouse_y - (by + pt)
        w = bw - pl - pr
        h = bh - pt - pb

        # Clamp to bounds
        rel_x = max(0, min(rel_x, w))
        rel_y = max(0, min(rel_y, h))

        return (rel_x, rel_y, w, h)

    mouseBounds = mouse_bounds

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def _event_handler(self, event: Event) -> int:
        etype = event.get_type()

        if not self.slider_enabled:
            return EVENT_UNUSED

        if etype == EVENT_SCROLL:
            self._move_slider(event.get_scroll())
            return EVENT_CONSUME

        elif etype == EVENT_MOUSE_DOWN and not self.jump_on_down:
            self.mouse_state = MOUSE_DOWN
            self._update_mouse_origin_offset(event)
            return EVENT_CONSUME

        elif etype == EVENT_MOUSE_DRAG or (
            etype == EVENT_MOUSE_DOWN and self.jump_on_down
        ):
            self._update_mouse_origin_offset(event)

            if not self.jump_on_down:
                if not self._mouse_exceeded_buffer_distance(self.drag_threshold):
                    return EVENT_CONSUME

            self.mouse_state = MOUSE_DRAG

            x, y, w, h = self.mouse_bounds(event)
            if w > h:
                # Horizontal
                if self.pill_drag_only:
                    px, py, pw, ph = self.get_pill_bounds(True)
                    mx, my = event.get_mouse()[:2]
                    if self.pill_offset is None:
                        if px <= mx <= px + pw:
                            self.pill_offset = mx - px
                            return EVENT_CONSUME
                        else:
                            return EVENT_CONSUME
                    x_adj = x - self.pill_offset
                    denom = w - pw if pw else w
                    if denom > 0:
                        self._set_slider(x_adj / denom)
                else:
                    if w > 0:
                        self._set_slider(x / w)
            else:
                # Vertical
                if self.pill_drag_only:
                    px, py, pw, ph = self.get_pill_bounds(False)
                    mx, my = event.get_mouse()[:2]
                    if self.pill_offset is None:
                        if py <= my <= py + ph:
                            self.pill_offset = my - py
                            return EVENT_CONSUME
                        else:
                            return EVENT_CONSUME
                    y_adj = y - self.pill_offset
                    denom = h - ph if ph else h
                    if denom > 0:
                        self._set_slider(y_adj / denom)
                else:
                    denom = h - self.touchpad_bottom_correction
                    if denom > 0:
                        self._set_slider(y / denom)

            self.use_drag_done_closure = True
            return EVENT_CONSUME

        elif etype == EVENT_MOUSE_UP:
            if self.use_drag_done_closure:
                self.use_drag_done_closure = False
                if self.drag_done_closure is not None:
                    self.drag_done_closure(self, self.size, False)

            if self.mouse_state in (MOUSE_COMPLETE, MOUSE_DRAG):
                return self._finish_mouse_sequence()

            if not self.jump_on_down:
                x, y, w, h = self.mouse_bounds(event)
                if w > h:
                    slider_fraction = x / w if w > 0 else 0
                else:
                    slider_fraction = y / h if h > 0 else 0

                pos = slider_fraction * self.range
                in_upper = slider_fraction < PAGING_BOUNDARY_BUFFER_FRACTION
                in_lower = slider_fraction > (1 - PAGING_BOUNDARY_BUFFER_FRACTION)

                if in_upper or (pos <= self.value and not in_lower):
                    from jive.ui.framework import Framework

                    Framework.push_action("page_up")  # type: ignore[call-arg, arg-type]
                elif in_lower or pos > self.value + self.size:
                    from jive.ui.framework import Framework

                    Framework.push_action("page_down")  # type: ignore[call-arg, arg-type]

            return self._finish_mouse_sequence()

        elif etype in (EVENT_MOUSE_PRESS, EVENT_MOUSE_HOLD):
            return EVENT_CONSUME

        elif etype == EVENT_KEY_PRESS:
            keycode = event.get_keycode()

            if keycode == KEY_DOWN:
                self._move_slider(-1)
            elif keycode == KEY_UP:
                self._move_slider(1)

            if keycode == KEY_FWD:
                return self._call_closure_action()

            return EVENT_UNUSED

        elif etype & EVENT_IR_ALL:
            if hasattr(event, "is_ir_code") and (
                event.is_ir_code("arrow_up") or event.is_ir_code("arrow_down")
            ):
                if etype in (EVENT_IR_DOWN, EVENT_IR_REPEAT):
                    val = 1 if event.is_ir_code("arrow_up") else -1
                    if val != 0:
                        self._move_slider(val)
            return EVENT_UNUSED

        return EVENT_UNUSED

    # ------------------------------------------------------------------
    # Skin (jiveL_slider_skin)
    # ------------------------------------------------------------------

    def re_skin(self) -> None:
        """Reset all slider-specific cached skin state, then call super."""
        self._bg_tile = None
        self._tile = None
        self._pill_img = None
        self._pill_x = 0
        self._pill_y = 0
        self._pill_w = 0
        self._pill_h = 0
        self._horizontal = True
        self._align = int(ALIGN_CENTER)
        super().re_skin()

    def _skin(self) -> None:
        from jive.ui.style import (
            style_align,
            style_image,
            style_int,
            style_tile,
        )

        self._widget_pack()

        # Background tile
        bg = style_tile(self, "bgImg", None)
        if self._bg_tile is not bg:
            self._bg_tile = bg

        # Horizontal/vertical
        self._horizontal = bool(style_int(self, "horizontal", 1))

        # Bar tile
        tile = style_tile(self, "img", None)
        if self._tile is not tile:
            self._tile = tile

        # Pill image
        pill_img = style_image(self, "pillImg", None)
        if self._pill_img is not pill_img:
            self._pill_img = pill_img

        # Alignment
        self._align = style_align(self, "align", int(ALIGN_CENTER))

        log.debug(
            "Slider._skin: horizontal=%s bgImg=%s img=%s pillImg=%s",
            self._horizontal,
            self._bg_tile,
            self._tile,
            self._pill_img,
        )

    # ------------------------------------------------------------------
    # Layout (jiveL_slider_layout)
    # ------------------------------------------------------------------

    def _layout(self) -> None:
        if self._tile is None:
            return

        # Pill dimensions
        if self._pill_img is not None:
            self._pill_w, self._pill_h = self._pill_img.get_size()
        else:
            self._pill_w = 0
            self._pill_h = 0

        # Tile min size
        tw, th = 0, 0
        if self._tile is not None:
            try:
                tw, th = self._tile.get_min_size()
            except (AttributeError, TypeError):
                tw, th = 0, 0

        bx, by, bw, bh = self.get_bounds()

        if bw != WH_NIL:
            tw = bw
        if bh != WH_NIL:
            th = bh

        if self._horizontal:
            self._slider_y = Widget.valign(self._align, by, bh, th) - by
            self._slider_x = 0
        else:
            self._slider_x = Widget.halign(self._align, bx, bw, tw) - bx
            self._slider_y = 0

    # ------------------------------------------------------------------
    # Draw (jiveL_slider_draw)
    # ------------------------------------------------------------------

    def draw(self, surface: Surface, layer: int = LAYER_ALL) -> None:
        draw_layer = layer & self._layer

        if not draw_layer:
            return

        bx, by, bw, bh = self.get_bounds()
        pl, pt, pr, pb = self.get_padding()

        # Background tile
        if self._bg_tile is not None:
            self._bg_tile.blit(
                surface,
                bx + self._slider_x,
                by + self._slider_y,
                bw,
                bh,
            )

        if self._tile is not None:
            height = bh - pt - pb
            width = bw - pl - pr

            range_val = self.range
            value = self.value
            size_val = self.size

            # Get tile minimum size
            try:
                tw, th = self._tile.get_min_size()
            except (AttributeError, TypeError):
                tw, th = 0, 0

            if self._horizontal:
                if range_val > 1:
                    width_minus_tw = width - tw
                    x_pos = (
                        int((width_minus_tw / (range_val - 1)) * (value - 1))
                        if range_val > 1
                        else 0
                    )
                    w_pos = (
                        int((width_minus_tw / (range_val - 1)) * (size_val - 1) + tw)
                        if range_val > 1
                        else tw
                    )
                else:
                    x_pos = 0
                    w_pos = width
                y_pos = 0
                h_pos = height
                self._pill_x = bx + self._slider_x + pl + (w_pos - tw)
                self._pill_y = by + self._slider_y + pt + y_pos
            else:
                if range_val > 1:
                    height_minus_th = height - th
                    x_pos = 0
                    w_pos = width
                    y_pos = (
                        int((height_minus_th / (range_val - 1)) * (value - 1))
                        if range_val > 1
                        else 0
                    )
                    h_pos = (
                        int((height_minus_th / (range_val - 1)) * (size_val - 1) + th)
                        if range_val > 1
                        else th
                    )
                else:
                    x_pos = 0
                    w_pos = width
                    y_pos = 0
                    h_pos = height
                self._pill_x = bx + self._slider_x + pl + x_pos
                self._pill_y = by + self._slider_y + pt + (h_pos - th)

            self._tile.blit(
                surface,
                bx + self._slider_x + pl + x_pos,
                by + self._slider_y + pt + y_pos,
                w_pos,
                h_pos,
            )

            # Draw pill
            if self._pill_img is not None:
                surface.blit(self._pill_img, self._pill_x, self._pill_y)

    # ------------------------------------------------------------------
    # Preferred bounds (jiveL_slider_get_preferred_bounds)
    # ------------------------------------------------------------------

    def get_preferred_bounds(
        self,
    ) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
        self.check_skin()

        w, h = 0, 0

        if self._bg_tile is not None:
            try:
                w, h = self._bg_tile.get_min_size()
            except (AttributeError, TypeError):
                w, h = 0, 0

        pb = self.preferred_bounds
        px = pb[0] if pb[0] is not None and pb[0] != XY_NIL else None
        py = pb[1] if pb[1] is not None and pb[1] != XY_NIL else None

        if self._horizontal:
            pw = pb[2] if pb[2] is not None and pb[2] != WH_NIL else WH_FILL
            ph = pb[3] if pb[3] is not None and pb[3] != WH_NIL else h
        else:
            pw = pb[2] if pb[2] is not None and pb[2] != WH_NIL else w
            ph = pb[3] if pb[3] is not None and pb[3] != WH_NIL else WH_FILL

        return (px, py, pw, ph)

    # ------------------------------------------------------------------
    # jive_widget_pack — read common style properties
    # ------------------------------------------------------------------

    def _widget_pack(self) -> None:
        """
        Read common widget style properties: preferred bounds,
        padding, border, layer, z-order, hidden.
        """
        from jive.ui.style import style_insets, style_int

        sx = style_int(self, "x", XY_NIL)
        sy = style_int(self, "y", XY_NIL)
        sw = style_int(self, "w", WH_NIL)
        sh = style_int(self, "h", WH_NIL)

        self.preferred_bounds[0] = None if sx == XY_NIL else sx
        self.preferred_bounds[1] = None if sy == XY_NIL else sy
        self.preferred_bounds[2] = None if sw == WH_NIL else sw
        self.preferred_bounds[3] = None if sh == WH_NIL else sh

        pad = style_insets(self, "padding", [0, 0, 0, 0])
        self.padding[:] = pad[:4] if len(pad) >= 4 else pad + [0] * (4 - len(pad))

        bdr = style_insets(self, "border", [0, 0, 0, 0])
        self.border[:] = bdr[:4] if len(bdr) >= 4 else bdr + [0] * (4 - len(bdr))

        self._layer = style_int(self, "layer", int(LAYER_CONTENT))
        self._z_order = style_int(self, "zOrder", 0)
        self._hidden = bool(style_int(self, "hidden", 0))

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Slider(range={self.range}, value={self.value}, size={self.size})"

    def __str__(self) -> str:
        return self.__repr__()


# ---------------------------------------------------------------------------
# Scrollbar widget — extends Slider
# ---------------------------------------------------------------------------


class Scrollbar(Slider):
    """
    A scrollbar widget, extends Slider.

    Provides scrollbar-specific behaviour: the closure is called with a
    position value (not a percentage), and ``_set_slider`` clamps
    boundaries for scrollbar semantics.

    Parameters
    ----------
    style : str
        The style key used to look up skin parameters.
    closure : callable, optional
        Called as ``closure(scrollbar, value, done)`` on position change.
    """

    __slots__ = ()

    def __init__(
        self,
        style: str,
        closure: Optional[Callable[..., Any]] = None,
    ) -> None:
        super().__init__(style)

        self.range = 1
        self.value = 1
        self.size = 1
        self.closure = closure
        self.jump_on_down = False

    # ------------------------------------------------------------------
    # Scrollbar-specific API
    # ------------------------------------------------------------------

    def set_scrollbar(self, min_val: int, max_val: int, pos: int, size: int) -> None:
        """
        Set the scrollbar range, position, and visible size.

        Parameters
        ----------
        min_val : int
            Minimum value.
        max_val : int
            Maximum value.
        pos : int
            Current position.
        size : int
            Number of visible items.
        """
        self.range = max_val - min_val
        self.value = pos - min_val
        self.size = size
        self.re_draw()

    setScrollbar = set_scrollbar

    def _set_slider(self, percent: float) -> None:
        """
        Set the scrollbar position from a percentage.

        Overrides Slider._set_slider with boundary clamping.
        """
        # Boundary guard
        if percent < 0:
            percent = 0
        elif percent >= 1:
            percent = 0.9999

        pos = percent * self.range
        self.value = math.floor(pos)
        self.re_draw()

        if self.closure is not None:
            self.closure(self, self.value, False)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Scrollbar(range={self.range}, value={self.value}, size={self.size})"

    def __str__(self) -> str:
        return self.__repr__()
