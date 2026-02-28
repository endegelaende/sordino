"""
jive.ui.constants — UI constants for the Jivelite Python3 port.

Ported from the C header ``src/jive.h`` in the original jivelite project.
All event type bitmasks, key codes, alignment/layout/layer enums, and
framework constants are defined here so that every other UI module can
``from jive.ui.constants import ...`` without circular imports.

Copyright 2010 Logitech. All Rights Reserved. (original C definitions)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from enum import IntEnum, IntFlag

__all__ = [
    # Frame rate
    "FRAME_RATE_DEFAULT",
    # Sentinel geometry values
    "XY_NIL",
    "WH_NIL",
    "WH_FILL",
    # Colours
    "COLOR_WHITE",
    "COLOR_BLACK",
    # Enums
    "Align",
    "Layout",
    "Layer",
    "EventType",
    "EventStatus",
    "Key",
    "Gesture",
    # Convenience aliases (flat names matching Lua ``jive.ui.EVENT_*``)
    "EVENT_NONE",
    "EVENT_SCROLL",
    "EVENT_ACTION",
    "EVENT_KEY_DOWN",
    "EVENT_KEY_UP",
    "EVENT_KEY_PRESS",
    "EVENT_KEY_HOLD",
    "EVENT_MOUSE_DOWN",
    "EVENT_MOUSE_UP",
    "EVENT_MOUSE_PRESS",
    "EVENT_MOUSE_HOLD",
    "EVENT_MOUSE_MOVE",
    "EVENT_MOUSE_DRAG",
    "EVENT_WINDOW_PUSH",
    "EVENT_WINDOW_POP",
    "EVENT_WINDOW_ACTIVE",
    "EVENT_WINDOW_INACTIVE",
    "EVENT_SHOW",
    "EVENT_HIDE",
    "EVENT_FOCUS_GAINED",
    "EVENT_FOCUS_LOST",
    "EVENT_WINDOW_RESIZE",
    "EVENT_SWITCH",
    "EVENT_MOTION",
    "EVENT_CHAR_PRESS",
    "EVENT_IR_PRESS",
    "EVENT_IR_HOLD",
    "EVENT_IR_UP",
    "EVENT_IR_DOWN",
    "EVENT_IR_REPEAT",
    "ACTION",
    "EVENT_GESTURE",
    "EVENT_CHAR_ALL",
    "EVENT_IR_ALL",
    "EVENT_KEY_ALL",
    "EVENT_MOUSE_ALL",
    "EVENT_ALL_INPUT",
    "EVENT_VISIBLE_ALL",
    "EVENT_ALL",
    "EVENT_UNUSED",
    "EVENT_CONSUME",
    "EVENT_QUIT",
    "EVENT_UPDATE",
    "KEY_NONE",
    "KEY_GO",
    "KEY_BACK",
    "KEY_UP",
    "KEY_DOWN",
    "KEY_LEFT",
    "KEY_RIGHT",
    "KEY_HOME",
    "KEY_PLAY",
    "KEY_ADD",
    "KEY_PAUSE",
    "KEY_REW",
    "KEY_FWD",
    "KEY_VOLUME_UP",
    "KEY_VOLUME_DOWN",
    "KEY_PAGE_UP",
    "KEY_PAGE_DOWN",
    "KEY_PRINT",
    "KEY_PRESET_0",
    "KEY_PRESET_1",
    "KEY_PRESET_2",
    "KEY_PRESET_3",
    "KEY_PRESET_4",
    "KEY_PRESET_5",
    "KEY_PRESET_6",
    "KEY_PRESET_7",
    "KEY_PRESET_8",
    "KEY_PRESET_9",
    "KEY_ALARM",
    "KEY_MUTE",
    "KEY_POWER",
    "KEY_STOP",
    "KEY_REW_SCAN",
    "KEY_FWD_SCAN",
    "GESTURE_L_R",
    "GESTURE_R_L",
    "LAYER_FRAME",
    "LAYER_CONTENT",
    "LAYER_CONTENT_OFF_STAGE",
    "LAYER_CONTENT_ON_STAGE",
    "LAYER_LOWER",
    "LAYER_TITLE",
    "LAYER_ALL",
    "ALIGN_CENTER",
    "ALIGN_LEFT",
    "ALIGN_RIGHT",
    "ALIGN_TOP",
    "ALIGN_BOTTOM",
    "ALIGN_TOP_LEFT",
    "ALIGN_TOP_RIGHT",
    "ALIGN_BOTTOM_LEFT",
    "ALIGN_BOTTOM_RIGHT",
    "LAYOUT_NORTH",
    "LAYOUT_EAST",
    "LAYOUT_SOUTH",
    "LAYOUT_WEST",
    "LAYOUT_CENTER",
    "LAYOUT_NONE",
]

# ---------------------------------------------------------------------------
# Frame rate
# ---------------------------------------------------------------------------

FRAME_RATE_DEFAULT: int = 30

# ---------------------------------------------------------------------------
# Sentinel geometry values  (from jive.h)
# ---------------------------------------------------------------------------

XY_NIL: int = -1
WH_NIL: int = 65535
WH_FILL: int = 65534

# ---------------------------------------------------------------------------
# Colour constants  (32-bit RGBA)
# ---------------------------------------------------------------------------

COLOR_WHITE: int = 0xFFFFFFFF
COLOR_BLACK: int = 0x000000FF

# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------


class Align(IntEnum):
    """Widget content alignment — ordered for left→right sort."""

    CENTER = 0
    LEFT = 1
    RIGHT = 2
    TOP = 3
    BOTTOM = 4
    TOP_LEFT = 5
    TOP_RIGHT = 6
    BOTTOM_LEFT = 7
    BOTTOM_RIGHT = 8


ALIGN_CENTER = Align.CENTER
ALIGN_LEFT = Align.LEFT
ALIGN_RIGHT = Align.RIGHT
ALIGN_TOP = Align.TOP
ALIGN_BOTTOM = Align.BOTTOM
ALIGN_TOP_LEFT = Align.TOP_LEFT
ALIGN_TOP_RIGHT = Align.TOP_RIGHT
ALIGN_BOTTOM_LEFT = Align.BOTTOM_LEFT
ALIGN_BOTTOM_RIGHT = Align.BOTTOM_RIGHT

# ---------------------------------------------------------------------------
# Layout  (border-layout regions)
# ---------------------------------------------------------------------------


class Layout(IntEnum):
    NORTH = 0
    EAST = 1
    SOUTH = 2
    WEST = 3
    CENTER = 4
    NONE = 5


LAYOUT_NORTH = Layout.NORTH
LAYOUT_EAST = Layout.EAST
LAYOUT_SOUTH = Layout.SOUTH
LAYOUT_WEST = Layout.WEST
LAYOUT_CENTER = Layout.CENTER
LAYOUT_NONE = Layout.NONE

# ---------------------------------------------------------------------------
# Layers  (bitmask — widgets can be in multiple layers)
# ---------------------------------------------------------------------------


class Layer(IntFlag):
    FRAME = 0x01
    CONTENT = 0x02
    CONTENT_OFF_STAGE = 0x04
    CONTENT_ON_STAGE = 0x08
    LOWER = 0x10
    TITLE = 0x20
    ALL = 0xFF


LAYER_FRAME = Layer.FRAME
LAYER_CONTENT = Layer.CONTENT
LAYER_CONTENT_OFF_STAGE = Layer.CONTENT_OFF_STAGE
LAYER_CONTENT_ON_STAGE = Layer.CONTENT_ON_STAGE
LAYER_LOWER = Layer.LOWER
LAYER_TITLE = Layer.TITLE
LAYER_ALL = Layer.ALL

# ---------------------------------------------------------------------------
# Event types  (bitmask — listeners register for a mask of event types)
# ---------------------------------------------------------------------------


class EventType(IntFlag):
    NONE = 0x00000000

    SCROLL = 0x00000001
    # EVENT_ACTION in Lua (0x02) — rarely used directly; see ACTION below
    EVENT_ACTION = 0x00000002

    KEY_DOWN = 0x00000010
    KEY_UP = 0x00000020
    KEY_PRESS = 0x00000040
    KEY_HOLD = 0x00000080

    MOUSE_DOWN = 0x00000100
    MOUSE_UP = 0x00000200
    MOUSE_PRESS = 0x00000400
    MOUSE_HOLD = 0x00000800
    MOUSE_MOVE = 0x01000000
    MOUSE_DRAG = 0x00100000

    WINDOW_PUSH = 0x00001000
    WINDOW_POP = 0x00002000
    WINDOW_ACTIVE = 0x00004000
    WINDOW_INACTIVE = 0x00008000

    SHOW = 0x00010000
    HIDE = 0x00020000
    FOCUS_GAINED = 0x00040000
    FOCUS_LOST = 0x00080000

    WINDOW_RESIZE = 0x00200000
    SWITCH = 0x00400000
    MOTION = 0x00800000

    CHAR_PRESS = 0x02000000
    IR_PRESS = 0x04000000
    IR_HOLD = 0x08000000
    IR_UP = 0x00000004
    IR_DOWN = 0x20000000
    IR_REPEAT = 0x40000000
    ACTION = 0x10000000
    GESTURE = 0x00000008

    # Virtual / non-SDL event used internally by widgets (e.g. Slider)
    UPDATE = 0x00000000  # dispatched directly, not mask-matched

    # ---------- Composite masks ----------

    CHAR_ALL = CHAR_PRESS
    IR_ALL = IR_PRESS | IR_HOLD | IR_UP | IR_DOWN | IR_REPEAT
    KEY_ALL = KEY_DOWN | KEY_UP | KEY_PRESS | KEY_HOLD
    MOUSE_ALL = (
        MOUSE_DOWN | MOUSE_UP | MOUSE_PRESS | MOUSE_HOLD | MOUSE_MOVE | MOUSE_DRAG
    )
    ALL_INPUT = KEY_ALL | MOUSE_ALL | SCROLL | CHAR_ALL | IR_ALL | GESTURE
    VISIBLE_ALL = SHOW | HIDE
    ALL = 0x7FFFFFFF


# Flat aliases — these match the names used throughout the Lua codebase and
# let callers write ``from jive.ui.constants import EVENT_KEY_PRESS`` instead
# of ``EventType.KEY_PRESS``.

EVENT_NONE = EventType.NONE
EVENT_SCROLL = EventType.SCROLL
EVENT_ACTION = EventType.EVENT_ACTION
EVENT_KEY_DOWN = EventType.KEY_DOWN
EVENT_KEY_UP = EventType.KEY_UP
EVENT_KEY_PRESS = EventType.KEY_PRESS
EVENT_KEY_HOLD = EventType.KEY_HOLD
EVENT_MOUSE_DOWN = EventType.MOUSE_DOWN
EVENT_MOUSE_UP = EventType.MOUSE_UP
EVENT_MOUSE_PRESS = EventType.MOUSE_PRESS
EVENT_MOUSE_HOLD = EventType.MOUSE_HOLD
EVENT_MOUSE_MOVE = EventType.MOUSE_MOVE
EVENT_MOUSE_DRAG = EventType.MOUSE_DRAG
EVENT_WINDOW_PUSH = EventType.WINDOW_PUSH
EVENT_WINDOW_POP = EventType.WINDOW_POP
EVENT_WINDOW_ACTIVE = EventType.WINDOW_ACTIVE
EVENT_WINDOW_INACTIVE = EventType.WINDOW_INACTIVE
EVENT_SHOW = EventType.SHOW
EVENT_HIDE = EventType.HIDE
EVENT_FOCUS_GAINED = EventType.FOCUS_GAINED
EVENT_FOCUS_LOST = EventType.FOCUS_LOST
EVENT_WINDOW_RESIZE = EventType.WINDOW_RESIZE
EVENT_SWITCH = EventType.SWITCH
EVENT_MOTION = EventType.MOTION
EVENT_CHAR_PRESS = EventType.CHAR_PRESS
EVENT_IR_PRESS = EventType.IR_PRESS
EVENT_IR_HOLD = EventType.IR_HOLD
EVENT_IR_UP = EventType.IR_UP
EVENT_IR_DOWN = EventType.IR_DOWN
EVENT_IR_REPEAT = EventType.IR_REPEAT
ACTION = EventType.ACTION
EVENT_GESTURE = EventType.GESTURE
EVENT_UPDATE = EventType.UPDATE
EVENT_CHAR_ALL = EventType.CHAR_ALL
EVENT_IR_ALL = EventType.IR_ALL
EVENT_KEY_ALL = EventType.KEY_ALL
EVENT_MOUSE_ALL = EventType.MOUSE_ALL
EVENT_ALL_INPUT = EventType.ALL_INPUT
EVENT_VISIBLE_ALL = EventType.VISIBLE_ALL
EVENT_ALL = EventType.ALL

# ---------------------------------------------------------------------------
# Event status  (return values from event listeners / dispatchers)
# ---------------------------------------------------------------------------


class EventStatus(IntFlag):
    UNUSED = 0x0000
    CONSUME = 0x0001
    QUIT = 0x0002


EVENT_UNUSED = EventStatus.UNUSED
EVENT_CONSUME = EventStatus.CONSUME
EVENT_QUIT = EventStatus.QUIT

# ---------------------------------------------------------------------------
# Key codes
# ---------------------------------------------------------------------------


class Key(IntEnum):
    NONE = 0
    GO = 1
    BACK = 2
    UP = 3
    DOWN = 4
    LEFT = 5
    RIGHT = 6
    HOME = 7
    PLAY = 8
    ADD = 9
    PAUSE = 10
    REW = 11
    FWD = 12
    VOLUME_UP = 13
    VOLUME_DOWN = 14
    PAGE_UP = 15
    PAGE_DOWN = 16
    PRINT = 17
    PRESET_0 = 18
    PRESET_1 = 19
    PRESET_2 = 20
    PRESET_3 = 21
    PRESET_4 = 22
    PRESET_5 = 23
    PRESET_6 = 24
    PRESET_7 = 25
    PRESET_8 = 26
    PRESET_9 = 27
    ALARM = 28
    MUTE = 29
    POWER = 30
    STOP = 31
    REW_SCAN = 32
    FWD_SCAN = 33


KEY_NONE = Key.NONE
KEY_GO = Key.GO
KEY_BACK = Key.BACK
KEY_UP = Key.UP
KEY_DOWN = Key.DOWN
KEY_LEFT = Key.LEFT
KEY_RIGHT = Key.RIGHT
KEY_HOME = Key.HOME
KEY_PLAY = Key.PLAY
KEY_ADD = Key.ADD
KEY_PAUSE = Key.PAUSE
KEY_REW = Key.REW
KEY_FWD = Key.FWD
KEY_VOLUME_UP = Key.VOLUME_UP
KEY_VOLUME_DOWN = Key.VOLUME_DOWN
KEY_PAGE_UP = Key.PAGE_UP
KEY_PAGE_DOWN = Key.PAGE_DOWN
KEY_PRINT = Key.PRINT
KEY_PRESET_0 = Key.PRESET_0
KEY_PRESET_1 = Key.PRESET_1
KEY_PRESET_2 = Key.PRESET_2
KEY_PRESET_3 = Key.PRESET_3
KEY_PRESET_4 = Key.PRESET_4
KEY_PRESET_5 = Key.PRESET_5
KEY_PRESET_6 = Key.PRESET_6
KEY_PRESET_7 = Key.PRESET_7
KEY_PRESET_8 = Key.PRESET_8
KEY_PRESET_9 = Key.PRESET_9
KEY_ALARM = Key.ALARM
KEY_MUTE = Key.MUTE
KEY_POWER = Key.POWER
KEY_STOP = Key.STOP
KEY_REW_SCAN = Key.REW_SCAN
KEY_FWD_SCAN = Key.FWD_SCAN

# ---------------------------------------------------------------------------
# Gesture codes
# ---------------------------------------------------------------------------


class Gesture(IntFlag):
    L_R = 0x0001
    R_L = 0x0002


GESTURE_L_R = Gesture.L_R
GESTURE_R_L = Gesture.R_L
