"""
jive.ui.numberletteraccel — Number-to-letter (T9-style) input for IR remotes.

Ported from ``NumberLetterAccel.lua`` in the original jivelite project.

Handles the classic phone-style text entry where pressing a number key
multiple times cycles through the letters assigned to that key (e.g.
pressing '2' cycles through a→b→c→A→B→C→2).  A timer fires after
1100 ms of inactivity to commit the current character and advance the
cursor.

Key mappings (matching the Squeezebox Controller IR codes)::

    0 → ' 0'
    1 → '1.,"?!@-'
    2 → 'abcABC2'
    3 → 'defDEF3'
    4 → 'ghiGHI4'
    5 → 'jklJKL5'
    6 → 'mnoMNO6'
    7 → 'pqrsPQRS7'
    8 → 'tuvTUV8'
    9 → 'wxyzWXYZ9'

The handler also supports preset-action-based mappings (``play_preset_0``
through ``play_preset_9``) for hardware that sends actions instead of
raw IR codes.

Overshoot protection:  If the timer has *just* fired (within 150 ms)
and the same key is pressed again, the input is consumed but ignored.
This prevents accidental double-entry when the user lifts their finger
right as the timer fires.

Usage::

    from jive.ui.numberletteraccel import NumberLetterAccel

    def on_switch_timeout():
        # cursor advances to next position
        move_cursor(1)
        redraw()

    nla = NumberLetterAccel(on_switch_timeout)

    # In an IR event handler:
    result = nla.handle_event(event, valid_chars_str)
    consume, switch_chars, scroll_letter, direct_letter = result
    if consume:
        if switch_chars and scroll_letter:
            move_cursor(1)
            scroll(1, scroll_letter, restart=True)
        elif scroll_letter:
            scroll(1, scroll_letter, restart=True)
        elif direct_letter:
            scroll(1, direct_letter, restart=True)
            move_cursor(1)

Copyright 2010 Logitech. All Rights Reserved. (original Lua implementation)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Callable,
    Dict,
    Optional,
    Tuple,
)

from jive.ui.constants import (
    ACTION,
    EVENT_IR_DOWN,
    EVENT_IR_HOLD,
    EVENT_IR_PRESS,
)
from jive.ui.timer import Timer
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event

__all__ = ["NumberLetterAccel"]

log = logger("jivelite.ui")

# ---------------------------------------------------------------------------
# Timing constants (matching Lua original)
# ---------------------------------------------------------------------------

NUMBER_LETTER_OVERSHOOT_TIME: int = 150  # ms
NUMBER_LETTER_TIMER_TIME: int = 1100  # ms

# ---------------------------------------------------------------------------
# IR code → letter mappings (matching Squeezebox Controller layout)
# ---------------------------------------------------------------------------

# Keyed by raw IR hex code (as used by the SB Controller remote)
NUMBER_LETTERS_MIXED: Dict[int, str] = {
    0x76899867: " 0",  # 0
    0x7689F00F: '1.,"?!@-',  # 1
    0x768908F7: "abcABC2",  # 2
    0x76898877: "defDEF3",  # 3
    0x768948B7: "ghiGHI4",  # 4
    0x7689C837: "jklJKL5",  # 5
    0x768928D7: "mnoMNO6",  # 6
    0x7689A857: "pqrsPQRS7",  # 7
    0x76896897: "tuvTUV8",  # 8
    0x7689E817: "wxyzWXYZ9",  # 9
}

# Keyed by preset action name (for hardware that uses actions)
NUMBER_LETTERS_MIXED_PRESET: Dict[str, str] = {
    "play_preset_0": " 0",  # 0
    "play_preset_1": '1.,"?!@-',  # 1
    "play_preset_2": "abcABC2",  # 2
    "play_preset_3": "defDEF3",  # 3
    "play_preset_4": "ghiGHI4",  # 4
    "play_preset_5": "jklJKL5",  # 5
    "play_preset_6": "mnoMNO6",  # 6
    "play_preset_7": "pqrsPQRS7",  # 7
    "play_preset_8": "tuvTUV8",  # 8
    "play_preset_9": "wxyzWXYZ9",  # 9
}

# Result tuple type: (consume, switch_characters, scroll_letter, direct_letter)
HandleResult = Tuple[bool, Optional[bool], Optional[str], Optional[str]]


class NumberLetterAccel:
    """
    T9-style number-to-letter input handler for IR remotes.

    Tracks the current character position within a number key's letter
    list, and uses a timer to auto-advance the cursor after a pause.

    Parameters
    ----------
    switch_timeout_callback : callable
        Called (with no arguments) when the letter-switch timer fires,
        indicating that the current character should be committed and
        the cursor should advance.
    """

    __slots__ = (
        "switch_timeout_callback",
        "last_number_letter_ir_code",
        "last_number_letter_t",
        "number_letter_timer",
        "current_scroll_letter",
    )

    def __init__(self, switch_timeout_callback: Callable[[], None]) -> None:
        if not callable(switch_timeout_callback):
            raise TypeError(
                f"switch_timeout_callback must be callable, "
                f"got {type(switch_timeout_callback).__name__}"
            )

        self.switch_timeout_callback: Callable[[], None] = switch_timeout_callback
        self.last_number_letter_ir_code: Optional[int] = None
        self.last_number_letter_t: Optional[int] = None
        self.current_scroll_letter: Optional[str] = None

        # Create the auto-advance timer (one-shot)
        self.number_letter_timer: Timer = Timer(
            NUMBER_LETTER_TIMER_TIME,
            self._on_timer_fire,
            once=True,
        )

    # ------------------------------------------------------------------
    # Timer callback
    # ------------------------------------------------------------------

    def _on_timer_fire(self) -> None:
        """Called when the letter-switch timer expires."""
        self.current_scroll_letter = None
        self.switch_timeout_callback()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def stop_current_character(self) -> None:
        """
        Stop the current character entry immediately.

        Cancels the auto-advance timer and clears the scroll-letter
        state.  Called when the input mode changes (e.g. user scrolls
        or presses a non-number key).
        """
        self.number_letter_timer.stop()
        self.current_scroll_letter = None

    def is_running(self) -> bool:
        """Return ``True`` if the letter-switch timer is currently active."""
        return self.number_letter_timer.is_running()

    def handle_event(
        self,
        event: Event,
        valid_chars: str,
    ) -> HandleResult:
        """
        Process an IR or action event for number-letter input.

        Parameters
        ----------
        event : Event
            The incoming event (``EVENT_IR_PRESS``, ``EVENT_IR_DOWN``,
            ``EVENT_IR_HOLD``, or ``ACTION``).
        valid_chars : str
            The set of characters currently allowed at the cursor
            position.

        Returns
        -------
        tuple of (consume, switch_characters, scroll_letter, direct_letter)
            - **consume** (``bool``): ``True`` if the event was handled
              and should be consumed.
            - **switch_characters** (``bool | None``): ``True`` if the
              cursor should advance before entering the new letter
              (because a *different* number key was pressed while the
              timer was active).
            - **scroll_letter** (``str | None``): The letter to scroll
              to (single character).
            - **direct_letter** (``str | None``): A letter to enter
              directly (used for IR hold → select the digit character).
        """
        timer_was_running: bool = self.number_letter_timer.is_running()

        ir_code: Optional[int] = None
        action_name: Optional[str] = None
        number_letters: Optional[str] = None

        event_type: int = event.get_type()

        if event_type == int(EVENT_IR_PRESS):
            ir_code = event.get_ir_code()
            number_letters = NUMBER_LETTERS_MIXED.get(ir_code)
        elif event_type == int(ACTION):
            action_name = event.get_action()
            if action_name is not None:
                number_letters = NUMBER_LETTERS_MIXED_PRESET.get(action_name)

        log.debug("validChars: %s", valid_chars)

        if number_letters is not None:
            self.number_letter_timer.stop()
            switch_characters: Optional[bool] = None
            scroll_letter: Optional[str] = None

            if (
                timer_was_running
                and self.last_number_letter_ir_code is not None
                and ir_code != self.last_number_letter_ir_code
            ):
                # Different key pressed while timer was active →
                # commit the previous character and start a new one
                switch_characters = True
                available = self._get_matching_chars(number_letters, valid_chars)
                if len(available) > 0:
                    scroll_letter = available[0]
                    self.current_scroll_letter = scroll_letter
            else:
                # Same key or first press

                # Check for "overshoot" — if the timer *just* fired and
                # another press on the same key happens within the
                # overshoot window, ignore it to avoid double-entry.
                if self.last_number_letter_t is not None:
                    number_letter_time_delta = (
                        event.get_ticks() - self.last_number_letter_t
                    )
                    if (
                        not timer_was_running
                        and number_letter_time_delta > NUMBER_LETTER_TIMER_TIME
                        and number_letter_time_delta
                        < NUMBER_LETTER_TIMER_TIME + NUMBER_LETTER_OVERSHOOT_TIME
                    ):
                        # Overshoot — consume but do nothing
                        return (True, None, None, None)

                # Filter number_letters by valid_chars
                available = self._get_matching_chars(number_letters, valid_chars)

                # On IR_HOLD, select the digit character directly
                # (if it is available in the valid set)
                if event_type == int(EVENT_IR_HOLD):
                    number_char = self._find_digit(available)
                    if number_char is not None:
                        direct_letter = number_char
                        self.last_number_letter_ir_code = None
                        return (True, None, None, direct_letter)

                # Cycle to the next letter in the available set
                if len(available) > 0:
                    if self.current_scroll_letter is None:
                        # Start at the first character
                        scroll_letter = available[0]
                    else:
                        loc = available.find(self.current_scroll_letter)
                        if loc == -1:
                            # Previous letter not in current set — restart
                            log.debug(
                                "unusual - last scrollLetter was not in set, restart"
                            )
                            scroll_letter = available[0]
                        elif loc == len(available) - 1:
                            # At end — wrap around to start
                            scroll_letter = available[0]
                        else:
                            # Advance to next letter
                            scroll_letter = available[loc + 1]

                    self.current_scroll_letter = scroll_letter

            self.last_number_letter_ir_code = ir_code
            self.last_number_letter_t = event.get_ticks()
            self.number_letter_timer.restart()

            log.debug(
                "switchCharacters: %s scrollLetter: %s",
                switch_characters,
                scroll_letter,
            )

            return (True, switch_characters, scroll_letter, None)

        # Event not handled by number-letter input
        return (False, None, None, None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_matching_chars(string_a: str, string_b: str) -> str:
        """
        Return characters from *string_a* that also appear in *string_b*.

        Preserves the order from *string_a*.  This filters the number
        key's letter list down to only the characters that are valid at
        the current cursor position.
        """
        result: list[str] = []
        for ch in string_a:
            if ch in string_b:
                result.append(ch)
        return "".join(result)

    @staticmethod
    def _find_digit(s: str) -> Optional[str]:
        """Return the first digit character in *s*, or ``None``."""
        for ch in s:
            if ch.isdigit():
                return ch
        return None

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"NumberLetterAccel("
            f"current={self.current_scroll_letter!r}, "
            f"timer_running={self.number_letter_timer.is_running()}"
            f")"
        )

    def __str__(self) -> str:
        return self.__repr__()
