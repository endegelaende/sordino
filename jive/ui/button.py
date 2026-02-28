"""
jive.ui.button — Mouse-state-machine for press/hold/drag on widgets.

Ported from ``Button.lua`` in the original jivelite project.

A Button wraps a widget with mouse-event listeners that implement a
state machine for press, hold, long-hold and drag gestures.  The
widget's style modifier is updated to ``"pressed"`` during a mouse-down,
and cleared on release or drag-away.

Mouse states::

    MOUSE_COMPLETE  →  (MOUSE_DOWN on down)
    MOUSE_DOWN      →  (MOUSE_HOLD on hold)  or  (press action on up)
    MOUSE_HOLD      →  (MOUSE_LONG_HOLD on second hold)  or  (done)
    MOUSE_LONG_HOLD →  (done)

Key behaviours:

* **Press** — fires *action* when mouse-up occurs inside the widget's
  press-buffer distance and no hold has fired.
* **Hold** — fires *hold_action* on ``EVENT_MOUSE_HOLD`` if the finger
  hasn't moved too far from the down-origin.
* **Long hold** — fires *long_hold_action* on a second hold event (only
  if *hold_action* didn't dismiss the window).
* **Drag** — tracks finger movement; toggles the ``"pressed"`` style
  modifier based on whether the pointer is still inside the press-buffer
  distance.  Large x-axis deltas suppress press on release.
* **Style modifier** — set to ``"pressed"`` on down, cleared on up/hold
  completion.

Usage::

    from jive.ui.button import Button

    label = Label("item", "Click me")
    btn = Button(label, action=my_callback, hold_action=my_hold_cb)
    # `label` now has mouse listeners installed
    # btn holds the state machine; keep a reference to it

Copyright 2010 Logitech. All Rights Reserved. (original Lua implementation)
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
)

from jive.ui.constants import (
    EVENT_CONSUME,
    EVENT_MOUSE_ALL,
    EVENT_MOUSE_DOWN,
    EVENT_MOUSE_DRAG,
    EVENT_MOUSE_HOLD,
    EVENT_MOUSE_UP,
    EVENT_SHOW,
    EVENT_UNUSED,
)
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event
    from jive.ui.widget import Widget

__all__ = ["Button"]

log = logger("jivelite.ui")

# ---------------------------------------------------------------------------
# Constants (from Button.lua)
# ---------------------------------------------------------------------------

# Distance (px) outside the widget bounds where a press is still accepted.
PRESS_BUFFER_DISTANCE_FROM_WIDGET: int = 30

# Maximum distance (px) from the mouse-down origin for a hold gesture
# to be recognised.  Relatively high because on touch devices the finger
# may roll while waiting.
HOLD_BUFFER_DISTANCE_FROM_ORIGIN: int = 30

# Maximum horizontal pixel delta (between down and up) for a press to
# be accepted.  Larger deltas are treated as horizontal swipes.
PRESS_MAX_X_DELTA: int = 100

# ---------------------------------------------------------------------------
# Mouse states
# ---------------------------------------------------------------------------

MOUSE_COMPLETE: int = 0
MOUSE_DOWN: int = 1
MOUSE_HOLD: int = 2
MOUSE_LONG_HOLD: int = 3


# ---------------------------------------------------------------------------
# Button class
# ---------------------------------------------------------------------------


class Button:
    """
    Attach a press/hold/drag state-machine to *widget*.

    All mouse-state data is stored internally on the Button instance
    (not on the widget), so it works with widgets that use ``__slots__``.

    Parameters
    ----------
    widget : Widget
        The widget to attach mouse listeners to.
    action : callable, optional
        Called on a successful press (mouse-up inside the widget).
        Should return an ``EventStatus`` value.
    hold_action : callable, optional
        Called on ``EVENT_MOUSE_HOLD`` if the finger hasn't drifted
        too far from the down-origin.
    long_hold_action : callable, optional
        Called on a second hold event (only applicable if *hold_action*
        didn't hide the window containing this button).
    """

    __slots__ = (
        "widget",
        "action",
        "hold_action",
        "long_hold_action",
        # Internal mouse-state (stored here, not on the widget)
        "mouse_state",
        "mouse_down_x",
        "mouse_down_y",
        "distance_from_mouse_down_max",
    )

    def __init__(
        self,
        widget: Widget,
        action: Optional[Callable[[], int]] = None,
        hold_action: Optional[Callable[[], int]] = None,
        long_hold_action: Optional[Callable[[], int]] = None,
    ) -> None:
        if widget is None:
            raise ValueError("widget must not be None")

        self.widget = widget
        self.action = action
        self.hold_action = hold_action
        self.long_hold_action = long_hold_action

        # Internal mouse-state
        self.mouse_state: int = MOUSE_COMPLETE
        self.mouse_down_x: Optional[int] = None
        self.mouse_down_y: Optional[int] = None
        self.distance_from_mouse_down_max: float = 0.0

        # Install EVENT_SHOW listener — reset pressed style on re-show
        widget.add_listener(
            int(EVENT_SHOW),
            self._on_show,
        )

        # Install mouse listener
        widget.add_listener(
            int(EVENT_MOUSE_ALL),
            self._on_mouse,
        )

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _finish_mouse_sequence(self) -> None:
        """Reset the mouse-state machine."""
        self.mouse_state = MOUSE_COMPLETE
        self.mouse_down_x = None
        self.mouse_down_y = None
        self.distance_from_mouse_down_max = 0.0

    def _update_mouse_origin_offset(self, event: Event) -> None:
        """Track the maximum distance from the mouse-down origin."""
        mx, my = event.get_mouse_xy()

        if self.mouse_down_x is None or self.mouse_down_y is None:
            # First point — record origin
            self.mouse_down_x = mx
            self.mouse_down_y = my
        else:
            # Subsequent point — update max distance
            dy = my - self.mouse_down_y
            dx = mx - self.mouse_down_x
            dist = math.sqrt(dx * dx + dy * dy)
            if dist > self.distance_from_mouse_down_max:
                self.distance_from_mouse_down_max = dist

    def _mouse_exceeded_hold_distance(self) -> bool:
        """Return ``True`` if the finger has moved too far for a hold."""
        return self.distance_from_mouse_down_max >= HOLD_BUFFER_DISTANCE_FROM_ORIGIN

    # ------------------------------------------------------------------
    # Listener callbacks
    # ------------------------------------------------------------------

    def _on_show(self, event: Event) -> int:
        """Reset pressed style when the widget is re-shown."""
        w = self.widget
        w.set_style_modifier(None)
        w.re_draw()
        return int(EVENT_UNUSED)

    def _on_mouse(self, event: Event) -> int:
        """Main mouse-event state machine."""
        w = self.widget
        etype = event.get_type()

        if log.is_debug():
            log.debug(
                "Button event: %s  state: %s",
                event,
                self.mouse_state,
            )

        # ---- MOUSE_DOWN ----
        if etype == int(EVENT_MOUSE_DOWN):
            # Finish any previous sequence defensively
            self._finish_mouse_sequence()
            self._update_mouse_origin_offset(event)

            w.set_style_modifier("pressed")
            self.mouse_state = MOUSE_DOWN
            w.re_draw()
            return int(EVENT_CONSUME)

        # ---- MOUSE_HOLD (first hold → hold_action) ----
        if (
            etype == int(EVENT_MOUSE_HOLD)
            and self.mouse_state == MOUSE_DOWN
            and self.hold_action is not None
            and not self._mouse_exceeded_hold_distance()
        ):
            self.mouse_state = MOUSE_HOLD

            # Finish up unless a long-hold is still to come
            if self.long_hold_action is None:
                w.set_style_modifier(None)
                w.re_draw()
                self._finish_mouse_sequence()

            return self.hold_action()

        # ---- MOUSE_HOLD (second hold → long_hold_action) ----
        if (
            etype == int(EVENT_MOUSE_HOLD)
            and self.mouse_state in (MOUSE_DOWN, MOUSE_HOLD)
            and self.long_hold_action is not None
            and not self._mouse_exceeded_hold_distance()
        ):
            self.mouse_state = MOUSE_LONG_HOLD
            w.set_style_modifier(None)
            w.re_draw()
            return self.long_hold_action()

        # ---- MOUSE_UP ----
        if etype == int(EVENT_MOUSE_UP):
            mx, my = event.get_mouse_xy()
            delta = 0
            if self.mouse_down_x is not None:
                delta = abs(self.mouse_down_x - mx)

            if self.mouse_state != MOUSE_DOWN:
                # Not a press (hold already fired, or sequence was reset)
                w.set_style_modifier(None)
                w.re_draw()
                self._finish_mouse_sequence()
                return int(EVENT_CONSUME)

            w.set_style_modifier(None)
            w.re_draw()
            self._finish_mouse_sequence()

            if (
                _mouse_inside_press_distance(w, event)
                and self.action is not None
                and delta < PRESS_MAX_X_DELTA
            ):
                return self.action()

            # Cancel (finger moved too far)
            return int(EVENT_CONSUME)

        # ---- MOUSE_DRAG ----
        if etype == int(EVENT_MOUSE_DRAG):
            if self.mouse_state == MOUSE_COMPLETE:
                return int(EVENT_CONSUME)

            self._update_mouse_origin_offset(event)

            if _mouse_inside_press_distance(w, event):
                modifier = "pressed"
                if w.get_style_modifier() != modifier:
                    w.set_style_modifier(modifier)
                    w.re_draw()
            else:
                if w.get_style_modifier() is not None:
                    w.set_style_modifier(None)
                    w.re_draw()

            return int(EVENT_CONSUME)

        # Default: consume
        return int(EVENT_CONSUME)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        has_action = self.action is not None
        has_hold = self.hold_action is not None
        has_long = self.long_hold_action is not None
        return (
            f"Button(widget={self.widget!r}, "
            f"action={has_action}, hold={has_hold}, long_hold={has_long})"
        )

    def __str__(self) -> str:
        return self.__repr__()


# ---------------------------------------------------------------------------
# Module-level helper functions (matching Lua free functions)
# ---------------------------------------------------------------------------


def _mouse_inside_press_distance(widget: Widget, event: Event) -> bool:
    """
    Return ``True`` if the mouse pointer is within the press-buffer
    distance of the widget's bounds.
    """
    mx, my = event.get_mouse_xy()
    bx, by, bw, bh = widget.get_bounds()

    # Compute shortest distance from mouse to widget bounding box
    if mx < bx:
        dx = bx - mx
    elif mx > bx + bw:
        dx = mx - (bx + bw)
    else:
        dx = 0

    if my < by:
        dy = by - my
    elif my > by + bh:
        dy = my - (by + bh)
    else:
        dy = 0

    if dx == 0 and dy == 0:
        # Inside widget bounds
        return True

    distance = math.sqrt(dx * dx + dy * dy)
    return distance < PRESS_BUFFER_DISTANCE_FROM_WIDGET
