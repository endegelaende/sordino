"""
jive.ui.textinput — Text input widget for the Jivelite Python3 port.

Ported from ``Textinput.lua`` (1239 LOC) and parts of the C rendering
engine in the original jivelite project.

A Textinput widget provides an editable text field with cursor
management, character scrolling, backspace/delete, insert, and
multiple value-type helpers for structured input (plain text, time,
hex, IP address).

Features:

* **Cursor management** — left/right movement, jump to start/end
* **Character scrolling** — cycle through allowed characters at the
  cursor position (via scroll wheel, IR remote, or on-screen keyboard)
* **Char press** — direct character entry from keyboard events
* **Delete / backspace** — context-aware deletion
* **Insert** — insert a new character at the cursor position
* **Value types** — pluggable value objects that control allowed
  characters, validation, and formatting per cursor position:
  - ``text_value(default, min, max)`` — length-bounded plain text
  - ``time_value(default, format)`` — 12h/24h time entry
  - ``hex_value(default, min, max)`` — hexadecimal value entry
  - ``ip_address_value(default)`` — dotted-quad IP address entry
* **Acceleration** — integrates with ``ScrollAccel``, ``IRMenuAccel``,
  and ``NumberLetterAccel`` for fast scrolling and T9 input
* **Action listeners** — go, back, play, add, finish_operation,
  cursor_left, cursor_right, clear, jump_rew, jump_fwd, etc.

Usage::

    from jive.ui.textinput import Textinput

    ti = Textinput("textinput", Textinput.text_value("hello", 1, 20),
                   closure=my_done_callback)
    window.add_widget(ti)

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
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

from jive.ui.constants import (
    EVENT_CHAR_PRESS,
    EVENT_CONSUME,
    EVENT_IR_ALL,
    EVENT_IR_DOWN,
    EVENT_IR_HOLD,
    EVENT_IR_PRESS,
    EVENT_IR_REPEAT,
    EVENT_IR_UP,
    EVENT_KEY_HOLD,
    EVENT_KEY_PRESS,
    EVENT_SCROLL,
    EVENT_UNUSED,
    EVENT_WINDOW_RESIZE,
    KEY_ADD,
    KEY_BACK,
    KEY_DOWN,
    KEY_FWD,
    KEY_LEFT,
    KEY_PLAY,
    KEY_PRESET_0,
    KEY_PRESET_1,
    KEY_PRESET_2,
    KEY_PRESET_3,
    KEY_PRESET_4,
    KEY_PRESET_5,
    KEY_PRESET_6,
    KEY_PRESET_7,
    KEY_PRESET_8,
    KEY_PRESET_9,
    KEY_REW,
    KEY_RIGHT,
    KEY_UP,
)
from jive.ui.widget import Widget
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event

__all__ = ["Textinput"]

log = logger("jivelite.ui")

# ---------------------------------------------------------------------------
# Timing constants (from Textinput.lua)
# ---------------------------------------------------------------------------

NUMBER_LETTER_OVERSHOOT_TIME: int = 150  # ms
NUMBER_LETTER_TIMER_TIME: int = 1100  # ms

# Default allowed characters (ASCII printable + space)
_DEFAULT_ALLOWED_CHARS: str = (
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    " !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
)


# ===========================================================================
# Value-type helpers (module-level factory functions, matching Lua originals)
# ===========================================================================


class _TextValueProxy:
    """
    A value proxy for plain text entry with optional min/max length.

    Behaves like a string (via ``__str__``) but also exposes
    ``setValue``, ``getValue``, ``getChars``, and ``isValid`` methods
    that the Textinput widget calls.
    """

    __slots__ = ("s", "min_len", "max_len")

    def __init__(
        self,
        default: str = "",
        min_len: Optional[int] = None,
        max_len: Optional[int] = None,
    ) -> None:
        self.s: str = default or ""
        self.min_len: Optional[int] = min_len
        self.max_len: Optional[int] = max_len

    def __str__(self) -> str:
        return self.s

    def __len__(self) -> int:
        return len(self.s)

    def setValue(self, value: Any) -> bool:
        self.s = str(value)
        return True

    def getValue(self) -> str:
        return self.s

    def getChars(self, cursor: int, allowed_chars: str) -> str:
        if self.max_len is not None and cursor > self.max_len:
            return ""
        return allowed_chars

    def isValid(self, cursor: int = 0) -> bool:
        if self.min_len is not None and len(self.s) < self.min_len:
            return False
        if self.max_len is not None and len(self.s) > self.max_len:
            return False
        return True


class _TimeValueProxy:
    """
    A value proxy for time entry (12h or 24h format).
    """

    __slots__ = ("parts", "fmt")

    def __init__(self, fmt: str = "24") -> None:
        self.parts: List[str] = []
        self.fmt: str = str(fmt)

    def __str__(self) -> str:
        if self.fmt == "12":
            if len(self.parts) >= 3 and self.parts[2]:
                return self.parts[0] + ":" + self.parts[1] + self.parts[2]
            return ":".join(self.parts)
        return ":".join(self.parts)

    def __len__(self) -> int:
        return len(str(self))

    def setValue(self, value: Any) -> bool:
        s = str(value)
        import re

        digits = re.findall(r"\d+", s)
        new_parts: List[str] = []
        for idx, dd in enumerate(digits):
            n = int(dd)
            if self.fmt == "12":
                if n > 12 and idx == 0:
                    n = 0
            else:
                if n > 23 and idx == 0:
                    n = 0
            new_parts.append(f"{n:02d}")
            if len(new_parts) >= 2:
                break
        if self.fmt == "12":
            # Search for 'a' or 'p' anywhere in the string (case-insensitive)
            ampm_match = re.search(r"[apAP]", s)
            if ampm_match:
                new_parts.append(ampm_match.group().lower())
            elif len(self.parts) >= 3:
                new_parts.append(self.parts[2] if len(self.parts) > 2 else "")
        self.parts = new_parts
        return True

    def getValue(self) -> str:
        norm: List[str] = []
        for v in self.parts:
            try:
                norm.append(str(int(v)))
            except (ValueError, TypeError):
                norm.append(str(v))
        if self.fmt == "12" and len(norm) >= 3:
            return norm[0] + ":" + norm[1] + norm[2]
        return ":".join(norm)

    def getChars(self, cursor: int, allowed_chars: str = "") -> str:
        if self.fmt == "12":
            if cursor == 7:
                return ""
            part_idx = cursor // 3
            v = 0
            if part_idx < len(self.parts):
                try:
                    v = int(self.parts[part_idx])
                except (ValueError, TypeError):
                    v = 0
            pos_in_group = cursor % 3 if cursor < 6 else cursor - 5
            if cursor == 1:
                if v == 10:
                    return "1"
                elif v < 3 or v > 10:
                    return "01"
                else:
                    return "0"
            elif cursor == 2:
                if v > 9:
                    return "012"
                else:
                    return "123456789"
            elif cursor == 3:
                return ""
            elif cursor == 4:
                return "012345"
            elif cursor == 5:
                return "0123456789"
            elif cursor == 6:
                return "ap"
            return ""
        else:
            # 24h format
            if cursor == 6:
                return ""
            part_idx = cursor // 3
            v = 0
            if part_idx < len(self.parts):
                try:
                    v = int(self.parts[part_idx])
                except (ValueError, TypeError):
                    v = 0
            if cursor == 1:
                return "012"
            elif cursor == 2:
                if v > 19:
                    return "0123"
                else:
                    return "0123456789"
            elif cursor == 3:
                return ""
            elif cursor == 4:
                return "012345"
            elif cursor == 5:
                return "0123456789"
            return ""

    def reverseScrollPolarityOnUpDownInput(self) -> bool:
        return True

    def isValid(self, cursor: int = 0) -> bool:
        if self.fmt == "12":
            return len(self.parts) == 3
        return len(self.parts) == 2


class _HexValueProxy:
    """
    A value proxy for hexadecimal input.
    """

    __slots__ = ("s", "min_len", "max_len")

    def __init__(
        self,
        default: str = "",
        min_len: Optional[int] = None,
        max_len: Optional[int] = None,
    ) -> None:
        self.s: str = default or ""
        self.min_len: Optional[int] = min_len
        self.max_len: Optional[int] = max_len

    def __str__(self) -> str:
        return self.s

    def __len__(self) -> int:
        return len(self.s)

    def setValue(self, value: Any) -> bool:
        s = str(value)
        if self.max_len is not None and len(s) > self.max_len:
            return False
        self.s = s
        return True

    def getValue(self) -> str:
        return self.s

    def getChars(self, cursor: int, allowed_chars: str = "") -> str:
        if self.max_len is not None and cursor > self.max_len:
            return ""
        return "0123456789ABCDEF"

    def reverseScrollPolarityOnUpDownInput(self) -> bool:
        return True

    def isValid(self, cursor: int = 0) -> bool:
        if self.min_len is not None and len(self.s) < self.min_len:
            return False
        return True


class _IPAddressValueProxy:
    """
    A value proxy for dotted-quad IP address input.
    """

    __slots__ = ("v", "str_val")

    def __init__(self, default: str = "") -> None:
        self.v: List[int] = []
        self.str_val: str = ""
        if default:
            self.setValue(default)

    def __str__(self) -> str:
        # For IR/key/scroll input, pad each octet to 3 digits
        try:
            from jive.ui.framework import framework as fw

            if (
                fw.is_most_recent_input("ir")
                or fw.is_most_recent_input("key")
                or fw.is_most_recent_input("scroll")
            ):
                parts = [f"{(octet or 0):03d}" for octet in self.v]
                while len(parts) < 4:
                    parts.append("000")
                return ".".join(parts)
        except (ImportError, AttributeError) as exc:
            log.debug("import fallback: %s", exc)
        return self.str_val

    def __len__(self) -> int:
        return len(str(self))

    def setValue(self, value: Any) -> bool:
        s = str(value)
        # Reject consecutive dots
        if ".." in s:
            return False

        import re

        new_v: List[int] = []
        for ddd in re.findall(r"\d+", s):
            n = int(ddd)
            # Allow changing first digit from 1 to 2, correct to 255
            if n > 255 and n < 300:
                n = 255
            if n > 255:
                return False
            new_v.append(n)
            if len(new_v) > 4:
                return False

        self.v = new_v
        self.str_val = ".".join(str(x) for x in new_v)
        if s.endswith("."):
            self.str_val += "."
        return True

    def getValue(self) -> str:
        norm = [str(int(x)) for x in self.v]
        return ".".join(norm)

    def getChars(self, cursor: int, allowed_chars: str = "") -> str:
        # Keyboard (touch) input
        try:
            from jive.ui.framework import framework as fw

            if not (
                fw.is_most_recent_input("ir")
                or fw.is_most_recent_input("key")
                or fw.is_most_recent_input("scroll")
            ):
                if len(self.v) < 4:
                    return "0123456789."
                else:
                    return "0123456789"
        except (ImportError, AttributeError):
            if len(self.v) < 4:
                return "0123456789."
            else:
                return "0123456789"

        # IR/key/scroll input — position-dependent chars
        n = cursor % 4
        if n == 0:
            return ""
        octet_idx = cursor // 4
        val = 0
        if octet_idx < len(self.v):
            val = int(self.v[octet_idx])

        a = val // 100
        b = (val % 100) // 10
        c = val % 10

        if n == 1:
            return "012"
        elif n == 2:
            if a >= 2 and c > 5:
                return "01234"
            elif a >= 2:
                return "012345"
            else:
                return "0123456789"
        elif n == 3:
            if a >= 2 and b >= 5:
                return "012345"
            else:
                return "0123456789"
        return ""

    def reverseScrollPolarityOnUpDownInput(self) -> bool:
        return True

    def defaultCursorToStart(self) -> bool:
        if not self.v:
            return True
        return False

    def isValid(self, cursor: int = 0) -> bool:
        return len(self.v) == 4 and not (
            self.v[0] == 0 and self.v[1] == 0 and self.v[2] == 0 and self.v[3] == 0
        )

    def useValueDelete(self) -> bool:
        try:
            from jive.ui.framework import framework as fw

            return (
                fw.is_most_recent_input("ir")
                or fw.is_most_recent_input("key")
                or fw.is_most_recent_input("scroll")
            )
        except (ImportError, AttributeError):
            return False

    def delete(self, cursor: int) -> Optional[int]:
        s = str(self)
        if cursor <= len(s):
            s1 = s[: cursor - 1]
            s2 = "0"
            s3 = s[cursor:]
            new = s1 + s2 + s3
            self.setValue(new)
            return -1
        elif cursor > 1:
            return -1
        else:
            return None


# ===========================================================================
# Textinput widget
# ===========================================================================


class Textinput(Widget):
    """
    A text input widget with cursor, character scrolling, and
    structured value support.

    Parameters
    ----------
    style : str
        The style key for skinning.
    value : object
        The initial value.  Can be a plain string, or a value-type
        proxy (from ``text_value``, ``time_value``, ``hex_value``,
        ``ip_address_value``) that provides ``getChars``, ``isValid``,
        ``setValue``, ``getValue`` methods.
    closure : callable, optional
        Called as ``closure(textinput, value)`` when the user confirms
        input.  Should return ``True`` if the value is accepted.
    allowed_chars : str, optional
        The characters available for scrolling at each cursor position.
        Defaults to a broad ASCII printable set.  Overridden by the
        value proxy's ``getChars()`` if available.
    """

    __slots__ = (
        "cursor",
        "indent",
        "max_width",
        "value",
        "cursor_width",
        "closure",
        "allowed_chars",
        "update_callback",
        "scroll_accel",
        "left_right_ir_accel",
        "ir_accel",
        "number_letter_accel",
        "last_number_letter_ir_code",
        "last_number_letter_key_code",
        "up_handles_cursor",
        "locked",
    )

    def __init__(
        self,
        style: str,
        value: Any = "",
        closure: Optional[Callable[..., bool]] = None,
        allowed_chars: Optional[str] = None,
    ) -> None:
        if not isinstance(style, str):
            raise TypeError(f"style must be a string, got {type(style).__name__}")
        if value is None:
            raise ValueError("value must not be None")

        super().__init__(style)

        self.cursor: int = 1
        self.indent: int = 0
        self.max_width: int = 0
        self.value: Any = value

        # Default cursor to end of string unless value says otherwise
        if self.value and not (
            hasattr(self.value, "defaultCursorToStart")
            and self.value.defaultCursorToStart()
        ):
            self.cursor = len(str(self.value)) + 1

        # Cursor width (visible cursor indicator for IR/key input)
        self.cursor_width: int = 0
        try:
            from jive.ui.framework import framework as fw

            if (
                fw.is_most_recent_input("ir")
                or fw.is_most_recent_input("key")
                or fw.is_most_recent_input("scroll")
            ):
                self.cursor_width = 1
        except (ImportError, AttributeError) as exc:
            log.debug("import fallback: %s", exc)

        self.closure: Optional[Callable[..., bool]] = closure
        self.allowed_chars: str = allowed_chars or _DEFAULT_ALLOWED_CHARS

        # Update callback (set by Keyboard)
        self.update_callback: Optional[Callable[..., None]] = None

        # Scroll acceleration
        from jive.ui.scrollaccel import ScrollAccel

        self.scroll_accel = ScrollAccel()

        # IR acceleration (left/right cursor movement)
        from jive.ui.irmenuaccel import IRMenuAccel

        self.left_right_ir_accel = IRMenuAccel("arrow_right", "arrow_left")
        self.left_right_ir_accel.only_scroll_by_one = True

        # IR acceleration (up/down character scrolling)
        self.ir_accel = IRMenuAccel()

        # Number-letter (T9) accelerator
        from jive.ui.numberletteraccel import NumberLetterAccel

        self.number_letter_accel = NumberLetterAccel(self._number_letter_timeout)

        # IR state tracking
        self.last_number_letter_ir_code: Optional[int] = None
        self.last_number_letter_key_code: Optional[int] = None
        self.up_handles_cursor: bool = False

        # Lock state (used by some value types)
        self.locked: Optional[Any] = None

        # Register action listeners
        self.add_action_listener("play", self, lambda obj, evt: self._go_action())
        self.add_action_listener("add", self, lambda obj, evt: self._insert_action())
        self.add_action_listener("go", self, lambda obj, evt: self._go_action())
        self.add_action_listener("back", self, lambda obj, evt: self._escape_action())
        self.add_action_listener(
            "finish_operation", self, lambda obj, evt: self._done_action()
        )
        self.add_action_listener(
            "cursor_left", self, lambda obj, evt: self._cursor_left_action()
        )
        self.add_action_listener(
            "cursor_right", self, lambda obj, evt: self._cursor_right_action()
        )
        self.add_action_listener("clear", self, lambda obj, evt: self._clear_action())
        self.add_action_listener(
            "jump_rew", self, lambda obj, evt: self._cursor_left_action()
        )
        self.add_action_listener(
            "jump_fwd", self, lambda obj, evt: self._cursor_right_action()
        )
        self.add_action_listener(
            "scanner_rew", self, lambda obj, evt: self._go_to_start_action()
        )
        self.add_action_listener(
            "scanner_fwd", self, lambda obj, evt: self._go_to_end_action()
        )

        # Register raw event listener for key/scroll/char/IR events
        mask = int(EVENT_CHAR_PRESS) | int(EVENT_KEY_PRESS) | int(EVENT_KEY_HOLD)
        mask |= int(EVENT_SCROLL) | int(EVENT_WINDOW_RESIZE) | int(EVENT_IR_ALL)
        self.add_listener(mask, self._event_handler)

    # ------------------------------------------------------------------
    # Number-letter timeout callback
    # ------------------------------------------------------------------

    def _number_letter_timeout(self) -> None:
        """Called when the T9 letter-switch timer fires."""
        self.last_number_letter_ir_code = None
        self.last_number_letter_key_code = None
        self._move_cursor(1)
        self.re_draw()

    # ------------------------------------------------------------------
    # Value access
    # ------------------------------------------------------------------

    def get_value(self) -> Any:
        """Return the current value."""
        return self.value

    def set_value(self, value: Any) -> bool:
        """
        Set the displayed value.

        Returns ``True`` if the value was accepted, ``False`` otherwise.
        """
        if value is None:
            return False

        ok = True
        if self.value != value:
            if hasattr(self.value, "setValue"):
                ok = self.value.setValue(value)
            else:
                self.value = value

            if self.update_callback is not None:
                self.update_callback(self)

            self.re_layout()

        return ok

    def set_update_callback(self, callback: Callable[..., None]) -> None:
        """Register a callback invoked when the textinput value changes."""
        self.update_callback = callback

    # Lua-compatible alias
    setUpdateCallback = set_update_callback

    # ------------------------------------------------------------------
    # Character helpers
    # ------------------------------------------------------------------

    def _get_chars(self) -> str:
        """Return the valid characters at the current cursor position."""
        if hasattr(self.value, "getChars"):
            return str(self.value.getChars(self.cursor, self.allowed_chars))
        return str(self.allowed_chars)

    def _reverse_scroll_polarity_on_up_down_input(self) -> bool:
        """Check if up/down scroll polarity should be reversed."""
        if hasattr(self.value, "reverseScrollPolarityOnUpDownInput"):
            return self.value.reverseScrollPolarityOnUpDownInput()  # type: ignore[no-any-return]
        return False

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def is_valid(self) -> bool:
        """Return ``True`` if the current text entry is valid."""
        if hasattr(self.value, "isValid"):
            return self.value.isValid(self.cursor)  # type: ignore[no-any-return]
        return True

    # Lua-compatible alias
    isValid = is_valid

    def _is_entered(self) -> bool:
        """Return ``True`` if text entry is complete."""
        if self.is_valid():
            return self.cursor > len(str(self.value))
        return False

    # ------------------------------------------------------------------
    # Scroll (character cycling)
    # ------------------------------------------------------------------

    def _scroll(
        self, direction: int, chars: Optional[str] = None, restart: bool = False
    ) -> None:
        """
        Scroll through characters at the cursor position.

        Parameters
        ----------
        direction : int
            Number of positions to scroll (positive = forward).
        chars : str, optional
            Override character set to use instead of ``_get_chars()``.
        restart : bool
            If ``True``, always start from the first character.
        """
        if direction == 0:
            return

        s = str(self.value)
        v = chars if chars else self._get_chars()
        if len(v) == 0:
            self.play_sound("BUMP")
            w = self.get_window()
            if w is not None:
                w.bump_right()  # type: ignore[attr-defined]
            return

        cursor = self.cursor
        s1 = s[: cursor - 1]
        s2 = s[cursor - 1 : cursor] if cursor <= len(s) else ""
        s3 = s[cursor:] if cursor <= len(s) else ""

        if not restart and s2 == "":
            # New char — keep cursor near the last letter
            if cursor > 1:
                s2 = s[cursor - 2 : cursor - 1]
            # Compensate for the initial nil value
            if direction > 0:
                direction -= 1

        # Find current character position
        # In Lua, restart sets i=0 (before 1-based first char), then i+dir
        # gives 1 (first char) when dir=1.  In Python (0-based), we use
        # i=-1 so that i+1=0 which is the first character.
        if restart:
            i = -1
        else:
            i = v.find(s2)
            if i == -1:
                i = 0

        # Move by direction
        i = i + direction

        # Handle wrap-around
        if i < 0:
            i = i + len(v)
        elif i >= len(v):
            i = i - len(v)

        # Clamp to valid range
        i = i % len(v)

        new_char = v[i]
        self.set_value(s1 + new_char + s3)
        self.play_sound("CLICK")

    # ------------------------------------------------------------------
    # Cursor movement
    # ------------------------------------------------------------------

    def _move_cursor(self, direction: int) -> None:
        """Move the cursor by *direction* positions."""
        s = str(self.value)

        # Range check
        if self.cursor == 1 and direction < 0:
            return
        if self.cursor > len(s) and direction > 0:
            return

        old_cursor = self.cursor
        self.cursor += direction

        # Check for a valid character at the new cursor position
        v = self._get_chars()
        if self.cursor <= len(s):
            s2 = s[self.cursor - 1 : self.cursor]
            if s2 and v and s2 not in v:
                # Character at new position is not valid — keep moving
                self._move_cursor(direction)
                return

        if self.cursor != old_cursor:
            self.play_sound("SELECT")

    # ------------------------------------------------------------------
    # Delete / backspace
    # ------------------------------------------------------------------

    def _delete(self, always_backspace: bool = False) -> bool:
        """
        Delete character at cursor or backspace.

        Returns ``True`` if a character was removed.
        """
        cursor = self.cursor

        # Check for value-type-specific delete
        if (
            hasattr(self.value, "delete")
            and hasattr(self.value, "useValueDelete")
            and self.value.useValueDelete()
        ):
            cursor_shift = self.value.delete(cursor)
            if cursor_shift is None:
                return False
            d = -1 if cursor_shift < 0 else 1
            for _ in range(abs(cursor_shift)):
                self._move_cursor(d)
            self.re_draw()
            return True

        s = str(self.value)

        if not always_backspace and cursor <= len(s):
            # Delete at cursor
            s1 = s[: cursor - 1]
            s3 = s[cursor:]
            self.set_value(s1 + s3)
            return True
        elif cursor > 1:
            # Backspace
            s1 = s[: cursor - 2]
            s3 = s[cursor - 1 :]
            self.set_value(s1 + s3)
            self.cursor = cursor - 1
            return True
        else:
            return False

    # ------------------------------------------------------------------
    # Insert
    # ------------------------------------------------------------------

    def _insert(self) -> bool:
        """Insert a new character at the cursor position."""
        cursor = self.cursor
        s = str(self.value)

        s1 = s[: cursor - 1]
        s3 = s[cursor - 1 :]

        v = self._get_chars()
        if len(v) == 0:
            return False

        c = v[0]
        if not self.set_value(s1 + c + s3):
            return False

        self._move_cursor(1)
        return True

    # ------------------------------------------------------------------
    # Cursor state queries
    # ------------------------------------------------------------------

    def _cursor_at_end(self) -> bool:
        """Return ``True`` if the cursor is past the end of the text."""
        return self.cursor > len(str(self.value))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _delete_action(
        self, event: Optional[Event] = None, always_backspace: bool = False
    ) -> int:
        """Handle delete/backspace action."""
        if self.cursor == 1 and not always_backspace:
            self.play_sound("WINDOWHIDE")
            self.hide()
        else:
            if self._delete(always_backspace):
                self.play_sound("CLICK")
            else:
                self.play_sound("BUMP")
                w = self.get_window()
                if w is not None:
                    w.bump_right()  # type: ignore[attr-defined]
        return int(EVENT_CONSUME)

    def _insert_action(self) -> int:
        """Handle insert action."""
        if self._insert():
            self.play_sound("CLICK")
        else:
            self.play_sound("BUMP")
            w = self.get_window()
            if w is not None:
                w.bump_right()  # type: ignore[attr-defined]
        return int(EVENT_CONSUME)

    def _go_action(
        self, event: Optional[Event] = None, bump_at_end: bool = False
    ) -> int:
        """Handle go / confirm action."""
        if self._is_entered():
            if bump_at_end:
                self.play_sound("BUMP")
                w = self.get_window()
                if w is not None:
                    w.bump_right()  # type: ignore[attr-defined]
                return int(EVENT_CONSUME)

            valid = False
            if self.closure is not None:
                valid = self.closure(self, self.get_value())

            if not valid:
                self.play_sound("BUMP")
                w = self.get_window()
                if w is not None:
                    w.bump_right()  # type: ignore[attr-defined]
        elif self.cursor <= len(str(self.value)):
            self._move_cursor(1)
            self.re_draw()
        else:
            self.play_sound("BUMP")
            w = self.get_window()
            if w is not None:
                w.bump_right()  # type: ignore[attr-defined]
        return int(EVENT_CONSUME)

    def _cursor_back_action(
        self, event: Optional[Event] = None, bump_at_start: bool = False
    ) -> int:
        """Handle cursor-back action."""
        if self.cursor == 1:
            if bump_at_start:
                self.play_sound("BUMP")
                w = self.get_window()
                if w is not None:
                    w.bump_left()  # type: ignore[attr-defined]
                return int(EVENT_CONSUME)
            else:
                self.play_sound("WINDOWHIDE")
                self.hide()
        else:
            self._move_cursor(-1)
            self.re_draw()
        return int(EVENT_CONSUME)

    def _escape_action(self) -> int:
        """Handle escape (cancel) action."""
        self._go_to_start_action()
        self.play_sound("WINDOWHIDE")
        self.hide()
        return int(EVENT_CONSUME)

    def _go_to_start_action(self) -> int:
        """Move cursor to the start of the text."""
        self.cursor = 1
        self.indent = 0
        self.re_draw()
        return int(EVENT_CONSUME)

    def _go_to_end_action(self) -> int:
        """Move cursor to the end of the text."""
        self.cursor = len(str(self.value)) + 1
        self.re_draw()
        return int(EVENT_CONSUME)

    def _cursor_left_action(self) -> int:
        """Handle cursor-left action."""
        self._cursor_back_action(bump_at_start=True)
        return int(EVENT_CONSUME)

    def _cursor_right_action(self) -> int:
        """Handle cursor-right action."""
        self._go_action(bump_at_end=True)
        return int(EVENT_CONSUME)

    def _done_action(self) -> int:
        """Handle finish_operation (done) action."""
        self._go_to_end_action()
        return self._go_action()

    def _clear_action(self) -> int:
        """Handle clear action — reset value to empty."""
        self.set_value("")
        self._go_to_start_action()
        return int(EVENT_CONSUME)

    # ------------------------------------------------------------------
    # Preset key detection
    # ------------------------------------------------------------------

    def _is_preset_button_press_event(self, event: Event) -> bool:
        """Return ``True`` if the event is a preset key press."""
        if event.get_type() != int(EVENT_KEY_PRESS):
            return False
        try:
            keycode = event.get_keycode()
        except TypeError:
            return False
        return keycode in (
            int(KEY_PRESET_0),
            int(KEY_PRESET_1),
            int(KEY_PRESET_2),
            int(KEY_PRESET_3),
            int(KEY_PRESET_4),
            int(KEY_PRESET_5),
            int(KEY_PRESET_6),
            int(KEY_PRESET_7),
            int(KEY_PRESET_8),
            int(KEY_PRESET_9),
        )

    # ------------------------------------------------------------------
    # Main event handler
    # ------------------------------------------------------------------

    def _event_handler(self, event: Event) -> int:
        """Process raw input events (key, scroll, char, IR)."""
        etype = event.get_type()

        # Update cursor width based on input mode
        try:
            from jive.ui.framework import framework as fw

            if (
                fw.is_most_recent_input("ir")
                or fw.is_most_recent_input("key")
                or fw.is_most_recent_input("scroll")
            ):
                self.cursor_width = 1
            else:
                self.cursor_width = 0
        except (ImportError, AttributeError) as exc:
            log.debug("import fallback: %s", exc)

        # ---- IR HOLD / PRESS: consume arrow and number keys ----
        if etype in (int(EVENT_IR_HOLD), int(EVENT_IR_PRESS)):
            if hasattr(event, "is_ir_code"):
                for code_name in (
                    "arrow_left",
                    "arrow_right",
                    "0",
                    "1",
                    "2",
                    "3",
                    "4",
                    "5",
                    "6",
                    "7",
                    "8",
                    "9",
                ):
                    if event.is_ir_code(code_name):
                        return int(EVENT_CONSUME)

        # ---- IR PRESS: play = go, add = insert ----
        if etype == int(EVENT_IR_PRESS):
            if hasattr(event, "is_ir_code"):
                if event.is_ir_code("play"):
                    self.number_letter_accel.stop_current_character()
                    return self._go_action()
                if event.is_ir_code("add"):
                    self.number_letter_accel.stop_current_character()
                    return self._insert_action()

        # ---- IR UP: handle cursor at ends ----
        if etype == int(EVENT_IR_UP):
            if self.up_handles_cursor and hasattr(event, "is_ir_code"):
                if event.is_ir_code("arrow_left") or event.is_ir_code("arrow_right"):
                    self.up_handles_cursor = False
                    if event.is_ir_code("arrow_left") and self.cursor == 1:
                        self._delete_action()
                    if event.is_ir_code("arrow_right") and self._cursor_at_end():
                        self._go_action()
                    return int(EVENT_CONSUME)

        # ---- IR DOWN / REPEAT ----
        if etype in (int(EVENT_IR_DOWN), int(EVENT_IR_REPEAT)):
            if hasattr(event, "is_ir_code"):
                # IR left/right cursor movement
                if event.is_ir_code("arrow_left") or event.is_ir_code("arrow_right"):
                    self.number_letter_accel.stop_current_character()
                    if self.locked is None:
                        direction = self.left_right_ir_accel.event(
                            event, 1, 1, 1, len(str(self.value))
                        )
                        if direction < 0:
                            if self.cursor != 1:
                                self._delete_action()
                            elif etype == int(EVENT_IR_DOWN):
                                self.up_handles_cursor = True
                        if direction > 0:
                            if not self._cursor_at_end():
                                self._go_action()
                            elif etype == int(EVENT_IR_DOWN):
                                self.up_handles_cursor = True
                        return int(EVENT_CONSUME)

                # IR up/down character scrolling
                if event.is_ir_code("arrow_up") or event.is_ir_code("arrow_down"):
                    self.number_letter_accel.stop_current_character()
                    if self.locked is None:
                        chars = self._get_chars()
                        s = str(self.value)
                        current_char = (
                            s[self.cursor - 1 : self.cursor]
                            if self.cursor <= len(s)
                            else ""
                        )
                        idx = (
                            chars.find(current_char) + 1
                            if current_char and current_char in chars
                            else 1
                        )

                        polarity = 1
                        if self._reverse_scroll_polarity_on_up_down_input():
                            polarity = -1

                        delta = polarity * self.ir_accel.event(
                            event, idx, idx, 1, len(chars)
                        )
                        self._scroll(delta)
                        return int(EVENT_CONSUME)

            # IR hold: rew -> start, fwd -> end
            if etype == int(EVENT_IR_HOLD):
                if hasattr(event, "is_ir_code"):
                    if event.is_ir_code("rew"):
                        return self._go_to_start_action()
                    elif event.is_ir_code("fwd"):
                        return self._go_to_end_action()

            # Number-letter (T9) input
            if etype in (int(EVENT_IR_DOWN), int(EVENT_IR_HOLD)):
                consume, switch_chars, scroll_letter, direct_letter = (
                    self.number_letter_accel.handle_event(event, self._get_chars())
                )
                if consume:
                    if switch_chars and scroll_letter:
                        self._move_cursor(1)
                        self.re_draw()
                        self._scroll(1, scroll_letter, restart=True)
                    elif scroll_letter:
                        self._scroll(1, scroll_letter, restart=True)
                    elif direct_letter:
                        self._scroll(1, direct_letter, restart=True)
                        self._move_cursor(1)
                    return int(EVENT_CONSUME)
                else:
                    return int(EVENT_UNUSED)

        # ---- SCROLL ----
        if etype == int(EVENT_SCROLL):
            self.number_letter_accel.stop_current_character()
            v = self._get_chars()
            s = str(self.value)
            current_char = (
                s[self.cursor - 1 : self.cursor] if self.cursor <= len(s) else ""
            )
            idx = v.find(current_char) + 1 if current_char and current_char in v else 1

            delta = self.scroll_accel.event(event, idx, idx, 1, len(v))
            self._scroll(delta)
            return int(EVENT_CONSUME)

        # ---- CHAR PRESS (keyboard input) ----
        if etype == int(EVENT_CHAR_PRESS):
            self.number_letter_accel.stop_current_character()

            char_code = event.get_unicode()
            keyboard_entry = chr(char_code)

            if keyboard_entry == "\b":
                return self._delete_action(event, always_backspace=True)
            elif keyboard_entry == "\x1b":  # Escape
                return self._escape_action()
            elif keyboard_entry not in self._get_chars():
                # Try uppercase match
                if keyboard_entry.islower():
                    keyboard_entry = keyboard_entry.upper()
                if keyboard_entry not in self._get_chars():
                    self.play_sound("BUMP")
                    w = self.get_window()
                    if w is not None:
                        w.bump_right()  # type: ignore[attr-defined]
                    return int(EVENT_CONSUME)

            # Insert character
            s = str(self.value)
            s1 = s[: self.cursor - 1]
            s3 = s[self.cursor - 1 :]
            if self.set_value(s1 + keyboard_entry + s3):
                self._move_cursor(1)
            else:
                self.play_sound("BUMP")
                w = self.get_window()
                if w is not None:
                    w.bump_right()  # type: ignore[attr-defined]

            return int(EVENT_CONSUME)

        # ---- WINDOW RESIZE ----
        if etype == int(EVENT_WINDOW_RESIZE):
            self.number_letter_accel.stop_current_character()
            self._move_cursor(0)

        # ---- KEY PRESS ----
        if etype == int(EVENT_KEY_PRESS):
            self.number_letter_accel.stop_current_character()
            try:
                keycode = event.get_keycode()
            except TypeError:
                return int(EVENT_UNUSED)

            if keycode in (int(KEY_UP), int(KEY_DOWN)):
                if self.locked is None:
                    polarity = 1
                    if self._reverse_scroll_polarity_on_up_down_input():
                        polarity = -1
                    self._scroll(polarity * (1 if keycode == int(KEY_DOWN) else -1))
            elif keycode == int(KEY_LEFT):
                return self._delete_action()
            elif keycode == int(KEY_RIGHT):
                if self._cursor_at_end():
                    return self._go_action()
                else:
                    return self._cursor_right_action()
            elif keycode == int(KEY_REW):
                return self._cursor_left_action()
            elif keycode == int(KEY_FWD):
                return self._cursor_right_action()
            elif keycode == int(KEY_BACK):
                return self._delete_action()

        # ---- KEY HOLD ----
        if etype == int(EVENT_KEY_HOLD):
            self.number_letter_accel.stop_current_character()
            try:
                keycode = event.get_keycode()
            except TypeError:
                return int(EVENT_UNUSED)

            if keycode == int(KEY_REW):
                return self._go_to_start_action()
            elif keycode == int(KEY_FWD):
                return self._go_to_end_action()

        return int(EVENT_UNUSED)

    # ==================================================================
    # Factory class methods for value types
    # ==================================================================

    @staticmethod
    def text_value(
        default: str = "",
        min_len: Optional[int] = None,
        max_len: Optional[int] = None,
    ) -> _TextValueProxy:
        """
        Create a value proxy for length-bounded text entry.

        Parameters
        ----------
        default : str
            Initial text value.
        min_len : int, optional
            Minimum required length for validation.
        max_len : int, optional
            Maximum allowed length.

        Returns
        -------
        _TextValueProxy
            A value object suitable for ``Textinput.__init__(value=...)``.
        """
        return _TextValueProxy(default, min_len, max_len)

    @staticmethod
    def time_value(
        default: Optional[str] = None,
        fmt: str = "24",
    ) -> _TimeValueProxy:
        """
        Create a value proxy for time entry.

        Parameters
        ----------
        default : str, optional
            Initial time string (e.g. ``"14:30"`` or ``"02:30p"``).
        fmt : str
            ``"24"`` for 24-hour format, ``"12"`` for 12-hour with AM/PM.

        Returns
        -------
        _TimeValueProxy
        """
        obj = _TimeValueProxy(fmt)
        if default:
            obj.setValue(default)
        return obj

    @staticmethod
    def hex_value(
        default: str = "",
        min_len: Optional[int] = None,
        max_len: Optional[int] = None,
    ) -> _HexValueProxy:
        """
        Create a value proxy for hexadecimal input.

        Parameters
        ----------
        default : str
            Initial hex string.
        min_len : int, optional
            Minimum required length.
        max_len : int, optional
            Maximum allowed length.

        Returns
        -------
        _HexValueProxy
        """
        return _HexValueProxy(default, min_len, max_len)

    @staticmethod
    def ip_address_value(
        default: str = "",
    ) -> _IPAddressValueProxy:
        """
        Create a value proxy for dotted-quad IP address input.

        Parameters
        ----------
        default : str
            Initial IP address string (e.g. ``"192.168.1.1"``).

        Returns
        -------
        _IPAddressValueProxy
        """
        return _IPAddressValueProxy(default)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Textinput(style={self.get_style()!r}, "
            f"value={str(self.value)!r}, "
            f"cursor={self.cursor})"
        )

    def __str__(self) -> str:
        return self.__repr__()
