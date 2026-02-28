"""
jive.ui.irmenuaccel — IR remote accelerated scroll event filter.

Ported from ``IRMenuAccel.lua`` in the original jivelite project.

Handles IR remote arrow-down/arrow-up (or custom button name) events
with acceleration.  The longer the user holds a button, the faster the
scroll delta increases — similar to ScrollAccel but driven by IR
repeat timing rather than scroll-wheel deltas.

Acceleration algorithm:

* On ``EVENT_IR_DOWN`` the task always scrolls by 1, and the
  acceleration resets.  A quick double-press (within 400 ms) causes
  the acceleration to kick in sooner.
* On ``EVENT_IR_REPEAT`` the acceleration tiers are based on the
  number of *item-change cycles* (not raw input count):

  - cycles ≤ ``cycles_before_acceleration_starts``: scroll by 1
    (but ``item_change_period`` may halve)
  - cycles 17–30: full-speed (period → 0), scroll by 1
  - cycles 31–40: scroll by 2
  - cycles 41–50: scroll by 4
  - cycles 51–60: scroll by 8
  - cycles 61–80: scroll by 16
  - cycles > 80: scroll by 64

  ``scroll_by`` is capped at ``list_size / 2`` to avoid overshooting.

* ``only_scroll_by_one`` — when ``True``, forces ``scroll_by = 1``
  regardless of acceleration (used by Textinput cursor movement).

Usage::

    from jive.ui.irmenuaccel import IRMenuAccel

    accel = IRMenuAccel("arrow_right", "arrow_left")
    accel.only_scroll_by_one = True

    # inside an IR event handler:
    delta = accel.event(event, list_top, list_index,
                        list_visible, list_size)

Copyright 2010 Logitech. All Rights Reserved. (original Lua implementation)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from jive.ui.constants import EVENT_IR_DOWN, EVENT_IR_REPEAT
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event

__all__ = ["IRMenuAccel"]

log = logger("jivelite.ui")

# ---------------------------------------------------------------------------
# Constants (matching IRMenuAccel.lua)
# ---------------------------------------------------------------------------

DOUBLE_CLICK_HOLD_TIME: int = 400  # ms
INITIAL_ITEM_CHANGE_PERIOD: int = 350  # ms
CYCLES_BEFORE_ACCELERATION_STARTS: int = 1


class IRMenuAccel:
    """
    Accelerated IR remote event filter.

    Tracks the timing and repeat count of IR button presses to compute
    an acceleration curve for menu scrolling / cursor movement.

    Parameters
    ----------
    positive_button_name : str, optional
        The IR button name that triggers positive (downward / forward)
        scrolling.  Defaults to ``"arrow_down"``.
    negative_button_name : str, optional
        The IR button name that triggers negative (upward / backward)
        scrolling.  Defaults to ``"arrow_up"``.
    """

    __slots__ = (
        "positive_button_name",
        "negative_button_name",
        "list_index",
        "last_item_change_t",
        "item_change_period",
        "item_change_cycles",
        "last_down_t",
        "only_scroll_by_one",
        "cycles_before_acceleration_starts",
    )

    def __init__(
        self,
        positive_button_name: Optional[str] = None,
        negative_button_name: Optional[str] = None,
    ) -> None:
        self.positive_button_name: str = (
            positive_button_name if positive_button_name else "arrow_down"
        )
        self.negative_button_name: str = (
            negative_button_name if negative_button_name else "arrow_up"
        )
        self.list_index: int = 1
        self.last_item_change_t: int = 0
        self.item_change_period: float = INITIAL_ITEM_CHANGE_PERIOD
        self.item_change_cycles: int = 0
        self.last_down_t: Optional[int] = None
        self.only_scroll_by_one: bool = False
        self.cycles_before_acceleration_starts: int = CYCLES_BEFORE_ACCELERATION_STARTS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def event(
        self,
        event: Event,
        list_top: int = 1,
        list_index: int = 1,
        list_visible: int = 1,
        list_size: int = 1,
    ) -> int:
        """
        Process an IR event and return the (possibly accelerated) delta.

        Parameters
        ----------
        event : Event
            An ``EVENT_IR_DOWN`` or ``EVENT_IR_REPEAT`` event.
        list_top : int
            1-based index of the top visible item.
        list_index : int
            1-based index of the currently selected item.
        list_visible : int
            Number of items visible on screen.
        list_size : int
            Total number of items in the list.

        Returns
        -------
        int
            Signed scroll-by amount.  Positive → forward/down,
            negative → backward/up.  Zero if no movement should happen
            this tick (the acceleration timer hasn't elapsed yet).
        """
        # Determine direction from the IR button name
        direction: Optional[int] = None
        if self._is_ir_code(event, self.positive_button_name):
            direction = 1
        elif self._is_ir_code(event, self.negative_button_name):
            direction = -1
        else:
            log.error("Unexpected irCode in IRMenuAccel.event()")
            return 0

        now: int = event.get_ticks()
        self.list_index = list_index if list_index else 1

        event_type = event.get_type()

        # ---- IR DOWN (new press) ----
        if event_type == int(EVENT_IR_DOWN):
            if (
                self.last_down_t is not None
                and (now - self.last_down_t) < DOUBLE_CLICK_HOLD_TIME
            ):
                # Quick double-press: make acceleration kick in faster
                self.last_down_t = None
                self.item_change_cycles = 12
                self.item_change_period = INITIAL_ITEM_CHANGE_PERIOD * 0.6
            else:
                self.last_down_t = now
                self.item_change_cycles = 1
                self.item_change_period = INITIAL_ITEM_CHANGE_PERIOD

            self.last_item_change_t = now

            # Always move by exactly 1 on a fresh IR_DOWN
            scroll_by = 1
            log.debug(
                "IR Acceleration params -- scrollBy: %d dir: %d "
                "itemChangePeriod: %s itemChangeCycles: %d",
                scroll_by,
                direction,
                self.item_change_period,
                self.item_change_cycles,
            )
            return scroll_by * direction

        # ---- IR REPEAT (held button) ----
        # Apply acceleration based on number of item-change cycles
        if now > self.item_change_period + self.last_item_change_t:
            self.last_item_change_t = now

            scroll_by = 1

            if self.item_change_cycles == self.cycles_before_acceleration_starts:
                self.item_change_period = self.item_change_period / 2.0
            elif self.item_change_cycles > 80:
                scroll_by = 64
            elif self.item_change_cycles > 60:
                scroll_by = 16
            elif self.item_change_cycles > 50:
                scroll_by = 8
            elif self.item_change_cycles > 40:
                scroll_by = 4
            elif self.item_change_cycles > 30:
                scroll_by = 2
            elif self.item_change_cycles > 16:
                # Full speed — period drops to zero
                self.item_change_period = 0

            self.item_change_cycles += 1

            if self.only_scroll_by_one:
                scroll_by = 1

            # Don't scroll more than half the list
            if list_size > 1 and scroll_by > list_size / 2:
                scroll_by = int(list_size / 2)

            log.debug(
                "IR Acceleration params -- scrollBy: %d dir: %d "
                "itemChangePeriod: %s itemChangeCycles: %d",
                scroll_by,
                direction,
                self.item_change_period,
                self.item_change_cycles,
            )
            return scroll_by * direction

        # Timer hasn't elapsed yet — no movement
        return 0

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_cycles_before_acceleration_starts(self, cycles: int) -> None:
        """Set the number of cycles before acceleration begins."""
        self.cycles_before_acceleration_starts = cycles

    def reset(self) -> None:
        """Reset all acceleration state to defaults."""
        self.list_index = 1
        self.last_item_change_t = 0
        self.item_change_period = INITIAL_ITEM_CHANGE_PERIOD
        self.item_change_cycles = 0
        self.last_down_t = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_ir_code(event: Event, button_name: str) -> bool:
        """
        Check if the event matches the given IR button name.

        Delegates to ``event.is_ir_code(name)`` if available, otherwise
        falls back to checking the IR code attribute directly.
        """
        if hasattr(event, "is_ir_code") and callable(event.is_ir_code):
            return event.is_ir_code(button_name)

        # Fallback: check for an ir_button_name attribute (test support)
        ir_name = getattr(event, "ir_button_name", None)
        if ir_name is not None:
            return ir_name == button_name

        return False

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"IRMenuAccel("
            f"pos={self.positive_button_name!r}, "
            f"neg={self.negative_button_name!r}, "
            f"cycles={self.item_change_cycles}, "
            f"period={self.item_change_period}"
            f")"
        )

    def __str__(self) -> str:
        return self.__repr__()
