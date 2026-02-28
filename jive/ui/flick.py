"""
jive.ui.flick — Touch-gesture flick engine for the Jivelite Python3 port.

Ported from ``Flick.lua`` in the original jivelite project.

A Flick manages finger-flick afterscroll physics for a scrollable parent
widget (typically a :class:`~jive.ui.menu.Menu`).  When the user lifts
their finger after a drag, the Flick calculates the speed and direction
and continues scrolling with deceleration until the speed drops below a
threshold.

Key behaviours:

* **Speed calculation** — uses the last N mouse-move data points
  (within a staleness window) to compute average drag speed.
* **Finger-stop detection** — if recent points show very little
  movement, the flick is suppressed (the user stopped their finger
  before lifting).
* **Deceleration** — after an initial constant-speed phase, the flick
  decelerates to a stop using physics (``v = v0 + a*t``,
  ``y = v0*t + 0.5*a*t²``).
* **Snap-to-item** — if the parent supports snapping, the flick will
  snap to the nearest item boundary when slowing down.
* **Boundary stopping** — flick stops at list top/bottom when
  wraparound is not enabled.
* **By-item scrolling** — at high speeds, scrolling switches from
  per-pixel to per-item for efficiency.
* **Timer-driven** — uses a 25ms repeating :class:`~jive.ui.timer.Timer`
  to drive the afterscroll animation.

Usage::

    from jive.ui.flick import Flick

    flick = Flick(my_menu)

    # In mouse-move handler:
    flick.update_flick_data(mouse_event)

    # In mouse-up handler:
    speed, direction = flick.get_flick_speed(item_height, mouse_up_ticks)
    if speed is not None:
        flick.flick(speed, direction)

    # To interrupt:
    flick.stop_flick(by_finger=True)

Copyright 2010 Logitech. All Rights Reserved. (original Lua implementation)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    List,
    Optional,
    Tuple,
)

from jive.ui.timer import Timer
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event

__all__ = ["Flick"]

log = logger("jivelite.ui")

# ---------------------------------------------------------------------------
# Physics constants (from Flick.lua)
# ---------------------------------------------------------------------------

# Speed (pixels/ms) threshold to start a flick.
FLICK_THRESHOLD_START_SPEED: float = 90.0 / 1000.0

# "Recent" distance (px) that must be surpassed for flick to start.
# Used to detect drag-then-quick-finger-stop-then-release scenarios
# that normal averaging doesn't handle well.
FLICK_RECENT_THRESHOLD_DISTANCE: float = 5.0

# Speed (pixels/ms) threshold: below this, scrolling is per-pixel;
# above this, scrolling is per-item.
FLICK_THRESHOLD_BY_PIXEL_SPEED: float = 600.0 / 1000.0

# Speed (pixels/ms) at which flick scrolling stops.
FLICK_STOP_SPEED: float = 1.0 / 1000.0

# Stop speed when snap-to-item is enabled (higher so snapping kicks in).
FLICK_STOP_SPEED_WITH_SNAP: float = 60.0 / 1000.0

# Pixel shift per snap step.
SNAP_PIXEL_SHIFT: int = 1

# If initial speed exceeds this, "letter" accelerators will be used.
FLICK_FORCE_ACCEL_SPEED: float = 72.0 * 30.0 / 1000.0

# Time (ms) after flick starts before deceleration begins.
FLICK_DECEL_START_TIME: float = 100.0

# Base deceleration duration (ms) from decel start to scroll stop.
FLICK_DECEL_TOTAL_TIME: float = 400.0

# Factor applied to flick speed to compute extra afterscroll time.
FLICK_SPEED_DECEL_TIME_FACTOR: float = 0.8

# Factor applied to flick speed to compute decel start delay.
FLICK_SPEED_DECEL_START_TIME_FACTOR: float = 0.7

# Only mouse points gathered in the last N ms are used for speed calc.
FLICK_STALE_TIME: int = 190


# ---------------------------------------------------------------------------
# Data point for flick speed calculation
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _FlickPoint:
    """A single data point in the flick history."""

    y: int
    ticks: int


# ---------------------------------------------------------------------------
# Flick class
# ---------------------------------------------------------------------------


class Flick:
    """
    Manages finger-flick afterscroll physics for a scrollable parent.

    Parameters
    ----------
    parent : object
        The scrollable widget (typically a Menu) that owns this Flick.
        Must implement:
        - ``handle_drag(pixel_offset, by_item_only=False)``
        - ``is_at_top()`` → bool
        - ``is_at_bottom()`` → bool

        May optionally implement:
        - ``snap_to_item_enabled`` (bool attribute, default ``False``)
        - ``is_wraparound_enabled()`` → bool (default ``False``)
        - ``pixel_offset_y`` (int attribute)
        - ``snap_to_nearest()``
    """

    __slots__ = (
        "parent",
        "_points",
        "flick_timer",
        "flick_in_progress",
        "flick_interrupted_by_finger",
        "snap_to_item_in_progress",
        # Flick physics state
        "flick_initial_speed",
        "flick_direction",
        "flick_initial_scroll_t",
        "flick_initial_deceleration_scroll_t",
        "flick_last_y",
        "flick_pre_decel_y",
        "flick_accel_rate",
        "flick_decel_start_t",
    )

    def __init__(self, parent: Any) -> None:
        self.parent = parent

        # Flick data points
        self._points: List[_FlickPoint] = []

        # State flags
        self.flick_in_progress: bool = False
        self.flick_interrupted_by_finger: bool = False
        self.snap_to_item_in_progress: bool = False

        # Physics state
        self.flick_initial_speed: float = 0.0
        self.flick_direction: int = 0
        self.flick_initial_scroll_t: Optional[int] = None
        self.flick_initial_deceleration_scroll_t: Optional[int] = None
        self.flick_last_y: float = 0.0
        self.flick_pre_decel_y: float = 0.0
        self.flick_accel_rate: float = 0.0
        self.flick_decel_start_t: float = 0.0

        # Timer (25ms interval, matching Lua)
        self.flick_timer: Timer = Timer(
            25,
            self._on_timer,
        )

    # ------------------------------------------------------------------
    # Timer callback
    # ------------------------------------------------------------------

    def _on_timer(self) -> None:
        """Called by the flick timer to continue afterscroll."""
        self.flick()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def stop_flick(self, by_finger: bool = False) -> None:
        """
        Stop any in-progress flick.

        Parameters
        ----------
        by_finger : bool
            ``True`` if the flick was interrupted by a new finger-down.
        """
        self.flick_timer.stop()
        self.flick_interrupted_by_finger = by_finger
        self.flick_in_progress = False
        self.snap_to_item_in_progress = False
        self.reset_flick_data()

    stopFlick = stop_flick

    def update_flick_data(self, mouse_event: Event) -> None:
        """
        Record a mouse-move data point for flick speed calculation.

        Parameters
        ----------
        mouse_event : Event
            A mouse event (``EVENT_MOUSE_MOVE`` or ``EVENT_MOUSE_DRAG``).
        """
        x, y = mouse_event.get_mouse_xy()
        ticks = mouse_event.get_ticks()

        # Skip zero ticks (workaround for occasional bad values)
        if ticks == 0:
            return

        # Reject outlier ticks (> 10s gap from previous point)
        if len(self._points) >= 1:
            previous_ticks = self._points[-1].ticks
            if abs(ticks - previous_ticks) > 10000:
                log.error(
                    "Erroneous tick value occurred, ignoring: %d "
                    "after previous tick value of: %d",
                    ticks,
                    previous_ticks,
                )
                return

        # Use last collection time as initial scroll time to avoid
        # jerky delay when afterscroll starts.
        self.flick_initial_scroll_t = _get_ticks()

        self._points.append(_FlickPoint(y=y, ticks=ticks))

        # Keep at most 20 points (empirically tuned).
        # Fewer points → jumpier afterscroll; more → less responsive.
        if len(self._points) >= 20:
            self._points.pop(0)

    updateFlickData = update_flick_data

    def reset_flick_data(self) -> None:
        """Clear all recorded flick data points."""
        self._points.clear()

    resetFlickData = reset_flick_data

    def get_flick_speed(
        self,
        item_height: int,
        mouse_up_t: Optional[int] = None,
    ) -> Optional[Tuple[float, int]]:
        """
        Calculate flick speed from recorded data points.

        Parameters
        ----------
        item_height : int
            The height of one item in pixels (used for thresholds).
        mouse_up_t : int, optional
            Timestamp of the mouse-up event (for finger-stop detection).

        Returns
        -------
        tuple[float, int] or None
            ``(speed, direction)`` where *speed* is pixels/ms and
            *direction* is ``-1`` (scroll up / content moves down) or
            ``+1`` (scroll down / content moves up).  Returns ``None``
            if a flick should not occur (too slow, finger stopped, etc.).
        """
        # Remove stale points
        if len(self._points) > 1:
            while (
                len(self._points) > 1
                and self._points[-1].ticks - self._points[0].ticks > FLICK_STALE_TIME
            ):
                self._points.pop(0)

        if len(self._points) < 2:
            return None

        # Check for long delay between last point and mouse-up
        if mouse_up_t is not None:
            delay_until_up = mouse_up_t - self._points[-1].ticks
            if delay_until_up > 25:
                # Long delay indicates finger stopped before lifting
                return None

        # Finger-stop checking: if the most recent N points show very
        # little movement, suppress the flick.
        recent_count = 5
        if len(self._points) > recent_count:
            recent_index = len(self._points) - recent_count
            recent_distance = self._points[-1].y - self._points[recent_index].y

            if abs(recent_distance) <= FLICK_RECENT_THRESHOLD_DISTANCE:
                log.debug(
                    "Returning None, didn't surpass 'recent' threshold distance: %s",
                    recent_distance,
                )
                return None

        distance = self._points[-1].y - self._points[0].y
        elapsed = self._points[-1].ticks - self._points[0].ticks

        if elapsed == 0:
            return None

        # speed = pixels/ms
        speed = distance / elapsed

        log.debug(
            "Flick info: speed: %s  distance: %s  time: %s",
            speed,
            distance,
            elapsed,
        )

        direction = -1 if speed >= 0 else 1
        return abs(speed), direction

    getFlickSpeed = get_flick_speed

    def snap(self, direction: int) -> None:
        """
        Start a snap-to-item flick at the minimum stop speed.

        Parameters
        ----------
        direction : int
            ``-1`` or ``+1`` indicating snap direction.
        """
        self.flick(FLICK_STOP_SPEED, direction, no_minimum=True)

    def flick(
        self,
        initial_speed: Optional[float] = None,
        direction: Optional[int] = None,
        no_minimum: bool = False,
    ) -> None:
        """
        Start or continue a flick afterscroll.

        Parameters
        ----------
        initial_speed : float, optional
            Starting speed in pixels/ms.  If ``None``, continues the
            existing flick (called by the timer).
        direction : int, optional
            ``-1`` or ``+1``.  Required when *initial_speed* is given.
        no_minimum : bool
            If ``True``, skip the minimum-speed threshold check.
        """
        now = _get_ticks()

        if initial_speed is not None:
            # Start a new flick
            self.stop_flick()

            if not no_minimum and initial_speed < FLICK_THRESHOLD_START_SPEED:
                log.debug("Under threshold, not flicking: %s", initial_speed)
                snap_enabled = getattr(self.parent, "snap_to_item_enabled", False)
                if snap_enabled and hasattr(self.parent, "snap_to_nearest"):
                    self.parent.snap_to_nearest()
                return

            self.flick_in_progress = True
            self.flick_initial_speed = initial_speed
            self.flick_direction = direction if direction is not None else 1
            self.snap_to_item_in_progress = False
            self.flick_timer.start()

            if self.flick_initial_scroll_t is None:
                self.flick_initial_scroll_t = now

            self.flick_last_y = 0.0
            self.flick_initial_deceleration_scroll_t = None
            self.flick_pre_decel_y = 0.0

            # Compute deceleration parameters
            decel_time = FLICK_DECEL_TOTAL_TIME * (
                1.0
                + abs(
                    math.pow(
                        self.flick_initial_speed / FLICK_SPEED_DECEL_TIME_FACTOR, 3
                    )
                )
            )
            self.flick_accel_rate = -self.flick_initial_speed / decel_time

            self.flick_decel_start_t = FLICK_DECEL_START_TIME * (
                1.0
                + abs(
                    math.pow(
                        self.flick_initial_speed / FLICK_SPEED_DECEL_START_TIME_FACTOR,
                        3.5,
                    )
                )
            )

            log.debug(
                "*****Starting flick - decelTime: %s  flickDecelStartT: %s",
                decel_time,
                self.flick_decel_start_t,
            )

        # Continue flick
        if self.flick_initial_scroll_t is None:
            # Safety: if somehow we got here without an initial time, bail.
            self.stop_flick()
            return

        flick_current_y: float = 0.0
        by_item_only: bool = False

        if self.flick_initial_deceleration_scroll_t is None:
            # Still at full speed
            flick_current_y = self.flick_initial_speed * (
                now - self.flick_initial_scroll_t
            )
            self.flick_pre_decel_y = flick_current_y

            # Start slowing down if past decel time
            elapsed_from_start = now - self.flick_initial_scroll_t
            if elapsed_from_start > self.flick_decel_start_t:
                log.debug("*****Starting flick slow down")
                self.flick_initial_deceleration_scroll_t = now

            by_item_only = (
                abs(self.flick_initial_speed) > FLICK_THRESHOLD_BY_PIXEL_SPEED
                and elapsed_from_start > 100
            )

        if self.flick_initial_deceleration_scroll_t is not None:
            elapsed_time = now - self.flick_initial_deceleration_scroll_t

            # v = v0 + a*t
            flick_current_speed = self.flick_initial_speed + (
                self.flick_accel_rate * elapsed_time
            )

            if self.snap_to_item_in_progress:
                flick_current_y = self.flick_last_y + SNAP_PIXEL_SHIFT
            else:
                # y = v0*t + 0.5 * a * t^2
                flick_current_y = (
                    self.flick_pre_decel_y
                    + self.flick_initial_speed * elapsed_time
                    + 0.5 * self.flick_accel_rate * elapsed_time * elapsed_time
                )
                by_item_only = abs(flick_current_speed) > FLICK_THRESHOLD_BY_PIXEL_SPEED

            # Determine stop speed
            snap_enabled = getattr(self.parent, "snap_to_item_enabled", False)
            stop_speed = (
                FLICK_STOP_SPEED_WITH_SNAP if snap_enabled else FLICK_STOP_SPEED
            )

            if self.snap_to_item_in_progress or flick_current_speed < stop_speed:
                pixel_offset_y = getattr(self.parent, "pixel_offset_y", 0)
                if snap_enabled and pixel_offset_y != 0:
                    log.debug(
                        "*******Snapping Flick at slow down point. "
                        "current speed: %s  offset: %s",
                        flick_current_speed,
                        pixel_offset_y,
                    )
                    self.snap_to_item_in_progress = True
                else:
                    log.debug(
                        "*******Stopping Flick at slow down point. "
                        "current speed: %s  offset: %s",
                        flick_current_speed,
                        pixel_offset_y,
                    )
                    self.stop_flick()
                    return

        pixel_offset = int(flick_current_y - self.flick_last_y)

        self.parent.handle_drag(self.flick_direction * pixel_offset, by_item_only)

        self.flick_last_y = self.flick_last_y + pixel_offset

        # Stop at boundaries if wraparound is not enabled
        wraparound_enabled = (
            self.parent.is_wraparound_enabled()
            if hasattr(self.parent, "is_wraparound_enabled")
            else False
        )

        if not wraparound_enabled:
            at_bottom = (
                self.parent.is_at_bottom()
                if hasattr(self.parent, "is_at_bottom")
                else False
            )
            at_top = (
                self.parent.is_at_top() if hasattr(self.parent, "is_at_top") else False
            )
            if (at_bottom and self.flick_direction > 0) or (
                at_top and self.flick_direction < 0
            ):
                log.debug("*******Stopping Flick at boundary")
                self.stop_flick()

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        state = "active" if self.flick_in_progress else "idle"
        pts = len(self._points)
        return (
            f"Flick(state={state}, points={pts}, "
            f"speed={self.flick_initial_speed:.4f}, "
            f"direction={self.flick_direction})"
        )

    def __str__(self) -> str:
        return self.__repr__()


# ---------------------------------------------------------------------------
# Module-level tick helper
# ---------------------------------------------------------------------------


def _get_ticks() -> int:
    """Return current ticks from Framework, or fall back to timer module."""
    try:
        from jive.ui.framework import framework as fw

        return fw.get_ticks()
    except (ImportError, AttributeError):
        pass
    # Fallback: use the timer module's tick function
    from jive.ui.timer import _get_ticks as timer_ticks

    return timer_ticks()
