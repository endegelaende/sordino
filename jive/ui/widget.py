"""
jive.ui.widget — Base class for UI widgets in the Jivelite Python3 port.

Ported from ``jive/ui/Widget.lua`` and ``jive_widget.c`` in the original
jivelite project.

Widget is the root of the widget hierarchy.  It manages:

* **Bounds** — position and size ``(x, y, w, h)``
* **Style** — a string key resolved against the active skin
* **Parent / child** — tree structure (parent link; ``iterate`` for children)
* **Listeners** — event callbacks registered with a bitmask
* **Animations** — per-frame animation callbacks with a target frame-rate
* **Timers** — widget-scoped timers that auto-start/stop with visibility
* **Event dispatch** — ``_event()`` walks listeners respecting mask & consume
* **Dirty flags** — ``re_skin``, ``re_layout``, ``re_draw`` for lazy update

Concrete widgets (Label, Icon, Group, Window, …) subclass Widget and
override ``_skin``, ``_layout``, ``draw``, and optionally ``iterate``.

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
    Sequence,
    Tuple,
    Union,
)

from jive.ui.constants import (
    ACTION,
    ALIGN_CENTER,
    EVENT_ALL,
    EVENT_CONSUME,
    EVENT_HIDE,
    EVENT_SHOW,
    EVENT_UNUSED,
    EVENT_UPDATE,
    FRAME_RATE_DEFAULT,
    LAYER_CONTENT,
    WH_FILL,
    WH_NIL,
    XY_NIL,
    Align,
    EventType,
    Layer,
)
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event
    from jive.ui.surface import Surface
    from jive.ui.timer import Timer as TimerType

__all__ = ["Widget"]

log = logger("jivelite.ui")

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

# A listener handle is a list ``[mask, callback]`` — mutable so the caller
# can hold a reference and we can identity-compare on removal.
ListenerHandle = list  # [int, Callable[[Event], int]]

# An animation handle is a list ``[callback, frame_skip, counter]``.
AnimationHandle = list  # [Callable[..., None], int, int]


# ---------------------------------------------------------------------------
# Widget class
# ---------------------------------------------------------------------------


class Widget:
    """
    Base class for all UI widgets.

    Subclasses **must** override:

    * ``_skin(self) -> None``   — apply skin/style parameters
    * ``_layout(self) -> None`` — compute child positions
    * ``draw(self, surface) -> None`` — paint onto *surface*

    Subclasses **may** override:

    * ``iterate(self, closure) -> None`` — call *closure(child)* for each
      contained child widget.
    """

    __slots__ = (
        "bounds",
        "preferred_bounds",
        "padding",
        "border",
        "parent",
        "visible",
        "timers",
        "listeners",
        "animations",
        "style",
        "style_modifier",
        "accel_key",
        "smoothscroll",
        "_layer",
        "_align",
        "_z_order",
        "_hidden",
        "_needs_skin",
        "_needs_layout",
        "_needs_draw",
        "_skin_origin",
        "_child_origin",
        "_layout_origin",
        "_mouse_bounds",
        "_stable_sort_index",
    )

    # Class-level frame rate — set by Framework.init(); defaults to 30.
    _frame_rate: int = FRAME_RATE_DEFAULT

    def __init__(self, style: str) -> None:
        if not isinstance(style, str):
            raise TypeError(f"style must be a string, got {type(style).__name__}")

        # Geometry — (x, y, w, h).  Stored as a mutable list for
        # compatibility with the C code that passes bounds by reference.
        self.bounds: list[int] = [0, 0, 0, 0]
        self.preferred_bounds: list[Optional[int]] = [None, None, None, None]
        self.padding: list[int] = [0, 0, 0, 0]  # left, top, right, bottom
        self.border: list[int] = [0, 0, 0, 0]  # left, top, right, bottom

        # Tree
        self.parent: Optional[Widget] = None
        self.visible: bool = False

        # Callbacks
        self.timers: list[TimerType] = []
        self.listeners: list[ListenerHandle] = []
        self.animations: list[AnimationHandle] = []

        # Style
        self.style: str = style
        self.style_modifier: Optional[str] = None
        self.accel_key: Optional[str] = None
        self.smoothscroll: Optional[bool] = None

        # Layer / alignment / z-order
        self._layer: int = int(LAYER_CONTENT)
        self._align: int = int(ALIGN_CENTER)
        self._z_order: int = 0
        self._hidden: bool = False

        # Dirty flags
        self._needs_skin: bool = True
        self._needs_layout: bool = True
        self._needs_draw: bool = True

        # Origin counters (for incremental skin/layout invalidation)
        self._skin_origin: int = 0
        self._child_origin: int = 0
        self._layout_origin: int = 0

        # Cached mouse-hit bounds (may differ from visual bounds)
        self._mouse_bounds: Optional[list[int]] = None

    # ------------------------------------------------------------------
    # Child iteration  (overridden by containers like Group, Window, Menu)
    # ------------------------------------------------------------------

    def iterate(self, closure: Callable[[Widget], None]) -> None:
        """
        Call *closure(child)* for every child widget.

        The base implementation does nothing (leaf widget).  Containers
        override this.
        """
        pass

    # ------------------------------------------------------------------
    # Bounds
    # ------------------------------------------------------------------

    def get_bounds(self) -> Tuple[int, int, int, int]:
        """Return ``(x, y, w, h)``."""
        b = self.bounds
        return b[0], b[1], b[2], b[3]

    def set_bounds(
        self,
        x: Optional[int] = None,
        y: Optional[int] = None,
        w: Optional[int] = None,
        h: Optional[int] = None,
    ) -> None:
        """
        Set the widget bounds.  ``None`` values leave the corresponding
        component unchanged.
        """
        if x is not None:
            self.bounds[0] = x
        if y is not None:
            self.bounds[1] = y
        if w is not None:
            self.bounds[2] = w
        if h is not None:
            self.bounds[3] = h

    def get_size(self) -> Tuple[int, int]:
        """Return ``(w, h)``."""
        return self.bounds[2], self.bounds[3]

    def set_size(self, w: int, h: int) -> None:
        """Set width and height."""
        self.set_bounds(w=w, h=h)

    def get_position(self) -> Tuple[int, int]:
        """Return ``(x, y)``."""
        return self.bounds[0], self.bounds[1]

    def set_position(self, x: int, y: int) -> None:
        """Set the x/y position."""
        self.set_bounds(x=x, y=y)

    def get_preferred_bounds(
        self,
    ) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
        """Return ``(x, y, w, h)`` preferred bounds (may contain ``None``)."""
        pb = self.preferred_bounds
        return pb[0], pb[1], pb[2], pb[3]

    # ------------------------------------------------------------------
    # Padding / Border
    # ------------------------------------------------------------------

    def get_padding(self) -> Tuple[int, int, int, int]:
        """Return ``(left, top, right, bottom)`` padding."""
        p = self.padding
        return p[0], p[1], p[2], p[3]

    def set_padding(
        self, left: int = 0, top: int = 0, right: int = 0, bottom: int = 0
    ) -> None:
        self.padding[:] = [left, top, right, bottom]

    def get_border(self) -> Tuple[int, int, int, int]:
        """Return ``(left, top, right, bottom)`` border widths."""
        b = self.border
        return b[0], b[1], b[2], b[3]

    def set_border(
        self, left: int = 0, top: int = 0, right: int = 0, bottom: int = 0
    ) -> None:
        self.border[:] = [left, top, right, bottom]

    # ------------------------------------------------------------------
    # Style
    # ------------------------------------------------------------------

    def get_style(self) -> str:
        """Return the widget's style name."""
        return self.style

    def set_style(self, style: str) -> None:
        """Set the widget's style name.  Triggers a re-skin."""
        if not isinstance(style, str):
            raise TypeError(f"style must be a string, got {type(style).__name__}")
        if self.style == style:
            return
        self.style = style
        self.re_skin()
        self.iterate(lambda w: w.re_skin())

    def get_style_modifier(self) -> Optional[str]:
        """Return the widget's style modifier (e.g. ``"selected"``)."""
        return self.style_modifier

    def set_style_modifier(self, modifier: Optional[str]) -> None:
        """Set the style modifier.  Triggers a re-skin if changed."""
        if self.style_modifier == modifier:
            return
        self.style_modifier = modifier
        self.re_skin()
        self.iterate(lambda w: w.re_skin())

    # ------------------------------------------------------------------
    # Layer / Alignment / Z-order / Hidden
    # ------------------------------------------------------------------

    @property
    def layer(self) -> int:
        return self._layer

    @layer.setter
    def layer(self, value: int) -> None:
        self._layer = value

    @property
    def align(self) -> int:
        return self._align

    @align.setter
    def align(self, value: int) -> None:
        self._align = value

    @property
    def z_order(self) -> int:
        return self._z_order

    @z_order.setter
    def z_order(self, value: int) -> None:
        self._z_order = value

    def is_hidden(self) -> bool:
        return self._hidden

    def set_hidden(self, hidden: bool) -> None:
        self._hidden = hidden

    # ------------------------------------------------------------------
    # Visibility
    # ------------------------------------------------------------------

    def is_visible(self) -> bool:
        """Return ``True`` if the widget is currently on stage."""
        return self.visible

    # ------------------------------------------------------------------
    # Parent / Window
    # ------------------------------------------------------------------

    def get_parent(self) -> Optional[Widget]:
        """Return the parent widget, or ``None``."""
        return self.parent

    def get_window(self) -> Optional[Widget]:
        """
        Return the Window containing this widget, or ``None``.

        Walks up the parent chain; the topmost widget with no parent that
        is a Window instance is returned.
        """
        if self.parent is not None:
            return self.parent.get_window()
        return None

    def hide(self, *args: Any, **kwargs: Any) -> None:
        """
        Hide the window containing this widget.

        Delegates to ``window.hide()``.
        """
        window = self.get_window()
        if window is not None:
            window.hide(*args, **kwargs)

    # ------------------------------------------------------------------
    # Dirty flags — re_skin / re_layout / re_draw
    # ------------------------------------------------------------------

    def re_skin(self) -> None:
        """
        Mark the widget as needing a skin update.

        Also implies re-layout and re-draw.
        """
        self._needs_skin = True
        self._needs_layout = True
        self._needs_draw = True

    def re_layout(self) -> None:
        """
        Mark the widget as needing a layout pass.

        Also implies re-draw.
        """
        self._needs_layout = True
        self._needs_draw = True

    def re_draw(self) -> None:
        """Mark the widget's bounding box for redrawing."""
        self._needs_draw = True

    def check_skin(self) -> None:
        """Apply the skin if the dirty flag is set."""
        if self._needs_skin:
            self._skin()
            self._needs_skin = False

    def check_layout(self) -> None:
        """
        Run the layout pass if the dirty flag is set, recursing into
        children.
        """
        self.check_skin()
        if self._needs_layout:
            self._layout()
            self._needs_layout = False
        # Recurse
        self.iterate(lambda child: child.check_layout())

    # ------------------------------------------------------------------
    # Skin / Layout / Draw  (to be overridden by subclasses)
    # ------------------------------------------------------------------

    def _skin(self) -> None:
        """
        Apply style parameters from the active skin.

        **Must** be overridden by concrete widget classes.
        """
        pass  # Leaf widgets with no skin can leave this as a no-op.

    def _layout(self) -> None:
        """
        Compute positions of child widgets.

        **Must** be overridden by concrete widget classes.
        """
        pass

    def draw(self, surface: Surface) -> None:
        """
        Paint the widget onto *surface*.

        **Must** be overridden by concrete widget classes.
        """
        pass

    # ------------------------------------------------------------------
    # Listeners
    # ------------------------------------------------------------------

    def add_listener(
        self,
        mask: int,
        listener: Callable[[Event], int],
    ) -> ListenerHandle:
        """
        Register *listener* for events matching *mask*.

        The listener is called with the Event and should return an
        ``EventStatus`` value (``EVENT_UNUSED`` or ``EVENT_CONSUME``).

        Returns a handle for use with ``remove_listener``.

        New listeners are prepended (LIFO) matching the Lua original.
        """
        if not isinstance(mask, int):
            raise TypeError(f"mask must be int, got {type(mask).__name__}")
        if not callable(listener):
            raise TypeError("listener must be callable")

        handle: ListenerHandle = [mask, listener]
        self.listeners.insert(0, handle)
        return handle

    def add_action_listener(
        self,
        action_name: str,
        obj: Any,
        listener: Callable[..., Optional[int]],
    ) -> Optional[ListenerHandle]:
        """
        Register a listener for a named action.

        This wraps ``add_listener(ACTION, ...)`` and filters by action
        name, matching the Lua ``addActionListener`` helper.

        *listener* is called as ``listener(obj, event)`` and should
        return an event-status or ``None`` (defaults to ``EVENT_CONSUME``).
        """
        # Verify action is registered (late import to avoid circular dep)
        try:
            from jive.ui.framework import framework as fw

            if fw.get_action_event_index_by_name(action_name) is None:
                log.error(
                    f"action name not registered: ({action_name}). "
                    f"Available actions: {fw.dump_actions()}"
                )
                return None
        except (ImportError, AttributeError):
            pass  # Framework not yet initialised — allow registration anyway

        def _wrapper(event: Event) -> int:
            evt_action = event.get_action()
            if evt_action != action_name:
                return int(EVENT_UNUSED)

            result = listener(obj, event)
            return int(result) if result is not None else int(EVENT_CONSUME)

        return self.add_listener(int(ACTION), _wrapper)

    def remove_listener(self, handle: ListenerHandle) -> None:
        """Remove the listener identified by *handle*."""
        try:
            self.listeners.remove(handle)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Animations
    # ------------------------------------------------------------------

    def add_animation(
        self,
        animation: Callable[..., None],
        frame_rate: int,
    ) -> AnimationHandle:
        """
        Register a per-frame *animation* function at the requested
        *frame_rate* (fps).

        The animation is called once per N frames where N is the ratio
        of the system frame-rate to the requested rate.

        Returns a handle for use with ``remove_animation``.
        """
        if not callable(animation):
            raise TypeError("animation must be callable")
        if not isinstance(frame_rate, (int, float)) or frame_rate <= 0:
            raise ValueError(f"frame_rate must be > 0, got {frame_rate}")

        # frame_skip = system_fps / requested_fps (integer)
        frame_skip = max(1, Widget._frame_rate // int(frame_rate))

        handle: AnimationHandle = [animation, frame_skip, frame_skip]
        self.animations.append(handle)

        if self.visible:
            self._register_animation_with_framework()

        return handle

    def remove_animation(self, handle: AnimationHandle) -> None:
        """Remove the animation identified by *handle*."""
        try:
            self.animations.remove(handle)
        except ValueError:
            pass

        if self.visible:
            self._unregister_animation_from_framework()

    def _register_animation_with_framework(self) -> None:
        """Tell Framework this widget has active animations."""
        try:
            from jive.ui.framework import framework as fw

            fw._add_animation_widget(self)
        except (ImportError, AttributeError):
            pass

    def _unregister_animation_from_framework(self) -> None:
        """Tell Framework this widget may no longer need animation ticks."""
        try:
            from jive.ui.framework import framework as fw

            fw._remove_animation_widget(self)
        except (ImportError, AttributeError):
            pass

    # ------------------------------------------------------------------
    # Timers
    # ------------------------------------------------------------------

    def add_timer(
        self,
        interval: int,
        callback: Callable[[], None],
        once: bool = False,
    ) -> TimerType:
        """
        Add a timer that fires *callback* every *interval* ms.

        The timer auto-starts when the widget is visible and auto-stops
        when hidden.
        """
        from jive.ui.timer import Timer

        timer = Timer(interval, callback, once)
        self.timers.append(timer)

        if self.visible:
            timer.start()

        return timer

    def remove_timer(self, timer: TimerType) -> None:
        """Stop and remove *timer* from this widget."""
        timer.stop()
        try:
            self.timers.remove(timer)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Event dispatch
    # ------------------------------------------------------------------

    def dispatch_new_event(self, event_type: int, **kwargs: Any) -> int:
        """
        Create a new Event of *event_type* and dispatch it through this
        widget's listeners via Framework.

        Additional keyword arguments are forwarded to the Event constructor.
        """
        from jive.ui.event import Event as EventCls

        event = EventCls(event_type, **kwargs)

        try:
            from jive.ui.framework import framework as fw

            return fw.dispatch_event(self, event)
        except (ImportError, AttributeError):
            # Framework not available — dispatch locally
            return self._event(event)

    def dispatch_update_event(self, value: int) -> int:
        """
        Send an ``EVENT_UPDATE`` with *value* to this widget's listeners.
        """
        from jive.ui.event import Event as EventCls

        event = EventCls(EVENT_UPDATE, value=value)
        try:
            from jive.ui.framework import framework as fw

            return fw.dispatch_event(self, event)
        except (ImportError, AttributeError):
            return self._event(event)

    def _event(self, event: Event) -> int:
        """
        Internal event handler.

        1. Handle ``EVENT_SHOW`` / ``EVENT_HIDE`` — toggle visibility and
           start/stop timers and animations.
        2. Walk the listener list; stop when a listener consumes the event.

        Returns a combined ``EventStatus`` bitmask.
        """
        etype = event.get_type()

        # ---- Visibility lifecycle ----
        if etype == int(EVENT_SHOW) and not self.visible:
            self.visible = True
            if self.animations:
                self._register_animation_with_framework()
            for timer in self.timers:
                timer.start()

        elif etype == int(EVENT_HIDE) and self.visible:
            self.visible = False
            if self.animations:
                self._unregister_animation_from_framework()
            for timer in self.timers:
                timer.stop()

        # ---- Dispatch to listeners ----
        result = 0
        for handle in self.listeners:
            mask, callback = handle[0], handle[1]
            if etype & mask:
                try:
                    r = callback(event)
                    result |= r or 0
                except Exception as exc:
                    log.warn(f"listener error: {exc}")

                if result & int(EVENT_CONSUME):
                    break

        return result

    # ------------------------------------------------------------------
    # Mouse hit-testing
    # ------------------------------------------------------------------

    def mouse_inside(self, event: Event) -> bool:
        """
        Return ``True`` if the mouse coordinates of *event* are inside
        this widget's bounds.
        """
        try:
            mx, my = event.get_mouse_xy()
        except TypeError:
            return False

        bx, by, bw, bh = self.get_bounds()
        return bx <= mx < bx + bw and by <= my < by + bh

    def get_mouse_bounds(self) -> Tuple[int, int, int, int]:
        """
        Return the mouse-hit bounds, which may differ from the visual
        bounds (e.g. a larger touch target).
        """
        if self._mouse_bounds is not None:
            mb = self._mouse_bounds
            return mb[0], mb[1], mb[2], mb[3]
        return self.get_bounds()

    def set_mouse_bounds(self, x: int, y: int, w: int, h: int) -> None:
        """Set explicit mouse-hit bounds."""
        self._mouse_bounds = [x, y, w, h]

    # ------------------------------------------------------------------
    # Accelerator key
    # ------------------------------------------------------------------

    def set_accel_key(self, key: Optional[str]) -> None:
        """Set the key letter displayed in an accelerated menu."""
        self.accel_key = key

    def get_accel_key(self) -> Optional[str]:
        """Return the accelerator key letter."""
        return self.accel_key

    # ------------------------------------------------------------------
    # Sound
    # ------------------------------------------------------------------

    def play_sound(self, sound: str) -> None:
        """Play a named sound if the widget is visible."""
        if self.visible:
            try:
                from jive.ui.framework import framework as fw

                fw.play_sound(sound)
            except (ImportError, AttributeError):
                pass

    # ------------------------------------------------------------------
    # Smooth scrolling flag
    # ------------------------------------------------------------------

    def set_smooth_scrolling_menu(self, val: Optional[bool]) -> None:
        self.smoothscroll = val

    # ------------------------------------------------------------------
    # Alignment helpers
    # ------------------------------------------------------------------

    @staticmethod
    def halign(align: int, x: int, outer_w: int, inner_w: int) -> int:
        """
        Compute the horizontal offset for *inner_w* inside *outer_w*
        according to *align*.
        """
        if align in (
            int(Align.LEFT),
            int(Align.TOP_LEFT),
            int(Align.BOTTOM_LEFT),
        ):
            return x
        elif align in (
            int(Align.RIGHT),
            int(Align.TOP_RIGHT),
            int(Align.BOTTOM_RIGHT),
        ):
            return x + outer_w - inner_w
        else:
            # CENTER, TOP, BOTTOM
            return x + (outer_w - inner_w) // 2

    @staticmethod
    def valign(align: int, y: int, outer_h: int, inner_h: int) -> int:
        """
        Compute the vertical offset for *inner_h* inside *outer_h*
        according to *align*.
        """
        if align in (
            int(Align.TOP),
            int(Align.TOP_LEFT),
            int(Align.TOP_RIGHT),
        ):
            return y
        elif align in (
            int(Align.BOTTOM),
            int(Align.BOTTOM_LEFT),
            int(Align.BOTTOM_RIGHT),
        ):
            return y + outer_h - inner_h
        else:
            # CENTER, LEFT, RIGHT
            return y + (outer_h - inner_h) // 2

    # ------------------------------------------------------------------
    # Widget packing (border-layout)
    # ------------------------------------------------------------------

    @staticmethod
    def pack(
        layout_region: int,
        bounds_x: int,
        bounds_y: int,
        bounds_w: int,
        bounds_h: int,
        preferred_w: Optional[int],
        preferred_h: Optional[int],
    ) -> Tuple[int, int, int, int, int, int, int, int]:
        """
        Compute how a child widget with a given *layout_region* and
        preferred size fits inside the container's remaining bounds.

        Returns ``(child_x, child_y, child_w, child_h,
                    remaining_x, remaining_y, remaining_w, remaining_h)``.
        """
        from jive.ui.constants import Layout

        cw = preferred_w if preferred_w and preferred_w != WH_NIL else bounds_w
        ch = preferred_h if preferred_h and preferred_h != WH_NIL else bounds_h

        if layout_region == int(Layout.NORTH):
            return (
                bounds_x,
                bounds_y,
                bounds_w,
                ch,
                bounds_x,
                bounds_y + ch,
                bounds_w,
                bounds_h - ch,
            )
        elif layout_region == int(Layout.SOUTH):
            return (
                bounds_x,
                bounds_y + bounds_h - ch,
                bounds_w,
                ch,
                bounds_x,
                bounds_y,
                bounds_w,
                bounds_h - ch,
            )
        elif layout_region == int(Layout.WEST):
            return (
                bounds_x,
                bounds_y,
                cw,
                bounds_h,
                bounds_x + cw,
                bounds_y,
                bounds_w - cw,
                bounds_h,
            )
        elif layout_region == int(Layout.EAST):
            return (
                bounds_x + bounds_w - cw,
                bounds_y,
                cw,
                bounds_h,
                bounds_x,
                bounds_y,
                bounds_w - cw,
                bounds_h,
            )
        else:
            # CENTER or NONE — take all remaining space
            return (
                bounds_x,
                bounds_y,
                bounds_w,
                bounds_h,
                bounds_x,
                bounds_y,
                0,
                0,
            )

    # ------------------------------------------------------------------
    # Debug / dump
    # ------------------------------------------------------------------

    def dump(self, level: int = 0) -> str:
        """
        Return a human-readable tree dump of this widget and its children.
        """
        pad = "  " * level
        parts: list[str] = [
            f"{pad}{self} [{self.peer_to_string()} visible={self.visible}]"
        ]
        self.iterate(lambda child: parts.append(child.dump(level + 1)))
        return "\n".join(parts)

    def peer_to_string(self) -> str:
        """Return a compact string identifying the widget's bounds."""
        b = self.bounds
        return f"({b[0]},{b[1]} {b[2]}x{b[3]})"

    def short_widget_to_string(self) -> str:
        """Return the class name without memory address."""
        s = str(self)
        paren = s.find("(")
        if paren < 0:
            return s
        return s[:paren]

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(style={self.style!r})"

    def __str__(self) -> str:
        return self.__repr__()
