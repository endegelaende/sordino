"""
jive.ui.event — UI event object for the Jivelite Python3 port.

Ported from ``jive_event.c`` and ``jive/ui/Event.lua`` in the original
jivelite project.

An Event carries a type (bitmask), a timestamp (ticks in ms), and a
type-specific payload (scroll amount, key code, mouse coordinates, etc.).

Copyright 2010 Logitech. All Rights Reserved. (original C implementation)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from jive.ui.constants import (
    ACTION,
    EVENT_CHAR_PRESS,
    EVENT_FOCUS_GAINED,
    EVENT_FOCUS_LOST,
    EVENT_GESTURE,
    EVENT_HIDE,
    EVENT_IR_DOWN,
    EVENT_IR_HOLD,
    EVENT_IR_PRESS,
    EVENT_IR_REPEAT,
    EVENT_IR_UP,
    EVENT_KEY_DOWN,
    EVENT_KEY_HOLD,
    EVENT_KEY_PRESS,
    EVENT_KEY_UP,
    EVENT_MOTION,
    EVENT_MOUSE_DOWN,
    EVENT_MOUSE_DRAG,
    EVENT_MOUSE_HOLD,
    EVENT_MOUSE_MOVE,
    EVENT_MOUSE_PRESS,
    EVENT_MOUSE_UP,
    EVENT_NONE,
    EVENT_SCROLL,
    EVENT_SHOW,
    EVENT_SWITCH,
    EVENT_UPDATE,
    EVENT_WINDOW_ACTIVE,
    EVENT_WINDOW_INACTIVE,
    EVENT_WINDOW_POP,
    EVENT_WINDOW_PUSH,
    EventType,
    Gesture,
    Key,
)

__all__ = [
    "Event",
    "ScrollData",
    "KeyData",
    "CharData",
    "MouseData",
    "ActionData",
    "MotionData",
    "SwitchData",
    "IRData",
    "GestureData",
]

# ---------------------------------------------------------------------------
# Startup timestamp — all ticks are relative to module load (like SDL)
# ---------------------------------------------------------------------------

_startup_time_ns: int = time.monotonic_ns()


def _get_ticks() -> int:
    """Return milliseconds since startup (matches ``Framework:getTicks()``)."""
    return (time.monotonic_ns() - _startup_time_ns) // 1_000_000


# ---------------------------------------------------------------------------
# Typed payload dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ScrollData:
    """Payload for ``EVENT_SCROLL``."""

    rel: int = 0


@dataclass(slots=True)
class KeyData:
    """Payload for ``EVENT_KEY_*``."""

    code: int = 0  # Key enum value (or bitmask for multi-key)


@dataclass(slots=True)
class CharData:
    """Payload for ``EVENT_CHAR_PRESS``."""

    unicode: int = 0


@dataclass(slots=True)
class MouseData:
    """Payload for ``EVENT_MOUSE_*``."""

    x: int = 0
    y: int = 0
    finger_count: int = 0
    finger_width: int = 0
    finger_pressure: int = 0
    chiral_value: int = 0
    chiral_active: bool = False


@dataclass(slots=True)
class ActionData:
    """Payload for ``ACTION`` events."""

    index: int = 0  # action index — resolved to name via Framework


@dataclass(slots=True)
class MotionData:
    """Payload for ``EVENT_MOTION``."""

    x: int = 0
    y: int = 0
    z: int = 0


@dataclass(slots=True)
class SwitchData:
    """Payload for ``EVENT_SWITCH``."""

    code: int = 0
    value: int = 0


@dataclass(slots=True)
class IRData:
    """Payload for ``EVENT_IR_*``."""

    code: int = 0


@dataclass(slots=True)
class GestureData:
    """Payload for ``EVENT_GESTURE``."""

    code: int = 0  # Gesture enum value


# ---------------------------------------------------------------------------
# Event class
# ---------------------------------------------------------------------------

# Maps event types to the data class used for their payload.
_SCROLL_TYPES = frozenset({EVENT_SCROLL})
_KEY_TYPES = frozenset({EVENT_KEY_DOWN, EVENT_KEY_UP, EVENT_KEY_PRESS, EVENT_KEY_HOLD})
_CHAR_TYPES = frozenset({EVENT_CHAR_PRESS})
_MOUSE_TYPES = frozenset(
    {
        EVENT_MOUSE_DOWN,
        EVENT_MOUSE_UP,
        EVENT_MOUSE_PRESS,
        EVENT_MOUSE_HOLD,
        EVENT_MOUSE_MOVE,
        EVENT_MOUSE_DRAG,
    }
)
_ACTION_TYPES = frozenset({ACTION})
_MOTION_TYPES = frozenset({EVENT_MOTION})
_SWITCH_TYPES = frozenset({EVENT_SWITCH})
_IR_TYPES = frozenset(
    {EVENT_IR_PRESS, EVENT_IR_HOLD, EVENT_IR_UP, EVENT_IR_DOWN, EVENT_IR_REPEAT}
)
_GESTURE_TYPES = frozenset({EVENT_GESTURE})


class Event:
    """
    A UI event, analogous to ``JiveEvent`` in the C code.

    Construction mirrors the Lua/C ``Event:new(type, ...)`` interface:

    - ``Event(EVENT_SCROLL, rel=3)``
    - ``Event(EVENT_KEY_PRESS, code=KEY_GO)``
    - ``Event(EVENT_MOUSE_DOWN, x=120, y=80)``
    - ``Event(ACTION, index=5)``
    - ``Event(EVENT_SHOW)``

    The event records a *ticks* timestamp at creation time (milliseconds
    since startup).
    """

    __slots__ = ("_type", "_ticks", "_data", "_value")

    def __init__(
        self,
        event_type: int,
        *,
        # Scroll
        rel: int = 0,
        # Key
        code: int = 0,
        # Char
        unicode: int = 0,
        # Mouse
        x: int = 0,
        y: int = 0,
        finger_count: int = 0,
        finger_width: int = 0,
        finger_pressure: int = 0,
        chiral_value: int = 0,
        chiral_active: bool = False,
        # Action
        index: int = 0,
        # Motion — uses x, y already defined above; z is extra
        z: int = 0,
        # Switch — uses code already defined above; value is extra
        value: int = 0,
        # Pre-set ticks (for testing or replay)
        ticks: Optional[int] = None,
    ) -> None:
        self._type: int = int(event_type)
        self._ticks: int = ticks if ticks is not None else _get_ticks()
        self._value: int = value  # also used for EVENT_UPDATE

        et = EventType(event_type) if event_type else EVENT_NONE

        if et in _SCROLL_TYPES:
            self._data: Any = ScrollData(rel=rel)
        elif et in _KEY_TYPES:
            self._data = KeyData(code=code)
        elif et in _CHAR_TYPES:
            self._data = CharData(unicode=unicode)
        elif et in _MOUSE_TYPES:
            self._data = MouseData(
                x=x,
                y=y,
                finger_count=finger_count,
                finger_width=finger_width,
                finger_pressure=finger_pressure,
                chiral_value=chiral_value,
                chiral_active=chiral_active,
            )
        elif et in _ACTION_TYPES:
            self._data = ActionData(index=index)
        elif et in _MOTION_TYPES:
            self._data = MotionData(x=x, y=y, z=z)
        elif et in _SWITCH_TYPES:
            self._data = SwitchData(code=code, value=value)
        elif et in _IR_TYPES:
            self._data = IRData(code=code)
        elif et in _GESTURE_TYPES:
            self._data = GestureData(code=code)
        else:
            # Events without a typed payload (SHOW, HIDE, WINDOW_*, FOCUS_*, UPDATE, …)
            self._data = None

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    def get_type(self) -> int:
        """Return the event type bitmask."""
        return self._type

    def get_ticks(self) -> int:
        """Return the timestamp in milliseconds since startup."""
        return self._ticks

    # ------------------------------------------------------------------
    # Typed accessors (mirror the C ``jiveL_event_get_*`` functions)
    # ------------------------------------------------------------------

    def get_scroll(self) -> int:
        """Return the relative scroll amount.  Raises for non-scroll events."""
        if not isinstance(self._data, ScrollData):
            raise TypeError(f"Not a scroll event (type=0x{self._type:08X})")
        return self._data.rel

    def get_keycode(self) -> int:
        """Return the key code.  Raises for non-key events."""
        if not isinstance(self._data, KeyData):
            raise TypeError(f"Not a key event (type=0x{self._type:08X})")
        return self._data.code

    def get_unicode(self) -> int:
        """Return the unicode codepoint.  Raises for non-char events."""
        if not isinstance(self._data, CharData):
            raise TypeError(f"Not a char event (type=0x{self._type:08X})")
        return self._data.unicode

    def get_mouse(self) -> tuple[int, int, int, int, int, Optional[int]]:
        """
        Return mouse data as ``(x, y[, finger_count, finger_width,
        finger_pressure, chiral_value|None])``.

        Always returns 6 elements for consistency; ``chiral_value`` is
        ``None`` when ``chiral_active`` is False.
        """
        if not isinstance(self._data, MouseData):
            raise TypeError(f"Not a mouse event (type=0x{self._type:08X})")
        d = self._data
        return (
            d.x,
            d.y,
            d.finger_count,
            d.finger_width,
            d.finger_pressure,
            d.chiral_value if d.chiral_active else None,
        )

    def get_mouse_xy(self) -> tuple[int, int]:
        """Convenience: return just ``(x, y)`` for mouse events."""
        if not isinstance(self._data, MouseData):
            raise TypeError(f"Not a mouse event (type=0x{self._type:08X})")
        return self._data.x, self._data.y

    def get_action_internal(self) -> int:
        """Return the raw action index.  Resolved to name by Framework."""
        if not isinstance(self._data, ActionData):
            raise TypeError(f"Not an action event (type=0x{self._type:08X})")
        return self._data.index

    def get_action(self) -> Optional[str]:
        """
        Return the action name by resolving the index via Framework.

        This is a convenience wrapper; if Framework is not available (e.g.
        during testing) or the index is unknown, returns ``None``.
        """
        if not isinstance(self._data, ActionData):
            raise TypeError(f"Not an action event (type=0x{self._type:08X})")
        # Late import to avoid circular dependency
        try:
            from jive.ui.framework import framework as fw

            return fw.get_action_event_name_by_index(self._data.index)
        except (ImportError, AttributeError):
            return None

    def get_motion(self) -> tuple[int, int, int]:
        """Return ``(x, y, z)`` for motion events."""
        if not isinstance(self._data, MotionData):
            raise TypeError(f"Not a motion event (type=0x{self._type:08X})")
        d = self._data
        return d.x, d.y, d.z

    def get_switch(self) -> tuple[int, int]:
        """Return ``(code, value)`` for switch events."""
        if not isinstance(self._data, SwitchData):
            raise TypeError(f"Not a switch event (type=0x{self._type:08X})")
        return self._data.code, self._data.value

    def get_ir_code(self) -> int:
        """Return the IR code.  Raises for non-IR events."""
        if not isinstance(self._data, IRData):
            raise TypeError(f"Not an IR event (type=0x{self._type:08X})")
        return self._data.code

    def get_gesture(self) -> int:
        """Return the gesture code.  Raises for non-gesture events."""
        if not isinstance(self._data, GestureData):
            raise TypeError(f"Not a gesture event (type=0x{self._type:08X})")
        return self._data.code

    def get_value(self) -> int:
        """Return the generic value (used by EVENT_UPDATE and others)."""
        return self._value

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def _type_name(self) -> str:
        """Human-readable name for the event type."""
        try:
            return EventType(self._type).name or f"0x{self._type:08X}"
        except ValueError:
            return f"0x{self._type:08X}"

    def __repr__(self) -> str:
        parts = [f"Event(ticks={self._ticks} type={self._type_name()}"]

        if isinstance(self._data, ScrollData):
            parts.append(f" rel={self._data.rel}")
        elif isinstance(self._data, KeyData):
            parts.append(f" code={self._data.code}")
        elif isinstance(self._data, CharData):
            parts.append(f" unicode={self._data.unicode}")
        elif isinstance(self._data, MouseData):
            d = self._data
            if d.finger_count:
                parts.append(
                    f" x={d.x},y={d.y},n={d.finger_count},"
                    f"w={d.finger_width},p={d.finger_pressure},"
                    f"c={d.chiral_value}"
                )
            else:
                parts.append(f" x={d.x},y={d.y}")
        elif isinstance(self._data, ActionData):
            parts.append(f" actionIndex={self._data.index}")
        elif isinstance(self._data, MotionData):
            d = self._data  # type: ignore[assignment]
            parts.append(f" x={d.x},y={d.y},z={d.z}")  # type: ignore[attr-defined]
        elif isinstance(self._data, SwitchData):
            parts.append(f" code={self._data.code},value={self._data.value}")
        elif isinstance(self._data, IRData):
            parts.append(f" code=0x{self._data.code:08X}")
        elif isinstance(self._data, GestureData):
            parts.append(f" code={self._data.code}")

        parts.append(")")
        return "".join(parts)

    def __str__(self) -> str:
        return self.__repr__()

    # ------------------------------------------------------------------
    # camelCase aliases — match the Lua ``Event:getKeycode()`` etc. API
    # so that applet code ported from Lua works without modification.
    # ------------------------------------------------------------------

    getType = get_type
    getTicks = get_ticks
    getScroll = get_scroll
    getKeycode = get_keycode
    getUnicode = get_unicode
    getMouse = get_mouse
    getMouseXY = get_mouse_xy
    getAction = get_action
    getActionInternal = get_action_internal
    getMotion = get_motion
    getSwitch = get_switch
    getIRCode = get_ir_code
    getGesture = get_gesture
    getValue = get_value
