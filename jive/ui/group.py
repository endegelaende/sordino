"""
jive.ui.group — Group widget for the Jivelite Python3 port.

Ported from ``Group.lua`` and ``jive_group.c`` in the original jivelite project.

A Group widget is a container for other widgets, arranged horizontally
(default) or vertically.  Widgets are stored in a dict keyed by name
and can be ordered via the ``order`` style parameter.

Features:

* **Named child widgets** — stored in a ``widgets`` dict, accessed by key
* **Ordered iteration** — the ``order`` style array controls widget
  ordering; without it, dict insertion order is used
* **Horizontal layout** (default) — children laid out left-to-right with
  ``WH_FILL`` support for flexible-width children
* **Vertical layout** — activated by ``orientation: 1`` style; children
  laid out top-to-bottom with ``WH_FILL`` support for flexible-height
  children
* **Background tile** — optional ``bgImg`` tile rendered behind children
* **Mouse event routing** — forwards mouse events to the child under the
  pointer, with fallback to the closest child by x-distance;
  mouse-down focus tracking for drag sequences
* **Event forwarding** — all non-mouse events forwarded to children
* **Preferred bounds** — reports aggregate child widths/heights + padding
* **Smooth scrolling** — delegates ``set_smooth_scrolling_menu`` to children

Copyright 2010 Logitech. All Rights Reserved. (original Lua/C code)
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
    Tuple,
    Union,
)

from jive.ui.constants import (
    ALIGN_CENTER,
    EVENT_ALL,
    EVENT_HIDE,
    EVENT_MOUSE_ALL,
    EVENT_MOUSE_DOWN,
    EVENT_MOUSE_MOVE,
    EVENT_MOUSE_UP,
    EVENT_SHOW,
    EVENT_UNUSED,
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

__all__ = ["Group"]

log = logger("jivelite.ui")


class Group(Widget):
    """
    A container widget that arranges child widgets horizontally or
    vertically.

    Parameters
    ----------
    style : str
        The style key used to look up skin parameters.
    widgets : dict[str, Widget]
        A dict of named child widgets.
    """

    __slots__ = (
        "widgets",
        "_bg_tile",
        "_widgets",
        "_order",
        "_orientation",
        "_mouse_event_focus_widget",
        "_type",
        "is_default_button_group",
    )

    def __init__(self, style: str, widgets: Optional[Dict[str, Widget]] = None) -> None:
        if not isinstance(style, str):
            raise TypeError(f"style must be a string, got {type(style).__name__}")

        super().__init__(style)

        # Track item type for checkbox/radio/choice state in _decorated_label
        self._type: Optional[str] = None

        # Flag for default button group identification.
        # In Lua, Button.__init__ returns the widget itself and arbitrary
        # attributes can be set on Lua tables.  In Python, Group uses
        # __slots__, so we declare the slot explicitly.
        self.is_default_button_group: bool = False

        self.widgets: Dict[str, Widget] = widgets if widgets is not None else {}

        # Set parent linkage for all children.
        # Button objects are wrappers around widgets (with __slots__,
        # no ``parent``).  In Lua, Button inherits from Widget so it
        # can be stored directly.  In Python we must unwrap.
        for key, widget in list(self.widgets.items()):
            if widget is not None:
                # If this is a Button wrapper, store the inner widget
                # in the widgets dict so that layout/draw work, but
                # keep the Button's event wiring intact (it references
                # the same inner widget).
                inner = getattr(widget, "widget", None)
                if inner is not None and not hasattr(widget, "parent"):
                    # It's a Button-like wrapper — use the inner widget
                    self.widgets[key] = inner
                    widget = inner
                widget.parent = self

        # Peer-equivalent state (mirroring GroupWidget in C)
        self._bg_tile: Optional[JiveTile] = None

        # Ordered widget list (built during layout)
        self._widgets: Optional[List[Widget]] = None

        # Style-provided order and orientation
        self._order: Optional[List[str]] = None
        self._orientation: int = 0  # 0 = horizontal, 1 = vertical

        # Mouse event focus tracking
        self._mouse_event_focus_widget: Optional[Widget] = None

        # Register event forwarding listener
        self.add_listener(
            int(EVENT_ALL),
            self._forward_event,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_widget(self, key: str) -> Optional[Widget]:
        """Return the child widget for *key*, or *None*."""
        return self.widgets.get(key)

    def set_widget(self, key: str, widget: Optional[Widget]) -> None:
        """
        Set or replace a child widget by *key*.

        Handles parent linkage and show/hide lifecycle events.
        If *widget* is a Button wrapper, the inner widget is unwrapped
        automatically (matching the __init__ behaviour).
        """
        # Unwrap Button wrapper (same logic as __init__)
        if widget is not None and not isinstance(widget, Widget):
            inner = getattr(widget, "widget", None)
            if inner is not None and isinstance(inner, Widget):
                widget = inner

        old = self.widgets.get(key)

        if old is widget and (old is None or old.parent is self):
            return

        # Detach old widget
        if old is not None:
            if old.parent != self:
                # Widget's parent changed — dispatch hide if we're visible
                if self.visible:
                    old.dispatch_new_event(int(EVENT_HIDE))
                old.parent = None

        self.widgets[key] = widget  # type: ignore[assignment]

        # Attach new widget
        if widget is not None:
            widget.parent = self
            widget.re_skin()

            if self.visible:
                widget.dispatch_new_event(int(EVENT_SHOW))

    def get_widget_value(self, key: str) -> Any:
        """Return the value of the child widget at *key*."""
        w = self.widgets.get(key)
        if w is None:
            raise KeyError(f"No widget with key {key!r}")
        return w.get_value() if hasattr(w, "get_value") else None

    def set_widget_value(self, key: str, value: Any, *args: Any) -> Any:
        """Set the value of the child widget at *key*."""
        w = self.widgets.get(key)
        if w is None:
            raise KeyError(f"No widget with key {key!r}")
        if hasattr(w, "set_value"):
            return w.set_value(value, *args)
        elif hasattr(w, "setValue"):
            return w.setValue(value, *args)
        return None

    def set_mouse_event_focus_widget(self, widget: Optional[Widget]) -> None:
        """Set the widget that receives mouse events during a drag."""
        self._mouse_event_focus_widget = widget

    def set_smooth_scrolling_menu(self, val: Optional[bool]) -> None:
        """Delegate smooth scrolling to all children."""
        for widget in self.widgets.values():
            if widget is not None:
                widget.set_smooth_scrolling_menu(val)
        self.smoothscroll = val

    # ------------------------------------------------------------------
    # Event forwarding (from Group.lua __init listener)
    # ------------------------------------------------------------------

    def _forward_event(self, event: Event) -> int:
        """
        Forward events to contained widgets.

        Mouse events go to the widget under the pointer (or the focus
        widget during a drag).  Non-mouse events go to all children.
        """
        evt_type = event.get_type()
        is_mouse = bool(evt_type & int(EVENT_MOUSE_ALL))
        r = int(EVENT_UNUSED)

        # Build the iteration list
        widget_list = list(self.widgets.values())

        if not is_mouse:
            # Forward to all children
            for widget in widget_list:
                if widget is None:
                    continue
                r = widget._event(event)
                if r != int(EVENT_UNUSED):
                    break
        else:
            # Mouse events — route to focused widget or widget under pointer
            for widget in widget_list:
                if widget is None:
                    continue

                should_forward = False
                if self._mouse_event_focus_widget is widget:
                    should_forward = True
                elif self._mouse_event_focus_widget is None and widget.mouse_inside(event):
                    should_forward = True

                if should_forward:
                    r = widget._event(event)
                    if r != int(EVENT_UNUSED):
                        if evt_type == int(EVENT_MOUSE_DOWN):
                            self.set_mouse_event_focus_widget(widget)
                        break

            # Fallback for MOUSE_DOWN: find closest widget by x-distance
            if r == int(EVENT_UNUSED) and evt_type == int(EVENT_MOUSE_DOWN):
                mouse_x, mouse_y = event.get_mouse_xy()
                closest_distance = 99999
                closest_widget: Optional[Widget] = None

                for widget in widget_list:
                    if widget is None:
                        continue
                    wx, wy, ww, wh = widget.get_bounds()
                    if ww <= 0:
                        continue

                    if mouse_x >= ww + wx:
                        dist = mouse_x - (ww + wx)
                    else:
                        dist = wx - mouse_x

                    if dist < closest_distance:
                        closest_distance = dist
                        closest_widget = widget

                if closest_widget is not None:
                    r = closest_widget._event(event)
                    if r != int(EVENT_UNUSED):
                        if evt_type == int(EVENT_MOUSE_DOWN):
                            self.set_mouse_event_focus_widget(closest_widget)

            # Release focus on MOUSE_UP
            if evt_type == int(EVENT_MOUSE_UP):
                self.set_mouse_event_focus_widget(None)

        return r

    # ------------------------------------------------------------------
    # Iteration
    # ------------------------------------------------------------------

    def iterate(self, closure: Callable[[Widget], None], include_hidden: bool = False) -> None:
        """
        Call *closure(child)* for each child widget, in order.

        Uses the ordered widget list (``_widgets``) if available,
        otherwise falls back to ``widgets`` dict values.

        Parameters
        ----------
        closure:
            Function to call for each child widget.
        include_hidden:
            If ``True``, hidden widgets are included in the iteration.
            Defaults to ``False`` (skip hidden widgets), matching the
            C ``jiveL_group_iterate`` behaviour.
        """
        widget_list = self._widgets if self._widgets is not None else list(self.widgets.values())

        for widget in widget_list:
            if widget is None:
                continue
            if not include_hidden and widget.is_hidden():
                continue
            closure(widget)

    # ------------------------------------------------------------------
    # Skin (jiveL_group_skin)
    # ------------------------------------------------------------------

    def re_skin(self) -> None:
        """Reset all group-specific cached skin state, then call super.

        Does NOT reset ``_order`` or ``_orientation`` — these are
        populated by ``_skin()`` and are needed between the re_skin
        flag being set and the next ``checkSkin()`` call.  Clearing
        them causes widget ordering issues during selection-style
        changes (e.g. icons disappearing when an item is selected).
        ``_widgets`` is likewise kept because it is rebuilt by
        ``_layout()`` from ``_order`` + ``self.widgets``.
        """
        self._bg_tile = None
        super().re_skin()

    def _skin(self) -> None:
        """
        Apply skin/style parameters.

        Reads: ``bgImg``, ``order``, ``orientation``.
        """
        from jive.ui.style import (
            style_tile,
            style_value,
        )

        # jive_widget_pack equivalent
        self._widget_pack()

        # Background tile
        bg_tile = style_tile(self, "bgImg", None)
        if bg_tile is not self._bg_tile:
            self._bg_tile = bg_tile

        # Order table
        order = style_value(self, "order", None)
        if order is not None and isinstance(order, (list, tuple)):
            self._order = list(order)
        else:
            self._order = None

        # Orientation: 0 = horizontal (default), 1 = vertical
        orient = style_value(self, "orientation", None)
        if orient is not None:
            self._orientation = int(orient)
        else:
            self._orientation = 0

    # ------------------------------------------------------------------
    # Layout (jiveL_group_layout)
    # ------------------------------------------------------------------

    def _layout(self) -> None:
        """
        Lay out child widgets horizontally or vertically.

        Mirrors ``jiveL_group_layout()`` in ``jive_group.c``.
        """
        # Build ordered widget list
        if self._order is not None:
            ordered: List[Widget] = []
            for key in self._order:
                w = self.widgets.get(key)
                if w is not None:
                    ordered.append(w)
            self._widgets = ordered
        else:
            self._widgets = list(self.widgets.values())

        if self._orientation == 1:
            self._layout_vertical()
        else:
            self._layout_horizontal()

    def _layout_horizontal(self) -> None:
        """Horizontal (left-to-right) layout — orientation 0."""
        widgets = self._widgets or []
        num = len(widgets)
        if num == 0:
            return

        bx, by, bw, bh = self.get_bounds()
        pl, pt, pr, pb = self.get_padding()

        # Collect preferred widths and borders
        widths: List[int] = [0] * num
        borders: List[Tuple[int, int, int, int]] = [(0, 0, 0, 0)] * num
        fill_count = 0
        fixed_width = 0
        max_h = 0

        for i, widget in enumerate(widgets):
            if widget is None:
                continue
            if widget.is_hidden():
                continue

            # Ensure child is skinned so preferred_bounds are available
            widget.check_skin()

            # Get border
            borders[i] = widget.get_border()
            bl, bt, br, bb = borders[i]

            # Get preferred bounds
            _px, _py, pw, ph = widget.get_preferred_bounds()

            pw = pw if pw is not None else 0
            ph = ph if ph is not None else 0

            max_h = max(max_h, ph + bt + bb)

            if pw == WH_FILL:
                fill_count += 1
                widths[i] = WH_FILL
            else:
                widths[i] = pw + bl + br
                fixed_width += widths[i]

        max_w = bw - pl - pr
        sum_w = 0

        for i in range(num):
            if widths[i] == WH_FILL:
                widths[i] = (max_w - fixed_width) // max(1, fill_count)

            if sum_w + widths[i] > max_w:
                widths[i] = max(0, max_w - sum_w)
            sum_w += widths[i]

        if max_h == WH_FILL:
            h = bh - pt - pb
        elif max_h != WH_NIL and max_h != WH_FILL:
            h = min(max_h, bh - pt - pb)
        else:
            h = bh - pt - pb

        x = bx + pl
        y = by + pt

        # Second pass: set bounds
        for i, widget in enumerate(widgets):
            if widget is None:
                continue
            bl, bt, br, bb = borders[i]
            widget.set_bounds(
                x=x + bl,
                y=y + bt,
                w=widths[i] - bl - br,
                h=h - bt - bb,
            )
            x += widths[i]

    def _layout_vertical(self) -> None:
        """Vertical (top-to-bottom) layout — orientation 1."""
        widgets = self._widgets or []
        num = len(widgets)
        if num == 0:
            return

        bx, by, bw, bh = self.get_bounds()
        pl, pt, pr, pb = self.get_padding()

        # Collect preferred heights and borders
        heights: List[int] = [0] * num
        borders: List[Tuple[int, int, int, int]] = [(0, 0, 0, 0)] * num
        fill_count = 0
        fixed_height = 0
        max_w = 0

        for i, widget in enumerate(widgets):
            if widget is None:
                continue
            if widget.is_hidden():
                continue

            # Ensure child is skinned so preferred_bounds are available
            widget.check_skin()

            # Get border
            borders[i] = widget.get_border()
            bl, bt, br, bb = borders[i]

            # Get preferred bounds
            _px, _py, pw, ph = widget.get_preferred_bounds()

            pw = pw if pw is not None else 0
            ph = ph if ph is not None else 0

            max_w = max(max_w, pw + bl + br)

            if ph == WH_FILL:
                fill_count += 1
                heights[i] = WH_FILL
            else:
                heights[i] = ph + bt + bb
                fixed_height += heights[i]

        max_h = bh - pt - pb
        sum_h = 0

        for i in range(num):
            if heights[i] == WH_FILL:
                heights[i] = (max_h - fixed_height) // max(1, fill_count)

            if sum_h + heights[i] > max_h:
                heights[i] = max(0, max_h - sum_h)
            sum_h += heights[i]

        if max_w == WH_FILL:
            w = bw - pl - pr
        elif max_w != WH_NIL and max_w != WH_FILL:
            w = min(max_w, bw - pl - pr)
        else:
            w = bw - pl - pr

        x = bx + pl
        y = by + pt

        # Second pass: set bounds
        for i, widget in enumerate(widgets):
            if widget is None:
                continue
            bl, bt, br, bb = borders[i]
            widget.set_bounds(
                x=x + bl,
                y=y + bt,
                w=w - bl - br,
                h=heights[i] - bt - bb,
            )
            y += heights[i]

    # ------------------------------------------------------------------
    # Draw (jiveL_group_draw)
    # ------------------------------------------------------------------

    def draw(self, surface: Surface, layer: int = LAYER_ALL) -> None:
        """
        Draw the group and its children onto *surface*.

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

        # Draw children
        def _draw_child(widget: Widget) -> None:
            # Only draw if we are the widget's parent (Bug 9362 fix)
            if widget.parent is self and hasattr(widget, "draw"):
                widget.draw(surface, layer)

        self.iterate(_draw_child)

    # ------------------------------------------------------------------
    # Preferred bounds (jiveL_group_get_preferred_bounds)
    # ------------------------------------------------------------------

    def get_preferred_bounds(
        self,
    ) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
        """
        Return the preferred ``(x, y, w, h)`` for layout purposes.

        Returns style-set preferred bounds (from ``_widget_pack``),
        falling back to aggregated child sizes for unset dimensions.

        Note: does NOT trigger ``check_layout()`` — the C original's
        ``getPreferredBounds`` reads directly from the peer struct
        without forcing a layout pass.
        """

        w = 0
        h = 0

        for widget in self.widgets.values():
            if widget is None:
                continue

            bl, bt, br, bb = widget.get_border()
            _px, _py, pw, ph = widget.get_preferred_bounds()

            pw = pw if pw is not None else 0
            ph = ph if ph is not None else 0

            w += pw + bl + br
            h = max(h, ph + bt + bb)

        pb = self.preferred_bounds
        px = pb[0] if pb[0] is not None and pb[0] != XY_NIL else None
        py = pb[1] if pb[1] is not None and pb[1] != XY_NIL else None
        pw = pb[2] if pb[2] is not None and pb[2] != WH_NIL else w
        ph = pb[3] if pb[3] is not None and pb[3] != WH_NIL else h

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
        parts = ["Group("]
        for widget in self.widgets.values():
            parts.append(str(widget))
        parts.append(")")
        return "".join(parts)

    def __str__(self) -> str:
        return self.__repr__()

    # ------------------------------------------------------------------
    # camelCase aliases (Lua compatibility)
    # ------------------------------------------------------------------
    setWidget = set_widget
    getWidget = get_widget
    setWidgetValue = set_widget_value
    getWidgetValue = get_widget_value
