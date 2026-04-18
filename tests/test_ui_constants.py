"""Tests for jive.ui.constants — enums, bitmask constants, sentinels, and flat aliases."""

from __future__ import annotations

from enum import IntEnum, IntFlag

import pytest

from jive.ui.constants import (
    ACTION,
    ALIGN_BOTTOM,
    ALIGN_BOTTOM_LEFT,
    ALIGN_BOTTOM_RIGHT,
    # Flat Align aliases
    ALIGN_CENTER,
    ALIGN_LEFT,
    ALIGN_RIGHT,
    ALIGN_TOP,
    ALIGN_TOP_LEFT,
    ALIGN_TOP_RIGHT,
    COLOR_BLACK,
    # Colors
    COLOR_WHITE,
    EVENT_ACTION,
    EVENT_ALL,
    EVENT_ALL_INPUT,
    EVENT_CHAR_ALL,
    EVENT_CHAR_PRESS,
    EVENT_CONSUME,
    EVENT_FOCUS_GAINED,
    EVENT_FOCUS_LOST,
    EVENT_GESTURE,
    EVENT_HIDE,
    EVENT_IR_ALL,
    EVENT_IR_DOWN,
    EVENT_IR_HOLD,
    EVENT_IR_PRESS,
    EVENT_IR_REPEAT,
    EVENT_IR_UP,
    EVENT_KEY_ALL,
    EVENT_KEY_DOWN,
    EVENT_KEY_HOLD,
    EVENT_KEY_PRESS,
    EVENT_KEY_UP,
    EVENT_MOTION,
    EVENT_MOUSE_ALL,
    EVENT_MOUSE_DOWN,
    EVENT_MOUSE_DRAG,
    EVENT_MOUSE_HOLD,
    EVENT_MOUSE_MOVE,
    EVENT_MOUSE_PRESS,
    EVENT_MOUSE_UP,
    # Flat EventType aliases
    EVENT_NONE,
    EVENT_QUIT,
    EVENT_SCROLL,
    EVENT_SHOW,
    EVENT_SWITCH,
    # Flat EventStatus aliases
    EVENT_UNUSED,
    EVENT_UPDATE,
    EVENT_VISIBLE_ALL,
    EVENT_WINDOW_ACTIVE,
    EVENT_WINDOW_INACTIVE,
    EVENT_WINDOW_POP,
    EVENT_WINDOW_PUSH,
    EVENT_WINDOW_RESIZE,
    # Frame rate
    FRAME_RATE_DEFAULT,
    # Flat Gesture aliases
    GESTURE_L_R,
    GESTURE_R_L,
    KEY_ADD,
    KEY_ALARM,
    KEY_BACK,
    KEY_DOWN,
    KEY_FWD,
    KEY_FWD_SCAN,
    KEY_GO,
    KEY_HOME,
    KEY_LEFT,
    KEY_MUTE,
    # Flat Key aliases
    KEY_NONE,
    KEY_PAGE_DOWN,
    KEY_PAGE_UP,
    KEY_PAUSE,
    KEY_PLAY,
    KEY_POWER,
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
    KEY_PRINT,
    KEY_REW,
    KEY_REW_SCAN,
    KEY_RIGHT,
    KEY_STOP,
    KEY_UP,
    KEY_VOLUME_DOWN,
    KEY_VOLUME_UP,
    LAYER_ALL,
    LAYER_CONTENT,
    LAYER_CONTENT_OFF_STAGE,
    LAYER_CONTENT_ON_STAGE,
    # Flat Layer aliases
    LAYER_FRAME,
    LAYER_LOWER,
    LAYER_TITLE,
    LAYOUT_CENTER,
    LAYOUT_EAST,
    LAYOUT_NONE,
    # Flat Layout aliases
    LAYOUT_NORTH,
    LAYOUT_SOUTH,
    LAYOUT_WEST,
    WH_FILL,
    WH_NIL,
    # Sentinels
    XY_NIL,
    # Enum classes
    Align,
    EventStatus,
    EventType,
    Gesture,
    Key,
    Layer,
    Layout,
)

# ---------------------------------------------------------------------------
# Sentinel geometry values
# ---------------------------------------------------------------------------


class TestSentinels:
    """Sentinel geometry values from jive.h."""

    def test_xy_nil(self) -> None:
        assert XY_NIL == -1

    def test_wh_nil(self) -> None:
        assert WH_NIL == 65535

    def test_wh_fill(self) -> None:
        assert WH_FILL == 65534

    def test_wh_fill_less_than_wh_nil(self) -> None:
        assert WH_FILL < WH_NIL

    def test_frame_rate_default(self) -> None:
        assert FRAME_RATE_DEFAULT == 30


# ---------------------------------------------------------------------------
# Colour constants
# ---------------------------------------------------------------------------


class TestColors:
    """32-bit RGBA colour constants."""

    def test_color_white(self) -> None:
        assert COLOR_WHITE == 0xFFFFFFFF

    def test_color_black(self) -> None:
        assert COLOR_BLACK == 0x000000FF

    def test_white_is_int(self) -> None:
        assert isinstance(COLOR_WHITE, int)

    def test_black_is_int(self) -> None:
        assert isinstance(COLOR_BLACK, int)

    def test_white_all_channels_max(self) -> None:
        r = (COLOR_WHITE >> 24) & 0xFF
        g = (COLOR_WHITE >> 16) & 0xFF
        b = (COLOR_WHITE >> 8) & 0xFF
        a = COLOR_WHITE & 0xFF
        assert (r, g, b, a) == (255, 255, 255, 255)

    def test_black_rgb_zero_alpha_full(self) -> None:
        r = (COLOR_BLACK >> 24) & 0xFF
        g = (COLOR_BLACK >> 16) & 0xFF
        b = (COLOR_BLACK >> 8) & 0xFF
        a = COLOR_BLACK & 0xFF
        assert (r, g, b, a) == (0, 0, 0, 255)


# ---------------------------------------------------------------------------
# EventType
# ---------------------------------------------------------------------------


class TestEventType:
    """EventType is an IntFlag with correct bitmask values."""

    def test_is_intflag(self) -> None:
        assert issubclass(EventType, IntFlag)

    def test_none_is_zero(self) -> None:
        assert EventType.NONE == 0x00000000

    def test_scroll(self) -> None:
        assert EventType.SCROLL == 0x00000001

    def test_event_action(self) -> None:
        assert EventType.EVENT_ACTION == 0x00000002

    def test_key_down(self) -> None:
        assert EventType.KEY_DOWN == 0x00000010

    def test_key_up(self) -> None:
        assert EventType.KEY_UP == 0x00000020

    def test_key_press(self) -> None:
        assert EventType.KEY_PRESS == 0x00000040

    def test_key_hold(self) -> None:
        assert EventType.KEY_HOLD == 0x00000080

    def test_mouse_down(self) -> None:
        assert EventType.MOUSE_DOWN == 0x00000100

    def test_mouse_up(self) -> None:
        assert EventType.MOUSE_UP == 0x00000200

    def test_mouse_press(self) -> None:
        assert EventType.MOUSE_PRESS == 0x00000400

    def test_mouse_hold(self) -> None:
        assert EventType.MOUSE_HOLD == 0x00000800

    def test_mouse_move(self) -> None:
        assert EventType.MOUSE_MOVE == 0x01000000

    def test_mouse_drag(self) -> None:
        assert EventType.MOUSE_DRAG == 0x00100000

    def test_window_push(self) -> None:
        assert EventType.WINDOW_PUSH == 0x00001000

    def test_window_pop(self) -> None:
        assert EventType.WINDOW_POP == 0x00002000

    def test_window_active(self) -> None:
        assert EventType.WINDOW_ACTIVE == 0x00004000

    def test_window_inactive(self) -> None:
        assert EventType.WINDOW_INACTIVE == 0x00008000

    def test_show(self) -> None:
        assert EventType.SHOW == 0x00010000

    def test_hide(self) -> None:
        assert EventType.HIDE == 0x00020000

    def test_focus_gained(self) -> None:
        assert EventType.FOCUS_GAINED == 0x00040000

    def test_focus_lost(self) -> None:
        assert EventType.FOCUS_LOST == 0x00080000

    def test_window_resize(self) -> None:
        assert EventType.WINDOW_RESIZE == 0x00200000

    def test_switch(self) -> None:
        assert EventType.SWITCH == 0x00400000

    def test_motion(self) -> None:
        assert EventType.MOTION == 0x00800000

    def test_char_press(self) -> None:
        assert EventType.CHAR_PRESS == 0x02000000

    def test_ir_press(self) -> None:
        assert EventType.IR_PRESS == 0x04000000

    def test_ir_hold(self) -> None:
        assert EventType.IR_HOLD == 0x08000000

    def test_ir_up(self) -> None:
        assert EventType.IR_UP == 0x00000004

    def test_ir_down(self) -> None:
        assert EventType.IR_DOWN == 0x20000000

    def test_ir_repeat(self) -> None:
        assert EventType.IR_REPEAT == 0x40000000

    def test_action(self) -> None:
        assert EventType.ACTION == 0x10000000

    def test_gesture(self) -> None:
        assert EventType.GESTURE == 0x00000008

    def test_update_is_zero(self) -> None:
        assert EventType.UPDATE == 0x00000000

    def test_all(self) -> None:
        assert EventType.ALL == 0x7FFFFFFF


class TestEventTypeComposites:
    """Composite bitmask values built from individual flags."""

    def test_key_all(self) -> None:
        expected = EventType.KEY_DOWN | EventType.KEY_UP | EventType.KEY_PRESS | EventType.KEY_HOLD
        assert EventType.KEY_ALL == expected
        assert EventType.KEY_ALL == 0x000000F0

    def test_mouse_all(self) -> None:
        expected = (
            EventType.MOUSE_DOWN
            | EventType.MOUSE_UP
            | EventType.MOUSE_PRESS
            | EventType.MOUSE_HOLD
            | EventType.MOUSE_MOVE
            | EventType.MOUSE_DRAG
        )
        assert EventType.MOUSE_ALL == expected

    def test_ir_all(self) -> None:
        expected = (
            EventType.IR_PRESS
            | EventType.IR_HOLD
            | EventType.IR_UP
            | EventType.IR_DOWN
            | EventType.IR_REPEAT
        )
        assert EventType.IR_ALL == expected

    def test_char_all(self) -> None:
        assert EventType.CHAR_ALL == EventType.CHAR_PRESS

    def test_visible_all(self) -> None:
        assert EventType.VISIBLE_ALL == (EventType.SHOW | EventType.HIDE)

    def test_all_input_includes_key_all(self) -> None:
        assert EventType.ALL_INPUT & EventType.KEY_ALL == EventType.KEY_ALL

    def test_all_input_includes_mouse_all(self) -> None:
        assert EventType.ALL_INPUT & EventType.MOUSE_ALL == EventType.MOUSE_ALL

    def test_all_input_includes_scroll(self) -> None:
        assert EventType.ALL_INPUT & EventType.SCROLL == EventType.SCROLL

    def test_all_input_includes_char_all(self) -> None:
        assert EventType.ALL_INPUT & EventType.CHAR_ALL == EventType.CHAR_ALL

    def test_all_input_includes_ir_all(self) -> None:
        assert EventType.ALL_INPUT & EventType.IR_ALL == EventType.IR_ALL

    def test_all_input_includes_gesture(self) -> None:
        assert EventType.ALL_INPUT & EventType.GESTURE == EventType.GESTURE

    def test_all_input_composition(self) -> None:
        expected = (
            EventType.KEY_ALL
            | EventType.MOUSE_ALL
            | EventType.SCROLL
            | EventType.CHAR_ALL
            | EventType.IR_ALL
            | EventType.GESTURE
        )
        assert EventType.ALL_INPUT == expected

    def test_all_input_excludes_window_events(self) -> None:
        assert EventType.ALL_INPUT & EventType.WINDOW_PUSH == 0
        assert EventType.ALL_INPUT & EventType.WINDOW_POP == 0
        assert EventType.ALL_INPUT & EventType.SHOW == 0
        assert EventType.ALL_INPUT & EventType.HIDE == 0


class TestEventTypeBitmaskOps:
    """IntFlag supports bitwise operations correctly."""

    def test_or_combines_flags(self) -> None:
        combined = EventType.SCROLL | EventType.KEY_PRESS
        assert combined & EventType.SCROLL
        assert combined & EventType.KEY_PRESS
        assert not (combined & EventType.MOUSE_DOWN)

    def test_and_masks_flags(self) -> None:
        mask = EventType.KEY_ALL
        assert mask & EventType.KEY_DOWN
        assert not (mask & EventType.MOUSE_DOWN)

    def test_membership_via_in(self) -> None:
        # Single flag is "in" a composite
        assert EventType.KEY_DOWN & EventType.KEY_ALL

    def test_can_use_as_int(self) -> None:
        assert int(EventType.SCROLL) == 1
        assert EventType.SCROLL + 0 == 1

    def test_no_overlap_between_key_and_mouse(self) -> None:
        assert EventType.KEY_ALL & EventType.MOUSE_ALL == 0


# ---------------------------------------------------------------------------
# EventType flat aliases
# ---------------------------------------------------------------------------


class TestEventTypeFlatAliases:
    """Flat aliases (EVENT_SCROLL etc.) match enum members exactly."""

    def test_event_none(self) -> None:
        assert EVENT_NONE == EventType.NONE
        assert EVENT_NONE is EventType.NONE

    def test_event_scroll(self) -> None:
        assert EVENT_SCROLL == EventType.SCROLL
        assert EVENT_SCROLL is EventType.SCROLL

    def test_event_action_alias(self) -> None:
        assert EVENT_ACTION == EventType.EVENT_ACTION
        assert EVENT_ACTION is EventType.EVENT_ACTION

    def test_event_key_down(self) -> None:
        assert EVENT_KEY_DOWN == EventType.KEY_DOWN
        assert EVENT_KEY_DOWN is EventType.KEY_DOWN

    def test_event_key_up(self) -> None:
        assert EVENT_KEY_UP == EventType.KEY_UP

    def test_event_key_press(self) -> None:
        assert EVENT_KEY_PRESS == EventType.KEY_PRESS

    def test_event_key_hold(self) -> None:
        assert EVENT_KEY_HOLD == EventType.KEY_HOLD

    def test_event_mouse_down(self) -> None:
        assert EVENT_MOUSE_DOWN == EventType.MOUSE_DOWN

    def test_event_mouse_up(self) -> None:
        assert EVENT_MOUSE_UP == EventType.MOUSE_UP

    def test_event_mouse_press(self) -> None:
        assert EVENT_MOUSE_PRESS == EventType.MOUSE_PRESS

    def test_event_mouse_hold(self) -> None:
        assert EVENT_MOUSE_HOLD == EventType.MOUSE_HOLD

    def test_event_mouse_move(self) -> None:
        assert EVENT_MOUSE_MOVE == EventType.MOUSE_MOVE

    def test_event_mouse_drag(self) -> None:
        assert EVENT_MOUSE_DRAG == EventType.MOUSE_DRAG

    def test_event_window_push(self) -> None:
        assert EVENT_WINDOW_PUSH == EventType.WINDOW_PUSH

    def test_event_window_pop(self) -> None:
        assert EVENT_WINDOW_POP == EventType.WINDOW_POP

    def test_event_window_active(self) -> None:
        assert EVENT_WINDOW_ACTIVE == EventType.WINDOW_ACTIVE

    def test_event_window_inactive(self) -> None:
        assert EVENT_WINDOW_INACTIVE == EventType.WINDOW_INACTIVE

    def test_event_show(self) -> None:
        assert EVENT_SHOW == EventType.SHOW

    def test_event_hide(self) -> None:
        assert EVENT_HIDE == EventType.HIDE

    def test_event_focus_gained(self) -> None:
        assert EVENT_FOCUS_GAINED == EventType.FOCUS_GAINED

    def test_event_focus_lost(self) -> None:
        assert EVENT_FOCUS_LOST == EventType.FOCUS_LOST

    def test_event_window_resize(self) -> None:
        assert EVENT_WINDOW_RESIZE == EventType.WINDOW_RESIZE

    def test_event_switch(self) -> None:
        assert EVENT_SWITCH == EventType.SWITCH

    def test_event_motion(self) -> None:
        assert EVENT_MOTION == EventType.MOTION

    def test_event_char_press(self) -> None:
        assert EVENT_CHAR_PRESS == EventType.CHAR_PRESS

    def test_event_ir_press(self) -> None:
        assert EVENT_IR_PRESS == EventType.IR_PRESS

    def test_event_ir_hold(self) -> None:
        assert EVENT_IR_HOLD == EventType.IR_HOLD

    def test_event_ir_up(self) -> None:
        assert EVENT_IR_UP == EventType.IR_UP

    def test_event_ir_down(self) -> None:
        assert EVENT_IR_DOWN == EventType.IR_DOWN

    def test_event_ir_repeat(self) -> None:
        assert EVENT_IR_REPEAT == EventType.IR_REPEAT

    def test_action_alias(self) -> None:
        assert ACTION == EventType.ACTION
        assert ACTION is EventType.ACTION

    def test_event_gesture(self) -> None:
        assert EVENT_GESTURE == EventType.GESTURE

    def test_event_update(self) -> None:
        assert EVENT_UPDATE == EventType.UPDATE

    def test_composite_key_all(self) -> None:
        assert EVENT_KEY_ALL == EventType.KEY_ALL

    def test_composite_mouse_all(self) -> None:
        assert EVENT_MOUSE_ALL == EventType.MOUSE_ALL

    def test_composite_ir_all(self) -> None:
        assert EVENT_IR_ALL == EventType.IR_ALL

    def test_composite_char_all(self) -> None:
        assert EVENT_CHAR_ALL == EventType.CHAR_ALL

    def test_composite_all_input(self) -> None:
        assert EVENT_ALL_INPUT == EventType.ALL_INPUT

    def test_composite_visible_all(self) -> None:
        assert EVENT_VISIBLE_ALL == EventType.VISIBLE_ALL

    def test_composite_all(self) -> None:
        assert EVENT_ALL == EventType.ALL


# ---------------------------------------------------------------------------
# EventStatus
# ---------------------------------------------------------------------------


class TestEventStatus:
    """EventStatus enum and flat aliases."""

    def test_is_intflag(self) -> None:
        assert issubclass(EventStatus, IntFlag)

    def test_unused(self) -> None:
        assert EventStatus.UNUSED == 0x0000

    def test_consume(self) -> None:
        assert EventStatus.CONSUME == 0x0001

    def test_quit(self) -> None:
        assert EventStatus.QUIT == 0x0002

    def test_alias_event_unused(self) -> None:
        assert EVENT_UNUSED == EventStatus.UNUSED
        assert EVENT_UNUSED == 0

    def test_alias_event_consume(self) -> None:
        assert EVENT_CONSUME == EventStatus.CONSUME
        assert EVENT_CONSUME == 1

    def test_alias_event_quit(self) -> None:
        assert EVENT_QUIT == EventStatus.QUIT
        assert EVENT_QUIT == 2

    def test_unused_is_falsy(self) -> None:
        assert not EVENT_UNUSED

    def test_consume_is_truthy(self) -> None:
        assert EVENT_CONSUME

    def test_quit_is_truthy(self) -> None:
        assert EVENT_QUIT


# ---------------------------------------------------------------------------
# Key
# ---------------------------------------------------------------------------


class TestKey:
    """Key enum — sequential key codes from 0 to 33."""

    def test_is_intenum(self) -> None:
        assert issubclass(Key, IntEnum)

    def test_key_none(self) -> None:
        assert Key.NONE == 0

    def test_key_go(self) -> None:
        assert Key.GO == 1

    def test_key_back(self) -> None:
        assert Key.BACK == 2

    def test_key_up(self) -> None:
        assert Key.UP == 3

    def test_key_down(self) -> None:
        assert Key.DOWN == 4

    def test_key_left(self) -> None:
        assert Key.LEFT == 5

    def test_key_right(self) -> None:
        assert Key.RIGHT == 6

    def test_key_home(self) -> None:
        assert Key.HOME == 7

    def test_key_play(self) -> None:
        assert Key.PLAY == 8

    def test_key_add(self) -> None:
        assert Key.ADD == 9

    def test_key_pause(self) -> None:
        assert Key.PAUSE == 10

    def test_key_rew(self) -> None:
        assert Key.REW == 11

    def test_key_fwd(self) -> None:
        assert Key.FWD == 12

    def test_key_volume_up(self) -> None:
        assert Key.VOLUME_UP == 13

    def test_key_volume_down(self) -> None:
        assert Key.VOLUME_DOWN == 14

    def test_key_page_up(self) -> None:
        assert Key.PAGE_UP == 15

    def test_key_page_down(self) -> None:
        assert Key.PAGE_DOWN == 16

    def test_key_print(self) -> None:
        assert Key.PRINT == 17

    def test_presets_0_through_9(self) -> None:
        assert Key.PRESET_0 == 18
        assert Key.PRESET_1 == 19
        assert Key.PRESET_2 == 20
        assert Key.PRESET_3 == 21
        assert Key.PRESET_4 == 22
        assert Key.PRESET_5 == 23
        assert Key.PRESET_6 == 24
        assert Key.PRESET_7 == 25
        assert Key.PRESET_8 == 26
        assert Key.PRESET_9 == 27

    def test_key_alarm(self) -> None:
        assert Key.ALARM == 28

    def test_key_mute(self) -> None:
        assert Key.MUTE == 29

    def test_key_power(self) -> None:
        assert Key.POWER == 30

    def test_key_stop(self) -> None:
        assert Key.STOP == 31

    def test_key_rew_scan(self) -> None:
        assert Key.REW_SCAN == 32

    def test_key_fwd_scan(self) -> None:
        assert Key.FWD_SCAN == 33

    def test_total_member_count(self) -> None:
        assert len(Key) == 34  # NONE(0) through FWD_SCAN(33)

    def test_sequential_no_gaps(self) -> None:
        values = sorted(m.value for m in Key)
        assert values == list(range(34))


class TestKeyFlatAliases:
    """Flat KEY_* aliases match enum members."""

    def test_key_none(self) -> None:
        assert KEY_NONE == Key.NONE

    def test_key_go(self) -> None:
        assert KEY_GO == Key.GO
        assert KEY_GO == 1

    def test_key_back(self) -> None:
        assert KEY_BACK == Key.BACK
        assert KEY_BACK == 2

    def test_key_up(self) -> None:
        assert KEY_UP == Key.UP

    def test_key_down(self) -> None:
        assert KEY_DOWN == Key.DOWN

    def test_key_left(self) -> None:
        assert KEY_LEFT == Key.LEFT

    def test_key_right(self) -> None:
        assert KEY_RIGHT == Key.RIGHT

    def test_key_home(self) -> None:
        assert KEY_HOME == Key.HOME

    def test_key_play(self) -> None:
        assert KEY_PLAY == Key.PLAY

    def test_key_add(self) -> None:
        assert KEY_ADD == Key.ADD

    def test_key_pause(self) -> None:
        assert KEY_PAUSE == Key.PAUSE

    def test_key_rew(self) -> None:
        assert KEY_REW == Key.REW

    def test_key_fwd(self) -> None:
        assert KEY_FWD == Key.FWD

    def test_key_volume_up(self) -> None:
        assert KEY_VOLUME_UP == Key.VOLUME_UP

    def test_key_volume_down(self) -> None:
        assert KEY_VOLUME_DOWN == Key.VOLUME_DOWN

    def test_key_page_up(self) -> None:
        assert KEY_PAGE_UP == Key.PAGE_UP

    def test_key_page_down(self) -> None:
        assert KEY_PAGE_DOWN == Key.PAGE_DOWN

    def test_key_print(self) -> None:
        assert KEY_PRINT == Key.PRINT

    def test_preset_aliases(self) -> None:
        assert KEY_PRESET_0 == Key.PRESET_0
        assert KEY_PRESET_1 == Key.PRESET_1
        assert KEY_PRESET_2 == Key.PRESET_2
        assert KEY_PRESET_3 == Key.PRESET_3
        assert KEY_PRESET_4 == Key.PRESET_4
        assert KEY_PRESET_5 == Key.PRESET_5
        assert KEY_PRESET_6 == Key.PRESET_6
        assert KEY_PRESET_7 == Key.PRESET_7
        assert KEY_PRESET_8 == Key.PRESET_8
        assert KEY_PRESET_9 == Key.PRESET_9

    def test_key_alarm(self) -> None:
        assert KEY_ALARM == Key.ALARM

    def test_key_mute(self) -> None:
        assert KEY_MUTE == Key.MUTE

    def test_key_power(self) -> None:
        assert KEY_POWER == Key.POWER

    def test_key_stop(self) -> None:
        assert KEY_STOP == Key.STOP

    def test_key_rew_scan(self) -> None:
        assert KEY_REW_SCAN == Key.REW_SCAN
        assert KEY_REW_SCAN == 32

    def test_key_fwd_scan(self) -> None:
        assert KEY_FWD_SCAN == Key.FWD_SCAN
        assert KEY_FWD_SCAN == 33


# ---------------------------------------------------------------------------
# Gesture
# ---------------------------------------------------------------------------


class TestGesture:
    """Gesture codes (IntFlag)."""

    def test_is_intflag(self) -> None:
        assert issubclass(Gesture, IntFlag)

    def test_l_r(self) -> None:
        assert Gesture.L_R == 0x0001

    def test_r_l(self) -> None:
        assert Gesture.R_L == 0x0002

    def test_alias_gesture_l_r(self) -> None:
        assert GESTURE_L_R == Gesture.L_R
        assert GESTURE_L_R is Gesture.L_R

    def test_alias_gesture_r_l(self) -> None:
        assert GESTURE_R_L == Gesture.R_L
        assert GESTURE_R_L is Gesture.R_L

    def test_no_overlap(self) -> None:
        assert Gesture.L_R & Gesture.R_L == 0

    def test_can_combine(self) -> None:
        both = Gesture.L_R | Gesture.R_L
        assert both & Gesture.L_R
        assert both & Gesture.R_L


# ---------------------------------------------------------------------------
# Layer
# ---------------------------------------------------------------------------


class TestLayer:
    """Layer bitmask (IntFlag)."""

    def test_is_intflag(self) -> None:
        assert issubclass(Layer, IntFlag)

    def test_frame(self) -> None:
        assert Layer.FRAME == 0x01

    def test_content(self) -> None:
        assert Layer.CONTENT == 0x02

    def test_content_off_stage(self) -> None:
        assert Layer.CONTENT_OFF_STAGE == 0x04

    def test_content_on_stage(self) -> None:
        assert Layer.CONTENT_ON_STAGE == 0x08

    def test_lower(self) -> None:
        assert Layer.LOWER == 0x10

    def test_title(self) -> None:
        assert Layer.TITLE == 0x20

    def test_all(self) -> None:
        assert Layer.ALL == 0xFF

    def test_all_includes_all_named_layers(self) -> None:
        named = (
            Layer.FRAME
            | Layer.CONTENT
            | Layer.CONTENT_OFF_STAGE
            | Layer.CONTENT_ON_STAGE
            | Layer.LOWER
            | Layer.TITLE
        )
        assert Layer.ALL & named == named

    def test_flat_aliases(self) -> None:
        assert LAYER_FRAME == Layer.FRAME
        assert LAYER_CONTENT == Layer.CONTENT
        assert LAYER_CONTENT_OFF_STAGE == Layer.CONTENT_OFF_STAGE
        assert LAYER_CONTENT_ON_STAGE == Layer.CONTENT_ON_STAGE
        assert LAYER_LOWER == Layer.LOWER
        assert LAYER_TITLE == Layer.TITLE
        assert LAYER_ALL == Layer.ALL


# ---------------------------------------------------------------------------
# Align
# ---------------------------------------------------------------------------


class TestAlign:
    """Align enum (IntEnum)."""

    def test_is_intenum(self) -> None:
        assert issubclass(Align, IntEnum)

    def test_center(self) -> None:
        assert Align.CENTER == 0

    def test_left(self) -> None:
        assert Align.LEFT == 1

    def test_right(self) -> None:
        assert Align.RIGHT == 2

    def test_top(self) -> None:
        assert Align.TOP == 3

    def test_bottom(self) -> None:
        assert Align.BOTTOM == 4

    def test_top_left(self) -> None:
        assert Align.TOP_LEFT == 5

    def test_top_right(self) -> None:
        assert Align.TOP_RIGHT == 6

    def test_bottom_left(self) -> None:
        assert Align.BOTTOM_LEFT == 7

    def test_bottom_right(self) -> None:
        assert Align.BOTTOM_RIGHT == 8

    def test_total_members(self) -> None:
        assert len(Align) == 9

    def test_flat_aliases(self) -> None:
        assert ALIGN_CENTER == Align.CENTER
        assert ALIGN_LEFT == Align.LEFT
        assert ALIGN_RIGHT == Align.RIGHT
        assert ALIGN_TOP == Align.TOP
        assert ALIGN_BOTTOM == Align.BOTTOM
        assert ALIGN_TOP_LEFT == Align.TOP_LEFT
        assert ALIGN_TOP_RIGHT == Align.TOP_RIGHT
        assert ALIGN_BOTTOM_LEFT == Align.BOTTOM_LEFT
        assert ALIGN_BOTTOM_RIGHT == Align.BOTTOM_RIGHT


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


class TestLayout:
    """Layout enum (IntEnum) — border-layout regions."""

    def test_is_intenum(self) -> None:
        assert issubclass(Layout, IntEnum)

    def test_north(self) -> None:
        assert Layout.NORTH == 0

    def test_east(self) -> None:
        assert Layout.EAST == 1

    def test_south(self) -> None:
        assert Layout.SOUTH == 2

    def test_west(self) -> None:
        assert Layout.WEST == 3

    def test_center(self) -> None:
        assert Layout.CENTER == 4

    def test_none(self) -> None:
        assert Layout.NONE == 5

    def test_total_members(self) -> None:
        assert len(Layout) == 6

    def test_flat_aliases(self) -> None:
        assert LAYOUT_NORTH == Layout.NORTH
        assert LAYOUT_EAST == Layout.EAST
        assert LAYOUT_SOUTH == Layout.SOUTH
        assert LAYOUT_WEST == Layout.WEST
        assert LAYOUT_CENTER == Layout.CENTER
        assert LAYOUT_NONE == Layout.NONE


# ---------------------------------------------------------------------------
# Cross-enum sanity checks
# ---------------------------------------------------------------------------


class TestCrossEnumSanity:
    """Verify there are no accidental collisions between unrelated constants."""

    def test_key_up_vs_event_key_up(self) -> None:
        # Key.UP == 3, EventType.KEY_UP == 0x20 — very different values
        assert Key.UP != EventType.KEY_UP

    def test_key_down_vs_event_key_down(self) -> None:
        assert Key.DOWN != EventType.KEY_DOWN

    def test_event_types_are_powers_of_two_or_composites(self) -> None:
        # Every non-composite, non-zero EventType member should be a power of 2
        composites = {
            EventType.KEY_ALL,
            EventType.MOUSE_ALL,
            EventType.IR_ALL,
            EventType.CHAR_ALL,
            EventType.ALL_INPUT,
            EventType.VISIBLE_ALL,
            EventType.ALL,
            EventType.NONE,
            EventType.UPDATE,  # 0, same as NONE
        }
        for member in EventType:
            if member in composites:
                continue
            if member.value == 0:
                continue
            # Must be a single bit set
            assert member.value & (member.value - 1) == 0, (
                f"{member.name}=0x{member.value:08X} is not a power of 2"
            )

    def test_all_event_types_usable_as_int(self) -> None:
        for member in EventType:
            assert isinstance(int(member), int)

    def test_all_keys_usable_as_int(self) -> None:
        for member in Key:
            assert isinstance(int(member), int)
